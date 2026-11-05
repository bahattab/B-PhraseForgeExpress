"""E-mail signatures: one place to keep them, insert them anywhere, and hand them to Outlook.

PhraseExpress has a signature manager for mail programs including Outlook:
signatures kept centrally, in several languages, with contact details from
ActiveDirectory, logos and formatted text, footers that appear only for a time,
and random quotes. PhraseForge builds the same on its own parts:

  Signatures/            a top-level folder; each phrase in it is one signature
                         (plain or formatted text, language versions, macros such
                         as {#ad name} or {#ad telephone} for ActiveDirectory fields)
  Signatures/Footers/    footers added below the signature while they are active:
                         setting signature.footer_dates = {"<phrase id>": ["MM-DD" or
                         "YYYY-MM-DD", same]}; a footer without dates is always on,
                         and an MM-DD range may wrap over New Year (12-15 .. 01-05)
  Signatures/Quotes/     one is picked at random below the signature when
                         signature.random_quote is "1"

  signature.default      phrase id of the default signature

The {#signature} macro inserts the default signature, or {#signature "Name"} a named
one. export_outlook() writes each signature as <name>.htm, .rtf and .txt into
Outlook's signature folder (%APPDATA%\\Microsoft\\Signatures), so Outlook's own
signature picker offers them; set_outlook_default() makes one the default for new
mail and replies (classic Outlook; the new Outlook keeps signatures in the cloud).
"""
from __future__ import annotations

import html as _html
import json
import os
import random
import re
from datetime import date
from pathlib import Path
from typing import Callable

from phraseforge.models import Folder, Phrase

FOLDER, FOOTERS, QUOTES = "Signatures", "Footers", "Quotes"
_ARABIC = re.compile(r"[\u0590-\u08FF\uFB1D-\uFDFF\uFE70-\uFEFF]")
_BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

TEMPLATE = "Best regards,\n\n{#ad name}\n{#ad title}\n{#ad company}\nTel. {#ad telephone}\n{#ad email}"


# ---------------------------------------------------------------- folders and settings
def _child(store, parent_id, name, create):
    f = next((f for f in store.folders(parent_id) if f.name == name), None)
    if f is None and create:
        f = store.add_folder(Folder(name, parent_id=parent_id))
    return f


def folder(store, create: bool = False):
    return _child(store, None, FOLDER, create)


def subfolder(store, name: str, create: bool = False):
    top = folder(store, create)
    return _child(store, top.id, name, create) if top else None


def _phrases_in(store, f) -> list[Phrase]:
    return sorted((p for p in store.phrases() if f is not None and p.folder_id == f.id),
                  key=lambda p: p.description.casefold())


def signatures(store) -> list[Phrase]:
    return _phrases_in(store, folder(store))


def footers(store) -> list[Phrase]:
    return _phrases_in(store, subfolder(store, FOOTERS))


def quotes(store) -> list[Phrase]:
    return _phrases_in(store, subfolder(store, QUOTES))


def new_signature(store, name: str, content: str = TEMPLATE) -> Phrase:
    p = store.add_phrase(Phrase(name, content, folder_id=folder(store, create=True).id))
    if not store.setting("signature.default", ""):
        set_default(store, p.id)
    return p


def default(store) -> Phrase | None:
    sigs = signatures(store)
    try:
        want = int(store.setting("signature.default", "") or 0)
    except ValueError:
        want = 0
    return next((p for p in sigs if p.id == want), sigs[0] if sigs else None)


def set_default(store, phrase_id: int) -> None:
    store.set_setting("signature.default", str(phrase_id))


def footer_dates(store) -> dict[int, tuple[str, str]]:
    try:
        raw = json.loads(store.setting("signature.footer_dates", "{}") or "{}")
    except ValueError:
        return {}
    out = {}
    for k, v in raw.items() if isinstance(raw, dict) else ():
        if isinstance(v, (list, tuple)) and len(v) == 2:
            try:
                out[int(k)] = (str(v[0] or ""), str(v[1] or ""))
            except ValueError:
                continue
    return out


def set_footer_dates(store, phrase_id: int, start: str, end: str) -> None:
    for s in (start, end):
        if s and _parse(s) is None:
            raise ValueError(f"not a date: {s!r} (use MM-DD or YYYY-MM-DD)")
    d = {str(k): list(v) for k, v in footer_dates(store).items()}
    if start or end:
        d[str(phrase_id)] = [start, end]
    else:
        d.pop(str(phrase_id), None)
    store.set_setting("signature.footer_dates", json.dumps(d))


# ---------------------------------------------------------------- dates
def _parse(s: str):
    """"MM-DD" -> (None, m, d); "YYYY-MM-DD" -> (y, m, d); else None."""
    m = re.fullmatch(r"(?:(\d{4})-)?(\d{1,2})-(\d{1,2})", s.strip())
    if not m:
        return None
    y, mo, d = (int(m.group(1)) if m.group(1) else None), int(m.group(2)), int(m.group(3))
    try:
        date(y or 2000, mo, d)                     # 2000 is a leap year, so 02-29 is allowed
    except ValueError:
        return None
    return y, mo, d


def is_active(start: str, end: str, today: date) -> bool:
    """Whether a footer with this date range shows today. Empty = open on that side."""
    a, b = (_parse(start) if start else None), (_parse(end) if end else None)
    if (start and a is None) or (end and b is None):
        return False
    if (a and a[0]) or (b and b[0]):                # at least one full date: compare dates
        lo = date(*a) if a and a[0] else (date(today.year, a[1], a[2]) if a else date.min)
        hi = date(*b) if b and b[0] else (date(today.year, b[1], b[2]) if b else date.max)
        return lo <= today <= hi
    t = (today.month, today.day)
    lo = (a[1], a[2]) if a else (1, 1)
    hi = (b[1], b[2]) if b else (12, 31)
    return lo <= t <= hi if lo <= hi else (t >= lo or t <= hi)   # wraps over New Year


def active_footers(store, today: date | None = None) -> list[Phrase]:
    today = today or date.today()
    dates = footer_dates(store)
    return [p for p in footers(store) if p.enabled and is_active(*dates.get(p.id, ("", "")), today)]


# ---------------------------------------------------------------- composing
def _text_to_html(text: str) -> str:
    out = []
    for line in text.split("\n"):
        esc = _html.escape(line, quote=False)      # quotes stay: macro arguments use them
        out.append(f'<span dir="rtl">{esc}</span>' if _ARABIC.search(line) else esc)
    return "<br>".join(out)


def find(store, name: str = "") -> Phrase | None:
    if not name:
        return default(store)
    key = name.casefold()
    sigs = signatures(store)
    return next((p for p in sigs if p.description.casefold() == key), None) or \
        next((p for p in sigs if str(p.id) == name), None)


def compose(store, name: str = "", lang: str = "", today: date | None = None,
            rng: random.Random | None = None) -> tuple[str, str] | None:
    """(content, format) of a signature with its active footers and a random quote,
    macros not yet run. None when there is no such signature."""
    sig = find(store, name)
    if sig is None:
        return None
    parts = [store.phrase_text(sig, lang)]
    parts += [store.phrase_text(p, lang) for p in active_footers(store, today)]
    if store.setting("signature.random_quote", "0") == "1":
        qs = [p for p in quotes(store) if p.enabled]
        if qs:
            parts.append(store.phrase_text((rng or random).choice(qs), lang))
    parts = [(c, f) for c, f in parts if (c or "").strip()]
    if all(f != "html" for _c, f in parts):
        return "\n\n".join(c.strip("\n") for c, _f in parts), "text"
    return "<br><br>".join(c if f == "html" else _text_to_html(c.strip("\n")) for c, f in parts), "html"


# ---------------------------------------------------------------- Outlook
def outlook_dir() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Microsoft" / "Signatures"


def file_name(name: str) -> str:
    """A signature name Windows accepts as a file name."""
    clean = _BAD_NAME.sub("_", name).strip().rstrip(".")
    return clean[:80] or "Signature"


def html_document(body: str, title: str = "") -> str:
    rtl = ' dir="rtl"' if _ARABIC.search(re.sub(r"<[^>]+>", "", body)) else ""
    return ('<html><head><meta http-equiv="Content-Type" content="text/html; charset=utf-8">'
            f"<title>{_html.escape(title)}</title></head>"
            f'<body{rtl}><div style="font-family:Calibri,Arial,sans-serif;font-size:11pt">'
            f"{body}</div></body></html>")


def export_outlook(store, expand: Callable[[str, str], str], target: str | Path | None = None,
                   ids: list[int] | None = None, today: date | None = None) -> list[Path]:
    """Write each signature (macros run by expand(content, format) -> text or HTML) as
    <name>.htm, .rtf and .txt into Outlook's signature folder. Returns the .htm paths."""
    from phraseforge import rtf
    from phraseforge.macros.engine import html_to_text
    out_dir = Path(target) if target else outlook_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for sig in signatures(store):
        if ids is not None and sig.id not in ids:
            continue
        content, fmt = compose(store, sig.description, today=today)
        result = expand(content, fmt)
        body = result if fmt == "html" else _text_to_html(result)
        plain = html_to_text(result) if fmt == "html" else result
        base = out_dir / file_name(sig.description)
        base.with_suffix(".htm").write_text(html_document(body, sig.description), encoding="utf-8")
        base.with_suffix(".rtf").write_text(rtf.html_to_rtf(body), encoding="ascii", errors="replace")
        base.with_suffix(".txt").write_text(plain, encoding="utf-16")    # Outlook reads Unicode .txt
        written.append(base.with_suffix(".htm"))
    return written


OUTLOOK_MAIL_SETTINGS = r"Software\Microsoft\Office\16.0\Common\MailSettings"


def set_outlook_default(name: str, new: bool = True, reply: bool = True, winreg=None) -> None:
    """Make an exported signature Outlook's default for new mail and/or replies
    (HKCU MailSettings NewSignature / ReplySignature; Outlook 2016 and later)."""
    if winreg is None:
        import winreg  # type: ignore
    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, OUTLOOK_MAIL_SETTINGS)
    try:
        for flag, value in (("NewSignature", new), ("ReplySignature", reply)):
            if value:
                winreg.SetValueEx(key, flag, 0, winreg.REG_SZ, file_name(name))
    finally:
        winreg.CloseKey(key)


def preview_expand(store) -> Callable[[str, str], str]:
    """expand() for export: macros run without prompts (form fields keep their defaults)."""
    from phraseforge.host import TextAction
    from phraseforge.macros import MacroEngine
    from phraseforge.ui.main_window import PreviewHost

    engine = MacroEngine(PreviewHost(store), store)

    def expand(content: str, fmt: str) -> str:
        actions = engine.expand(content)
        return "".join(a.text for a in actions if isinstance(a, TextAction)) if fmt == "html" \
            else engine.expand_to_text(content)
    return expand
