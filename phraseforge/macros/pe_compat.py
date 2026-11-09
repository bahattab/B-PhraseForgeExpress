"""PhraseExpress macro syntax -> PhraseForge (PRD FR-MAC-01).

translate(text) -> (pf_text, warnings) is a pure function, used when phrases are imported
from PhraseExpress. It changes only what PhraseForge would not understand:

  * macro names PhraseExpress spells differently (ALIASES, e.g. {#uppercase} -> {#upper});
    names are matched case-insensitively ({#ENTER} works as {#enter})
  * key blocks {#CTRL {#SHIFT a}} -> {#key ctrl+shift+a}; {#CTRL {#ENTER}} -> {#key ctrl+enter}
  * -count N on keys -> -repeat N
  * Delphi date formats: {#date -f "dd.mm.yyyy hh:nn"} -> {#date -format "dd.MM.yyyy HH:mm"}
    (nn = minutes, m after h = minutes, ddddd / dddddd = short / long date, am/pm)
  * anything else it does not know is kept as {#pe_unsupported "..."}, which shows
    "[PhraseExpress macro not supported: ...]" when the phrase runs, so nothing is lost or
    silently changed.

Text outside macros, quoting and nesting are kept exactly.
"""
from __future__ import annotations

import re

ALIASES = {
    "cond": "if", "endcond": "endif", "elsecond": "else",
    "uppercase": "upper", "lowercase": "lower",
    "uppercasefirst": "ucfirst", "lowercasefirst": "lcfirst",
    "uppercasewords": "ucwords", "lowercasewords": "lcwords",
    "formradiogroup": "formradio", "formcalendar": "formdate", "formeditmemo": "formmemo",
    "balloon": "notify", "httprequest": "http", "pause": "wait", "delay": "sleep",
    "clipboardtext": "clipboard", "backspace": "bksp", "delete": "del", "escape": "esc",
    "return": "enter", "pageup": "pgup", "pagedown": "pgdn", "insertphrase": "insert",
}
MODIFIERS = {"ctrl": "ctrl", "control": "ctrl", "shift": "shift", "alt": "alt", "win": "win", "windows": "win"}
NAMED_KEYS = {"enter", "tab", "esc", "bksp", "del", "up", "down", "left", "right", "home", "end", "pgup", "pgdn",
              "ins", *(f"f{i}" for i in range(1, 13))}
KEY_NAME = {"bksp": "backspace", "del": "delete", "pgup": "pageup", "pgdn": "pagedown", "ins": "insert"}
BLOCK_ENDS = {"endif", "else", "elseif", "endloop", "endforeach", "endform", "formgroupend"}
DATE_MACROS = {"date", "time", "datetime", "datecalc", "timecalc", "askdate", "datepick", "formdate"}


def _known(name: str) -> bool:
    from phraseforge.macros.registry import REGISTRY
    from phraseforge.macros import commands, commands_extra, commands_pe  # noqa: F401
    return name in REGISTRY or name in BLOCK_ENDS or name in ("pe_unsupported",)


# ---------------------------------------------------------------- scanning
def _scan_call(text: str, i: int) -> int:
    """Index just past the '}' closing the call that starts at text[i] == '{#'; -1 if unclosed."""
    depth, j, quote = 0, i, False
    while j < len(text):
        c = text[j]
        if quote:
            if c == "\\" and j + 1 < len(text):
                j += 2
                continue
            if c == '"':
                quote = False
            elif text.startswith("{#", j):
                end = _scan_call(text, j)
                if end < 0:
                    return -1
                j = end
                continue
            j += 1
            continue
        if text.startswith("{{", j) and depth:
            j += 2
            continue
        if text.startswith("{#", j):
            depth += 1
            j += 2
            continue
        if c == '"' and depth == 1:
            quote = True
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return -1


def _split_call(call: str) -> tuple[str, str]:
    m = re.match(r"\{#\s*([A-Za-z_][A-Za-z0-9_]*)", call)
    return (m.group(1), call[m.end():-1]) if m else ("", call[2:-1])


# ---------------------------------------------------------------- Delphi date formats
_DELPHI = re.compile(r"'[^']*'|\"[^\"]*\"|am/pm|a/p|ampm|yyyy|yy|mmmm|mmm|mm|m|dddddd|ddddd|dddd|ddd|dd|d|"
                     r"hh|h|nn|n|ss|s|zzz|z|.", re.I | re.S)


def delphi_format(fmt: str) -> tuple[str, list[str]]:
    """A Delphi FormatDateTime pattern as a PhraseForge date format."""
    toks = [m.group(0) for m in _DELPHI.finditer(fmt)]
    twelve = any(t.lower() in ("am/pm", "a/p", "ampm") for t in toks)
    out, warn, after_hour = [], [], False
    for t in toks:
        low = t.lower()
        if t[0] in "'\"" and len(t) >= 2:
            out.append("'" + t[1:-1].replace("'", "") + "'")
            continue
        if low in ("hh", "h"):
            out.append(("hh" if low == "hh" else "h") if twelve else ("HH" if low == "hh" else "H"))
            after_hour = True
            continue
        if low in ("mm", "m") and after_hour:
            out.append(low)                       # minutes right after an hour
            after_hour = False
            continue
        mapping = {"yyyy": "yyyy", "yy": "yy", "mmmm": "MMMM", "mmm": "MMM", "mm": "MM", "m": "M",
                   "dddd": "dddd", "ddd": "ddd", "dd": "dd", "d": "d", "nn": "mm", "n": "m", "ss": "ss",
                   "s": "s", "zzz": "zzz", "z": "zzz", "am/pm": "tt", "a/p": "tt", "ampm": "tt"}
        if low == "ddddd":
            out.append("dd/MM/yyyy")
            warn.append('"ddddd" (short date) became dd/MM/yyyy')
        elif low == "dddddd":
            out.append("dddd, d MMMM yyyy")
            warn.append('"dddddd" (long date) became dddd, d MMMM yyyy')
        elif low in mapping:
            out.append(mapping[low])
        elif t.isalpha():
            out.append("'" + t + "'")             # a stray letter is text in PE, a token in PF
        else:
            out.append(t)
        if low not in ("ss", "s", "nn", "n") and t.strip():
            after_hour = after_hour and not t.isalpha()
    return "".join(out), warn


# ---------------------------------------------------------------- translation
def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("{", "{{") + '"'


def _key_chord(name: str, body: str) -> str | None:
    """{#CTRL {#SHIFT a}} -> 'ctrl+shift+a'; None if not a key block."""
    mods = [MODIFIERS[name]]
    body = body.strip()
    while True:
        if body.startswith("{#") and _scan_call(body, 0) == len(body):
            inner, ibody = _split_call(body)
            low = ALIASES.get(inner.lower(), inner.lower())
            if low in MODIFIERS:
                mods.append(MODIFIERS[low])
                body = ibody.strip()
                continue
            if low in NAMED_KEYS and not ibody.strip():
                return "+".join(mods + [KEY_NAME.get(low, low)])
            return None
        if re.fullmatch(r"[^\s{}\"]", body) or body.lower() in ("space", "enter", "tab"):
            return "+".join(mods + [body.lower()])
        return None


def _translate_body(body: str, warnings: list[str]) -> str:
    """Translate the calls inside a macro's arguments."""
    return _translate(body, warnings)


def _translate_call(call: str, warnings: list[str]) -> str:
    name, body = _split_call(call)
    if not name:
        return call
    low = name.lower()
    if low in MODIFIERS:
        chord = _key_chord(low, body)
        if chord:
            return "{#key " + chord + "}"
        warnings.append(f"key block not understood: {call}")
        return "{#pe_unsupported " + _quote(call) + "}"
    target = ALIASES.get(low, low)
    if not _known(target):
        warnings.append(f"{{#{name}}} is not supported")
        return "{#pe_unsupported " + _quote(call) + "}"
    if target != low:
        warnings.append(f"{{#{name}}} became {{#{target}}}")
    body = _translate_body(body, warnings)
    if target in NAMED_KEYS or target in ("key", "keys"):
        body = re.sub(r"(^|\s)-count(?=\s)", r"\1-repeat", body)
    if target in DATE_MACROS:
        def fmt(m):
            q = m.group(2)
            new, w = delphi_format(q[1:-1] if q[:1] in "\"'" else q)
            warnings.extend(w)
            return f"{m.group(1)}-format \"{new}\""
        body = re.sub(r"(^|\s)-f\s+(\"[^\"]*\"|'[^']*'|\S+)", fmt, body)
    return "{#" + target + body + "}"


def _translate(text: str, warnings: list[str]) -> str:
    out, i = [], 0
    while True:
        j = text.find("{#", i)
        if j < 0:
            out.append(text[i:])
            return "".join(out)
        out.append(text[i:j])
        end = _scan_call(text, j)
        if end < 0:                               # unclosed: keep the rest as it is
            warnings.append("a macro is not closed with }")
            out.append(text[j:])
            return "".join(out)
        out.append(_translate_call(text[j:end], warnings))
        i = end


def translate(text: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    result = _translate(text or "", warnings)
    seen, uniq = set(), []
    for w in warnings:
        if w not in seen:
            seen.add(w)
            uniq.append(w)
    return result, uniq
