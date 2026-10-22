"""Autotext learning: notices sentences the user types repeatedly and records
them as suggestions (store.suggestions) the UI can offer to turn into phrases.

Settings: learning.enabled ("1"), learning.min_length (chars, default 12),
learning.min_count (repetitions before suggesting, default 3).
"""
from __future__ import annotations

import logging
import re
from typing import Callable

log = logging.getLogger(__name__)

SENTENCE_END = set(".!?\n")
MAX_BUFFER = 500
RESET_KEYS = {"left", "right", "up", "down", "home", "end", "pgup", "pgdn", "click", "focus",
              "delete", "ctrl", "escape", "insert"}


def normalize_candidate(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class Learner:
    def __init__(self, store, password_check: Callable[[], bool] | None = None):
        self.store = store
        self._password_check = password_check
        self._buf: list[str] = []
        self._tainted = False   # current sentence started in a password field

    # ------------------------------------------------------------ settings
    def _enabled(self) -> bool:
        return self.store.setting("learning.enabled", "1") == "1"

    def _int(self, key: str, default: int) -> int:
        try:
            return int(self.store.setting(key, str(default)) or default)
        except ValueError:
            return default

    def _is_password(self) -> bool:
        if self._password_check is None:
            try:
                from phraseforge.platform.windows import focused_is_password
                self._password_check = focused_is_password
            except Exception:
                self._password_check = lambda: False
        try:
            return bool(self._password_check())
        except Exception:
            return False

    # ------------------------------------------------------------ input
    def reset(self) -> None:
        self._buf.clear()
        self._tainted = False

    def feed_key(self, key: str) -> None:
        if key == "backspace":
            if self._buf:
                self._buf.pop()
        elif key in RESET_KEYS:
            self.reset()

    def feed_char(self, ch: str) -> str | None:
        """Returns the committed candidate text when a sentence ends (for tests/UI)."""
        if not self._enabled():
            self.reset()
            return None
        if not self._buf:
            if ch.isspace():
                return None
            self._tainted = self._is_password()
        if ch in SENTENCE_END:
            if ch != "\n":
                self._buf.append(ch)
            text = "".join(self._buf)
            tainted = self._tainted
            self.reset()
            return None if tainted else self._commit(text)
        self._buf.append(ch)
        if len(self._buf) > MAX_BUFFER:
            self.reset()
        return None

    def feed_text(self, chunk: str) -> list[str]:
        out = []
        for ch in chunk:
            r = self.feed_char(ch)
            if r:
                out.append(r)
        return out

    def _commit(self, text: str) -> str | None:
        cand = normalize_candidate(text)
        if len(cand) < self._int("learning.min_length", 12):
            return None
        if not any(c.isalpha() for c in cand):
            return None
        try:
            self.store.bump_suggestion(cand)
        except Exception:
            log.exception("could not record suggestion")
            return None
        return cand

    def suggestions(self) -> list[dict]:
        return self.store.suggestions(min_count=self._int("learning.min_count", 3))
