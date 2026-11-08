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
            rng: random.Random | None = None, sig: Phrase | None = None) -> tuple[str, str] | None:
    """(content, format) of a signature (by name, or the phrase `sig`) with its active
    footers and a random quote, macros not yet run. None when there is no such signature."""
    sig = sig or find(store, name)
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


_RESERVED = re.compile(r"(CON|PRN|AUX|NUL|COM[0-9¹²³]|LPT[0-9¹²³])(\..*)?", re.I)


def file_name(name: str) -> str:
    """A signature name Windows accepts as a file name (no extension added)."""
    clean = _BAD_NAME.sub("_", name).strip().rstrip(". ")
    clean = clean[:80].rstrip(". ") or "Signature"
    return "_" + clean if _RESERVED.fullmatch(clean) else clean     # CON, NUL, COM1 ... are devices


def outlook_names(store) -> dict[int, str]:
    """{signature phrase id: file name without extension}, unique ignoring case: a second
    "Sig" becomes "Sig (2)". The same names are used for the files and the registry."""
    used: set[str] = set()
    out = {}
    for sig in sorted(signatures(store), key=lambda p: p.id):
        base = name = file_name(sig.description)
        n = 2
        while name.casefold() in used:
            name = f"{base} ({n})"
            n += 1
        used.add(name.casefold())
        out[sig.id] = name
    return out


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
    names = outlook_names(store)
    for sig in signatures(store):
        if ids is not None and sig.id not in ids:
            continue
        content, fmt = compose(store, today=today, sig=sig)
        result = expand(content, fmt, signature_trusted(store, sig))
        body = result if fmt == "html" else _text_to_html(result)
        plain = html_to_text(result) if fmt == "html" else result
        stem = names[sig.id]                       # not with_suffix(): "Mr. Smith" must stay whole
        (out_dir / (stem + ".htm")).write_text(html_document(body, sig.description), encoding="utf-8")
        (out_dir / (stem + ".rtf")).write_text(rtf.html_to_rtf(body), encoding="ascii", errors="replace")
        (out_dir / (stem + ".txt")).write_text(plain, encoding="utf-16")    # Outlook reads Unicode .txt
        written.append(out_dir / (stem + ".htm"))
    return written


def signature_trusted(store, sig: Phrase) -> bool:
    """False when the signature, a footer or a quote is an imported or synced phrase not yet
    approved on this PC: its privileged macros ({#outputfile}, {#run} ...) must not run."""
    origin = getattr(store, "quarantine_origin", None)
    if origin is None:
        return True
    return not any(origin(p.id) for p in [sig] + footers(store) + quotes(store))


OUTLOOK_MAIL_SETTINGS = r"Software\Microsoft\Office\16.0\Common\MailSettings"


def set_outlook_default(name: str, new: bool = True, reply: bool = True, winreg=None) -> None:
    """Make an exported signature Outlook's default for new mail and/or replies
    (HKCU MailSettings NewSignature / ReplySignature; Outlook 2016 and later).
    `name` is the file name export_outlook() used (outlook_names()), without extension."""
    if winreg is None:
        import winreg  # type: ignore
    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, OUTLOOK_MAIL_SETTINGS)
    try:
        for flag, value in (("NewSignature", new), ("ReplySignature", reply)):
            if value:
                winreg.SetValueEx(key, flag, 0, winreg.REG_SZ, file_name(name))
    finally:
        winreg.CloseKey(key)


def preview_expand(store) -> Callable[..., str]:
    """expand(content, format, trusted=False) for preview and export: macros run without
    prompts (form fields keep their defaults). Privileged macros ({#outputfile}, {#run},
    {#http} ...) run only for trusted=True, i.e. an export of signatures that are all
    approved on this PC; a preview never runs them (security R21)."""
    from phraseforge.host import ExpansionContext, TextAction
    from phraseforge.macros import MacroEngine
    from phraseforge.ui.main_window import PreviewHost

    engine = MacroEngine(PreviewHost(store), store)

    def expand(content: str, fmt: str, trusted: bool = False) -> str:
        ctx = ExpansionContext(phrase_description="signature", allow_privileged=bool(trusted))
        actions = engine.expand(content, ctx)
        return "".join(a.text for a in actions if isinstance(a, TextAction)) if fmt == "html" \
            else engine.expand_to_text(content, ctx)
    return expand
