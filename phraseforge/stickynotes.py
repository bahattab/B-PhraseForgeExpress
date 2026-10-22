"""Read Microsoft Sticky Notes (the user's own notes file) - read-only.

Sticky Notes (Microsoft Store app) keeps notes in a SQLite file:
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
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

PACKAGE = "Microsoft.MicrosoftStickyNotes_8wekyb3d8bbwe"
APP_ID = PACKAGE + "!App"


def db_path() -> Path:
    base = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    return Path(base) / "Packages" / PACKAGE / "LocalState" / "plum.sqlite"


def installed() -> bool:
    return db_path().is_file()


@dataclass
class StickyNote:
    id: str
    text: str
    theme: str = ""
    updated: datetime | None = None
    created: datetime | None = None

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


def open_app() -> None:
    """Open the Sticky Notes app (its documented Store app id)."""
    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{APP_ID}"])
