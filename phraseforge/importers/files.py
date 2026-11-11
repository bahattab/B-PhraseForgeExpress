"""Import Word, RTF, Excel and image files as phrases, without Microsoft Office.

PhraseExpress's import of "Text/Bitmap/Excel/CSV files" offers four ways to
turn a file into phrases (vendor manual, doc/import/file):

  copy   Save a copy: the file's contents become the phrase. Images are copied
         into <data>/assets and the phrase pastes them with {#image}.
  link   Macro that loads the contents on trigger: {#document} / {#image} with
         the original path (moving the file breaks the phrase).
  open   Macro that opens the file in its program: {#open}.
  lines  Line-by-line: one phrase per paragraph (Word, RTF) or row (Excel).
         An Excel sheet whose first row names the columns (Description,
         Content, Autotext, Hotkey, Folder ...) is read like a phrase table.

Readers (also used by the {#document} macro):
  docx_paragraphs  word/document.xml from the .docx zip (tabs, breaks kept)
  rtf_text         a small RTF reader: groups, skipped destinations, \\par,
                   \\line, \\tab, \\'hh in the document code page (\\ansicpg,
                   e.g. 1256 for Arabic) and \\uN Unicode escapes
  xlsx_rows        cell values with openpyxl (read-only, values not formulas)
"""
from __future__ import annotations

import codecs
import hashlib
import os
import re
import shutil
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from phraseforge import paths
from phraseforge.db import Store, untrusted_import
from phraseforge.models import Phrase, Trigger, TriggerKind

WORD_EXT = (".docx", ".docm", ".dotx")
RTF_EXT = (".rtf",)
EXCEL_EXT = (".xlsx", ".xlsm")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp")
SUPPORTED = WORD_EXT + RTF_EXT + EXCEL_EXT + IMAGE_EXT

MODES = ("copy", "link", "open", "lines")


def modes_for(path: str | Path) -> tuple[str, ...]:
    """Import modes that make sense for this file type."""
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXT:
        return ("copy", "link", "open")
    if ext in EXCEL_EXT:
        return ("lines", "copy", "open")          # {#document} cannot read a workbook
    return MODES


# ---------------------------------------------------------------- readers
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


MAX_DOCUMENT_XML = 64 * 1024 * 1024     # unpacked word/document.xml; larger is treated as a zip bomb


class _PrologDone(Exception):
    pass


def refuse_dtd(data: bytes) -> None:
    """Raise ValueError if the XML has a DTD. Word never writes one; refusing it rules
    out entity expansion and external entities whatever the parser's own limits are.
    The XML parser reads the prolog itself, so the check holds for every encoding
    (a byte search for "<!DOCTYPE" misses UTF-16). Parsing stops at the first element."""
    from xml.parsers import expat

    def doctype(*_):
        raise ValueError("word/document.xml contains a DTD")

    def first_element(*_):
        raise _PrologDone

    p = expat.ParserCreate()
    p.StartDoctypeDeclHandler = doctype
    p.EntityDeclHandler = doctype
    p.StartElementHandler = first_element
    try:
        p.Parse(data, True)
    except _PrologDone:
        pass
    except expat.ExpatError as e:
        raise ValueError(f"word/document.xml is not valid XML: {e}") from None


def docx_paragraphs(path: str | Path) -> list[str]:
    with zipfile.ZipFile(path) as z:
        if z.getinfo("word/document.xml").file_size > MAX_DOCUMENT_XML:
            raise ValueError("word/document.xml is too large")
        data = z.read("word/document.xml")
    refuse_dtd(data)
    root = ET.fromstring(data)
    out = []
    for para in root.iter(_W + "p"):
        parts = []
        for el in para.iter():
            if el.tag == _W + "t":
                parts.append(el.text or "")
            elif el.tag == _W + "tab":
                parts.append("\t")
            elif el.tag in (_W + "br", _W + "cr"):
                parts.append("\n")
        out.append("".join(parts))
    return out


# destinations whose text is not document text
_RTF_SKIP = {"fonttbl", "colortbl", "stylesheet", "info", "pict", "header", "footer", "headerl", "headerr",
             "footerl", "footerr", "footnote", "listtable", "listoverridetable", "rsidtbl", "generator",
             "xmlnstbl", "themedata", "colorschememapping", "datastore", "latentstyles", "object", "fldinst",
             "filetbl", "revtbl", "mmathPr", "pgdsctbl"}
_RTF_TOKEN = re.compile(r"\\([a-zA-Z]+)(-?\d+)? ?|\\'([0-9a-fA-F]{2})|\\(.)|([{}])|([^\\{}\r\n]+)|[\r\n]+", re.S)


# \ansicpg values Python has no "cpN" name for, and the old character-set words
_RTF_CODEPAGES = {"10000": "mac_roman", "10004": "mac_arabic", "10006": "mac_greek", "10007": "mac_cyrillic",
                  "10029": "mac_latin2", "10079": "mac_iceland", "10081": "mac_turkish"}
_RTF_CHARSETS = {"ansi": "cp1252", "mac": "mac_roman", "pc": "cp437", "pca": "cp850"}


def _rtf_codec(name: str) -> str:
    """A codec Python knows, or cp1252 (RTF's default) for an unknown or broken code page."""
    try:
        return codecs.lookup(name).name
    except LookupError:
        return "cp1252"


def rtf_to_text(rtf: str) -> str:
    """Plain text of an RTF document."""
    out: list[str] = []
    stack: list[tuple[bool, int]] = []       # (skipping, uc) saved at each "{"
    skipping, uc, pending_skip = False, 1, 0
    codepage = "cp1252"
    hexbuf = bytearray()

    def flush_hex():
        if hexbuf:
            if not skipping:
                out.append(hexbuf.decode(codepage, errors="replace"))
            hexbuf.clear()

    for m in _RTF_TOKEN.finditer(rtf):
        word, arg, hexcode, sym, brace, text = m.groups()
        if hexcode is not None:
            if pending_skip:
                pending_skip -= 1
                continue
            hexbuf.append(int(hexcode, 16))
            continue
        flush_hex()
        if brace == "{":
            stack.append((skipping, uc))
        elif brace == "}":
            skipping, uc = stack.pop() if stack else (False, 1)
        elif word is not None:
            if word in _RTF_SKIP:
                skipping = True
            elif word == "ansicpg" and arg:
                codepage = _rtf_codec(_RTF_CODEPAGES.get(arg.lstrip("-"), f"cp{arg.lstrip('-')}"))
            elif word in _RTF_CHARSETS and not stack[1:]:     # \mac, \pc ... in the header
                codepage = _RTF_CHARSETS[word]
            elif word == "uc" and arg:
                uc = int(arg)
            elif word == "u" and arg:
                if not skipping:
                    n = int(arg)
                    n = n + 65536 if n < 0 else n
                    if 0 <= n <= 0xFFFF:          # RTF \uN is 16-bit; pairs are joined below
                        out.append(chr(n))
                pending_skip = uc
            elif not skipping:
                if word in ("par", "line", "sect", "page"):
                    out.append("\n")
                elif word in ("tab", "cell"):
                    out.append("\t")
                elif word == "row":
                    out.append("\n")
                elif word == "emdash":
                    out.append("—")
                elif word == "endash":
                    out.append("–")
                elif word in ("lquote", "rquote"):
                    out.append("'")
                elif word in ("ldblquote", "rdblquote"):
                    out.append('"')
        elif sym is not None:
            if sym == "*":
                skipping = True                 # {\* ...} unknown destination
            elif not skipping and sym in "\\{}":
                out.append(sym)
            elif not skipping and sym == "~":
                out.append("\u00a0")
        elif text is not None:
            if pending_skip:                     # characters standing in for a \uN escape
                take = min(pending_skip, len(text))
                text = text[take:]
                pending_skip -= take
            if not skipping and text:
                out.append(text)
    flush_hex()
    # Word writes characters outside the BMP (emoji) as two \uN surrogates: join them,
    # and turn a lone surrogate into U+FFFD so the text can be stored.
    joined = "".join(out).encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")
    lines = joined.split("\n")
    return "\n".join(line.rstrip() for line in lines).strip("\n")


def rtf_text(path: str | Path) -> str:
    return rtf_to_text(Path(path).read_bytes().decode("latin-1"))


def xlsx_rows(path: str | Path) -> list[tuple[str, list[list[str]]]]:
    """[(sheet name, rows)] with every cell as text; empty trailing cells dropped."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheets = []
        for ws in wb.worksheets:
            rows = []
            for row in ws.iter_rows(values_only=True):
                cells = ["" if v is None else str(v) for v in row]
                while cells and not cells[-1].strip():
                    cells.pop()
                if cells:
                    rows.append(cells)
            sheets.append((ws.title, rows))
        return sheets
    finally:
        wb.close()


def file_text(path: str | Path) -> str:
    """The text of a Word, RTF or Excel file."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext in WORD_EXT:
        return "\n".join(docx_paragraphs(p))
    if ext in RTF_EXT:
        return rtf_text(p)
    if ext in EXCEL_EXT:
        return "\n\n".join("\n".join("\t".join(r) for r in rows) for _name, rows in xlsx_rows(p))
    raise ValueError(f"not a document: {p.name}")


# ---------------------------------------------------------------- import
def assets_dir() -> Path:
    d = paths.data_dir() / "assets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _copy_asset(p: Path) -> Path:
    """Copy into the assets folder under a content hash, so a re-import reuses the file."""
    digest = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    target = assets_dir() / f"{p.stem[:40]}-{digest}{p.suffix.lower()}"
    if not target.exists():
        shutil.copyfile(p, target)
    return target


MAX_ATTACHMENT = 50 * 1024 * 1024
ATTACHED = "attached"


def attach_file(path: str | Path) -> str:
    """Keep a copy of a file with PhraseForge (G-21: a file attached to a phrase) and return the
    macro that pastes it: {#pastefile "attached/<hash>/<name>"}. The path is relative to the
    assets folder, so it still works when the data folder moves (portable mode); the copy keeps
    the file's own name, which is what the pasted file is called."""
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"Not a file: {p.name}")
    size = p.stat().st_size
    if size > MAX_ATTACHMENT:
        raise ValueError(f"{p.name} is larger than {MAX_ATTACHMENT // (1024 * 1024)} MB.")
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    folder = assets_dir() / ATTACHED / h.hexdigest()[:16]
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / p.name
    if not target.exists():
        shutil.copyfile(p, target)
    rel = target.relative_to(assets_dir()).as_posix()
    return '{#pastefile "' + rel.replace('"', "'") + '"}'


def resolve_attachment(path: str) -> Path | None:
    """The file of a relative "attached/..." path, or None when it is not one of ours
    (absolute, outside the attachments folder, or missing)."""
    if not path or os.path.isabs(path) or not path.replace("\\", "/").startswith(ATTACHED + "/"):
        return None
    base = (assets_dir() / ATTACHED).resolve()
    target = (assets_dir() / path).resolve()
    if base not in target.parents or not target.is_file():
        return None
    return target


def _q(path: Path) -> str:
    return '"' + str(path).replace('"', '\\"') + '"'


def _label(text: str, limit: int = 60) -> str:
    one = " ".join(text.split())
    return one if len(one) <= limit else one[:limit - 1].rstrip() + "…"


def _table_phrases(rows: list[list[str]]) -> list[Phrase]:
    """Rows of a sheet → phrases. A header row naming the columns maps them
    (same names as the PhraseExpress CSV import); otherwise column A is the
    description and the other cells the content (or column A alone)."""
    from phraseforge.importers.phraseexpress import map_header
    out = []
    cols = map_header(rows[0]) if rows else None
    body = rows[1:] if cols else rows
    for cells in body:
        if cols:
            rec = {f: cells[i].strip() if i < len(cells) else "" for i, f in cols.items()}
            content = rec.get("content", "")
            desc = rec.get("description") or _label(content)
            if not (desc or content):
                continue
            p = Phrase(desc, content)
            p.folder_path = rec.get("folder", "")
            trig = []
            for ab in (rec.get("autotext") or "").split("|"):
                if ab.strip():
                    trig.append(Trigger(TriggerKind.AUTOTEXT, ab.strip()))
            if rec.get("hotkey"):
                trig.append(Trigger(TriggerKind.HOTKEY, rec["hotkey"]))
            p.triggers = trig
        else:
            filled = [c for c in cells if c.strip()]
            if not filled:
                continue
            if len(cells) >= 2 and cells[0].strip() and any(c.strip() for c in cells[1:]):
                p = Phrase(_label(cells[0]), "\t".join(cells[1:]).rstrip("\t"))
            else:
                p = Phrase(_label(filled[0]), "\t".join(cells))
            p.folder_path = ""
            p.triggers = []
        out.append(p)
    return out


def phrases_from_file(path: str | Path, mode: str = "copy") -> list[Phrase]:
    """The phrases importing this file would create (nothing is stored)."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext not in SUPPORTED:
        raise ValueError(f"Unsupported file type: {ext or p.name}")
    if mode not in modes_for(p):
        raise ValueError(f"{mode!r} import is not available for {ext} files")
    if mode == "open":
        return [Phrase(p.stem, "{#open " + _q(p) + "}")]
    if ext in IMAGE_EXT:
        target = _copy_asset(p) if mode == "copy" else p
        return [Phrase(p.stem, "{#image " + _q(target) + "}")]
    if mode == "link":
        return [Phrase(p.stem, "{#document " + _q(p) + "}")]
    if ext in EXCEL_EXT:
        sheets = xlsx_rows(p)
        if mode == "copy":
            return [Phrase(p.stem if len(sheets) == 1 else f"{p.stem} - {name}",
                           "\n".join("\t".join(r) for r in rows)) for name, rows in sheets if rows]
        out = []
        for _name, rows in sheets:
            out += _table_phrases(rows)
        return out
    if mode == "copy":
        return [Phrase(p.stem, file_text(p))]
    paras = docx_paragraphs(p) if ext in WORD_EXT else rtf_text(p).split("\n")
    return [Phrase(_label(t), t) for t in (x.strip() for x in paras) if t]


@untrusted_import
def import_document_file(store: Store, path: str | Path, mode: str = "copy",
                         into_folder_id: int | None = None) -> int:
    """Import one file in the chosen mode; returns the number of phrases created."""
    from phraseforge.io_formats import ensure_folder_path
    phrases = phrases_from_file(path, mode)
    for ph in phrases:
        sub = getattr(ph, "folder_path", "")
        ph.folder_id = ensure_folder_path(store, sub, into_folder_id) if sub else into_folder_id
        store.add_phrase(ph)
    return len(phrases)
