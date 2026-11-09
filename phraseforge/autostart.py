"""'Start with Windows' via the per-user Run registry key (no admin needed)."""
from __future__ import annotations

import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "PhraseForge"


def command_line() -> str:
    exe = sys.executable.replace("python.exe", "pythonw.exe")
    if getattr(sys, "frozen", False):  # packaged build
        return f'"{sys.executable}" --minimized'
    return f'"{exe}" -m phraseforge --minimized'


def set_enabled(enabled: bool) -> None:
    from phraseforge.paths import refuse_in_portable
    refuse_in_portable("Start with Windows")       # the Run key is in this PC's registry
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, NAME, 0, winreg.REG_SZ, command_line())
        else:
            try:
                winreg.DeleteValue(k, NAME)
            except FileNotFoundError:
                pass


def is_enabled() -> bool:
    from phraseforge.paths import is_portable
    if is_portable():
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, NAME)
            return True
    except FileNotFoundError:
        return False
