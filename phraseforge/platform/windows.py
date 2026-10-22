"""Foreground window info, program launching, caret position, selected text."""
from __future__ import annotations

import ctypes
import os
import time

from ctypes import wintypes as wt

from phraseforge.platform._win32 import (
    GUITHREADINFO, SHELLEXECUTEINFOW, ULONG_PTR, WNDENUMPROC, kernel32, shell32, user32,
)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SEE_MASK_NOCLOSEPROCESS = 0x00000040
SEE_MASK_FLAG_NO_UI = 0x00000400
INFINITE = 0xFFFFFFFF
EM_GETPASSWORDCHAR = 0x00D2
SMTO_ABORTIFHUNG = 0x0002


def _window_text(hwnd) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def window_class(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def process_exe(pid: int) -> str:
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        size = wt.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(h)


def foreground_app() -> tuple[str, str]:
    """(exe file name in lower case, window title) of the foreground window."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", ""
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe = os.path.basename(process_exe(pid.value)).lower()
    return exe, _window_text(hwnd)


def find_window(title_substring: str) -> int | None:
    needle = title_substring.lower()
    found: list[int] = []

    @WNDENUMPROC
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and needle in _window_text(hwnd).lower():
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def wait_for_window(title_substring: str, timeout_s: float = 10) -> bool:
    """Wait until a visible window whose title contains the text exists."""
    deadline = time.monotonic() + max(0.0, timeout_s)
    while True:
        if find_window(title_substring):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def run_program(cmd: str, args: str = "", wait: bool = False, workdir: str = "") -> int:
    """Start a program, document or URL through the shell. Returns the exit
    code when wait=True, else 0. Raises OSError on failure."""
    sei = SHELLEXECUTEINFOW()
    sei.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
    sei.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_FLAG_NO_UI
    sei.lpVerb = "open"
    sei.lpFile = cmd
    sei.lpParameters = args or None
    sei.lpDirectory = workdir or None
    sei.nShow = 1
    if not shell32.ShellExecuteExW(ctypes.byref(sei)):
        raise OSError(ctypes.get_last_error(), f"could not start {cmd!r}")
    code = 0
    if sei.hProcess:
        try:
            if wait:
                kernel32.WaitForSingleObject(sei.hProcess, INFINITE)
                ec = wt.DWORD()
                kernel32.GetExitCodeProcess(sei.hProcess, ctypes.byref(ec))
                code = ec.value
        finally:
            kernel32.CloseHandle(sei.hProcess)
    return code


def open_target(target: str) -> None:
    """Open a file, folder or URL with its default handler."""
    os.startfile(target)  # noqa: S606 - user-configured target


def _gui_info() -> GUITHREADINFO | None:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    tid = user32.GetWindowThreadProcessId(hwnd, None)
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(GUITHREADINFO)
    if not user32.GetGUIThreadInfo(tid, ctypes.byref(info)):
        return None
    return info


def caret_position() -> tuple[int, int] | None:
    """Screen position just below the text caret, or None when the app does
    not expose a Win32 caret (many browsers / Electron apps)."""
    info = _gui_info()
    if not info or not info.hwndCaret:
        return None
    pt = wt.POINT(info.rcCaret.left, info.rcCaret.bottom)
    if not user32.ClientToScreen(info.hwndCaret, ctypes.byref(pt)):
        return None
    if pt.x == 0 and pt.y == 0:
        return None
    return pt.x, pt.y


def mouse_position() -> tuple[int, int]:
    pt = wt.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def focused_is_password() -> bool:
    """Best effort: True if the focused control is a classic password edit."""
    info = _gui_info()
    if not info or not info.hwndFocus:
        return False
    res = ULONG_PTR()
    ok = user32.SendMessageTimeoutW(info.hwndFocus, EM_GETPASSWORDCHAR, 0, 0, SMTO_ABORTIFHUNG, 50,
                                    ctypes.byref(res))
    return bool(ok and res.value)


def get_selected_text(timeout_s: float = 0.4) -> str:
    """Copy the current selection of the foreground app via Ctrl+C, then
    restore the previous clipboard contents."""
    from phraseforge.platform import clipboard, sendinput
    snap = clipboard.save_all()
    try:
        before = clipboard.sequence_number()
        sendinput.release_modifiers()
        sendinput.send_keys("ctrl+c")
        deadline = time.monotonic() + timeout_s
        while clipboard.sequence_number() == before and time.monotonic() < deadline:
            time.sleep(0.02)
        if clipboard.sequence_number() == before:
            return ""
        return clipboard.get_text()
    finally:
        clipboard.restore(snap)
