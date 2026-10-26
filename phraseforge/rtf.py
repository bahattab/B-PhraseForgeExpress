"""HTML -> RTF for the clipboard, so programs that prefer RTF (WordPad, some mail
programs, older Office dialogs) receive formatted text. Covers what phrase content
uses: bold, italic, underline, strike, paragraphs, line breaks, lists, links (as
text), and right-to-left paragraphs for Arabic. Every non-ASCII character is written
as \\uN? so Arabic needs no code page."""
from __future__ import annotations

import unicodedata
from html.parser import HTMLParser

_INLINE = {"b": r"\b", "strong": r"\b", "i": r"\i", "em": r"\i", "u": r"\ul", "s": r"\strike",
           "strike": r"\strike", "del": r"\strike"}
_OFF = {r"\b": r"\b0", r"\i": r"\i0", r"\ul": r"\ulnone", r"\strike": r"\strike0"}
_BLOCK = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "blockquote", "pre"}


def escape(text: str) -> str:
    out = []
    for ch in text:
        o = ord(ch)
        if ch in "\\{}":
            out.append("\\" + ch)
        elif ch == "\n":
            out.append("\\line ")
        elif ch == "\t":
            out.append("\\tab ")
        elif o < 128:
            out.append(ch)
        elif o < 0x10000:
            out.append(f"\\u{o if o < 32768 else o - 65536}?")
        else:                                   # surrogate pair for emoji etc.
            o -= 0x10000
            for u in (0xD800 + (o >> 10), 0xDC00 + (o & 0x3FF)):
                out.append(f"\\u{u - 65536}?")
    return "".join(out)


def _rtl(text: str) -> bool:
    for ch in text:
        d = unicodedata.bidirectional(ch)
        if d in ("R", "AL"):
            return True
        if d == "L":
            return False
    return False


class _Conv(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paras: list[list[str]] = [[]]
        self.plain: list[str] = [""]
        self.skip = 0
        self.list_depth = 0

    def _new_para(self):
        if self.paras[-1] or self.plain[-1]:
            self.paras.append([])
            self.plain.append("")

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head", "title"):
            self.skip += 1
        elif tag in _INLINE:
            self.paras[-1].append(_INLINE[tag] + " ")
        elif tag == "br":
            self.paras[-1].append("\\line ")
            self.plain[-1] += "\n"
        elif tag in ("ul", "ol"):
            self.list_depth += 1
            self._new_para()
        elif tag in _BLOCK:
            self._new_para()
            if tag == "li":
                self.paras[-1].append("\\bullet\\tab ")
            elif tag.startswith("h"):
                self.paras[-1].append("\\b ")

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head", "title"):
            self.skip = max(0, self.skip - 1)
        elif tag in _INLINE:
            self.paras[-1].append(_OFF[_INLINE[tag]] + " ")
        elif tag in ("ul", "ol"):
            self.list_depth = max(0, self.list_depth - 1)
            self._new_para()
        elif tag in _BLOCK:
            if tag.startswith("h"):
                self.paras[-1].append("\\b0 ")
            self._new_para()
        elif tag in ("td", "th"):
            self.paras[-1].append("\\tab ")

    def handle_data(self, data):
        if self.skip:
            return
        data = " ".join(data.split("\n")) if "\n" in data else data
        if not data:
            return
        self.paras[-1].append(escape(data))
        self.plain[-1] += data


def html_to_rtf(html: str) -> str:
    c = _Conv()
    c.feed(html or "")
    c.close()
    paras = [(p, t) for p, t in zip(c.paras, c.plain) if p or t]
    body = []
    for i, (parts, text) in enumerate(paras):
        direction = "\\rtlpar\\qr " if _rtl(text) else "\\ltrpar\\ql "
        body.append("\\pard" + direction + "".join(parts) + ("\\par\n" if i < len(paras) - 1 else ""))
    return ("{\\rtf1\\ansi\\ansicpg1252\\deff0\\uc1"
            "{\\fonttbl{\\f0\\fnil\\fcharset0 Segoe UI;}}\\f0\\fs22\n" + "".join(body) + "}")
