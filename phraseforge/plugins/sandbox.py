"""Low-integrity plugin processes on Windows (PRD FR-PLG-02 "restricted token / low integrity").

launch() starts the plugin with a copy of the user's token whose integrity level is Low
(S-1-16-4096). Windows then refuses the plugin every write to objects at Medium integrity: the
user's files and folders, the PhraseForge database, the registry under HKCU (except the Low
parts) and other programs' windows and processes.

What this does NOT stop (documented residual risk): reading files the user can read, and
opening network connections itself instead of through the per-plugin proxy (netproxy.py). An
AppContainer sandbox would be needed for those.

The process is created suspended, put in its job object (memory cap, no children, killed with
PhraseForge) and only then resumed, and it inherits exactly its three pipe handles.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

LOW_INTEGRITY_SID = "S-1-16-4096"


class SandboxError(OSError):
    pass


def low_temp_dir() -> Path:
    """A temp folder a low-integrity process may write: %USERPROFILE%\\AppData\\LocalLow\\PhraseForge\\Temp."""
    from phraseforge import paths
    if paths.is_portable():                              # leave no trace on the PC (portable mode)
        base = paths.data_dir() / "PluginTemp"
    else:
        base = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "AppData" / "LocalLow" / "PhraseForge" / "Temp"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _cmdline(args: list[str]) -> str:
    import subprocess
    return subprocess.list2cmdline(args)


def _env_block(env: dict[str, str]) -> str:
    # sorted, case-insensitively, as CreateProcess expects; double NUL at the end
    return "".join(f"{k}={v}\0" for k, v in sorted(env.items(), key=lambda kv: kv[0].upper())) + "\0"


class LowProcess:
    """The part of subprocess.Popen that PluginProcess uses: stdin/stdout/stderr, poll, wait, kill."""

    def __init__(self, handle: int, pid: int, stdin, stdout, stderr):
        self._handle = handle
        self.pid = pid
        self.stdin, self.stdout, self.stderr = stdin, stdout, stderr
        self.returncode = None

    def poll(self):
        if self.returncode is None:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            if k32.WaitForSingleObject(wintypes.HANDLE(self._handle), 0) == 0:
                code = wintypes.DWORD()
                k32.GetExitCodeProcess(wintypes.HANDLE(self._handle), ctypes.byref(code))
                self.returncode = code.value
        return self.returncode

    def wait(self, timeout: float | None = None):
        import ctypes
        import subprocess
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ms = 0xFFFFFFFF if timeout is None else int(timeout * 1000)
        if k32.WaitForSingleObject(wintypes.HANDLE(self._handle), ms) != 0:
            raise subprocess.TimeoutExpired("plugin", timeout)
        return self.poll()

    def kill(self) -> None:
        import ctypes
        from ctypes import wintypes
        if self.poll() is None:
            ctypes.WinDLL("kernel32").TerminateProcess(wintypes.HANDLE(self._handle), 1)

    terminate = kill

    def __del__(self):
        try:
            import ctypes
            from ctypes import wintypes
            if self._handle:
                ctypes.WinDLL("kernel32").CloseHandle(wintypes.HANDLE(self._handle))
                self._handle = 0
        except Exception:      # noqa: BLE001 - interpreter shutdown
            pass


def launch(args: list[str], cwd: str, env: dict[str, str], job_factory) -> tuple[LowProcess, object]:
    """Start args at Low integrity. job_factory(proc) -> job handle or None; without a job the
    process is killed and SandboxError raised (its limits are part of the sandbox)."""
    if sys.platform != "win32":
        raise SandboxError("the sandbox is only available on Windows")
    import ctypes
    import msvcrt
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    k32.ResumeThread.restype = wintypes.DWORD            # its failure value is 0xFFFFFFFF, not -1

    def fail(what):
        raise SandboxError(f"{what} failed (error {ctypes.get_last_error()})")

    # ---- a Low copy of our own token
    TOKEN_ALL = 0x0001 | 0x0002 | 0x0008 | 0x0080 | 0x0100   # ASSIGN_PRIMARY|DUPLICATE|QUERY|ADJUST_DEFAULT|ADJUST_SESSIONID
    tok = wintypes.HANDLE()
    # GetCurrentProcess() returns the pseudo-handle -1; pass it as a HANDLE (a bare 64-bit int overflows)
    if not adv.OpenProcessToken(wintypes.HANDLE(k32.GetCurrentProcess()), TOKEN_ALL, ctypes.byref(tok)):
        fail("OpenProcessToken")
    low = wintypes.HANDLE()
    try:
        if not adv.DuplicateTokenEx(tok, TOKEN_ALL, None, 2, 1, ctypes.byref(low)):  # Impersonation, TokenPrimary
            fail("DuplicateTokenEx")
    finally:
        k32.CloseHandle(tok)
    sid = ctypes.c_void_p()
    if not adv.ConvertStringSidToSidW(ctypes.c_wchar_p(LOW_INTEGRITY_SID), ctypes.byref(sid)):
        k32.CloseHandle(low)
        fail("ConvertStringSidToSid")

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

    label = SID_AND_ATTRIBUTES(sid, 0x20)                    # SE_GROUP_INTEGRITY
    adv.GetLengthSid.restype = wintypes.DWORD
    ok = adv.SetTokenInformation(low, 25, ctypes.byref(label),      # TokenIntegrityLevel
                                 ctypes.sizeof(label) + adv.GetLengthSid(sid))
    k32.LocalFree(sid)
    if not ok:
        k32.CloseHandle(low)
        fail("SetTokenInformation")

    # ---- three pipes; only the child's ends are inherited
    pipes = [os.pipe() for _ in range(3)]                    # (read, write)
    child_fds = [pipes[0][0], pipes[1][1], pipes[2][1]]
    parent_fds = [pipes[0][1], pipes[1][0], pipes[2][0]]
    try:
        child_handles = [msvcrt.get_osfhandle(fd) for fd in child_fds]
        for h in child_handles:
            k32.SetHandleInformation(wintypes.HANDLE(h), 1, 1)  # HANDLE_FLAG_INHERIT
    except BaseException:
        for fd in child_fds + parent_fds:
            os.close(fd)
        k32.CloseHandle(low)
        raise

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
                    ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                    ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
                    ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                    ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
                    ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]

    class STARTUPINFOEXW(ctypes.Structure):
        _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                    ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]

    size = ctypes.c_size_t()
    k32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    attrs = ctypes.create_string_buffer(size.value)
    handle_list = (wintypes.HANDLE * 3)(*child_handles)
    pi = PROCESS_INFORMATION()
    initialized = False
    try:
        if not k32.InitializeProcThreadAttributeList(attrs, 1, 0, ctypes.byref(size)):
            fail("InitializeProcThreadAttributeList")
        initialized = True
        if not k32.UpdateProcThreadAttribute(attrs, 0, ctypes.c_size_t(0x20002),   # PROC_THREAD_ATTRIBUTE_HANDLE_LIST
                                             handle_list, ctypes.sizeof(handle_list), None, None):
            fail("UpdateProcThreadAttribute")
        si = STARTUPINFOEXW()
        si.StartupInfo.cb = ctypes.sizeof(si)
        si.StartupInfo.dwFlags = 0x100                       # STARTF_USESTDHANDLES
        si.StartupInfo.hStdInput, si.StartupInfo.hStdOutput, si.StartupInfo.hStdError = child_handles
        si.lpAttributeList = ctypes.cast(attrs, ctypes.c_void_p)
        flags = 0x08000000 | 0x00000004 | 0x00000400 | 0x00080000   # NO_WINDOW|SUSPENDED|UNICODE_ENV|EXTENDED_STARTUPINFO
        cmd = ctypes.create_unicode_buffer(_cmdline(args))
        block = ctypes.create_unicode_buffer(_env_block(env))
        if not adv.CreateProcessAsUserW(low, None, cmd, None, None, True, flags, block, ctypes.c_wchar_p(cwd),
                                        ctypes.byref(si), ctypes.byref(pi)):
            fail("CreateProcessAsUser")
    except BaseException:
        for fd in parent_fds:
            os.close(fd)
        raise
    finally:
        if initialized:
            k32.DeleteProcThreadAttributeList(attrs)
        k32.CloseHandle(low)
        for fd in child_fds:
            os.close(fd)

    proc = LowProcess(int(pi.hProcess), pi.dwProcessId, open(parent_fds[0], "wb", buffering=0),
                      open(parent_fds[1], "rb"), open(parent_fds[2], "rb"))

    def abandon(msg):
        k32.TerminateProcess(pi.hProcess, 1)
        k32.CloseHandle(pi.hThread)
        for f in (proc.stdin, proc.stdout, proc.stderr):
            f.close()
        k32.CloseHandle(pi.hProcess)
        proc._handle = 0
        raise SandboxError(msg)

    try:
        job = job_factory(proc)
    except Exception as e:                              # noqa: BLE001
        abandon(f"the plugin could not be put in its job object ({e})")
    if not job:                                         # no limits: do not let it run
        abandon("the plugin could not be put in its job object")
    if k32.ResumeThread(pi.hThread) == 0xFFFFFFFF:
        abandon(f"ResumeThread failed (error {ctypes.get_last_error()})")
    k32.CloseHandle(pi.hThread)
    return proc, job
