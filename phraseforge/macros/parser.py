"""Parser for the PhraseForge macro language.

Grammar (informal):
    content  := (text | "{{" | call)*
    call     := "{#" NAME (ws token)* ws? "}"
    token    := quoted | bare
    quoted   := '"' (char | '\\"' | "{{" | call)* '"'
    bare     := (char-not-ws-or-} | "{{" | call)+

A bare token "-name" (name starts with a letter) is an option key. The token
after it is its value unless that token is another option key or there is
none, in which case the option is a flag (value "1").

Unknown or malformed calls are kept as literal text.  After the flat parse,
block calls (if/elseif/else/endif, loop/endloop, foreach/endforeach,
form/endform) are folded into block nodes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_OPT = re.compile(r"-[A-Za-z][A-Za-z0-9_\-]*$")


@dataclass
class Text:
    text: str


@dataclass
class Token:
    parts: list = field(default_factory=list)   # list[Node]
    quoted: bool = False

    @property
    def bare_text(self) -> str | None:
        """The literal text if this token is unquoted plain text, else None."""
        if self.quoted or any(not isinstance(p, Text) for p in self.parts):
            return None
        return "".join(p.text for p in self.parts)


@dataclass
class Call:
    name: str                                    # lower-cased
    args: list[Token] = field(default_factory=list)
    opts: dict[str, Token | None] = field(default_factory=dict)
    raw: str = ""


@dataclass
class IfBlock:
    branches: list = field(default_factory=list)  # list[(Call | None, list[Node])]  None = else
    raw: str = ""


@dataclass
class LoopBlock:
    call: Call
    body: list = field(default_factory=list)


@dataclass
class FormBlock:
    call: Call
    body: list = field(default_factory=list)


class _Fail(Exception):
    pass


def _add_text(nodes: list, s: str) -> None:
    if not s:
        return
    if nodes and isinstance(nodes[-1], Text):
        nodes[-1].text += s
    else:
        nodes.append(Text(s))


def parse_flat(s: str) -> list:
    nodes: list = []
    i, n = 0, len(s)
    buf = []
    while i < n:
        if s.startswith("{{", i):
            buf.append("{")
            i += 2
        elif s.startswith("{#", i):
            try:
                call, j = _parse_call(s, i)
            except _Fail:
                buf.append("{#")
                i += 2
                continue
            _add_text(nodes, "".join(buf))
            buf = []
            nodes.append(call)
            i = j
        else:
            buf.append(s[i])
            i += 1
    _add_text(nodes, "".join(buf))
    return nodes


def _parse_call(s: str, i: int) -> tuple[Call, int]:
    m = _NAME.match(s, i + 2)
    if not m:
        raise _Fail
    name = m.group(0).lower()
    j = m.end()
    n = len(s)
    tokens: list[Token] = []
    while True:
        while j < n and s[j] in " \t\r\n":
            j += 1
        if j >= n:
            raise _Fail
        if s[j] == "}":
            j += 1
            break
        tok, j = _parse_token(s, j)
        tokens.append(tok)
    call = Call(name=name, raw=s[i:j])
    k = 0
    while k < len(tokens):
        t = tokens[k]
        bt = t.bare_text
        if bt is not None and _OPT.match(bt):
            key = bt[1:].lower()
            nxt = tokens[k + 1] if k + 1 < len(tokens) else None
            nbt = nxt.bare_text if nxt is not None else None
            if nxt is None or (nbt is not None and _OPT.match(nbt)):
                call.opts[key] = None
                k += 1
            else:
                call.opts[key] = nxt
                k += 2
        else:
            call.args.append(t)
            k += 1
    return call, j


def _parse_token(s: str, j: int) -> tuple[Token, int]:
    n = len(s)
    tok = Token()
    buf: list[str] = []

    def flush():
        if buf:
            _add_text(tok.parts, "".join(buf))
            buf.clear()

    if s[j] == '"':
        tok.quoted = True
        j += 1
        while True:
            if j >= n:
                raise _Fail
            c = s[j]
            if c == "\\" and j + 1 < n and s[j + 1] == '"':
                buf.append('"')
                j += 2
            elif c == '"':
                j += 1
                break
            elif s.startswith("{{", j):
                buf.append("{")
                j += 2
            elif s.startswith("{#", j):
                try:
                    call, j2 = _parse_call(s, j)
                except _Fail:
                    buf.append("{#")
                    j += 2
                    continue
                flush()
                tok.parts.append(call)
                j = j2
            else:
                buf.append(c)
                j += 1
    else:
        while j < n and s[j] not in " \t\r\n}":
            if s.startswith("{{", j):
                buf.append("{")
                j += 2
            elif s.startswith("{#", j):
                call, j2 = _parse_call(s, j)   # failure propagates: outer call is malformed
                flush()
                tok.parts.append(call)
                j = j2
            else:
                buf.append(s[j])
                j += 1
    flush()
    tok.parts = build_blocks(tok.parts)
    return tok, j


# ------------------------------------------------------------------ blocks
_OPENERS = {"if": "endif", "loop": "endloop", "foreach": "endforeach", "form": "endform"}
_CLOSERS = {"endif", "endloop", "endforeach", "endform", "elseif", "else"}


def build_blocks(nodes: list) -> list:
    out, _, _ = _build(nodes, 0, frozenset())
    return out


def _build(nodes: list, i: int, stops: frozenset) -> tuple[list, int, Call | None]:
    out: list = []
    while i < len(nodes):
        nd = nodes[i]
        if isinstance(nd, Call):
            if nd.name in stops:
                return out, i + 1, nd
            if nd.name == "if":
                block = IfBlock(raw=nd.raw)
                cond: Call | None = nd
                i += 1
                while True:
                    body, i, term = _build(nodes, i, frozenset({"elseif", "else", "endif"}))
                    block.branches.append((cond, body))
                    if term is None or term.name == "endif":
                        break
                    if term.name == "elseif":
                        cond = term
                    else:  # else
                        cond = None
                        body, i, term = _build(nodes, i, frozenset({"endif"}))
                        block.branches.append((None, body))
                        break
                out.append(block)
                continue
            if nd.name in ("loop", "foreach", "form"):
                body, i, _ = _build(nodes, i + 1, frozenset({_OPENERS[nd.name]}))
                out.append(FormBlock(nd, body) if nd.name == "form" else LoopBlock(nd, body))
                continue
            if nd.name in _CLOSERS:
                _add_text(out, nd.raw)   # unmatched closer -> literal
                i += 1
                continue
        if isinstance(nd, Text):
            _add_text(out, nd.text)
        else:
            out.append(nd)
        i += 1
    return out, i, None


def parse(s: str) -> list:
    return build_blocks(parse_flat(s))
