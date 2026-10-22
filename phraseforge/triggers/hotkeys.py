"""Hotkey strings ("ctrl+alt+k") and a matcher used inside the keyboard hook."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from phraseforge.platform import keys as K


@dataclass(frozen=True)
class Hotkey:
    modifiers: frozenset[str]
    vk: int

    def __str__(self) -> str:
        return format_hotkey(self)


ORDER = ("ctrl", "alt", "shift", "win")


def parse_hotkey(spec: str, vk_from_char=None) -> Hotkey:
    """Parse 'Ctrl+Alt+K', 'ctrl+shift+f5', 'win+space', 'ctrl++'. Raises ValueError."""
    s = spec.strip().lower().replace(" ", "")
    if not s:
        raise ValueError("empty hotkey")
    if s.endswith("++"):
        s = s[:-2] + "+plus"
    parts = [p for p in s.split("+") if p]
    mods = set()
    for p in parts[:-1]:
        m = K.MODIFIER_ALIASES.get(p)
        if not m:
            raise ValueError(f"{p!r} is not a modifier")
        mods.add(m)
    last = parts[-1]
    if last in K.MODIFIER_ALIASES:
        raise ValueError("hotkey needs a non-modifier key")
    vk = K.key_name_to_vk(last, vk_from_char)
    return Hotkey(frozenset(mods), vk)


def format_hotkey(hk: Hotkey) -> str:
    names = [m for m in ORDER if m in hk.modifiers] + [K.vk_to_name(hk.vk)]
    return "+".join(n.capitalize() if len(n) > 1 else n.upper() for n in names)


def normalize_hotkey(spec: str) -> str:
    return format_hotkey(parse_hotkey(spec))


class HotkeyMatcher:
    """Maps hotkeys to payloads. on_key_down(vk, modifiers) returns the payload
    when the exact chord matches. The matching key's release is swallowed too."""

    def __init__(self, vk_from_char=None):
        self._map: dict[Hotkey, Any] = {}
        self._swallowed_up: set[int] = set()
        self._lock = threading.Lock()
        self.vk_from_char = vk_from_char
        self.errors: list[str] = []

    def clear(self) -> None:
        with self._lock:
            self._map.clear()
            self.errors.clear()

    def register(self, spec: str, payload: Any) -> Hotkey | None:
        if not spec or not spec.strip():
            return None
        try:
            hk = parse_hotkey(spec, self.vk_from_char)
        except ValueError as e:
            self.errors.append(f"{spec}: {e}")
            return None
        with self._lock:
            self._map.setdefault(hk, payload)   # first registration wins
        return hk

    def on_key_down(self, vk: int, modifiers: set[str] | frozenset[str]) -> Any | None:
        if vk in K.MODIFIER_VKS:
            return None
        with self._lock:
            payload = self._map.get(Hotkey(frozenset(modifiers), vk))
        if payload is not None:
            self._swallowed_up.add(vk)
        return payload

    def on_key_up(self, vk: int) -> bool:
        """True if this key-up belongs to a swallowed hotkey press."""
        if vk in self._swallowed_up:
            self._swallowed_up.discard(vk)
            return True
        return False

    def __len__(self) -> int:
        return len(self._map)
