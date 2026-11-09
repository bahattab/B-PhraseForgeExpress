"""Session and privilege checks for the trigger layer (PRD FR-INP-04, FR-INP-06).

session_state(): "active", "locked" (Win+L, lock screen) or "disconnected" (a Remote
Desktop session that was disconnected), from Windows' own session flags.

window_elevated(hwnd): the program owning the window runs at a higher integrity level
than PhraseForge (for example "Run as administrator"). Windows (UIPI) then keeps our
keyboard hook from seeing its keys and blocks the keys we would type into it.
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
from ctypes import wintypes as wt

log = logging.getLogger(__name__)

WTS_CURRENT_SERVER_HANDLE = 0
WTS_CURRENT_SESSION = 0xFFFFFFFF
WTSDisconnected = 4
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TokenElevation, TokenIntegrityLevel = 20, 25
ERROR_ACCESS_DENIED = 5

ACTIVE, LOCKED, DISCONNECTED = "active", "locked", "disconnected"


def _dlls():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
    user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    wtsapi32.WTSQuerySessionInformationW.argtypes = [wt.HANDLE, wt.DWORD, ctypes.c_int,
                                                     ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wt.DWORD)]
    wtsapi32.WTSFreeMemory.argtypes = [ctypes.c_void_p]
    kernel32.OpenProcess.restype = wt.HANDLE
    kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    kernel32.CloseHandle.argtypes = [wt.HANDLE]
    kernel32.GetCurrentProcess.restype = wt.HANDLE
    advapi32.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
    advapi32.GetTokenInformation.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD,
                                             ctypes.POINTER(wt.DWORD)]
    advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    advapi32.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
    advapi32.GetSidSubAuthority.restype = ctypes.POINTER(wt.DWORD)
    advapi32.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wt.DWORD]
    return user32, kernel32, advapi32, wtsapi32


_D = None


def _d():
    global _D
    if _D is None:
        _D = _dlls()
    return _D


# ---------------------------------------------------------------- session (FR-INP-06)
WTSSessionInfoEx = 25
WTS_SESSIONSTATE_LOCK, WTS_SESSIONSTATE_UNLOCK = 0, 1


class WTSINFOEX_LEVEL1_W(ctypes.Structure):
    _fields_ = [("SessionId", wt.ULONG), ("SessionState", ctypes.c_int), ("SessionFlags", wt.LONG),
                ("WinStationName", ctypes.c_wchar * 33), ("UserName", ctypes.c_wchar * 21),
                ("DomainName", ctypes.c_wchar * 18), ("LogonTime", ctypes.c_longlong),
                ("ConnectTime", ctypes.c_longlong), ("DisconnectTime", ctypes.c_longlong),
                ("LastInputTime", ctypes.c_longlong), ("CurrentTime", ctypes.c_longlong),
                ("IncomingBytes", wt.DWORD), ("OutgoingBytes", wt.DWORD), ("IncomingFrames", wt.DWORD),
                ("OutgoingFrames", wt.DWORD), ("IncomingCompressedBytes", wt.DWORD),
                ("OutgoingCompressedBytes", wt.DWORD)]


class _WTSINFOEX_DATA(ctypes.Union):
    _fields_ = [("Level1", WTSINFOEX_LEVEL1_W)]


class WTSINFOEXW(ctypes.Structure):
    _fields_ = [("Level", wt.DWORD), ("Data", _WTSINFOEX_DATA)]


def _session_info() -> tuple[int, int] | None:
    """(connect state, lock flag) of our session, or None if Windows does not say."""
    _, _, _, wts = _d()
    buf, size = ctypes.c_void_p(), wt.DWORD()
    if not wts.WTSQuerySessionInformationW(WTS_CURRENT_SERVER_HANDLE, WTS_CURRENT_SESSION, WTSSessionInfoEx,
                                           ctypes.byref(buf), ctypes.byref(size)):
        return None
    try:
        if size.value < ctypes.sizeof(WTSINFOEXW):
            return None
        info = ctypes.cast(buf, ctypes.POINTER(WTSINFOEXW)).contents
        if info.Level != 1:
            return None
        return info.Data.Level1.SessionState, info.Data.Level1.SessionFlags
    finally:
        wts.WTSFreeMemory(buf)


def classify(connect_state: int, flags: int) -> str:
    """Anything Windows does not clearly call locked or disconnected counts as active, so a
    misreport can never switch expansion off."""
    if connect_state == WTSDisconnected:
        return DISCONNECTED
    if flags == WTS_SESSIONSTATE_LOCK:
        return LOCKED
    return ACTIVE


def session_state() -> str:
    if os.name != "nt":
        return ACTIVE
    try:
        info = _session_info()
        return ACTIVE if info is None else classify(*info)
    except Exception:
        log.debug("session state check failed", exc_info=True)
        return ACTIVE


# ---------------------------------------------------------------- integrity (FR-INP-04)
def _token_integrity(token) -> int | None:
    _, _, adv, _ = _d()
    size = wt.DWORD()
    adv.GetTokenInformation(token, TokenIntegrityLevel, None, 0, ctypes.byref(size))
    if not size.value:
        return None
    buf = ctypes.create_string_buffer(size.value)
    if not adv.GetTokenInformation(token, TokenIntegrityLevel, buf, size, ctypes.byref(size)):
        return None
    sid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p)).contents.value     # TOKEN_MANDATORY_LABEL.Label.Sid
    count = adv.GetSidSubAuthorityCount(sid).contents.value
    return adv.GetSidSubAuthority(sid, count - 1).contents.value


def process_integrity(pid: int | None = None) -> int | None:
    """Mandatory integrity level (0x2000 medium, 0x3000 high, 0x4000 system).
    None when the process cannot be opened; -1 when it opens but its token is off-limits,
    which for a normal user's PhraseForge means the process is elevated."""
    _, k32, adv, _ = _d()
    own = pid is None
    h = k32.GetCurrentProcess() if own else k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        token = wt.HANDLE()
        if not adv.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(token)):
            return -1 if ctypes.get_last_error() == ERROR_ACCESS_DENIED else None
        try:
            return _token_integrity(token)
        finally:
            k32.CloseHandle(token)
    finally:
        if not own:
            k32.CloseHandle(h)


_OWN_LEVEL: int | None = None


def own_integrity() -> int:
    global _OWN_LEVEL
    if _OWN_LEVEL is None:
        _OWN_LEVEL = process_integrity() or 0x2000
    return _OWN_LEVEL


def higher_than_us(level: int | None, own: int) -> bool:
    if level is None:
        return False
    if level == -1:                 # opened but token denied
        return own < 0x3000
    return level > own


def window_elevated(hwnd) -> bool:
    """True when the window's program runs at a higher integrity level than PhraseForge."""
    if os.name != "nt" or not hwnd:
        return False
    try:
        user32 = _d()[0]
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return False
        return higher_than_us(process_integrity(pid.value), own_integrity())
    except Exception:
        log.debug("integrity check failed", exc_info=True)
        return False


def running_as_admin() -> bool:
    return os.name == "nt" and own_integrity() >= 0x3000


def restart_command() -> tuple[str, str]:
    """(program, parameters) that start this PhraseForge again."""
    import subprocess
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    return sys.executable, subprocess.list2cmdline(["-m", "phraseforge"])


def restart_as_admin() -> bool:
    """Start PhraseForge elevated (Windows asks for consent). The new copy waits for this one
    to exit (--after-exit <pid>). True when the user agreed; the caller then quits."""
    if os.name != "nt":
        return False
    exe, params = restart_command()
    params = (params + " " if params else "") + f"--minimized --after-exit {os.getpid()}"
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteW.restype = ctypes.c_void_p
    shell32.ShellExecuteW.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, ctypes.c_int]
    r = shell32.ShellExecuteW(None, "runas", exe, params, None, 0)
    return (r or 0) > 32


def wait_for_exit(pid: int, timeout_s: float = 15.0) -> None:
    """--after-exit: let the copy that started us close before taking the single-instance lock."""
    if os.name != "nt" or pid <= 0:
        return
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wt.HANDLE
    k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    SYNCHRONIZE = 0x00100000
    h = k32.OpenProcess(SYNCHRONIZE, False, pid)
    if not h:
        return
    try:
        k32.WaitForSingleObject(wt.HANDLE(h), int(timeout_s * 1000))
    finally:
        k32.CloseHandle(wt.HANDLE(h))
