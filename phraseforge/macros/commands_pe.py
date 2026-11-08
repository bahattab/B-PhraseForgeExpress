"""Macros from the PhraseExpress macro list that PhraseForge was missing (PRD G-11,
FR-MAC-02/03, FR-AI-05).

PhraseExpress does not publish full parameter docs for several of these (PRD U-04), so
the behaviour below is PhraseForge's own and marked "compat: approximate" in
macros/README.md. Each command is small and self-contained.
"""
from __future__ import annotations

import re
import sys
import threading

from phraseforge.macros.commands import _arg, _esc, _flag
from phraseforge.macros.engine import apply_case
from phraseforge.macros.registry import MacroError, macro


# ====================================================================== text
def _text(args, start=0) -> str:
    return " ".join(args[start:])


@macro("explode", "Text", '{#explode text -sep "," -index 2 -join "\\n" -trim}',
       "Split text at a separator. With -index N it outputs item N (1-based, negative counts from "
       "the end); without it the items are joined again with -join (default: new line).",
       '{#explode "a,b,c" -sep "," -index 2}')
def _explode(rt, args, opts):
    sep = _esc(opts.get("sep", ","))
    if not sep:
        raise MacroError("-sep must not be empty")
    items = _text(args).split(sep)
    if _flag(opts, "trim"):
        items = [x.strip() for x in items]
    if _flag(opts, "noempty"):
        items = [x for x in items if x.strip()]
    if "index" in opts:
        try:
            i = int(opts["index"])
        except ValueError as e:
            raise MacroError("-index must be a number") from e
        if i == 0 or abs(i) > len(items):
            return ""
        return items[i - 1] if i > 0 else items[i]
    if _flag(opts, "count"):
        return str(len(items))
    return _esc(opts.get("join", "\\n")).join(items)


def _roman(n: int) -> str:
    if n <= 0:
        return str(n)
    out = []
    for v, s in ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"),
                 (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        while n >= v:
            out.append(s)
            n -= v
    return "".join(out)


def _alpha(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(ord("a") + r) + s
    return s or str(n)


NUMLIST_MAX_LEVEL, NUMLIST_MAX_START, NUMLIST_MAX_OUTPUT = 20, 1_000_000, 1_000_000
NUMLIST_STYLES = ("decimal", "alpha", "ALPHA", "roman", "ROMAN", "bullet", "dash", "arabic")


def _number(i: int, style: str) -> str:
    if style == "alpha":
        return _alpha(i)
    if style == "ALPHA":
        return _alpha(i).upper()
    if style == "roman":
        return _roman(i)
    if style == "ROMAN":
        return _roman(i).upper()
    if style == "arabic":         # Arabic-Indic digits
        return str(i).translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))
    return str(i)


@macro("numlist", "Text",
       '{#numlist "a|b|c" -sep "|" -style decimal|alpha|ALPHA|roman|ROMAN|arabic|bullet|dash '
       '-start 1 -suffix ". " -level 1 -indent "  "}',
       "Numbered or bulleted list, one item per line. -level indents the list "
       "(level 2 = one indent).", '{#numlist "First|Second|Third" -sep "|"}')
def _numlist(rt, args, opts):
    sep = _esc(opts.get("sep", "\\n"))
    items = [x for x in _text(args).split(sep) if x.strip()] if sep else [_text(args)]
    style = opts.get("style", "decimal")
    if style not in NUMLIST_STYLES:
        raise MacroError(f"unknown list style {style!r}")
    try:
        start = int(opts.get("start", "1"))
        level = max(1, int(opts.get("level", "1")))
    except ValueError as e:
        raise MacroError("-start and -level must be numbers") from e
    if level > NUMLIST_MAX_LEVEL:
        raise MacroError(f"-level is at most {NUMLIST_MAX_LEVEL}")
    if abs(start) > NUMLIST_MAX_START:
        raise MacroError(f"-start is at most {NUMLIST_MAX_START:,}")
    indent = _esc(opts.get("indent", "  "))
    if len(indent) > 16:
        raise MacroError("-indent is at most 16 characters")
    pad = indent * (level - 1)
    suffix = _esc(opts.get("suffix", " " if style in ("bullet", "dash") else ". "))
    lines = []
    for i, item in enumerate(items):
        mark = {"bullet": "•", "dash": "-"}.get(style) or _number(start + i, style)
        lines.append(f"{pad}{mark}{suffix}{item.strip()}")
    out = "\n".join(lines)
    if len(out) > NUMLIST_MAX_OUTPUT:
        raise MacroError("the list is too long")
    return out


@macro("autocase", "Text", "{#autocase text}",
       "Match the case of the typed abbreviation: typed in CAPITALS gives upper case, typed "
       "Capitalized gives a capital first letter, otherwise the text is unchanged.",
       "{#autocase {#clipboard}}")
def _autocase(rt, args, opts):
    return apply_case(_text(args), opts.get("like", rt.ctx.typed_abbreviation))


@macro("lastchars", "Text", "{#lastchars text -count 3}", "The last N characters of the text.")
def _lastchars(rt, args, opts):
    try:
        n = int(opts.get("count", "1"))
    except ValueError as e:
        raise MacroError("-count must be a number") from e
    t = _text(args)
    return t[-n:] if n > 0 else ""


@macro("textempty", "Text", "{#textempty text}",
       'Outputs "1" when the text is empty or only spaces, else "0". Use it in {#if}.')
def _textempty(rt, args, opts):
    return "1" if not _text(args).strip() else "0"


@macro("prefix", "Text", '{#prefix "Dear " text}',
       "Put the prefix in front of the text, but only when the text is not empty.")
def _prefix(rt, args, opts):
    pre, t = _esc(_arg(args, 0)), _text(args, 1)
    return pre + t if t.strip() else ""


@macro("postfix", "Text", '{#postfix ", " text}',
       "Put the suffix after the text, but only when the text is not empty.", aliases=("suffix",))
def _postfix(rt, args, opts):
    post, t = _esc(_arg(args, 0)), _text(args, 1)
    return t + post if t.strip() else ""


def _rx(args, opts, fn):
    """fn(compiled pattern, text) with saferegex's limits (no catastrophic backtracking)."""
    from phraseforge import saferegex
    try:
        return saferegex.run(_arg(args, 1), re.I if _flag(opts, "i") else 0, _arg(args, 0), fn)
    except saferegex.RegexError as e:
        raise MacroError(str(e)) from e


@macro("regexpos", "Text", "{#regexpos text pattern -i}",
       "1-based position of the first regex match; 0 when there is none.")
def _regexpos(rt, args, opts):
    m = _rx(args, opts, lambda rx, t: rx.search(t))
    return str(m.start() + 1) if m else "0"


@macro("regexcount", "Text", "{#regexcount text pattern -i}", "Number of regex matches in the text.")
def _regexcount(rt, args, opts):
    return str(_rx(args, opts, lambda rx, t: sum(1 for _ in rx.finditer(t))))


# ====================================================================== variables
# Temporary variables live for as long as PhraseForge runs: shared between expansions,
# never written to the database and gone after a restart.
TEMP_VARS: dict[str, str] = {}
_temp_lock = threading.Lock()


@macro("settemp", "Variables", "{#settemp name value}",
       "Set a temporary variable: kept between expansions until PhraseForge closes, never saved.")
def _settemp(rt, args, opts):
    name = _arg(args, 0)
    if not name:
        raise MacroError("missing variable name")
    with _temp_lock:
        TEMP_VARS[name] = _text(args, 1) if len(args) > 1 else opts.get("value", "")
    return None


@macro("gettemp", "Variables", "{#gettemp name -default x}", "Read a temporary variable.")
def _gettemp(rt, args, opts):
    with _temp_lock:
        v = TEMP_VARS.get(_arg(args, 0), "")
    return v if v != "" else opts.get("default", "")


# ====================================================================== phrases
@macro("setlevel", "Phrases", "{#setlevel de}",
       "Use this language version for the {#insert} calls that follow in this expansion "
       '("" or default = the default version).')
def _setlevel(rt, args, opts):
    lang = _arg(args, 0).strip()
    rt.level = "" if lang.lower() in ("", "default", "-") else lang
    return None


# ====================================================================== language detection
_SCRIPTS = [  # (code, ranges)
    ("ar", [(0x0600, 0x06FF), (0x0750, 0x077F), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)]),
    ("he", [(0x0590, 0x05FF)]),
    ("el", [(0x0370, 0x03FF)]),
    ("ru", [(0x0400, 0x04FF)]),
    ("hi", [(0x0900, 0x097F)]),
    ("th", [(0x0E00, 0x0E7F)]),
    ("ko", [(0xAC00, 0xD7AF), (0x1100, 0x11FF)]),
    ("ja", [(0x3040, 0x30FF)]),
    ("zh", [(0x4E00, 0x9FFF)]),
]

# frequent short words of Latin-script languages (lower case)
_STOPWORDS = {
    "en": "the and of to is in that it for you with on was are this be have not but at",
    "de": "der die und das ist nicht ich sie es zu den mit sich ein eine auf für von dem",
    "fr": "le la les et est un une des que pas pour dans du sur vous il elle avec ce qui",
    "es": "el la los las y es un una que de en por con para no se su del lo como",
    "it": "il lo la gli le e è un una che di per non con sono del della nel questo",
    "pt": "o a os as e é um uma que de do da em para não com por se na no",
    "nl": "de het een en is van dat niet ik je op te met voor zijn er maar",
    "tr": "ve bir bu da de için ile ne çok ama gibi daha olarak var değil",
}
_STOPSETS = {k: set(v.split()) for k, v in _STOPWORDS.items()}


def detect_language(text: str) -> str:
    """ISO-639-1 code of the text's language, offline: the writing system first, then
    common words for Latin-script languages. "" when the text has no letters."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return ""
    counts: dict[str, int] = {}
    latin = 0
    for c in letters:
        o = ord(c)
        for code, ranges in _SCRIPTS:
            if any(a <= o <= b for a, b in ranges):
                counts[code] = counts.get(code, 0) + 1
                break
        else:
            latin += 1
    if counts:
        code, n = max(counts.items(), key=lambda kv: kv[1])
        if code == "zh" and counts.get("ja"):
            code, n = "ja", n + counts["ja"]      # kanji with kana = Japanese
        if n * 2 >= len(letters):
            return code
    words = re.findall(r"[^\W\d_]+", text.lower())
    scores = {k: sum(1 for w in words if w in s) for k, s in _STOPSETS.items()}
    best = max(scores.items(), key=lambda kv: kv[1])
    if best[1]:
        return best[0]
    if "ß" in text or "ä" in text.lower() or "ü" in text.lower():
        return "de"
    return "en"


@macro("langdetect", "Text", "{#langdetect text}",
       "Two-letter code (ISO 639-1) of the language the text is written in, detected offline "
       "(ar, en, de, fr, es, ru, zh, ...).", "{#langdetect {#clipboard}}")
def _langdetect(rt, args, opts):
    return detect_language(_text(args))


# ====================================================================== mouse / sound
def cursor_pos() -> tuple[int, int] | None:
    """Mouse position on screen, or None when it cannot be read."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            pt = wintypes.POINT()
            if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
                return pt.x, pt.y
        except Exception:
            pass
    try:
        from PySide6.QtGui import QCursor, QGuiApplication
        if QGuiApplication.instance() is not None:
            p = QCursor.pos()
            return p.x(), p.y()
    except Exception:
        pass
    return None


@macro("mousex", "Keys & cursor", "{#mousex}", "Horizontal mouse position on screen, in pixels.")
def _mousex(rt, args, opts):
    p = cursor_pos()
    return str(p[0]) if p else ""


@macro("mousey", "Keys & cursor", "{#mousey}", "Vertical mouse position on screen, in pixels.")
def _mousey(rt, args, opts):
    p = cursor_pos()
    return str(p[1]) if p else ""


@macro("mouseposition", "Keys & cursor", '{#mouseposition -sep ","}', 'Mouse position as "x,y".')
def _mousepos(rt, args, opts):
    p = cursor_pos()
    return f"{p[0]}{_esc(opts.get('sep', ','))}{p[1]}" if p else ""


SOUNDS = {"beep": 0xFFFFFFFF, "info": 0x40, "warning": 0x30, "error": 0x10, "question": 0x20}


@macro("sound", "System", '{#sound "C:\\sounds\\done.wav"}',
       "Play a .wav file, or a Windows sound: beep, info, warning, error, question. Outputs nothing.",
       "{#sound beep}")
def _sound(rt, args, opts):
    what = _arg(args, 0, "beep").strip()
    if sys.platform != "win32":
        return None
    import winsound
    try:
        if what.lower() in SOUNDS:
            winsound.MessageBeep(SOUNDS[what.lower()])
        else:
            if not what.lower().endswith(".wav"):
                raise MacroError("sound needs a .wav file or beep/info/warning/error/question")
            winsound.PlaySound(what, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except RuntimeError as e:
        raise MacroError(f"cannot play {what}: {e}") from e
    return None
