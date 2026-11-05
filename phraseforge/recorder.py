"""Macro recorder (PRD FR-REC-01, gap G-23).

Records what the user types and clicks in any program and turns it into a
phrase that replays it with the existing macros:

  typed text        plain text (corrections with Backspace are folded in)
  Enter, Tab, Esc,
  arrows, F-keys …  {#key enter}
  shortcuts         {#key ctrl+c}, {#key win+r}
  mouse clicks      {#mouse click -x 640 -y 380}, rclick, dblclick; with
                    recorder.window_relative = "1" the position is relative to
                    the window in front, so the macro still works after it moved
  mouse wheel       {#mouse wheel -delta -120}
  pauses            {#sleep 800}; pauses shorter than recorder.min_pause_ms
                    (default 300) are dropped, longer ones are capped at
                    recorder.max_pause_ms (default 2000) so idle time is not replayed

Recording stops with the stop hotkey (recorder.stop_hotkey, default
ctrl+shift+f12), which is not recorded itself. Keys typed in password fields
are not recorded. The Windows hooks live in platform/record_hook.py; this
module only collects events and writes the macro, so it is tested without
Windows.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Iterable

from phraseforge.platform.keys import MODIFIER_VKS, VK_BACK, VK_RETURN, VK_TAB, vk_to_name

DOUBLE_CLICK_MS = 500
DOUBLE_CLICK_PX = 4
DEFAULTS = {"recorder.stop_hotkey": "ctrl+shift+f12", "recorder.min_pause_ms": "300",
            "recorder.max_pause_ms": "2000", "recorder.window_relative": "0", "recorder.record_mouse": "1"}
TEXT_KEYS = {VK_RETURN: "enter", VK_TAB: "tab"}     # replayed as keys, not as text


@dataclass
class RecKey:
    t: float                   # seconds
    vk: int
    char: str | None = None    # the character it typed, None for keys that type nothing
    mods: frozenset = frozenset()


@dataclass
class RecClick:
    t: float
    button: str                # left | right | middle
    x: int
    y: int
    rel_x: int | None = None   # relative to the foreground window, when known
    rel_y: int | None = None


@dataclass
class RecWheel:
    t: float
    delta: int                 # +120 = one notch away from the user


def wheel_delta(mouse_data: int) -> int:
    """The signed wheel delta in the high word of a WH_MOUSE_LL mouseData."""
    hi = (mouse_data >> 16) & 0xFFFF
    return hi - 0x10000 if hi >= 0x8000 else hi


def chord_of(ev: RecKey) -> str:
    """'ctrl+shift+f12' style name of a key press."""
    order = [m for m in ("ctrl", "alt", "shift", "win") if m in ev.mods]
    return "+".join(order + [vk_to_name(ev.vk)])


def norm_chord(spec: str) -> str:
    parts = [p.strip().lower() for p in spec.replace(" ", "").split("+") if p.strip()]
    mods = [m for m in ("ctrl", "alt", "shift", "win") if m in parts]
    rest = [p for p in parts if p not in ("ctrl", "alt", "shift", "win")]
    return "+".join(mods + rest)


def _escape(text: str) -> str:
    return text.replace("{", "{{")


def to_macro(events: Iterable, min_pause_ms: int = 300, max_pause_ms: int = 2000,
             window_relative: bool = False) -> str:
    """The phrase content that replays the recorded events."""
    out: list[str] = []
    run: list[str] = []
    last_t: float | None = None

    def flush_run():
        if run:
            out.append(_escape("".join(run)))
            run.clear()

    def pause(t: float):
        nonlocal last_t
        if last_t is not None:
            ms = int(round((t - last_t) * 1000))
            if ms >= min_pause_ms:
                flush_run()
                ms = min(ms, max_pause_ms) if max_pause_ms > 0 else ms
                out.append(f"{{#sleep {int(round(ms / 50.0) * 50)}}}")
        last_t = t

    def click_macro(c: RecClick, double: bool) -> str:
        kind = {"left": "click", "right": "rclick"}.get(c.button, "click")
        if double:
            kind = "dblclick"
        if window_relative and c.rel_x is not None and c.rel_y is not None:
            return f"{{#mouse {kind} -x {c.rel_x} -y {c.rel_y} -relative 1}}"
        return f"{{#mouse {kind} -x {c.x} -y {c.y}}}"

    evs = sorted(events, key=lambda e: e.t)
    i = 0
    while i < len(evs):
        ev = evs[i]
        if isinstance(ev, RecKey):
            if ev.vk in MODIFIER_VKS:
                i += 1
                continue
            pause(ev.t)
            shortcut = bool(ev.mods & {"ctrl", "alt", "win"}) and not (
                ev.char and {"ctrl", "alt"} <= ev.mods and "win" not in ev.mods)   # AltGr types a character
            if ev.vk == VK_BACK and not ev.mods and run:
                run.pop()                               # a typing correction: fold it in
            elif ev.vk in TEXT_KEYS and not shortcut:
                flush_run()
                out.append(f"{{#key {'shift+' if 'shift' in ev.mods else ''}{TEXT_KEYS[ev.vk]}}}")
            elif ev.char and not shortcut:
                run.append(ev.char)
            else:
                flush_run()
                out.append(f"{{#key {chord_of(ev)}}}")
        elif isinstance(ev, RecClick):
            pause(ev.t)
            flush_run()
            nxt = evs[i + 1] if i + 1 < len(evs) else None
            double = (isinstance(nxt, RecClick) and nxt.button == ev.button
                      and (nxt.t - ev.t) * 1000 <= DOUBLE_CLICK_MS
                      and abs(nxt.x - ev.x) <= DOUBLE_CLICK_PX and abs(nxt.y - ev.y) <= DOUBLE_CLICK_PX)
            out.append(click_macro(ev, double))
            if double:
                i += 1
                last_t = nxt.t
        elif isinstance(ev, RecWheel):
            pause(ev.t)
            flush_run()
            out.append(f"{{#mouse wheel -delta {ev.delta}}}")
        i += 1
    flush_run()
    return _merge_wheels("".join(out))


def _merge_wheels(text: str) -> str:
    """Neighbouring wheel notches in the same direction become one scroll."""
    import re
    pat = re.compile(r"(\{#mouse wheel -delta (-?\d+)\})+")

    def merge(m):
        deltas = [int(d) for d in re.findall(r"-delta (-?\d+)", m.group(0))]
        groups: list[int] = []
        for d in deltas:
            if groups and (groups[-1] > 0) == (d > 0):
                groups[-1] += d
            else:
                groups.append(d)
        return "".join(f"{{#mouse wheel -delta {g}}}" for g in groups)
    return pat.sub(merge, text)


class Recorder:
    """Collects events from the hooks until the stop hotkey; thread-safe enough for the
    hook threads (appends only)."""

    def __init__(self, setting: Callable[[str, str], str] | None = None, clock=time.monotonic,
                 password_check: Callable[[], bool] | None = None):
        get = setting or (lambda k, d="": d)
        self.setting = lambda k: get(k, DEFAULTS[k]) or DEFAULTS[k]
        self.clock = clock
        self.password_check = password_check or (lambda: False)
        self.events: list = []
        self.recording = False
        self.skipped_passwords = 0
        self.stop_chord = norm_chord(self.setting("recorder.stop_hotkey"))
        self.on_stop: Callable[[], None] | None = None

    def start(self) -> None:
        self.events.clear()
        self.skipped_passwords = 0
        self.recording = True

    def stop(self) -> str:
        self.recording = False
        # the modifiers of the stop hotkey were pressed before it: drop that trailing tail
        while self.events and isinstance(self.events[-1], RecKey) and self.events[-1].vk in MODIFIER_VKS:
            self.events.pop()
        return self.macro()

    def macro(self) -> str:
        def num(k):
            try:
                return int(self.setting(k))
            except ValueError:
                return int(DEFAULTS[k])
        return to_macro(self.events, num("recorder.min_pause_ms"), num("recorder.max_pause_ms"),
                        self.setting("recorder.window_relative") == "1")

    # ---- called by the hooks; True = the event was the stop hotkey (swallow it)
    def key(self, vk: int, char: str | None, mods: set[str]) -> bool:
        if not self.recording:
            return False
        ev = RecKey(self.clock(), vk, char, frozenset(mods))
        if vk not in MODIFIER_VKS and chord_of(ev) == self.stop_chord:
            self.stop()
            if self.on_stop:
                self.on_stop()
            return True
        if vk not in MODIFIER_VKS and self.password_check():
            self.skipped_passwords += 1             # never record what goes into a password field
            return False
        self.events.append(ev)
        return False

    def click(self, button: str, x: int, y: int, rel: tuple[int, int] | None = None) -> None:
        if self.recording and self.setting("recorder.record_mouse") == "1":
            self.events.append(RecClick(self.clock(), button, x, y, *(rel or (None, None))))

    def wheel(self, delta: int) -> None:
        if self.recording and self.setting("recorder.record_mouse") == "1":
            self.events.append(RecWheel(self.clock(), delta))
