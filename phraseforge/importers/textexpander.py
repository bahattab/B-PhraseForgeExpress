"""Import TextExpander snippet exports into PhraseForge.

Built from TextExpander's public snippet documentation and its export formats;
no TextExpander code or binaries are used. Supported inputs:
- CSV export: rows of abbreviation, content[, label]
- .textexpander group file (XML plist with a `snippetsTE2` array)

TextExpander macros are converted to PhraseForge macros where an equivalent
exists; anything unknown is kept as literal text and reported.
"""
from __future__ import annotations

import csv
import plistlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from phraseforge.db import Store
from phraseforge.models import AutotextMode, Folder, Phrase, Trigger, TriggerKind

# TextExpander date/time tokens -> PhraseForge {#date -format} tokens
DATE_TOKENS = {
    "Y": "yyyy", "y": "yy", "m": "MM", "1m": "M", "B": "MMMM", "b": "MMM",
    "d": "dd", "e": "d", "A": "dddd", "a": "ddd",
    "H": "HH", "1H": "H", "I": "hh", "1I": "h", "M": "mm", "S": "ss", "p": "tt",
    "j": "DDD", "Z": "zzz",
}
# %key:name% names -> PhraseForge key names
KEY_NAMES = {
    "tab": "tab", "enter": "enter", "return": "enter", "esc": "esc", "escape": "esc",
    "space": "space", "backspace": "backspace", "delete": "delete", "del": "delete",
    "up": "up", "down": "down", "left": "left", "right": "right",
    "uparrow": "up", "downarrow": "down", "leftarrow": "left", "rightarrow": "right",
    "home": "home", "end": "end", "pageup": "pgup", "pagedown": "pgdn",
}
_DATE_MATH_UNITS = {"D": "d", "M": "m", "Y": "y", "h": "h", "m": "min", "s": "s"}

_TOKEN = re.compile(
    r"%(?:"
    r"(?P<datemath>@[+-]\d+[DMYhms])"
    r"|(?P<clip>clipboard)"
    r"|(?P<named>snippet:[^%]+|key:[^%]+|(?:fill(?:text|area|popup|part|date)?):[^%]*|fillpartend|fill)"
    r"(?P<close>%)"
    r"|(?P<cursor>\|)"
    r"|(?P<pct>%)"
    r"|(?P<date>1[mHI]|[YymBbdeAaHIMSpjZ])"
    r")"
)


def q(s: str) -> str:
    """Quote an argument for PhraseForge macro syntax."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


@dataclass
class Conversion:
    content: str
    unknown: list[str] = field(default_factory=list)


def _parse_fill(spec: str) -> tuple[str, dict[str, str], list[str]]:
    """'filltext:name=First Name:default=Bob:width=20' -> ('filltext', {...}, [popup options])."""
    kind, _, rest = spec.partition(":")
    opts: dict[str, str] = {}
    extra: list[str] = []
    for part in rest.split(":") if rest else []:
        if "=" in part:
            k, _, v = part.partition("=")
            opts[k.strip()] = v
        elif part:
            extra.append(part)
    return kind, opts, extra


def convert(te: str) -> Conversion:
    """Convert one TextExpander snippet body into PhraseForge macro text."""
    out: list[str] = []
    unknown: list[str] = []
    date_run: list[str] = []      # consecutive date tokens + literal separators
    date_offset = ""
    fill_count = 0
    pos = 0

    def flush_date():
        nonlocal date_offset
        if date_run:
            fmt = "".join(date_run)
            opt = f" -offset {date_offset}" if date_offset else ""
            out.append("{#date -format " + q(fmt) + opt + "}")
            date_run.clear()
            date_offset = ""  # an offset applies to the next date run only

    def lit(s: str):
        out.append(s.replace("{", "{{"))

    for m in _TOKEN.finditer(te):
        between = te[pos:m.start()]
        pos = m.end()
        # short literal separators between date tokens stay inside the format
        if date_run and between and re.fullmatch(r"[ ,./:\-]{1,3}", between) and m.group("date"):
            date_run.append(between.replace("'", "''") if between.isalpha() else between)
        else:
            flush_date()
            if between:
                lit(between)
        if m.group("date"):
            date_run.append(DATE_TOKENS[m.group("date")])
            continue
        if m.group("datemath"):
            flush_date()
            sign_n, unit = m.group("datemath")[1:-1], m.group("datemath")[-1]
            date_offset = sign_n + _DATE_MATH_UNITS[unit]
            continue
        flush_date()
        if m.group("clip"):
            out.append("{#clipboard}")
        elif m.group("cursor"):
            out.append("{#cursor}")
        elif m.group("pct"):
            out.append("%")
        elif m.group("named"):
            name = m.group("named")
            if name.startswith("snippet:"):
                out.append("{#insert " + q(name[8:]) + "}")
            elif name.startswith("key:"):
                key = KEY_NAMES.get(name[4:].lower().replace(" ", ""))
                if key:
                    out.append("{#keys " + key + "}")
                else:
                    unknown.append(name)
                    lit("%" + name + "%")
            elif name == "fillpartend":
                out.append("{#endif}")
            else:
                kind, opts, extra = _parse_fill(name)
                fill_count += 1
                fname = opts.get("name") or f"field{fill_count}"
                default = opts.get("default", "")
                var = "te_" + re.sub(r"\W+", "_", fname).strip("_").lower()
                if kind in ("fill", "filltext"):
                    out.append("{#ask " + q(var) + " -prompt " + q(fname) + " -default " + q(default) + "}")
                elif kind == "fillarea":
                    out.append("{#ask " + q(var) + " -prompt " + q(fname) + " -default " + q(default) + " -multiline}")
                elif kind == "fillpopup":
                    options = [default] + [o for o in extra if o != default] if default else extra
                    out.append("{#askchoice " + q(var) + " -prompt " + q(fname) + " -options "
                               + q("|".join(options)) + "}")
                elif kind == "fillpart":
                    on = opts.get("default", "yes").lower() in ("yes", "true", "1")
                    out.append("{#askcheck " + q(var) + " -prompt " + q(fname)
                               + (" -checked" if on else "") + "}{#if {#var " + q(var) + "} == \"1\"}")
                elif kind == "filldate":
                    out.append("{#askdate " + q(var) + " -prompt " + q(fname) + "}")
                else:
                    unknown.append(name)
                    lit("%" + name + "%")
    tail = te[pos:]
    flush_date()
    if tail:
        lit(tail)
    return Conversion("".join(out), unknown)


@dataclass
class ImportReport:
    imported: int = 0
    skipped: int = 0
    unknown_macros: dict[str, int] = field(default_factory=dict)
    folder_id: int | None = None


def _add(store: Store, folder_id: int, abbr: str, body: str, label: str, html: bool,
         report: ImportReport) -> None:
    if not body and not abbr:
        report.skipped += 1
        return
    conv = convert(body)
    for u in conv.unknown:
        report.unknown_macros[u] = report.unknown_macros.get(u, 0) + 1
    triggers = [Trigger(TriggerKind.AUTOTEXT, abbr, mode=AutotextMode.IMMEDIATE, word_start_only=False)] if abbr else []
    store.add_phrase(Phrase(label or abbr or body[:40], conv.content, folder_id=folder_id,
                            content_format="html" if html else "text", triggers=triggers,
                            tags=["textexpander"]))
    report.imported += 1


def import_csv(store: Store, path: str | Path, folder_name: str | None = None) -> ImportReport:
    """TextExpander CSV export: abbreviation, content[, label]. No header row."""
    path = Path(path)
    report = ImportReport()
    folder = store.add_folder(Folder(folder_name or path.stem))
    report.folder_id = folder.id
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            if row[0].strip().lower() in ("abbreviation", "abbr") and len(row) > 1 \
                    and row[1].strip().lower() in ("content", "snippet", "plaintext"):
                continue  # header row from some export tools
            abbr = row[0].strip()
            body = row[1] if len(row) > 1 else ""
            label = row[2].strip() if len(row) > 2 else ""
            _add(store, folder.id, abbr, body, label, False, report)
    return report


def import_textexpander_file(store: Store, path: str | Path) -> ImportReport:
    """A .textexpander group file (XML or binary plist)."""
    path = Path(path)
    with open(path, "rb") as fh:
        data = plistlib.load(fh)
    report = ImportReport()
    name = data.get("groupInfo", {}).get("groupName") if isinstance(data.get("groupInfo"), dict) else None
    folder = store.add_folder(Folder(name or path.stem))
    report.folder_id = folder.id
    for s in data.get("snippetsTE2") or data.get("snippets") or []:
        abbr = s.get("abbreviation", "")
        # snippetType 0 = plain text, 1 = rich text (RTF; we keep plainText), 2/3 = scripts
        stype = int(s.get("snippetType", 0) or 0)
        body = s.get("plainText", "")
        if stype >= 2:
            report.unknown_macros["script snippet"] = report.unknown_macros.get("script snippet", 0) + 1
            body = "{#message " + q("Script snippet imported as text; review it before use.") + "}" + body
        _add(store, folder.id, abbr, body, s.get("label", ""), False, report)
    return report


def import_any(store: Store, path: str | Path) -> ImportReport:
    p = Path(path)
    if p.suffix.lower() == ".csv":
        return import_csv(store, p)
    return import_textexpander_file(store, p)
