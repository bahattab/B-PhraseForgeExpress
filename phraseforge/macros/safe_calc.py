"""Safe arithmetic evaluation (no eval)."""
from __future__ import annotations

import ast
import math
import operator

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_UN = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"round": round, "abs": abs, "min": min, "max": max, "sqrt": math.sqrt,
          "floor": math.floor, "ceil": math.ceil, "int": int}
_CONST = {"pi": math.pi, "e": math.e}


def calc(expr: str) -> float | int:
    expr =expr.replace("×", "*").replace("÷", "/").replace("^", "**")
    tree = ast.parse(expr.strip(), mode="eval")
    return _ev(tree.body)


def _ev(n):
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
        return n.value
    if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
        a, b = _ev(n.left), _ev(n.right)
        if isinstance(n.op, ast.Pow) and abs(b) > 1000:
            raise ValueError("exponent too large")
        return _BIN[type(n.op)](a, b)
    if isinstance(n, ast.UnaryOp) and type(n.op) in _UN:
        return _UN[type(n.op)](_ev(n.operand))
    if isinstance(n, ast.Name) and n.id in _CONST:
        return _CONST[n.id]
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS and not n.keywords:
        return _FUNCS[n.func.id](*[_ev(a) for a in n.args])
    raise ValueError("unsupported expression")


def fmt_number(v, decimals: int | None = None) -> str:
    if decimals is not None:
        return f"{v:.{decimals}f}"
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        return repr(round(v, 10)).rstrip("0").rstrip(".") if "e" not in repr(v) else repr(v)
    return str(v)
