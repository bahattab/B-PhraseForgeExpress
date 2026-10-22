"""Macro command registry. Commands register with @macro; catalog() lists them."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class MacroInfo:
    name: str
    category: str
    syntax: str
    description: str
    template: str


class MacroError(Exception):
    """A command failed; rendered inline as [name: message]."""


# name -> (info, fn). fn(rt, args: list[str], opts: dict[str, str]) -> str | Action | list | None
REGISTRY: dict[str, tuple[MacroInfo, Callable | None]] = {}
_PRIMARY: list[str] = []


def macro(name: str, category: str, syntax: str, description: str,
          template: str | None = None, aliases: tuple[str, ...] = ()):
    def deco(fn):
        register(name, category, syntax, description, template, aliases, fn)
        return fn
    return deco


def register(name, category, syntax, description, template=None, aliases=(), fn=None) -> None:
    info = MacroInfo(name, category, syntax, description, template if template is not None else syntax)
    if name not in REGISTRY:
        _PRIMARY.append(name)
    REGISTRY[name] = (info, fn)
    for a in aliases:
        REGISTRY[a] = (info, fn)


def catalog() -> list[MacroInfo]:
    from phraseforge.macros import commands, commands_extra  # noqa: F401  (ensure registration)
    return [REGISTRY[n][0] for n in _PRIMARY]
