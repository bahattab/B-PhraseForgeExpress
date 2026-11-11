"""Phrase language levels (PRD G-17): which version of a phrase autotext and hotkeys insert."""
from __future__ import annotations

import json


def languages(stored: str) -> list[str]:
    """The phrase.languages setting (a JSON list) as clean names; anything else is no list."""
    try:
        v = json.loads(stored or "[]")
    except ValueError:
        return []
    out: list[str] = []
    for x in v if isinstance(v, list) else []:
        name = str(x).strip()
        if name and name not in out:
            out.append(name)
    return out


def next_language(current: str, stored: str) -> str:
    """Default -> first language -> ... -> last -> Default. An unknown current one starts over."""
    order = [""] + languages(stored)
    try:
        i = order.index(current or "")
    except ValueError:
        return order[1] if len(order) > 1 else ""
    return order[(i + 1) % len(order)]
