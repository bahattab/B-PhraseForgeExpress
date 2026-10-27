"""Sticky notes built into PhraseForge, plus a read-only importer for Microsoft Sticky Notes.

PhraseForge's own notes live in its database (Store.sticky_notes) and are shown
as small desktop windows by ui/sticky_notes.py. No other program is started.

Import: the Microsoft Sticky Notes Store app keeps its notes in a SQLite file:
  %LOCALAPPDATA%\\Packages\\Microsoft.MicrosoftStickyNotes_8wekyb3d8bbwe\\LocalState\\plum.sqlite
We never open that file in place: it is copied (with its -wal/-shm journal) to a
temporary folder and read there, so Sticky Notes is never locked or modified.

Note.Text holds one paragraph per line, each prefixed with "\\id=<guid> ".
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

PACKAGE = "Microsoft.MicrosoftStickyNotes_8wekyb3d8bbwe"

# Note colours: (name, paper, header) - the seven colours Sticky Notes offers.
COLORS = {
    "yellow": ("#fff7d1", "#fff2ab"),
    "green": ("#e4f9e0", "#cbf1c4"),
    "pink": ("#ffe4f1", "#ffcce5"),
    "purple": ("#f2e6ff", "#e7cfff"),
    "blue": ("#e2f1ff", "#cde9ff"),
    "gray": ("#f3f2f1", "#e1dfdd"),
    "charcoal": ("#696969", "#4f4f4f"),
}
# Microsoft Sticky Notes theme names -> our colours (used by the importer)
_MS_THEMES = {"yellow": "yellow", "green": "green", "pink": "pink", "purple": "purple",
              "blue": "blue", "gray": "gray", "charcoal": "charcoal"}


def color_of(theme: str) -> str:
    t = (theme or "").strip().lower()
    return _MS_THEMES.get(t, "yellow")


def db_path() -> Path:
    base = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    return Path(base) / "Packages" / PACKAGE / "LocalState" / "plum.sqlite"


def installed() -> bool:
    return db_path().is_file()


@dataclass
class StickyNote:
    id: object                       # int for PhraseForge notes, str (guid) for imported ones
    text: str
    theme: str = ""                  # colour name (COLORS)
    updated: datetime | None = None
    created: datetime | None = None
    html: str = ""                   # rich text (bold, italic, lists...) as Qt HTML
    x: int | None = None
    y: int | None = None
    w: int = 300
    h: int = 300
    visible: bool = True
    on_top: bool = False

    @property
    def title(self) -> str:
        first = next((l.strip() for l in self.text.splitlines() if l.strip()), "")
        return (first[:60] + "...") if len(first) > 60 else (first or "(empty note)")


_ID_PREFIX = re.compile(r"^\\id=[0-9a-fA-F-]+\s?")


def parse_text(raw: str) -> str:
    """Note.Text -> plain text. Only the per-paragraph "\\id=<guid> " prefix is removed;
    other backslashes are real text (e.g. Windows paths) and are kept."""
    lines = [_ID_PREFIX.sub("", line).rstrip() for line in (raw or "").replace("\r\n", "\n").split("\n")]
    return "\n".join(lines).strip("\n")


def _ticks(v) -> datetime | None:
    """Sticky Notes stores times as .NET ticks (100 ns since 0001-01-01, UTC)."""
    try:
        t = int(v)
    except (TypeError, ValueError):
        return None
    if t <= 0:
        return None
    try:
        return datetime(1, 1, 1) + timedelta(microseconds=t // 10)
    except OverflowError:
        return None


_cache: dict = {"key": None, "notes": []}
_lock = threading.Lock()


def read_notes(path: Path | None = None, use_cache: bool = True) -> list[StickyNote]:
    """All non-deleted notes, newest first. Empty list when Sticky Notes isn't installed."""
    src = Path(path) if path else db_path()
    if not src.is_file():
        return []
    stamp = tuple((src.with_name(src.name + ext).stat().st_mtime_ns
                   if src.with_name(src.name + ext).exists() else 0) for ext in ("", "-wal"))
    with _lock:
        if use_cache and _cache["key"] == (str(src), stamp):
            return list(_cache["notes"])
        tmp = Path(tempfile.mkdtemp(prefix="pf-sticky-"))
        try:
            for ext in ("", "-wal", "-shm"):
                s = src.with_name(src.name + ext)
                if s.exists():
                    shutil.copyfile(s, tmp / ("plum.sqlite" + ext))
            con = sqlite3.connect(str(tmp / "plum.sqlite"))
            try:
                rows = con.execute(
                    "SELECT Id, Text, Theme, UpdatedAt, CreatedAt FROM Note "
                    "WHERE DeletedAt IS NULL OR DeletedAt = 0 OR DeletedAt = ''").fetchall()
            finally:
                con.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        notes = [StickyNote(str(r[0]), parse_text(r[1] or ""), r[2] or "", _ticks(r[3]), _ticks(r[4]))
                 for r in rows]
        notes = [n for n in notes if n.text.strip()]
        notes.sort(key=lambda n: n.updated or datetime.min, reverse=True)
        _cache.update(key=(str(src), stamp), notes=notes)
        return list(notes)


def find(notes: list[StickyNote], query: str) -> StickyNote | None:
    """Note whose first line equals query, else the newest note containing it (case-insensitive)."""
    q = (query or "").strip().lower()
    if not q:
        return notes[0] if notes else None
    for n in notes:
        if n.title.lower().rstrip(".") == q:
            return n
    return next((n for n in notes if q in n.text.lower()), None)
