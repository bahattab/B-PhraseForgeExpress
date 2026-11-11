"""Windows hooks for the macro recorder (recorder.py): keys through the existing
low-level keyboard hook, mouse clicks and the wheel through WH_MOUSE_LL.

Input PhraseForge sends itself (dwExtraInfo == INJECT_MAGIC) is not recorded, and
neither are clicks on PhraseForge's own windows (the recording bar's Stop button).
"""
from __future__ import annotations

import ctypes
import logging
import os
import threading
from ctypes import wintypes as wt

from phraseforge.platform._win32 import HOOKPROC, INJECT_MAGIC, WM_QUIT, kernel32, user32
from phraseforge.platform.keyboard_hook import KeyboardHook
from phraseforge.recorder import wheel_delta

log = logging.getLogger(__name__)

WH_MOUSE_LL = 14
WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN, WM_MOUSEWHEEL = 0x201, 0x204, 0x207, 0x20A
GA_ROOT = 2
LLMHF_INJECTED = 0x1
BUTTONS = {WM_LBUTTONDOWN: "left", WM_RBUTTONDOWN: "right", WM_MBUTTONDOWN: "middle"}


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wt.POINT), ("mouseData", wt.DWORD), ("flags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


try:                                                # 64-bit window handles: declare the signatures
    user32.WindowFromPoint.restype = wt.HWND
    user32.WindowFromPoint.argtypes = [wt.POINT]
    user32.GetAncestor.restype = wt.HWND
    user32.GetAncestor.argtypes = [wt.HWND, wt.UINT]
    user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    user32.GetWindowThreadProcessId.restype = wt.DWORD
except AttributeError:                              # not Windows (tests import the pure helpers)
    pass


def _window_at(x: int, y: int):
    hwnd = user32.WindowFromPoint(wt.POINT(x, y))
    return user32.GetAncestor(hwnd, GA_ROOT) if hwnd else None


def _own_window(hwnd) -> bool:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value == os.getpid()


class MouseHook:
    def __init__(self, recorder):
        self.recorder = recorder
        self._proc = HOOKPROC(self._callback)
        self._thread = None
        self._tid = 0
        self._failed = False
        self._ready = threading.Event()

    def start(self) -> None:
        self._failed = False
        self._thread = threading.Thread(target=self._run, name="pf-record-mouse", daemon=True)
        self._thread.start()
        self._ready.wait(5)
        if self._failed or not self._ready.is_set():
            raise OSError("the mouse hook could not be installed")   # no silent recording without clicks (R157)

    def stop(self) -> None:
        if self._thread and self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._thread.join(3)
        self._thread = None

    def _run(self) -> None:
        self._tid = kernel32.GetCurrentThreadId()
        msg = wt.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, kernel32.GetModuleHandleW(None), 0)
        self._ready.set()
        if not hook:
            log.error("mouse hook failed: %s", ctypes.get_last_error())
            self._failed = True
            return
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnhookWindowsHookEx(hook)

    def _callback(self, ncode, wparam, lparam):
        # middle clicks are not recorded: replayed they would be left clicks (R58)
        if ncode == 0 and wparam in (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MOUSEWHEEL):
            try:
                ms = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                # neither PhraseForge's own input nor clicks other programs inject
                # (LLMHF_INJECTED), like the keyboard hook (R58)
                if ms.dwExtraInfo != INJECT_MAGIC and not (ms.flags & LLMHF_INJECTED):
                    x, y = ms.pt.x, ms.pt.y
                    root = _window_at(x, y)
                    if root is None or not _own_window(root):
                        if wparam == WM_MOUSEWHEEL:
                            self.recorder.wheel(wheel_delta(ms.mouseData))
                        else:
                            rel = None
                            rect = wt.RECT()
                            if root and user32.GetWindowRect(root, ctypes.byref(rect)):
                                rel = (x - rect.left, y - rect.top)
                            self.recorder.click(BUTTONS[wparam], x, y, rel)
            except Exception:
                log.exception("mouse hook callback failed")
        return user32.CallNextHookEx(None, ncode, wparam, lparam)


class RecordSession:
    """Both hooks around one Recorder. The keyboard hook swallows the stop hotkey."""

    def __init__(self, recorder):
        self.recorder = recorder
        self.keys = KeyboardHook(lambda ev: ev.down and recorder.key(ev.vk, ev.char, ev.modifiers),
                                 pass_foreign_injected=False)
        from phraseforge.platform.native_hook import make_mouse_hook
        self.mouse = make_mouse_hook(recorder)       # pfhook.dll when it loads (G-05)
        self.mouse_failed = False

    def start(self) -> None:
        self.recorder.start()
        self.keys.start()
        try:
            self.mouse.start()
        except OSError as e:                         # the native hook failed: use the Python one
            log.warning("native mouse hook failed (%s); using the Python hook", e)
            self.mouse = MouseHook(self.recorder)
            try:
                self.mouse.start()
            except OSError as e2:                    # neither hook: the keys are still recorded
                log.error("no mouse hook could be installed (%s); clicks will not be recorded", e2)
                self.mouse_failed = True

    def stop(self) -> None:
        self.keys.stop()
        self.mouse.stop()
