"""Macro evaluation: turns phrase content into a list of host Actions."""
from __future__ import annotations

import html as _html
import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from phraseforge.host import (
    Action, Cancelled, CursorAction, ExpansionContext, FormField, HostServices, HtmlAction, ImageAction,
    KeyAction, MouseAction, SleepAction, TextAction,
)
from phraseforge.macros.parser import Call, FormBlock, IfBlock, LoopBlock, Text, Token, parse
from phraseforge.macros.registry import REGISTRY, MacroError

MAX_INSERT_DEPTH = 10
MAX_LOOP = 1000


@dataclass
class LoopFrame:
    index: int
    count: int
    item: str = ""


@dataclass
class Runtime:
    engine: "MacroEngine"
    host: HostServices
    ctx: ExpansionContext
    store: Any = None
    locals: dict[str, str] = field(default_factory=dict)
    form_values: dict[str, str] = field(default_factory=dict)
    loops: list[LoopFrame] = field(default_factory=list)
    insert_stack: list[str] = field(default_factory=list)
    collecting: list[FormField] | None = None       # set while inside {#form}
    field_specs: dict[str, dict[str, str]] = field(default_factory=dict)

    def now(self) -> datetime:
        return self.engine.clock()

    @property
    def rng(self) -> random.Random:
        return self.engine.rng

    def setting(self, key: str, default: str = "") -> str:
        try:
            v = self.host.setting(key, default)
        except Exception:
            v = default
        return v if v is not None else default

    # variables: local -> form -> host global
    def get_var(self, name: str, scope: str = "") -> str:
        if scope in ("", "local"):
            if name in self.locals:
                return self.locals[name]
            if name in self.form_values:
                return self.form_values[name]
            if scope == "local":
                return ""
            scope = "global"
        return self.host.get_var(name, scope) or ""

    def set_var(self, name: str, value: str, scope: str = "local") -> None:
        if scope in ("", "local"):
            self.locals[name] = value
        else:
            self.host.set_var(name, value, scope)


def _truthy(s: str) -> bool:
    return s.strip().lower() not in ("", "0", "false", "no", "off")


def _num(s: str) -> float | None:
    try:
        return float(s.strip())
    except (ValueError, AttributeError):
        return None


_BINOPS = {"==", "=", "!=", "<>", "<", ">", "<=", ">=", "contains", "!contains", "startswith",
           "endswith", "=~", "!~", "in"}


def _compare(a: str, op: str, b: str) -> bool:
    op = op.lower()
    na, nb = _num(a), _num(b)
    if op in ("==", "="):
        return na == nb if na is not None and nb is not None else a == b
    if op in ("!=", "<>"):
        return not _compare(a, "==", b)
    if op in ("<", ">", "<=", ">="):
        x, y = (na, nb) if na is not None and nb is not None else (a, b)
        return {"<": x < y, ">": x > y, "<=": x <= y, ">=": x >= y}[op]
    if op == "contains":
        return b.lower() in a.lower()
    if op == "!contains":
        return b.lower() not in a.lower()
    if op == "startswith":
        return a.lower().startswith(b.lower())
    if op == "endswith":
        return a.lower().endswith(b.lower())
    if op == "=~":
        return re.search(b, a) is not None
    if op == "!~":
        return re.search(b, a) is None
    if op == "in":
        return a.lower() in [x.strip().lower() for x in b.split(",")]
    raise MacroError(f"unknown operator {op}")


class _Cond:
    """Recursive-descent condition evaluator over (value, is_bare) tokens."""

    def __init__(self, toks: list[tuple[str, bool]]):
        self.t = toks
        self.i = 0

    def peek_op(self, *words) -> str | None:
        if self.i < len(self.t):
            v, bare = self.t[self.i]
            if bare and v.lower() in words:
                return v.lower()
        return None

    def run(self) -> bool:
        if not self.t:
            return False
        r = self.or_()
        return r

    def or_(self) -> bool:
        r = self.and_()
        while self.peek_op("or", "||"):
            self.i += 1
            rhs = self.and_()
            r = r or rhs
        return r

    def and_(self) -> bool:
        r = self.not_()
        while self.peek_op("and", "&&"):
            self.i += 1
            rhs = self.not_()
            r = r and rhs
        return r

    def not_(self) -> bool:
        if self.peek_op("not", "!"):
            self.i += 1
            return not self.not_()
        return self.atom()

    def value(self) -> str:
        if self.i >= len(self.t):
            return ""
        v = self.t[self.i][0]
        self.i += 1
        return v

    def atom(self) -> bool:
        if self.peek_op("("):
            self.i += 1
            r = self.or_()
            if self.peek_op(")"):
                self.i += 1
            return r
        if self.peek_op("empty"):
            self.i += 1
            return self.value().strip() == ""
        if self.peek_op("notempty"):
            self.i += 1
            return self.value().strip() != ""
        a = self.value()
        op = self.peek_op(*_BINOPS)
        if op:
            self.i += 1
            return _compare(a, op, self.value())
        return _truthy(a)


def html_to_text(h: str) -> str:
    h = re.sub(r"(?i)<br\s*/?>", "\n", h)
    h = re.sub(r"(?i)</p\s*>", "\n", h)
    h = re.sub(r"<[^>]+>", "", h)
    return _html.unescape(h).strip("\n")


def apply_case(text: str, typed: str) -> str:
    """Mirror the case of the typed abbreviation: ALL CAPS -> upper, Capitalized -> first letter upper."""
    letters = [c for c in typed if c.isalpha()]
    if not letters or not text:
        return text
    if len(letters) > 1 and all(c.isupper() for c in letters):
        return text.upper()
    if letters[0].isupper() and all(c.islower() for c in letters[1:]):
        for i, c in enumerate(text):
            if c.isalpha():
                return text[:i] + c.upper() + text[i + 1:]
    return text


def actions_to_text(actions: list, keys_as_markers: bool = False) -> str:
    out = []
    for a in actions:
        if isinstance(a, TextAction):
            out.append(a.text)
        elif isinstance(a, HtmlAction):
            out.append(a.plain)
        elif keys_as_markers and isinstance(a, KeyAction):
            out.append(f"<{a.keys}>" * max(1, a.repeat))
        elif keys_as_markers and isinstance(a, ImageAction):
            out.append(f"[image: {a.path}]")
    return "".join(out)


def merge_text(actions: list) -> list:
    out: list = []
    for a in actions:
        if isinstance(a, TextAction):
            if not a.text:
                continue
            if out and isinstance(out[-1], TextAction):
                out[-1] = TextAction(out[-1].text + a.text)
                continue
        out.append(a)
    return out


class MacroEngine:
    def __init__(self, host: HostServices, store=None, clock: Callable[[], datetime] | None = None,
                 rng: random.Random | None = None):
        from phraseforge.macros import commands  # noqa: F401  (register commands)
        self.host = host
        self.store = store
        self.clock = clock or datetime.now
        self.rng = rng or random.Random()

    # ------------------------------------------------------------ public
    def expand(self, content: str, ctx: ExpansionContext | None = None) -> list[Action]:
        ctx = ctx or ExpansionContext()
        rt = Runtime(engine=self, host=self.host, ctx=ctx, store=self.store)
        if ctx.phrase_description:
            rt.insert_stack.append(ctx.phrase_description.lower())
        actions = merge_text(self.eval_nodes(parse(content), rt))
        if ctx.typed_abbreviation and ctx.depth == 0:
            first = True
            letters = [c for c in ctx.typed_abbreviation if c.isalpha()]
            all_caps = len(letters) > 1 and all(c.isupper() for c in letters)
            for i, a in enumerate(actions):
                if isinstance(a, TextAction):
                    if all_caps:
                        actions[i] = TextAction(a.text.upper())
                    elif first:
                        actions[i] = TextAction(apply_case(a.text, ctx.typed_abbreviation))
                    first = False
        return actions

    def expand_to_text(self, content: str, ctx: ExpansionContext | None = None) -> str:
        return actions_to_text(self.expand(content, ctx), keys_as_markers=True)

    # ------------------------------------------------------------ evaluation
    def eval_nodes(self, nodes: list, rt: Runtime) -> list:
        out: list = []
        for nd in nodes:
            if isinstance(nd, Text):
                out.append(TextAction(nd.text))
            elif isinstance(nd, Call):
                out.extend(self.eval_call(nd, rt))
            elif isinstance(nd, IfBlock):
                out.extend(self.eval_if(nd, rt))
            elif isinstance(nd, LoopBlock):
                out.extend(self.eval_loop(nd, rt))
            elif isinstance(nd, FormBlock):
                out.extend(self.eval_form(nd, rt))
        return out

    def eval_token(self, tok: Token | None, rt: Runtime) -> str:
        if tok is None:
            return "1"
        return actions_to_text(self.eval_nodes(tok.parts, rt))

    def eval_call(self, call: Call, rt: Runtime) -> list:
        entry = REGISTRY.get(call.name)
        if entry is None or entry[1] is None:
            return [TextAction(call.raw)]
        fn = entry[1]
        args = [self.eval_token(t, rt) for t in call.args]
        opts = {k: self.eval_token(v, rt) for k, v in call.opts.items()}
        if not getattr(rt.ctx, "allow_privileged", True):
            from phraseforge.security import privileged_reason
            if privileged_reason(entry[0].name, args, opts):
                return [TextAction(f"[{call.name}: blocked, phrase not approved on this PC]")]
        try:
            res = fn(rt, args, opts)
        except Cancelled:
            raise
        except MacroError as e:
            return [TextAction(f"[{call.name}: {e}]")]
        except Exception as e:  # noqa: BLE001 - surface any failure inline
            return [TextAction(f"[{call.name}: {type(e).__name__}: {e}]")]
        return _norm(res)

    def eval_if(self, block: IfBlock, rt: Runtime) -> list:
        for cond, body in block.branches:
            if cond is None or self.eval_condition(cond, rt):
                return self.eval_nodes(body, rt)
        return []

    def eval_condition(self, call: Call, rt: Runtime) -> bool:
        toks = [(self.eval_token(t, rt), t.bare_text is not None) for t in call.args]
        try:
            return _Cond(toks).run()
        except re.error as e:
            raise MacroError(f"bad regex: {e}") from e

    def eval_loop(self, block: LoopBlock, rt: Runtime) -> list:
        call = block.call
        args = [self.eval_token(t, rt) for t in call.args]
        opts = {k: self.eval_token(v, rt) for k, v in call.opts.items()}
        if call.name == "loop":
            try:
                n = int(float(args[0])) if args else 1
            except ValueError:
                return [TextAction(f"[loop: bad count '{args[0]}']")]
            items = [""] * max(0, min(n, MAX_LOOP))
        else:
            sep = opts.get("sep", ",")
            if len(args) == 1:
                items = [x.strip() for x in args[0].split(sep)] if args[0] else []
            else:
                items = list(args)
            items = items[:MAX_LOOP]
        joiner = opts.get("join", "")
        out: list = []
        for i, item in enumerate(items):
            rt.loops.append(LoopFrame(i, len(items), item))
            try:
                if i and joiner:
                    out.append(TextAction(joiner))
                out.extend(self.eval_nodes(block.body, rt))
            finally:
                rt.loops.pop()
        return out

    def eval_form(self, block: FormBlock, rt: Runtime) -> list:
        opts = {k: self.eval_token(v, rt) for k, v in block.call.opts.items()}
        args = [self.eval_token(t, rt) for t in block.call.args]
        title = opts.get("title") or (args[0] if args else "") or rt.ctx.phrase_description or "Form"
        prev = rt.collecting
        rt.collecting = []
        try:
            self.eval_nodes(block.body, rt)          # fields register themselves; other output dropped
            fields = rt.collecting
        finally:
            rt.collecting = prev
        values = rt.host.show_form(title, fields)
        store_form_values(rt, fields, values)
        return []


def store_form_values(rt: Runtime, fields: list[FormField], values: dict) -> None:
    from phraseforge.macros.datetimes import format_dt
    for f in fields:
        if f.kind == "label":
            continue
        v = values.get(f.name, f.default) if values is not None else f.default
        spec = rt.field_specs.get(f.name, {})
        if f.kind == "checkbox":
            on = isinstance(v, bool) and v or (isinstance(v, str) and _truthy(v))
            v = spec.get("on", "1") if on else spec.get("off", "")
        elif f.kind == "date" and spec.get("format") and v:
            try:
                v = format_dt(datetime.fromisoformat(str(v)), spec["format"], spec.get("lang", "en"))
            except ValueError:
                pass
        elif isinstance(v, (list, tuple)):
            v = spec.get("sep", ", ").join(str(x) for x in v)
        elif isinstance(v, float) and v.is_integer():
            v = str(int(v))
        rt.form_values[f.name] = "" if v is None else str(v)


def _norm(res) -> list:
    if res is None:
        return []
    if isinstance(res, str):
        return [TextAction(res)]
    if isinstance(res, (TextAction, HtmlAction, KeyAction, CursorAction, SleepAction, MouseAction, ImageAction)):
        return [res]
    if isinstance(res, list):
        return res
    return [TextAction(str(res))]
