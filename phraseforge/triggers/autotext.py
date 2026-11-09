"""Pure autotext / regex matcher over the stream of typed characters.

Convention: when a Match is returned the key that completed it has NOT been
typed into the target app yet - the caller swallows that keystroke (or, for the
"confirm"/"pause"/"continue" execution modes, lets it through and uses
typed_len(match) as the number of characters to erase).
  * No trailing delimiter needed: the last abbreviation char completes the
    match -> erase_chars = len(abbreviation) - 1.
  * Trailing delimiter needed: the delimiter completes it -> erase_chars =
    len(abbreviation), trailing_delimiter holds it (re-typed after output unless
    the trigger says remove_trailing).
  * REGEX: like the no-delimiter case over the regex match.

Word position (Trigger.eff_word_pos):
  start   the abbreviation must begin a word (leading delimiter before it)
  end     may follow letters, but must be followed by a trailing delimiter
  middle  anywhere
  entire  leading delimiter before and trailing delimiter after

Delimiter choices (Trigger.lead_delim / trail_delim, PRD FR-TRG-03): one of
models.DELIMITER_CHOICES, several joined with "+" ("Space+Comma"), and "Custom:<chars>".
"Standard" is another name for "Default" (the global set in Settings).

Fast typing only (Trigger.fast_only, FR-TRG-01): the abbreviation fires only when no two of
its characters were typed more than fast_ms apart, so a word typed slowly stays as it is.
skip_next() (FR-TRG-05) makes the next match be ignored once.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, replace
from typing import Callable

from phraseforge.models import Folder, Trigger, TriggerKind

MAX_BUFFER = 256
PUNCTUATION = set(".,;:!?)]}'\"([{/\\-_<>")
START_OF_TEXT = "\x00"   # in the leading-delimiter setting: "start of text counts"

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
    # other triggers with the same abbreviation that matched at the same keystroke
    # (PhraseExpress "multiple choice autotext": the caller offers a menu)
    alternatives: tuple[Trigger, ...] = ()


def typed_len(m: Match) -> int:
    """Characters already on screen if the completing key is NOT swallowed."""
    return len(m.typed) + len(m.trailing_delimiter)


class AutotextMatcher:
    def __init__(self, delimiters: str = " \t\n.,;:!?)]}'\"", leading: str | None = None,
                 route_enter_tab: bool = True):
        self._route = route_enter_tab
        self._trail_raw = delimiters
        self._lead_raw = leading
        self._buf = ""
        self._times: list[float] = []      # when each character of _buf was typed
        self.fast_ms = 150
        self._skip_next = False
        self._clock = time.monotonic
        self._no_trail: list[Trigger] = []
        self._trail: list[Trigger] = []
        self._regex: list[tuple[Trigger, re.Pattern]] = []
        self._lock = threading.Lock()
        self._rebuild_sets()

    # ------------------------------------------------------------ setup
    def _rebuild_sets(self) -> None:
        trail = set(self._trail_raw) | {" "}
        if self._route:
            trail |= {"\n", "\t"}
        else:
            trail -= {"\n", "\t", "\r"}
        self.delimiters = trail
        lead = set(self._lead_raw) if self._lead_raw is not None else (set(self._trail_raw) | {" ", "\n", "\t"})
        self.leading = lead | {"\n"}          # a new line always starts a word

    def set_delimiters(self, delimiters: str) -> None:
        self._trail_raw = delimiters
        self._rebuild_sets()

    def set_leading(self, leading: str | None) -> None:
        self._lead_raw = leading
        self._rebuild_sets()

    def set_route_enter_tab(self, on: bool) -> None:
        self._route = bool(on)
        self._rebuild_sets()

    def load(self, triggers: list[Trigger]) -> None:
        no_trail, trail, rx = [], [], []
        for t in triggers:
            if not t.enabled or not t.value:
                continue
            kind = TriggerKind(t.kind)
            if kind == TriggerKind.AUTOTEXT:
                (no_trail if self._trail_pred(t) is None else trail).append(t)
            elif kind == TriggerKind.REGEX:
                try:
                    flags = 0 if t.case_sensitive else re.IGNORECASE
                    rx.append((t, re.compile(f"(?:{t.value})$", flags)))
                except re.error:
                    continue
        # longest first so the first hit is the longest match
        no_trail.sort(key=lambda t: -len(t.value))
        trail.sort(key=lambda t: -len(t.value))
        with self._lock:
            self._no_trail, self._trail, self._regex = no_trail, trail, rx

    @property
    def buffer(self) -> str:
        return self._buf

    def reset(self) -> None:
        self._buf = ""
        self._times = []

    def set_fast_ms(self, ms: int) -> None:
        self.fast_ms = max(10, int(ms))

    def skip_next(self) -> None:
        """Ignore the next autotext or regex match once (the Skip-next hotkey)."""
        self._skip_next = True

    @property
    def skipping(self) -> bool:
        return self._skip_next

    def _fast(self, t: Trigger, times: list[float]) -> bool:
        if not t.fast_only:
            return True
        limit = self.fast_ms / 1000.0
        return all(b - a <= limit for a, b in zip(times, times[1:]))

    def _set_buf(self, buf: str, times: list[float]) -> None:
        self._buf, self._times = buf, times[-len(buf):] if buf else []

    def _hit(self, m: Match) -> Match | None:
        self._buf, self._times = "", []
        if self._skip_next:
            self._skip_next = False
            return None
        return m

    # ------------------------------------------------------------ delimiter rules
    def _choice_pred(self, choice: str, default: set[str]) -> Callable[[str], bool] | None:
        if choice == "None":
            return None
        if choice.startswith("Custom:"):
            chars = set(choice[len("Custom:"):])
            return lambda c: c in chars
        if "+" in choice and choice not in ("+",):
            preds = [p for p in (self._choice_pred(part.strip(), default) for part in choice.split("+") if part.strip())
                     if p is not None]
            return (lambda c: any(p(c) for p in preds)) if preds else None
        if choice == "All":
            return lambda c: True
        if choice == "Letters":
            return lambda c: c.isalpha()
        if choice == "Numbers":
            return lambda c: c.isdigit()
        if choice == "Point":
            return lambda c: c == "."
        if choice == "Comma":
            return lambda c: c == ","
        if choice == "Custom":              # "Custom" without characters: nothing matches
            return lambda c: False
        if choice == "Space":
            return lambda c: c == " "
        if choice == "Enter":
            return lambda c: c == "\n"
        if choice == "Tab":
            return lambda c: c == "\t"
        if choice == "Punctuation":
            return lambda c: c in PUNCTUATION
        if choice == "Any non-letter":
            return lambda c: not c.isalpha()
        return lambda c, s=default: c in s      # "Default"

    def _trail_pred(self, t: Trigger) -> Callable[[str], bool] | None:
        choice = t.eff_trail()
        if t.eff_word_pos() in ("end", "entire") and choice == "None":
            choice = "Default"                  # these positions need a word end
        return self._choice_pred(choice, self.delimiters)

    def _lead_ok(self, t: Trigger, buf: str, start: int) -> bool:
        if t.eff_word_pos() in ("middle", "end"):
            return True
        if start == 0:                          # nothing known before it (start of input)
            return True
        pred = self._choice_pred(t.eff_lead(), self.leading)
        return True if pred is None else pred(buf[start - 1])

    def _suffix(self, t: Trigger, buf: str) -> int | None:
        """Start index of t.value as a suffix of buf, honoring case and leading rules."""
        v = t.value
        if len(v) > len(buf):
            return None
        tail = buf[-len(v):]
        ok = tail == v if t.case_sensitive else tail.casefold() == v.casefold()
        if not ok:
            return None
        start = len(buf) - len(v)
        return start if self._lead_ok(t, buf, start) else None

    @staticmethod
    def _same(t: Trigger, rest: list[Trigger], matches: Callable[[Trigger], bool]) -> tuple[Trigger, ...]:
        """Triggers after t (same list, longest first) with the same abbreviation that also match."""
        out = []
        for o in rest:
            if len(o.value) != len(t.value):
                break
            if o.value.casefold() == t.value.casefold() and matches(o):
                out.append(o)
        return tuple(out)

    # ------------------------------------------------------------ matching
    def feed(self, char: str | None, key: str | None = None, now: float | None = None) -> Match | None:
        """Feed one keystroke. char is the produced text (may be '\\n'/'\\t');
        key names a non-text key ('backspace', 'left', 'click', ...)."""
        with self._lock:
            if char is None:
                if key == "backspace":
                    self._buf, self._times = self._buf[:-1], self._times[:-1]
                elif key in RESET_KEYS or key is not None:
                    self._buf, self._times = "", []
                return None
            now = self._clock() if now is None else now
            buf = self._buf + char
            times = (self._times + [now])[-len(buf):]
            # 1. triggers that need no trailing delimiter (abbreviation ends with this char)
            for i, t in enumerate(self._no_trail):
                start = self._suffix(t, buf)
                if start is not None and self._fast(t, times[start:]):
                    alts = self._same(t, self._no_trail[i + 1:],
                                      lambda o: self._suffix(o, buf) == start and self._fast(o, times[start:]))
                    return self._hit(Match(t, erase_chars=len(t.value) - 1, typed=buf[start:], alternatives=alts))
            # 2. regex triggers
            for t, rx in self._regex:
                m = rx.search(buf)
                if m and m.end() > m.start():
                    return self._hit(Match(t, erase_chars=(m.end() - m.start()) - 1, typed=m.group(0),
                                           groups=tuple(g or "" for g in m.groups())))
            # 3. triggers completed by a trailing delimiter (this char)
            prev, ptimes = self._buf, self._times
            for i, t in enumerate(self._trail):
                pred = self._trail_pred(t)
                if pred is not None and pred(char):
                    start = self._suffix(t, prev)
                    if start is not None and self._fast(t, ptimes[start:]):

                        def also(o, start=start):
                            op = self._trail_pred(o)
                            return (op is not None and op(char) and self._suffix(o, prev) == start
                                    and self._fast(o, ptimes[start:]))

                        alts = self._same(t, self._trail[i + 1:], also)
                        return self._hit(Match(t, erase_chars=len(t.value), trailing_delimiter=char,
                                               typed=prev[start:], alternatives=alts))
            if char == "\n":
                self._set_buf("\n", [now])   # keep a boundary marker, drop old line
            else:
                self._set_buf(buf[-MAX_BUFFER:], times)
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


def folder_prefixes(folders: list[Folder]) -> dict[int, str]:
    """Effective abbreviation prefix of every folder: its own, else the nearest parent's."""
    by_id = {f.id: f for f in folders}
    out: dict[int, str] = {}

    def eff(fid, seen=()):
        if fid in out:
            return out[fid]
        f = by_id.get(fid)
        if f is None or fid in seen:
            return ""
        val = f.abbrev_prefix or eff(f.parent_id, seen + (fid,))
        out[fid] = val
        return val

    for fid in by_id:
        eff(fid)
    return out


def apply_group_prefixes(triggers: list[Trigger], phrase_folder: dict[int, int | None],
                         prefixes: dict[int, str]) -> list[Trigger]:
    """TextExpander "Group prefix": autotext abbreviations of phrases in a folder with a
    prefix are matched as prefix + abbreviation. Returns copies; other triggers unchanged."""
    if not any(prefixes.values()):
        return triggers
    out = []
    for t in triggers:
        pre = ""
        if TriggerKind(t.kind) == TriggerKind.AUTOTEXT and t.phrase_id is not None:
            fid = phrase_folder.get(t.phrase_id)
            pre = prefixes.get(fid, "") if fid is not None else ""
        out.append(replace(t, value=pre + t.value) if pre and t.value and not t.value.startswith(pre) else t)
    return out


def apply_global_prefix(triggers: list[Trigger], prefix: str) -> list[Trigger]:
    """Settings > Autotext "global prefix" (FR-TRG-02): every autotext abbreviation must be typed
    after the prefix ("#sig"); the prefix is erased with the abbreviation. Returns copies."""
    if not prefix:
        return triggers
    return [replace(t, value=prefix + t.value)
            if TriggerKind(t.kind) == TriggerKind.AUTOTEXT and t.value else t
            for t in triggers]
