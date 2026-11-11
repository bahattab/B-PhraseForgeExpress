"""Import AutoHotkey hotstrings (PRD G-16, FR-IMP-04).

Reads the auto-replace hotstrings of an .ahk script, as AutoHotkey documents them
(https://www.autohotkey.com/docs/v2/Hotstrings.htm):

    ::btw::by the way                 single line
    :*:]d::{#date}                    options between the first two colons
    ::sig::                           a continuation section: the text is the lines
    (                                 between "(" and ")"
    Best regards,
    John
    )

Options kept: `*` (no ending character needed) -> expand immediately, `?` (inside words) ->
also in the middle of a word, `C` -> case-sensitive, `O` -> the ending character is dropped.
`R`/`T` (raw/text) send the text as written. Without them, {Enter}, {Tab}, {Space}, {{} and
{}} are translated; other {Key} names and the modifier symbols ^ ! + # are kept as text and
counted in the report, because they mean keys that PhraseForge would press differently.

Not imported (counted as skipped): hotstrings that run code (option X, or an empty
replacement followed by code lines), and every other line of the script. Imported phrases
are quarantined like every import (db.untrusted_import).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from phraseforge.db import Store, untrusted_import
from phraseforge.models import AutotextMode, Folder, Phrase, Trigger, TriggerKind

HOTSTRING = re.compile(r"^\s*:([0-9A-Za-z*?]*):(.+?)::(.*)$")
ESCAPES = {"n": "\n", "t": "\t", "r": "", "`": "`", ";": ";", ":": ":", "{": "{", "}": "}", "s": " ",
           "b": "", '"': '"', "'": "'"}
KEYS = {"enter": "\n", "tab": "\t", "space": " ", "{": "{", "}": "}"}
KEY_RE = re.compile(r"\{([^{}]+|\{|\})\}")
MAX_FILE = 8 * 1024 * 1024
MAX_HOTSTRINGS = 20000     # a hotstring list, not a database (R148)
OPTION = re.compile(r"[*?]0?|[A-Z]\d*", re.I)


def options(opts: str) -> dict[str, str]:
    """':*?C1O:' options as {letter: value}; "0" turns an option off, so it is left out.
    Unknown letters (B0, SI, Kn, Pn, Z, ...) are kept and ignored."""
    out: dict[str, str] = {}
    for tok in OPTION.findall(opts or ""):
        letter, value = tok[0].upper(), tok[1:]
        if value == "0":
            out.pop(letter, None)
        else:
            out[letter] = value
    return out


@dataclass
class ImportReport:
    imported: int = 0
    skipped: int = 0
    unknown_macros: dict[str, int] = field(default_factory=dict)
    folder_id: int | None = None


@dataclass
class Hotstring:
    abbr: str
    text: str
    options: str
    raw: bool


def unescape(s: str) -> str:
    """AutoHotkey's escape character is the backtick: `n newline, `t tab, `` a backtick."""
    out, i = [], 0
    while i < len(s):
        ch = s[i]
        if ch == "`" and i + 1 < len(s):
            out.append(ESCAPES.get(s[i + 1], s[i + 1]))
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def strip_comment(line: str) -> str:
    """Drop a ' ;comment' (a semicolon after whitespace; `; is an escaped semicolon)."""
    m = re.search(r"(?<!`)\s;", line)
    return line[:m.start()] if m else line


def parse(text: str) -> tuple[list[Hotstring], int]:
    """(hotstrings, skipped): the auto-replace hotstrings of a script."""
    lines = text.splitlines()
    found: list[Hotstring] = []
    skipped = 0
    i = 0
    in_comment = False
    while i < len(lines):
        line = lines[i]
        i += 1
        s = line.strip()
        if in_comment:
            in_comment = not s.startswith("*/")
            continue
        if s.startswith("/*"):
            in_comment = not s.endswith("*/")
            continue
        m = HOTSTRING.match(line)
        if not m:
            continue
        opts, abbr, rest = m.group(1), m.group(2), m.group(3)
        o = options(opts)
        raw = "R" in o or "T" in o
        if "X" in o:
            skipped += 1                   # runs code, not text
            continue
        body = strip_comment(rest).rstrip(" \t")   # trailing blanks are ignored unless escaped (`s)
        if body.strip() == "{":           # v2 function body: code
            skipped += 1
            continue
        if not body.strip():
            if i < len(lines) and lines[i].strip().startswith("("):      # continuation section
                sec = lines[i].strip()[1:].split()
                i += 1
                part = []
                while i < len(lines) and not lines[i].lstrip().startswith(")"):
                    part.append(lines[i])
                    i += 1
                if i >= len(lines):        # no ")": not a section, do not swallow the script
                    skipped += 1
                    continue
                i += 1                     # the ")" line
                low = [x.lower() for x in sec]
                join = "\n"
                for x in sec:
                    if x.lower().startswith("join"):
                        join = unescape(x[4:])
                if "ltrim" in low:
                    part = [p.lstrip(" \t") for p in part]
                if "rtrim0" not in low:    # AutoHotkey trims each line's end by default
                    part = [p.rstrip(" \t") for p in part]
                if "c" in low or "comments" in low:
                    part = [strip_comment(p).rstrip(" \t") for p in part if not p.lstrip().startswith(";")]
                found.append(Hotstring(unescape(abbr), unescape(join.join(part)), opts, raw))
            else:
                skipped += 1               # "::abbr::" then code lines (Send, Run, ... return)
            continue
        found.append(Hotstring(unescape(abbr), unescape(body), opts, raw))   # `n etc. also in R/T mode
    return found, skipped


def convert(h: Hotstring, unknown: dict[str, int]) -> str:
    """The phrase text. Braces in the AutoHotkey text are literal there (AutoHotkey has no
    {#...} macros), so a "{" before "#" or "{" is written "{{" and stays text (R147)."""
    return _literal(_convert(h, unknown))


def _literal(text: str) -> str:
    return re.sub(r"\{(?=[{#])", "{{", text)


def _convert(h: Hotstring, unknown: dict[str, int]) -> str:
    if h.raw:
        return h.text

    def key(m):
        name = m.group(1).strip()
        k = KEYS.get(name.lower())
        if k is not None:
            return k
        unknown["{" + name + "}"] = unknown.get("{" + name + "}", 0) + 1
        return m.group(0)
    out = KEY_RE.sub(key, h.text)
    for sym in "^!+#":
        if sym in KEY_RE.sub("", h.text):
            unknown[sym] = unknown.get(sym, 0) + 1
    return out


def trigger_for(h: Hotstring) -> Trigger:
    o = options(h.options)
    t = Trigger(TriggerKind.AUTOTEXT, h.abbr,
                mode=AutotextMode.IMMEDIATE if "*" in o else AutotextMode.DELIMITER,
                case_sensitive="C" in o and o["C"] != "1",       # C = case-sensitive, C1 = not
                word_start_only="?" not in o)
    if "?" in o:
        t.word_pos = "middle"
    if "O" in o and "*" not in o:
        t.remove_trailing = True
    return t


@untrusted_import
def import_ahk(store: Store, path: str | Path) -> ImportReport:
    path = Path(path)
    if path.stat().st_size > MAX_FILE:
        raise ValueError("The script is larger than 8 MB; this is not a hotstring list.")
    raw = path.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = raw.decode("utf-16", "replace")
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:          # older scripts are often saved as ANSI
            text = raw.decode("cp1252", "replace")
    hotstrings, skipped = parse(text)
    if len(hotstrings) > MAX_HOTSTRINGS:
        raise ValueError(f"The script has more than {MAX_HOTSTRINGS} hotstrings; split it into smaller files.")
    report = ImportReport(skipped=skipped)
    folder = store.add_folder(Folder(path.stem))
    report.folder_id = folder.id
    for h in hotstrings:
        if not h.abbr:
            report.skipped += 1
            continue
        body = convert(h, report.unknown_macros)
        label = (body.strip().splitlines() or [h.abbr])[0][:60] or h.abbr
        store.add_phrase(Phrase(label, body, folder_id=folder.id, triggers=[trigger_for(h)], tags=["autohotkey"]))
        report.imported += 1
    return report
