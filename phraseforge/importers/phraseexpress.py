"""Exchange phrases with PhraseExpress and other text expanders.

What is known about PhraseExpress's own files (see docs/EVIDENCE.md):
- Phrase files (.pexdb) and hub files (.pexdbhub) are encrypted. Two sample
  files had no readable header, byte entropy 8.0 bits/byte and sizes that are
  multiples of 4096 bytes, so they cannot be read without the vendor's key.
  PhraseForge does not try to break or extract that key (EULA); it detects
  these files and tells the user how to get a readable export instead.
- PhraseExpress imports and exports spreadsheet/CSV files. Its exact column
  names are not published, so the CSV reader maps common header names and
  sniffs the delimiter (comma, semicolon or tab).

Writers (all without third-party code):
- PhraseExpress-style CSV: Description, Content, Autotext, Hotkey, Folder.
- TextExpander CSV: abbreviation, content, label (no header, as TextExpander
  exports it), with PhraseForge macros converted back where an equivalent exists.
- macOS Text Replacements plist: a list of {"phrase", "shortcut"} entries.
"""
from __future__ import annotations

import csv
import io
import math
import plistlib
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from phraseforge.db import Store
from phraseforge.models import Folder, Phrase, Trigger, TriggerKind

ENCRYPTED_SUFFIXES = (".pexdb", ".pexdbhub", ".pxp")

ENCRYPTED_MESSAGE = (
    "This PhraseExpress file is encrypted and can only be opened by PhraseExpress.\n\n"
    "To bring your phrases into PhraseForge:\n"
    "1. In PhraseExpress select the folder to move (or the top folder).\n"
    "2. Use Export and choose a spreadsheet / CSV file.\n"
    "3. In PhraseForge use Import > From PhraseExpress and pick that CSV file."
)

# header name (lower case, no spaces/underscores) -> PhraseForge field
HEADER_ALIASES = {
    "description": "description", "phrasedescription": "description", "label": "description",
    "name": "description", "title": "description", "caption": "description",
    "content": "content", "phrasecontent": "content", "phrase": "content", "text": "content",
    "snippet": "content", "plaintext": "content", "expansion": "content", "replacement": "content",
    "body": "content",
    "autotext": "autotext", "abbreviation": "autotext", "abbr": "autotext", "shortcut": "autotext",
    "trigger": "autotext", "keyword": "autotext",
    "hotkey": "hotkey", "shortcutkey": "hotkey",
    "folder": "folder", "folderpath": "folder", "group": "folder", "category": "folder", "path": "folder",
    "format": "format", "contentformat": "format",
}
FIELDS_IN_ORDER = ["description", "content", "autotext", "hotkey", "folder"]
PE_HEADER = ["Description", "Content", "Autotext", "Hotkey", "Folder"]


class EncryptedPhraseFile(ValueError):
    """A PhraseExpress database that PhraseForge cannot read."""


@dataclass
class ExchangeReport:
    imported: int = 0
    skipped: int = 0
    exported: int = 0
    folder_id: int | None = None
    notes: list[str] = field(default_factory=list)
    kept_as_text: dict[str, int] = field(default_factory=dict)


# ------------------------------------------------------------------ detection
def byte_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    n = len(data)
    return -sum(c / n * math.log2(c / n) for c in Counter(data).values())


def looks_encrypted(path: str | Path, sample: int = 65536) -> bool:
    """True for a file with no known header whose bytes look random."""
    with open(path, "rb") as fh:
        head = fh.read(sample)
    if head.startswith((b"SQLite format 3\x00", b"<?xml", b"PK\x03\x04", b"bplist", b"\xef\xbb\xbf")):
        return False
    return byte_entropy(head) > 7.9


def check_phraseexpress_file(path: str | Path) -> None:
    """Raise EncryptedPhraseFile for a PhraseExpress database file."""
    p = Path(path)
    if p.suffix.lower() in ENCRYPTED_SUFFIXES:
        raise EncryptedPhraseFile(ENCRYPTED_MESSAGE)


# ------------------------------------------------------------------ CSV reading
def _read_text(path: str | Path) -> str:
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-16"):
        try:
            text = raw.decode(enc)
            if enc == "utf-16" and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
                continue
            return text
        except UnicodeDecodeError:
            continue
    return raw.decode("cp1252", errors="replace")


def _dialect(text: str):
    try:
        return csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
    except csv.Error:
        return csv.excel


def map_header(row: list[str]) -> dict[int, str] | None:
    """Column index -> field when the row is a header row, else None."""
    cols: dict[int, str] = {}
    for i, h in enumerate(row):
        key = re.sub(r"[\s_\-]+", "", h.strip().lower())
        f = HEADER_ALIASES.get(key)
        if f and f not in cols.values():
            cols[i] = f
    return cols if "content" in cols.values() else None


def read_rows(path: str | Path) -> list[dict[str, str]]:
    text = _read_text(path)
    rows = [r for r in csv.reader(io.StringIO(text), _dialect(text)) if any(c.strip() for c in r)]
    if not rows:
        return []
    cols = map_header(rows[0])
    if cols is None:            # no header: PhraseExpress-style order
        cols = dict(enumerate(FIELDS_IN_ORDER))
    else:
        rows = rows[1:]
    return [{f: (row[i] if i < len(row) else "") for i, f in cols.items()} for row in rows]


def import_csv(store: Store, path: str | Path, folder_name: str | None = None) -> ExchangeReport:
    """Import a CSV exported from PhraseExpress (or a similar spreadsheet)."""
    from phraseforge.io_formats import ensure_folder_path
    p = Path(path)
    rep = ExchangeReport()
    top = store.add_folder(Folder(folder_name or p.stem))
    rep.folder_id = top.id
    for rec in read_rows(p):
        content = rec.get("content", "")
        if not content.strip() and not rec.get("autotext", "").strip():
            rep.skipped += 1
            continue
        desc = rec.get("description", "").strip() or (content.strip().splitlines() or ["Phrase"])[0][:60]
        triggers = []
        for at in filter(None, (s.strip() for s in rec.get("autotext", "").split("|"))):
            triggers.append(Trigger(TriggerKind.AUTOTEXT, at))
        if rec.get("hotkey", "").strip():
            triggers.append(Trigger(TriggerKind.HOTKEY, rec["hotkey"].strip()))
        folder = rec.get("folder", "").strip().replace("\\", "/")
        fid = ensure_folder_path(store, folder, top.id) if folder else top.id
        fmt = rec.get("format", "").strip().lower()
        fmt = fmt if fmt in ("text", "html", "rtf") else ("html" if re.search(r"</?(p|b|i|br|div|span)\b", content, re.I) else "text")
        store.add_phrase(Phrase(desc, content, folder_id=fid, triggers=triggers, content_format=fmt))
        rep.imported += 1
    return rep


# ------------------------------------------------------------------ writing
def _phrases(store: Store, folder_id: int | None = None) -> list[Phrase]:
    phrases = store.phrases()
    if folder_id is None:
        return phrases
    keep = {folder_id}
    changed = True
    folders = store.folders()
    while changed:
        changed = False
        for f in folders:
            if f.parent_id in keep and f.id not in keep:
                keep.add(f.id)
                changed = True
    return [p for p in phrases if p.folder_id in keep]


def _trigger(p: Phrase, kind: TriggerKind) -> str:
    return next((t.value for t in p.triggers if t.kind == kind and t.value), "")


def _text_of(store: Store, p: Phrase, language: str) -> str:
    if language:
        content, _fmt = store.phrase_text(p, language)
        return content
    return p.content


def export_phraseexpress_csv(store: Store, path: str | Path, folder_id: int | None = None,
                             language: str = "") -> ExchangeReport:
    """CSV with a header row; UTF-8 with BOM so Excel and PhraseExpress keep Arabic text."""
    from phraseforge.io_formats import folder_path
    rep = ExchangeReport()
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(PE_HEADER)
        for p in _phrases(store, folder_id):
            at = "|".join(t.value for t in p.triggers if t.kind == TriggerKind.AUTOTEXT and t.value)
            w.writerow([p.description, _text_of(store, p, language), at, _trigger(p, TriggerKind.HOTKEY),
                        folder_path(store, p.folder_id)])
            rep.exported += 1
    return rep


_PF_MACRO = re.compile(r"\{\{|\{#(\w+)([^{}]*)\}")
_DATE_BACK = {"yyyy": "%Y", "yy": "%y", "MMMM": "%B", "MMM": "%b", "MM": "%m", "M": "%1m",
              "dddd": "%A", "ddd": "%a", "dd": "%d", "d": "%e", "HH": "%H", "H": "%1H",
              "hh": "%I", "h": "%1I", "mm": "%M", "ss": "%S", "tt": "%p"}
_DATE_FMT_TOKEN = re.compile("|".join(sorted(map(re.escape, _DATE_BACK), key=len, reverse=True)))


def to_textexpander(content: str, rep: ExchangeReport | None = None) -> str:
    """PhraseForge macro text -> TextExpander snippet text (best effort)."""
    out: list[str] = []
    pos = 0
    for m in _PF_MACRO.finditer(content):
        out.append(content[pos:m.start()].replace("%", "%%"))
        pos = m.end()
        if m.group(0) == "{{":
            out.append("{")
            continue
        name, args = m.group(1).lower(), m.group(2).strip()
        if name == "clipboard":
            out.append("%clipboard")
        elif name == "cursor":
            out.append("%|")
        elif name == "date" and not args:
            out.append("%d/%m/%Y")
        elif name == "date" and (fm := re.search(r"-format\s+\"([^\"]*)\"", args)) and "-offset" not in args:
            out.append(_DATE_FMT_TOKEN.sub(lambda t: _DATE_BACK[t.group(0)], fm.group(1)))
        elif name == "insert" and (im := re.fullmatch(r"\"([^\"]*)\"", args)):
            out.append("%snippet:" + im.group(1) + "%")
        else:
            out.append(m.group(0))
            if rep is not None:
                rep.kept_as_text[name] = rep.kept_as_text.get(name, 0) + 1
    out.append(content[pos:].replace("%", "%%"))
    return "".join(out)


def export_textexpander_csv(store: Store, path: str | Path, folder_id: int | None = None,
                            language: str = "") -> ExchangeReport:
    """abbreviation, content, label rows (TextExpander's CSV layout, no header)."""
    rep = ExchangeReport()
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        for p in _phrases(store, folder_id):
            abbr = _trigger(p, TriggerKind.AUTOTEXT)
            if not abbr:
                rep.skipped += 1
                continue
            w.writerow([abbr, to_textexpander(_text_of(store, p, language), rep), p.description])
            rep.exported += 1
    if rep.skipped:
        rep.notes.append(f"{rep.skipped} phrase(s) without an autotext were left out.")
    return rep


def to_plain(content: str, rep: ExchangeReport | None = None) -> str:
    """Macro text -> plain text for formats without macros (macOS)."""
    def sub(m):
        if m.group(0) == "{{":
            return "{"
        if rep is not None:
            rep.kept_as_text[m.group(1).lower()] = rep.kept_as_text.get(m.group(1).lower(), 0) + 1
        return m.group(0)
    return _PF_MACRO.sub(sub, content)


def export_macos_plist(store: Store, path: str | Path, folder_id: int | None = None,
                       language: str = "") -> ExchangeReport:
    """macOS Text Replacements: drag the file into System Settings > Keyboard > Text Replacements."""
    rep = ExchangeReport()
    items = []
    for p in _phrases(store, folder_id):
        abbr = _trigger(p, TriggerKind.AUTOTEXT)
        if not abbr:
            rep.skipped += 1
            continue
        items.append({"phrase": to_plain(_text_of(store, p, language), rep), "shortcut": abbr})
        rep.exported += 1
    with open(path, "wb") as fh:
        plistlib.dump(items, fh, fmt=plistlib.FMT_XML)
    if rep.skipped:
        rep.notes.append(f"{rep.skipped} phrase(s) without an autotext were left out.")
    return rep


def export_any(store: Store, path: str | Path, kind: str, folder_id: int | None = None,
               language: str = "") -> ExchangeReport:
    fn = {"phraseexpress": export_phraseexpress_csv, "textexpander": export_textexpander_csv,
          "macos": export_macos_plist}[kind]
    return fn(store, path, folder_id, language)


def import_any(store: Store, path: str | Path) -> ExchangeReport:
    """PhraseExpress CSV/TXT import; encrypted PhraseExpress databases raise EncryptedPhraseFile."""
    p = Path(path)
    check_phraseexpress_file(p)
    if p.suffix.lower() in (".csv", ".txt", ".tsv"):
        return import_csv(store, p)
    if looks_encrypted(p):
        raise EncryptedPhraseFile(ENCRYPTED_MESSAGE)
    raise ValueError(f"Unsupported PhraseExpress file: {p.name}. Export a CSV file from PhraseExpress.")
