/* pfhook.dll - PhraseForge's low-level keyboard hook in native code (PRD FR-INP-01/02).
 *
 * Why: a WH_KEYBOARD_LL callback written in Python has to take the GIL. When Python is
 * busy (garbage collection, a slow Qt slot, an import), every key on the PC waits, and
 * after repeated timeouts Windows silently removes the hook.
 *
 * How: the hook runs on its own native thread and never touches Python. Each key event is
 * written to a single-producer/single-consumer ring buffer that a Python thread reads with
 * pf_next(). For each key the hook waits up to a short budget (pf_set_options) for
 * Python's decision (pf_reply: swallow or pass). If Python does not answer in time, the
 * key passes and the hook stops waiting ("degraded") until Python has caught up with the
 * ring. While degraded, keys in the rule table (hotkey chords) are still swallowed here,
 * so a hotkey never leaks into the target program. Rules marked ALWAYS (Caps Lock when it
 * is disabled) are swallowed here in every mode.
 *
 * While PhraseForge types a phrase (pf_block_begin / pf_block_end, PRD FR-TRG-06), the
 * user's keys are held back in order and sent again afterwards, or dropped.
 *
 * Build (x64 Developer Command Prompt):
 *   cl /nologo /O2 /W4 /LD pfhook.c /Fe:pfhook.dll user32.lib
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#define PF_API __declspec(dllexport)
#define PF_VERSION 4

#define RING_SIZE 1024u                 /* power of two */
#define MAX_RULES 256
#define MAX_BLOCKED 512
#define REPLAY_MAGIC ((ULONG_PTR)0x50465252u)   /* "PFRR": keys we replay after output (FR-TRG-06) */

/* PFEvent.status bits */
#define ST_DOWN      0x01u
#define ST_INJECTED  0x02u
#define ST_EXTENDED  0x04u
#define ST_WAITED    0x08u              /* the hook waited for Python's decision */
#define ST_NATIVE    0x10u              /* swallowed by the rule table, no decision asked */

/* modifier bits */
#define M_SHIFT 1u
#define M_CTRL  2u
#define M_ALT   4u
#define M_WIN   8u

/* PFRule.when */
#define W_ALWAYS   1u
#define W_DEGRADED 2u

typedef struct {
    UINT32 seq, vk, scan, flags, time, mods, status, nchars;
    WCHAR chars[8];
} PFEvent;

typedef struct { UINT32 vk, mods, when; } PFRule;

typedef struct {
    UINT64 events, waited, timeouts, dropped, native_swallowed, late_replies;
    UINT32 max_us, p99_us, degraded, running;
    UINT32 hist[32];                    /* bucket b: callback time < 2^b microseconds */
    UINT64 blocked, replayed;           /* keys held back during output, keys sent again (v2) */
} PFStats;

typedef struct { UINT32 vk, scan, flags; } PFKey;

static PFEvent g_ring[RING_SIZE];
static volatile LONG g_head, g_tail;    /* head: hook thread writes; tail: reader writes */
static HANDLE g_avail;                  /* auto-reset: an event was queued (or stop) */
static HANDLE g_reply;                  /* auto-reset: Python answered the awaited event */
static volatile LONG g_wait_seq;        /* seq the hook waits for, 0 = none */
static volatile LONG g_reply_val, g_reply_seq;
static volatile LONG g_degraded;
static volatile LONG g_running;
static volatile LONG g_budget_ms = 40;
static volatile LONG g_pass_foreign = 1;
static ULONG_PTR g_magic;

static SRWLOCK g_rules_lock = SRWLOCK_INIT;
static PFRule g_rules[MAX_RULES];
static int g_nrules;
static BYTE g_swallow_up[256];          /* key-up of a natively swallowed key-down */

/* FR-TRG-06: while PhraseForge types a phrase, the user's keys are held back here and
 * sent again afterwards, so they cannot land in the middle of the phrase. */
static SRWLOCK g_block_lock = SRWLOCK_INIT;
static volatile LONG g_block;
static ULONGLONG g_block_until;         /* safety: stop holding keys back after this tick */
static PFKey g_blocked[MAX_BLOCKED];
static int g_nblocked;
static volatile LONG g_block_replay = 1; /* what a flush at the limit does: 1 replay, 0 drop (v4) */
static volatile LONG g_flush_pending;   /* a flush at the limit has been submitted (v4) */
static volatile LONG g_block_gen;       /* +1 per pf_block_begin2: a late flush skips a newer block */
static SRWLOCK g_end_lock = SRWLOCK_INIT; /* one pf_block_end at a time (Python or the flush) */
PF_API UINT32 pf_block_end(int replay);

static HHOOK g_hook;
static HANDLE g_thread, g_ready;
static DWORD g_tid, g_start_error;
static UINT32 g_seq;
static LARGE_INTEGER g_freq;
static PFStats g_stats;

static UINT32 current_mods(void) {
    UINT32 m = 0;
    if (GetAsyncKeyState(VK_SHIFT) & 0x8000) m |= M_SHIFT;
    if (GetAsyncKeyState(VK_CONTROL) & 0x8000) m |= M_CTRL;
    if (GetAsyncKeyState(VK_MENU) & 0x8000) m |= M_ALT;
    if ((GetAsyncKeyState(VK_LWIN) & 0x8000) || (GetAsyncKeyState(VK_RWIN) & 0x8000)) m |= M_WIN;
    return m;
}

static int is_modifier(UINT32 vk) {
    switch (vk) {
    case VK_SHIFT: case VK_LSHIFT: case VK_RSHIFT:
    case VK_CONTROL: case VK_LCONTROL: case VK_RCONTROL:
    case VK_MENU: case VK_LMENU: case VK_RMENU:
    case VK_LWIN: case VK_RWIN:
        return 1;
    }
    return 0;
}

/* Same translation as keyboard_hook.translate_vk; Python finishes it (Enter, Tab, control codes). */
static UINT32 translate(UINT32 vk, UINT32 scan, UINT32 mods, WCHAR *out) {
    BYTE state[256];
    HWND fg;
    DWORD tid;
    int n;
    if (mods & M_WIN) return 0;
    ZeroMemory(state, sizeof state);
    if (mods & M_SHIFT) state[VK_SHIFT] = 0x80;
    if (mods & M_CTRL) state[VK_CONTROL] = 0x80;
    if (mods & M_ALT) state[VK_MENU] = 0x80;
    if (GetKeyState(VK_CAPITAL) & 1) state[VK_CAPITAL] = 0x01;
    fg = GetForegroundWindow();
    tid = fg ? GetWindowThreadProcessId(fg, NULL) : 0;
    n = ToUnicodeEx(vk, scan, state, out, 7, 0x4 /* no state change */, GetKeyboardLayout(tid));
    if (n <= 0) return 0;
    if (n > 7) n = 7;
    out[n] = 0;
    return (UINT32)n;
}

static UINT32 rule_for(UINT32 vk, UINT32 mods) {
    UINT32 when = 0;
    int i;
    AcquireSRWLockShared(&g_rules_lock);
    for (i = 0; i < g_nrules; i++)
        if (g_rules[i].vk == vk && g_rules[i].mods == mods) { when = g_rules[i].when; break; }
    ReleaseSRWLockShared(&g_rules_lock);
    return when;
}

static int push(const PFEvent *ev) {
    LONG head = g_head;
    if ((UINT32)(head - g_tail) >= RING_SIZE) return 0;
    g_ring[(UINT32)head & (RING_SIZE - 1)] = *ev;
    MemoryBarrier();
    InterlockedExchange(&g_head, head + 1);
    SetEvent(g_avail);
    return 1;
}

/* Wait until Python's answer for seq arrives (a signal can belong to an older, late answer). */
static int wait_answer(UINT32 seq, DWORD ms) {
    ULONGLONG end = GetTickCount64() + ms;
    for (;;) {
        ULONGLONG now = GetTickCount64();
        DWORD left = now >= end ? 0 : (DWORD)(end - now);
        if (WaitForSingleObject(g_reply, left) != WAIT_OBJECT_0) return -1;
        if ((UINT32)g_reply_seq == seq) return g_reply_val != 0;
    }
}

/* Wait for Python's answer to seq. Returns 1 = swallow. */
static int await_reply(UINT32 seq) {
    int r = wait_answer(seq, (DWORD)g_budget_ms);
    if (r >= 0) return r;
    /* timed out: withdraw the request unless Python is answering right now */
    if (InterlockedCompareExchange(&g_wait_seq, 0, (LONG)seq) == (LONG)seq) {
        g_stats.timeouts++;
        InterlockedExchange(&g_degraded, 1);
        return 0;
    }
    r = wait_answer(seq, 5);
    return r > 0;
}

static void record_time(LARGE_INTEGER t0) {
    LARGE_INTEGER t1;
    UINT64 us;
    UINT32 b = 0;
    QueryPerformanceCounter(&t1);
    us = (UINT64)(t1.QuadPart - t0.QuadPart) * 1000000u / (UINT64)g_freq.QuadPart;
    if (us > g_stats.max_us) g_stats.max_us = (UINT32)(us > 0xFFFFFFFFu ? 0xFFFFFFFFu : us);
    while (b < 31 && (1ull << b) <= us) b++;
    g_stats.hist[b]++;
}

static VOID CALLBACK flush_at_limit(PTP_CALLBACK_INSTANCE inst, PVOID ctx) {
    (void)inst;
    /* PhraseForge may have ended this block and begun the next one meanwhile: leave that one */
    if ((LONG)(ULONG_PTR)ctx == g_block_gen) pf_block_end((int)g_block_replay);
    InterlockedExchange(&g_flush_pending, 0);
}

/* Hold a key back while output runs. Returns 1 when held (swallow it).
 * Past the time limit, or when the buffer is nearly full, the key is still held, and a flush
 * on a pool thread sends (or drops) everything held, in order, and ends blocking. Letting the
 * new key pass at once (before v4) put it ahead of the keys still held: typed text came out
 * reordered. Only a completely full buffer lets a key pass. */
static int hold_back(const KBDLLHOOKSTRUCT *kb) {
    int held = 0, flush = 0;
    LONG gen;
    AcquireSRWLockExclusive(&g_block_lock);
    gen = g_block_gen;
    if (g_block) {
        if (g_nblocked < MAX_BLOCKED) {
            g_blocked[g_nblocked].vk = kb->vkCode;
            g_blocked[g_nblocked].scan = kb->scanCode;
            g_blocked[g_nblocked].flags = kb->flags;
            g_nblocked++;
            g_stats.blocked++;
            held = 1;
        }
        if (GetTickCount64() >= g_block_until || g_nblocked >= MAX_BLOCKED - 32) flush = 1;
    }
    ReleaseSRWLockExclusive(&g_block_lock);
    if (flush && InterlockedCompareExchange(&g_flush_pending, 1, 0) == 0
            && !TrySubmitThreadpoolCallback(flush_at_limit, (PVOID)(ULONG_PTR)gen, NULL)) {
        InterlockedExchange(&g_flush_pending, 0);
        InterlockedExchange(&g_block, 0);   /* no pool thread: stop holding (the old way) */
    }
    return held;
}

static void fill_input(INPUT *in, const PFKey *k) {
    ZeroMemory(in, sizeof *in);
    in->type = INPUT_KEYBOARD;
    in->ki.dwExtraInfo = REPLAY_MAGIC;
    if (k->vk == VK_PACKET) {             /* a Unicode character from an IME or on-screen keyboard */
        in->ki.wScan = (WORD)k->scan;
        in->ki.dwFlags = KEYEVENTF_UNICODE;
    } else {
        in->ki.wVk = (WORD)k->vk;
        in->ki.wScan = (WORD)k->scan;
        if (k->flags & LLKHF_EXTENDED) in->ki.dwFlags |= KEYEVENTF_EXTENDEDKEY;
    }
    if (k->flags & LLKHF_UP) in->ki.dwFlags |= KEYEVENTF_KEYUP;
}

/* replay = 0 (discard): send only key releases whose press was not held back, so a key the
 * user was already holding when output started does not stay down. */
static UINT32 send_keys(const PFKey *keys, int n, int replay) {
    INPUT in[MAX_BLOCKED];
    BYTE pressed[256];
    int i, m = 0;
    ZeroMemory(pressed, sizeof pressed);
    for (i = 0; i < n; i++) {
        UINT32 vk = keys[i].vk & 0xFF;
        if (!replay) {
            if (!(keys[i].flags & LLKHF_UP)) { pressed[vk] = 1; continue; }
            if (pressed[vk] || keys[i].vk == VK_PACKET) continue;
        }
        fill_input(&in[m++], &keys[i]);
    }
    return m ? SendInput((UINT)m, in, sizeof(INPUT)) : 0;
}

static LRESULT CALLBACK hook_proc(int code, WPARAM wp, LPARAM lp) {
    KBDLLHOOKSTRUCT *kb;
    PFEvent ev;
    LARGE_INTEGER t0;
    UINT32 when;
    int down, native = 0, wait, swallow = 0;
    if (code != HC_ACTION) return CallNextHookEx(NULL, code, wp, lp);
    kb = (KBDLLHOOKSTRUCT *)lp;
    if (kb->dwExtraInfo == g_magic) return CallNextHookEx(NULL, code, wp, lp);   /* our own output */
    if (g_block && kb->dwExtraInfo != REPLAY_MAGIC && hold_back(kb)) return 1;
    if ((kb->flags & LLKHF_INJECTED) && !g_pass_foreign) return CallNextHookEx(NULL, code, wp, lp);
    QueryPerformanceCounter(&t0);
    down = (wp == WM_KEYDOWN || wp == WM_SYSKEYDOWN);
    ZeroMemory(&ev, sizeof ev);
    ev.vk = kb->vkCode;
    ev.scan = kb->scanCode;
    ev.flags = kb->flags;
    ev.time = kb->time;
    ev.mods = current_mods();
    if (down) ev.status |= ST_DOWN;
    if (kb->flags & LLKHF_INJECTED) ev.status |= ST_INJECTED;
    if (kb->flags & LLKHF_EXTENDED) ev.status |= ST_EXTENDED;
    if (down && !is_modifier(ev.vk)) ev.nchars = translate(ev.vk, ev.scan, ev.mods, ev.chars);

    if (ev.vk < 256 && !down && g_swallow_up[ev.vk]) {
        g_swallow_up[ev.vk] = 0;
        native = 1;
    } else if (down && !is_modifier(ev.vk)) {
        when = rule_for(ev.vk, ev.mods);
        if ((when & W_ALWAYS) || ((when & W_DEGRADED) && g_degraded)) {
            native = 1;
            if (ev.vk < 256) g_swallow_up[ev.vk] = 1;
        }
    }
    if (native) {
        ev.status |= ST_NATIVE;
        swallow = 1;
        g_stats.native_swallowed++;
    }
    wait = !native && !g_degraded;
    if (wait) ev.status |= ST_WAITED;
    ev.seq = ++g_seq;
    if (ev.seq == 0) ev.seq = ++g_seq;          /* 0 means "none" in g_wait_seq */
    if (wait) InterlockedExchange(&g_wait_seq, (LONG)ev.seq);
    if (!push(&ev)) {
        g_stats.dropped++;
        if (wait) InterlockedExchange(&g_wait_seq, 0);
        wait = 0;
    }
    g_stats.events++;
    if (wait) {
        g_stats.waited++;
        swallow = await_reply(ev.seq);
    }
    record_time(t0);
    if (swallow) return 1;
    return CallNextHookEx(NULL, code, wp, lp);
}

static DWORD WINAPI hook_thread(LPVOID unused) {
    MSG msg;
    HMODULE self = NULL;
    (void)unused;
    PeekMessageW(&msg, NULL, 0, 0, PM_NOREMOVE);       /* create the message queue */
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                       (LPCWSTR)(const void *)&g_ring, &self);   /* any address inside this DLL */
    g_hook = SetWindowsHookExW(WH_KEYBOARD_LL, hook_proc, self, 0);
    g_start_error = g_hook ? 0 : GetLastError();
    SetEvent(g_ready);
    if (!g_hook) return 1;
    while (GetMessageW(&msg, NULL, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    UnhookWindowsHookEx(g_hook);
    g_hook = NULL;
    return 0;
}

PF_API int pf_version(void) { return PF_VERSION; }

/* budget_ms: how long a key waits for Python's decision; magic: dwExtraInfo of our own output. */
PF_API void pf_set_options(UINT32 budget_ms, int pass_foreign_injected, ULONG_PTR magic) {
    if (budget_ms < 1) budget_ms = 1;
    if (budget_ms > 300) budget_ms = 300;        /* far below LowLevelHooksTimeout */
    InterlockedExchange(&g_budget_ms, (LONG)budget_ms);
    InterlockedExchange(&g_pass_foreign, pass_foreign_injected ? 1 : 0);
    g_magic = magic;
}

PF_API int pf_set_rules(const PFRule *rules, int n) {
    if (n < 0) n = 0;
    if (n > MAX_RULES) n = MAX_RULES;
    AcquireSRWLockExclusive(&g_rules_lock);
    if (n && rules) CopyMemory(g_rules, rules, sizeof(PFRule) * (SIZE_T)n);
    g_nrules = n;
    ReleaseSRWLockExclusive(&g_rules_lock);
    return n;
}

/* Returns 0 on success, else the Windows error code. */
PF_API DWORD pf_start(void) {
    if (g_running) return 0;
    QueryPerformanceFrequency(&g_freq);
    if (!g_avail) g_avail = CreateEventW(NULL, FALSE, FALSE, NULL);
    if (!g_reply) g_reply = CreateEventW(NULL, FALSE, FALSE, NULL);
    if (!g_ready) g_ready = CreateEventW(NULL, TRUE, FALSE, NULL);
    if (!g_avail || !g_reply || !g_ready) return GetLastError();
    g_head = g_tail = 0;
    g_wait_seq = 0;
    g_degraded = 0;
    ZeroMemory(g_swallow_up, sizeof g_swallow_up);
    ResetEvent(g_reply);
    ResetEvent(g_ready);
    g_thread = CreateThread(NULL, 0, hook_thread, NULL, 0, &g_tid);
    if (!g_thread) return GetLastError();
    WaitForSingleObject(g_ready, 5000);
    if (!g_hook) {
        WaitForSingleObject(g_thread, 1000);
        CloseHandle(g_thread);
        g_thread = NULL;
        return g_start_error ? g_start_error : ERROR_GEN_FAILURE;
    }
    SetThreadPriority(g_thread, THREAD_PRIORITY_TIME_CRITICAL);
    InterlockedExchange(&g_running, 1);
    return 0;
}

PF_API void pf_stop(void) {
    if (!g_thread) return;
    pf_block_end(1);                            /* never keep the user's keys */
    InterlockedExchange(&g_running, 0);
    PostThreadMessageW(g_tid, WM_QUIT, 0, 0);
    WaitForSingleObject(g_thread, 3000);
    CloseHandle(g_thread);
    g_thread = NULL;
    SetEvent(g_avail);                          /* wake the reader so it sees "stopped" */
}

/* Next queued event. Returns 1 = event, 0 = timeout, -1 = the hook is stopped. */
PF_API int pf_next(PFEvent *out, DWORD timeout_ms) {
    for (;;) {
        LONG tail = g_tail;
        if (tail != g_head) {
            MemoryBarrier();
            *out = g_ring[(UINT32)tail & (RING_SIZE - 1)];
            InterlockedExchange(&g_tail, tail + 1);
            if (tail + 1 == g_head) InterlockedExchange(&g_degraded, 0);   /* caught up */
            return 1;
        }
        if (!g_running) return -1;
        if (WaitForSingleObject(g_avail, timeout_ms) != WAIT_OBJECT_0) return 0;
    }
}

/* Python's decision for an event with ST_WAITED. Returns 0 if the hook had stopped waiting. */
PF_API int pf_reply(UINT32 seq, int swallow) {
    if (InterlockedCompareExchange(&g_wait_seq, 0, (LONG)seq) != (LONG)seq) {
        g_stats.late_replies++;
        return 0;
    }
    InterlockedExchange(&g_reply_val, swallow ? 1 : 0);
    InterlockedExchange(&g_reply_seq, (LONG)seq);
    SetEvent(g_reply);
    return 1;
}

/* FR-TRG-06: hold the user's keys back from now on, for at most max_ms; replay says what a
 * flush at the limit does with them (the same as the pf_block_end PhraseForge will call).
 * Keys still held from an earlier block are kept: only pf_block_end sends or drops them
 * (before v4 they were thrown away here). */
PF_API void pf_block_begin2(UINT32 max_ms, int replay) {
    if (max_ms < 100) max_ms = 100;
    if (max_ms > 120000) max_ms = 120000;
    AcquireSRWLockExclusive(&g_block_lock);
    g_block_until = GetTickCount64() + max_ms;
    InterlockedIncrement(&g_block_gen);
    InterlockedExchange(&g_block_replay, replay ? 1 : 0);
    InterlockedExchange(&g_block, 1);
    ReleaseSRWLockExclusive(&g_block_lock);
}

PF_API void pf_block_begin(UINT32 max_ms) { pf_block_begin2(max_ms, 1); }

/* Stop holding keys back. replay = 1 sends them again in order (marked REPLAY_MAGIC, so the
 * hook lets them through and PhraseForge sees them as typing); 0 drops them. Keys typed while
 * the replay is being sent are held too and sent after it. Returns the number of keys sent. */
PF_API UINT32 pf_block_end(int replay) {
    static PFKey batch[MAX_BLOCKED];      /* one caller at a time: g_end_lock */
    UINT32 sent = 0;
    AcquireSRWLockExclusive(&g_end_lock);
    for (;;) {
        int n;
        AcquireSRWLockExclusive(&g_block_lock);
        n = g_nblocked;
        if (n) CopyMemory(batch, g_blocked, sizeof(PFKey) * (SIZE_T)n);
        g_nblocked = 0;
        if (!n) InterlockedExchange(&g_block, 0);
        ReleaseSRWLockExclusive(&g_block_lock);
        if (!n) break;
        sent += send_keys(batch, n, replay);
    }
    g_stats.replayed += sent;
    ReleaseSRWLockExclusive(&g_end_lock);
    return sent;
}

PF_API void pf_stats(PFStats *out) {
    UINT64 total = 0, acc = 0;
    UINT32 b;
    PFStats s = g_stats;
    for (b = 0; b < 32; b++) total += s.hist[b];
    s.p99_us = 0;
    if (total) {
        for (b = 0; b < 32; b++) {
            acc += s.hist[b];
            if (acc * 100 >= total * 99) { s.p99_us = 1u << b; break; }
        }
    }
    s.degraded = (UINT32)g_degraded;
    s.running = (UINT32)g_running;
    *out = s;
}

/* ---------------------------------------------------------------- mouse (v3, macro recorder)
 * WH_MOUSE_LL for the macro recorder (recorder.py), so recording never makes the mouse lag.
 * It only observes: every event is passed on at once. Left and right clicks and the wheel
 * are queued for Python, without PhraseForge's own input, input other programs inject and
 * clicks on PhraseForge's own windows (the recording bar's Stop button). Middle clicks are
 * not recorded (replayed they would be left clicks, R58). */
#define MRING_SIZE 512u                 /* power of two */
#define MK_LEFT 1u
#define MK_RIGHT 2u
#define MK_WHEEL 3u

typedef struct {
    UINT32 kind;                        /* MK_LEFT | MK_RIGHT | MK_WHEEL */
    INT32 x, y;                         /* screen point, physical pixels */
    INT32 rx, ry;                       /* point inside the top-level window under it */
    UINT32 has_rel;                     /* rx, ry are valid */
    UINT32 mouse_data;                  /* MSLLHOOKSTRUCT.mouseData (wheel delta in the high word) */
    UINT32 time;
} PFMouse;

static PFMouse g_mring[MRING_SIZE];
static volatile LONG g_mhead, g_mtail, g_mrunning, g_mdropped;
static HANDLE g_mavail, g_mready, g_mthread;
static HHOOK g_mhook;
static DWORD g_mtid, g_mstart_error, g_own_pid;

static LRESULT CALLBACK mouse_proc(int code, WPARAM wp, LPARAM lp) {
    if (code == HC_ACTION && (wp == WM_LBUTTONDOWN || wp == WM_RBUTTONDOWN || wp == WM_MOUSEWHEEL)) {
        const MSLLHOOKSTRUCT *ms = (const MSLLHOOKSTRUCT *)lp;
        if (ms->dwExtraInfo != g_magic && !(ms->flags & LLMHF_INJECTED)) {
            HWND hit = WindowFromPoint(ms->pt);
            HWND root = hit ? GetAncestor(hit, GA_ROOT) : NULL;
            DWORD pid = 0;
            if (root) GetWindowThreadProcessId(root, &pid);
            if (!root || pid != g_own_pid) {
                LONG head = g_mhead;
                if ((UINT32)(head - g_mtail) < MRING_SIZE) {
                    PFMouse *m = &g_mring[(UINT32)head & (MRING_SIZE - 1)];
                    RECT r;
                    ZeroMemory(m, sizeof *m);
                    m->kind = wp == WM_LBUTTONDOWN ? MK_LEFT : wp == WM_RBUTTONDOWN ? MK_RIGHT : MK_WHEEL;
                    m->x = ms->pt.x;
                    m->y = ms->pt.y;
                    if (root && GetWindowRect(root, &r)) {
                        m->rx = ms->pt.x - r.left;
                        m->ry = ms->pt.y - r.top;
                        m->has_rel = 1;
                    }
                    m->mouse_data = ms->mouseData;
                    m->time = ms->time;
                    MemoryBarrier();
                    InterlockedExchange(&g_mhead, head + 1);
                    SetEvent(g_mavail);
                } else {
                    InterlockedIncrement(&g_mdropped);
                }
            }
        }
    }
    return CallNextHookEx(NULL, code, wp, lp);
}

static DWORD WINAPI mouse_thread(LPVOID unused) {
    MSG msg;
    HMODULE self = NULL;
    (void)unused;
    PeekMessageW(&msg, NULL, 0, 0, PM_NOREMOVE);
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                       (LPCWSTR)(const void *)&g_mring, &self);
    g_mhook = SetWindowsHookExW(WH_MOUSE_LL, mouse_proc, self, 0);
    g_mstart_error = g_mhook ? 0 : GetLastError();
    SetEvent(g_mready);
    if (!g_mhook) return 1;
    while (GetMessageW(&msg, NULL, 0, 0) > 0) DispatchMessageW(&msg);
    UnhookWindowsHookEx(g_mhook);
    g_mhook = NULL;
    return 0;
}

/* magic: dwExtraInfo of PhraseForge's own output. Returns 0 on success, else the Windows error. */
PF_API DWORD pf_mouse_start(ULONG_PTR magic) {
    if (g_mrunning) return 0;
    if (!g_magic) g_magic = magic;
    g_own_pid = GetCurrentProcessId();
    if (!g_mavail) g_mavail = CreateEventW(NULL, FALSE, FALSE, NULL);
    if (!g_mready) g_mready = CreateEventW(NULL, TRUE, FALSE, NULL);
    if (!g_mavail || !g_mready) return GetLastError();
    g_mhead = g_mtail = 0;
    g_mdropped = 0;
    ResetEvent(g_mready);
    g_mthread = CreateThread(NULL, 0, mouse_thread, NULL, 0, &g_mtid);
    if (!g_mthread) return GetLastError();
    WaitForSingleObject(g_mready, 5000);
    if (!g_mhook) {
        WaitForSingleObject(g_mthread, 1000);
        CloseHandle(g_mthread);
        g_mthread = NULL;
        return g_mstart_error ? g_mstart_error : ERROR_GEN_FAILURE;
    }
    SetThreadPriority(g_mthread, THREAD_PRIORITY_TIME_CRITICAL);
    InterlockedExchange(&g_mrunning, 1);
    return 0;
}

PF_API void pf_mouse_stop(void) {
    if (!g_mthread) return;
    InterlockedExchange(&g_mrunning, 0);
    PostThreadMessageW(g_mtid, WM_QUIT, 0, 0);
    WaitForSingleObject(g_mthread, 3000);
    CloseHandle(g_mthread);
    g_mthread = NULL;
    SetEvent(g_mavail);
}

/* Next queued mouse event. Returns 1 = event, 0 = timeout, -1 = stopped (queue empty). */
PF_API int pf_mouse_next(PFMouse *out, DWORD timeout_ms) {
    for (;;) {
        LONG tail = g_mtail;
        if (tail != g_mhead) {
            MemoryBarrier();
            *out = g_mring[(UINT32)tail & (MRING_SIZE - 1)];
            InterlockedExchange(&g_mtail, tail + 1);
            return 1;
        }
        if (!g_mrunning) return -1;
        if (WaitForSingleObject(g_mavail, timeout_ms) != WAIT_OBJECT_0) return 0;
    }
}

PF_API UINT32 pf_mouse_dropped(void) { return (UINT32)g_mdropped; }
