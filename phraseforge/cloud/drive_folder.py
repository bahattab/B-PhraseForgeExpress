"""Find the folders that Google Drive for desktop keeps in sync on this PC.

Google Drive for desktop shows Drive either as its own drive letter (streaming,
usually G:) or as a folder in the user profile (mirroring). Either way the
user's files are in a "My Drive" folder. Syncing PhraseForge through that
folder needs no Google sign-in at all.
"""
from __future__ import annotations

import os
import string
import sys
from pathlib import Path

MY_DRIVE = "My Drive"
DRIVE_LABEL = "Google Drive"           # volume label of the streaming drive
SKIP = {"shared drives", "other computers", "computers", "$recycle.bin", "system volume information"}


def _volume_label(root: str) -> str:
    if sys.platform != "win32":
        return ""
    import ctypes
    buf = ctypes.create_unicode_buffer(261)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(ctypes.c_wchar_p(root), buf, len(buf),
                                                      None, None, None, None, 0)
    return buf.value if ok else ""


def _drive_roots() -> list[Path]:
    if sys.platform != "win32":
        return []
    import ctypes
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    return [Path(f"{c}:\\") for i, c in enumerate(string.ascii_uppercase) if mask >> i & 1]


def _is_dir(p: Path) -> bool:
    try:
        return p.is_dir()
    except OSError:          # drive not ready, access denied
        return False


def _children(p: Path) -> list[Path]:
    try:
        return sorted((c for c in p.iterdir() if _is_dir(c) and not c.name.startswith(".")
                       and c.name.lower() not in SKIP), key=lambda c: c.name.lower())
    except OSError:
        return []


def find_google_drive_folders(roots: list[Path] | None = None, home: Path | None = None,
                              label=_volume_label) -> list[Path]:
    """Candidate "My Drive" folders, most likely first. Empty if Drive for desktop is not found.

    roots/home/label can be replaced in tests.
    """
    roots = _drive_roots() if roots is None else roots
    home = Path(os.path.expanduser("~")) if home is None else home
    found: list[Path] = []

    def add(p: Path) -> None:
        if _is_dir(p) and p not in found:
            found.append(p)

    for r in roots:
        if _is_dir(r / MY_DRIVE):
            add(r / MY_DRIVE)
        elif label(str(r)).strip().lower() == DRIVE_LABEL.lower():
            # Streaming drive with a translated "My Drive" name: offer its top-level folders.
            for c in _children(r):
                add(c)
    for p in (home / MY_DRIVE, home / DRIVE_LABEL / MY_DRIVE, home / DRIVE_LABEL):
        add(p)
    return found


def sync_folder_in(drive_folder: Path) -> Path:
    """The PhraseForge folder inside a Drive folder (created on the first sync)."""
    return drive_folder / "PhraseForge"
