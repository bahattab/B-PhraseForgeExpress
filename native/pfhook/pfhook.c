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
 * Build (x64 Developer Command Prompt):
 *   cl /nologo /O2 /W4 /LD pfhook.c /Fe:pfhook.dll user32.lib
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#define PF_API __declspec(dllexport)
#define PF_VERSION 2

#define RING_SIZE 1024u                 /* power of two */
#define MAX_RULES 256

/* PFEvent.status bits */
#define ST_DOWN      0x01u
#define ST_INJECTED  0x02u
#define ST_EXTENDED  0x04u
#define ST_WAITED    0x08u              /* the hook waited for Python's decision */
#define ST_NATIVE    0x10u              /* swallowed by the rule table, no decision asked */
#define ST_BLOCKED   0x20u              /* held while a phrase is typed (pf_set_block, FR-TRG-06) */

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
} PFStats;

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
static BYTE g_block_up[256];            /* key-up of a key-down held by pf_set_block */
static volatile LONG g_block;           /* 1 = hold every physical key (output running) */

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

static LRESULT CALLBACK hook_proc(int code, WPARAM wp, LPARAM lp) {
    KBDLLHOOKSTRUCT *kb;
    PFEvent ev;
    LARGE_INTEGER t0;
    UINT32 when;
    int down, native = 0, wait, swallow = 0;
    if (code != HC_ACTION) return CallNextHookEx(NULL, code, wp, lp);
    kb = (KBDLLHOOKSTRUCT *)lp;
    if (kb->dwExtraInfo == g_magic) return CallNextHookEx(NULL, code, wp, lp);   /* our own output */
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

    if (down && !g_block && !(kb->flags & LLKHF_INJECTED) && ev.vk < 256)
        g_block_up[ev.vk] = 0;                  /* this down passed: so does its up */
    if (!(kb->flags & LLKHF_INJECTED) && ev.vk < 256 && (down ? g_block : g_block_up[ev.vk])) {
        /* keyboard blocking: hold the key; Python replays it after the output */
        g_block_up[ev.vk] = (BYTE)(down ? 1 : 0);
        ev.status |= ST_BLOCKED;
        native = 1;
    } else if (ev.vk < 256 && !down && g_swallow_up[ev.vk]) {
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

/* on = 1: swallow every physical key-down (and its key-up) and queue it with ST_BLOCKED. */
PF_API void pf_set_block(int on) { InterlockedExchange(&g_block, on ? 1 : 0); }

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
    ZeroMemory(g_block_up, sizeof g_block_up);
    g_block = 0;
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
