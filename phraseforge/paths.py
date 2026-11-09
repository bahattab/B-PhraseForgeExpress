"""Where PhraseForge keeps its data.

In this order:
  PHRASEFORGE_HOME (or --home <dir>)   that folder
  portable mode                         PhraseForgeData next to the program
  otherwise                             %APPDATA%\\PhraseForge

Portable mode (PRD G-09, FR-APP-03) is on for the portable EXE (its file name contains
"portable"), when a file portable.ini sits next to the program, with --portable, or with
PHRASEFORGE_PORTABLE=1 (PHRASEFORGE_PORTABLE=0 turns it off). In portable mode PhraseForge
writes nothing to %APPDATA% or the registry: everything stays on the stick, and the features
that only work through the registry or the user profile ("Start with Windows", "Export
signatures to Outlook") are switched off with a message.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PORTABLE_MARKER = "portable.ini"
PORTABLE_DATA = "PhraseForgeData"


def app_dir() -> Path:
    """The folder of the program: the EXE's folder, or the source checkout."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def is_portable() -> bool:
    flag = os.environ.get("PHRASEFORGE_PORTABLE", "")
    if flag in ("0", "1"):
        return flag == "1"
    if os.environ.get("PHRASEFORGE_HOME"):
        return False                        # an explicit data folder wins
    if getattr(sys, "frozen", False) and "portable" in Path(sys.executable).name.lower():
        return True
    return (app_dir() / PORTABLE_MARKER).is_file()


def data_dir() -> Path:
    home = os.environ.get("PHRASEFORGE_HOME")
    if home:
        base = Path(home)
    elif is_portable():
        base = app_dir() / PORTABLE_DATA
    else:
        base = Path(os.environ.get("APPDATA", str(Path.home()))) / "PhraseForge"
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> Path:
    return data_dir() / "phrases.db"


def backups_dir() -> Path:
    p = data_dir() / "backups"
    p.mkdir(exist_ok=True)
    return p


class PortableRefused(PermissionError):
    """A feature that would write to the registry or the user profile, in portable mode."""


def refuse_in_portable(what: str) -> None:
    if is_portable():
        raise PortableRefused(f"{what} is not available in portable mode: it would write to this PC's "
                              "registry or user profile, and portable PhraseForge leaves no trace on the PC.")


def apply_command_line(argv: list[str]) -> list[str]:
    """--portable and --home <dir> (FR-APP-02): set before anything reads the data folder.
    Returns argv without them."""
    out, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a == "--portable":
            os.environ["PHRASEFORGE_PORTABLE"] = "1"
            os.environ.pop("PHRASEFORGE_HOME", None)
        elif a == "--home" and i + 1 < len(argv):
            os.environ["PHRASEFORGE_HOME"] = str(Path(argv[i + 1]).expanduser())
            os.environ["PHRASEFORGE_PORTABLE"] = "0"
            i += 1
        elif a.startswith("--home="):
            os.environ["PHRASEFORGE_HOME"] = str(Path(a.split("=", 1)[1]).expanduser())
            os.environ["PHRASEFORGE_PORTABLE"] = "0"
        else:
            out.append(a)
        i += 1
    return out
