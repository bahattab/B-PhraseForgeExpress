"""Global low-level keyboard hook (WH_KEYBOARD_LL) on its own thread."""
from __future__ import annotations

import ctypes
import logging
import threading
from dataclasses import dataclass, field
from typing import Callable

from ctypes import wintypes as wt

from phraseforge.platform import keys as K
from phraseforge.platform._win32 import (
    HOOKPROC, INJECT_MAGIC, KBDLLHOOKSTRUCT, WM_QUIT, kernel32, user32,
)

log = logging.getLogger(__name__)

WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105
LLKHF_INJECTED = 0x10
LLKHF_EXTENDED = 0x01
TOUNICODE_NO_STATE_CHANGE = 0x4  # Windows 10 1607+: don't disturb dead-key state


@dataclass
class KeyEvent:
    vk: int
    scan: int
    char: str | None          # translated character, None for non-printing keys
    down: bool
    injected: bool
    modifiers: set[str] = field(default_factory=set)   # {"ctrl","alt","shift","win"}
    extended: bool = False
    # Native hook only (native_hook.py): the key already reached the program because Python
    # did not answer in time (late), or the hook swallowed it from its rule table (native).
    late: bool = False
    native: bool = False

    @property
    def altgr(self) -> bool:
        return "ctrl" in self.modifiers and "alt" in self.modifiers and self.char is not None


def _pressed(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def current_modifiers() -> set[str]:
    mods = set()
    if _pressed(0x10):
        mods.add("shift")
    if _pressed(0x11):
        mods.add("ctrl")
    if _pressed(0x12):
        mods.add("alt")
    if _pressed(0x5B) or _pressed(0x5C):
        mods.add("win")
    return mods


def translate_vk(vk: int, scan: int, mods: set[str]) -> str | None:
    """Translate a key press to text with the foreground window's keyboard layout."""
    if "win" in mods:
        return None
    hwnd = user32.GetForegroundWindow()
    tid = user32.GetWindowThreadProcessId(hwnd, None) if hwnd else 0
    hkl = user32.GetKeyboardLayout(tid)
    state = (ctypes.c_ubyte * 256)()
    if "shift" in mods:
        state[0x10] = 0x80
    if "ctrl" in mods:
        state[0x11] = 0x80
    if "alt" in mods:
        state[0x12] = 0x80
    if user32.GetKeyState(0x14) & 1:      # caps lock toggle
        state[0x14] = 0x01
    buf = ctypes.create_unicode_buffer(8)
    n = user32.ToUnicodeEx(vk, scan, state, buf, 8, TOUNICODE_NO_STATE_CHANGE, hkl)
    if n <= 0:
        return None
    return finish_char(vk, buf.value[:n])


def finish_char(vk: int, text: str) -> str | None:
    """The text ToUnicodeEx gave for a key, as the trigger layer wants it."""
    if not text:
        return None
    if vk == K.VK_RETURN:
        return "\n"
    if vk == K.VK_TAB:
        return "\t"
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in text):   # ctrl+letter control codes
        return None
    return text


LLKHF_UP = 0x80
VK_PACKET = 0xE7
REPLAY_MAGIC = 0x50465252          # same marker as pfhook.dll: keys sent again after output
MAX_BLOCKED = 512


def keys_to_send(keys: list[tuple[int, int, int]], replay: bool) -> list[tuple[int, int, int]]:
    """Held-back keys (vk, scan, LLKHF flags) to send when output ends (FR-TRG-06). replay:
    all of them in order. Discard: only releases of keys pressed before output started, so a
    key the user was holding does not stay down."""
    if replay:
        return list(keys)
    pressed, out = set(), []
    for vk, scan, flags in keys:
        if not flags & LLKHF_UP:
            pressed.add(vk)
        elif vk not in pressed and vk != VK_PACKET:
            out.append((vk, scan, flags))
    return out


def send_held_keys(keys: list[tuple[int, int, int]]) -> int:
    from phraseforge.platform._win32 import INPUT, KEYBDINPUT
    KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x1, 0x2, 0x4
    if not keys:
        return 0
    arr = (INPUT * len(keys))()
    for i, (vk, scan, flags) in enumerate(keys):
        f = KEYEVENTF_KEYUP if flags & LLKHF_UP else 0
        if vk == VK_PACKET:
            ki = KEYBDINPUT(0, scan, f | KEYEVENTF_UNICODE, 0, REPLAY_MAGIC)
        else:
            ki = KEYBDINPUT(vk, scan, f | (KEYEVENTF_EXTENDEDKEY if flags & LLKHF_EXTENDED else 0), 0,
                            REPLAY_MAGIC)
        arr[i].type = 1
        arr[i].ki = ki
    return user32.SendInput(len(keys), arr, ctypes.sizeof(INPUT))


class KeyboardHook:
    """Calls on_key(KeyEvent) for every key event; return True to swallow it.
    Events we injected ourselves (dwExtraInfo == INJECT_MAGIC) are passed
    through without calling on_key."""

    def __init__(self, on_key: Callable[[KeyEvent], bool], pass_foreign_injected: bool = True):
        self.on_key = on_key
        self.pass_foreign_injected = pass_foreign_injected  # report other apps' injected keys
        self._thread: threading.Thread | None = None
        self._tid = 0
        self._hook = None
        self._proc = HOOKPROC(self._callback)   # keep a reference
        self._ready = threading.Event()
        self._block_lock = threading.Lock()
        self._blocking = False
        self._block_until = 0.0
        self._held: list[tuple[int, int, int]] = []
        self._block_replay = True
        self._block_gen = 0
        self._flushing = False
        self._end_lock = threading.Lock()

    # FR-TRG-06 (same contract as NativeKeyboardHook; best effort, the callback runs Python)
    def begin_block(self, max_ms: int = 10000, replay: bool = True) -> None:
        import time
        with self._block_lock:
            # keys still held from an earlier block stay: only end_block sends or drops them (R161)
            self._blocking = True
            self._block_gen += 1
            self._block_replay = replay
            self._block_until = time.monotonic() + max(0.1, max_ms / 1000)

    def end_block(self, replay: bool = True) -> int:
        sent = 0
        with self._end_lock:                    # end_block and the flush at the limit, one at a time
            while True:
                with self._block_lock:
                    batch, self._held = self._held, []
                    if not batch:
                        self._blocking = False
                        break
                sent += send_held_keys(keys_to_send(batch, replay))
        return sent

    def _hold_back(self, kb) -> bool:
        """Past the time limit or with the buffer nearly full the key is still held, and a
        thread sends everything held, in order (R161: letting it pass at once put it ahead of
        the keys still held). Only a full buffer lets a key pass."""
        import time
        with self._block_lock:
            if not self._blocking:
                return False
            held = len(self._held) < MAX_BLOCKED
            if held:
                self._held.append((kb.vkCode, kb.scanCode, kb.flags))
            flush = time.monotonic() >= self._block_until or len(self._held) >= MAX_BLOCKED - 32
            start = flush and not self._flushing
            if start:
                self._flushing = True
            gen = self._block_gen
        if start:
            threading.Thread(target=self._flush_at_limit, args=(gen,), name="pf-block-flush",
                             daemon=True).start()
        return held

    def _flush_at_limit(self, gen: int) -> None:
        try:
            if gen == self._block_gen:          # not a newer block PhraseForge began meanwhile
                self.end_block(self._block_replay)
        finally:
            with self._block_lock:
                self._flushing = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="pf-keyboard-hook", daemon=True)
        self._thread.start()
        self._ready.wait(5)

    def stop(self) -> None:
        if self._thread and self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._thread.join(3)
        self._thread = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and self._hook)

    def _run(self) -> None:
        self._tid = kernel32.GetCurrentThreadId()
        msg = wt.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # create message queue
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, kernel32.GetModuleHandleW(None), 0)
        self._ready.set()
        if not self._hook:
            log.error("SetWindowsHookExW failed: %s", ctypes.get_last_error())
            return
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def _callback(self, ncode: int, wparam: int, lparam: int) -> int:
        if ncode == 0:
            try:
                kb = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if (self._blocking and kb.dwExtraInfo not in (INJECT_MAGIC, REPLAY_MAGIC)
                        and self._hold_back(kb)):
                    return 1
                injected = bool(kb.flags & LLKHF_INJECTED)
                if kb.dwExtraInfo != INJECT_MAGIC and (not injected or self.pass_foreign_injected):
                    down = wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)
                    mods = current_modifiers()
                    char = None
                    if down and kb.vkCode not in K.MODIFIER_VKS:
                        char = translate_vk(kb.vkCode, kb.scanCode, mods)
                    ev = KeyEvent(vk=kb.vkCode, scan=kb.scanCode, char=char, down=down, injected=injected,
                                  modifiers=mods, extended=bool(kb.flags & LLKHF_EXTENDED))
                    if self.on_key(ev):
                        return 1
            except Exception:  # never let an exception escape into the hook chain
                log.exception("keyboard hook callback failed")
        return user32.CallNextHookEx(None, ncode, wparam, lparam)
