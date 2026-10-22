"""Pure autotext / regex matcher over the stream of typed characters.

Convention: when a Match is returned the key that completed it has NOT been
typed into the target app yet - the caller swallows that keystroke.
  * IMMEDIATE: the last abbreviation char is swallowed ->
    erase_chars = len(abbreviation) - 1.
  * DELIMITER: the delimiter is swallowed -> erase_chars = len(abbreviation),
    and trailing_delimiter holds it so output can re-type it.
  * REGEX: like IMMEDIATE over the regex match.
Callers that do NOT swallow (e.g. confirm mode) should use typed_len(match).
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass

from phraseforge.models import AutotextMode, Trigger, TriggerKind

MAX_BUFFER = 256

# Keys that move the caret or change focus: the buffer no longer reflects
# the text left of the caret.
RESET_KEYS = {"left", "right", "up", "down", "home", "end", "pgup", "pgdn", "escape", "click",
              "delete", "focus", "ctrl", "alt", "win", "insert", "f-key"}


@dataclass
class Match:
    trigger: Trigger
    erase_chars: int
    trailing_delimiter: str = ""
    typed: str = ""                    # abbreviation text as the user typed it (incl. completing char)
    groups: tuple[str, ...] = ()
    swallow: bool = True


def typed_len(m: Match) -> int:
    """Characters already on screen if the completing key is NOT swallowed."""
    return len(m.typed) + len(m.trailing_delimiter)


class AutotextMatcher:
    def __init__(self, delimiters: str = " \t\n.,;:!?)]}'\""):
        self.delimiters = set(delimiters) | {"\n", "\t", " "}
        self._buf = ""
        self._immediate: list[Trigger] = []
        self._delimited: list[Trigger] = []
        self._regex: list[tuple[Trigger, re.Pattern]] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------ setup
    def set_delimiters(self, delimiters: str) -> None:
        self.delimiters = set(delimiters) | {"\n", "\t", " "}

    def load(self, triggers: list[Trigger]) -> None:
        imm, dlm, rx = [], [], []
        for t in triggers:
            if not t.enabled or not t.value:
                continue
            kind = TriggerKind(t.kind)
            if kind == TriggerKind.AUTOTEXT:
                mode = AutotextMode(t.mode)
                (imm if mode == AutotextMode.IMMEDIATE else dlm).append(t)
            elif kind == TriggerKind.REGEX:
                try:
                    flags = 0 if t.case_sensitive else re.IGNORECASE
                    rx.append((t, re.compile(f"(?:{t.value})$", flags)))
                except re.error:
                    continue
        # longest first so the first hit is the longest match
        imm.sort(key=lambda t: -len(t.value))
        dlm.sort(key=lambda t: -len(t.value))
        with self._lock:
            self._immediate, self._delimited, self._regex = imm, dlm, rx

    @property
    def buffer(self) -> str:
        return self._buf

    def reset(self) -> None:
        self._buf = ""

    # ------------------------------------------------------------ matching
    def _boundary_ok(self, t: Trigger, buf: str, start: int) -> bool:
        if not t.word_start_only or start == 0:
            return True
        return buf[start - 1] in self.delimiters

    def _suffix(self, t: Trigger, buf: str) -> int | None:
        """Start index of t.value as a suffix of buf, honoring case rules."""
        v = t.value
        if len(v) > len(buf):
            return None
        tail = buf[-len(v):]
        ok = tail == v if t.case_sensitive else tail.casefold() == v.casefold()
        if not ok:
            return None
        start = len(buf) - len(v)
        return start if self._boundary_ok(t, buf, start) else None

    def feed(self, char: str | None, key: str | None = None) -> Match | None:
        """Feed one keystroke. char is the produced text (may be '\\n'/'\\t');
        key names a non-text key ('backspace', 'left', 'click', ...)."""
        with self._lock:
            if char is None:
                if key == "backspace":
                    self._buf = self._buf[:-1]
                elif key in RESET_KEYS or key is not None:
                    self._buf = ""
                return None
            buf = self._buf + char
            # 1. immediate triggers (abbreviation ends with this char)
            for t in self._immediate:
                start = self._suffix(t, buf)
                if start is not None:
                    self._buf = ""
                    return Match(t, erase_chars=len(t.value) - 1, typed=buf[start:])
            # 2. regex triggers
            for t, rx in self._regex:
                m = rx.search(buf)
                if m and m.end() > m.start():
                    self._buf = ""
                    return Match(t, erase_chars=(m.end() - m.start()) - 1, typed=m.group(0),
                                 groups=tuple(g or "" for g in m.groups()))
            # 3. delimiter triggers (abbreviation precedes this delimiter)
            if char in self.delimiters:
                prev = self._buf
                for t in self._delimited:
                    start = self._suffix(t, prev)
                    if start is not None:
                        self._buf = ""
                        return Match(t, erase_chars=len(t.value), trailing_delimiter=char, typed=prev[start:])
            self._buf = buf[-MAX_BUFFER:]
            if char == "\n":
                self._buf = "\n"   # keep a boundary marker, drop old line
            return None


def apply_case(expansion: str, typed: str, abbreviation: str) -> str:
    """Helper for case-insensitive triggers: 'Sig' -> capitalize, 'SIG' -> upper."""
    letters = [c for c in typed if c.isalpha()]
    if not letters or typed == abbreviation:
        return expansion
    if all(c.isupper() for c in letters) and len(letters) > 1:
        return expansion.upper()
    if letters[0].isupper() and not abbreviation[:1].isupper():
        return expansion[:1].upper() + expansion[1:]
    return expansion
