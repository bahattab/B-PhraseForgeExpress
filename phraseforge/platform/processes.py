"""Names of the running programs, read directly from Windows (Tool Help API).

Replaces running the "tasklist" command. Returns [] on other systems.
"""
from __future__ import annotations

import ctypes
import os

TH32CS_SNAPPROCESS = 0x00000002
MAX_PATH = 260


def running_exes() -> list[str]:
    """Lower-case exe names of running processes, sorted and unique."""
    if os.name != "nt":
        return []
    from ctypes import wintypes as wt

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wt.DWORD),
                    ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                    ("szExeFile", ctypes.c_wchar * MAX_PATH)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
    k32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32FirstW.restype = wt.BOOL
    k32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.restype = wt.BOOL
    k32.CloseHandle.argtypes = [wt.HANDLE]
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == wt.HANDLE(-1).value:
        return []
    names: set[str] = set()
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            n = entry.szExeFile.strip().lower()
            if n:
                names.add(n)
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return sorted(names)
