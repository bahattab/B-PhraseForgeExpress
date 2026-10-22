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


# ---------------------------------------------------------------- AutoComplete words
WORD_CHARS = re.compile(r"[\w'’-]")


class WordLearner:
    """Learns the words the user types and suggests completions (Settings > AutoComplete).

    autocomplete.suggest_words      on/off
    autocomplete.learn_corrections  when off, a word the user corrected with Backspace is not learned
    autocomplete.filter_letter / filter_upper / filter_number / filter_special
        a suggestion must begin with one of the checked kinds of character
        (none checked = any word)
    Words are kept in memory and, when `path` is given, saved as JSON there.
    """

    MIN_WORD = 4

    def __init__(self, store, path=None):
        self.store = store
        self.path = path
        self.counts: dict[str, int] = {}
        self._word: list[str] = []
        self._corrected = False
        self._dirty = 0
        self.last_was_correction = False   # the word just learned had been corrected (sound cue)
        self._load()

    # ------------------------------------------------------------ persistence
    def _load(self) -> None:
        if not self.path:
            return
        try:
            import json
            from pathlib import Path
            p = Path(self.path)
            if p.is_file():
                self.counts = {str(k): int(v) for k, v in json.loads(p.read_text(encoding="utf-8")).items()}
        except Exception:
            log.exception("could not read learned words")

    def save(self) -> None:
        if not self.path or not self._dirty:
            return
        try:
            import json
            from pathlib import Path
            Path(self.path).write_text(json.dumps(self.counts, ensure_ascii=False), encoding="utf-8")
            self._dirty = 0
        except Exception:
            log.exception("could not save learned words")

    # ------------------------------------------------------------ settings
    def enabled(self) -> bool:
        return self.store.setting("autocomplete.suggest_words", "0") == "1"

    def allowed(self, word: str) -> bool:
        if not word:
            return False
        c = word[0]
        rules = [("autocomplete.filter_letter", "1", c.isalpha()),
                 ("autocomplete.filter_upper", "1", c.isupper()),
                 ("autocomplete.filter_number", "0", c.isdigit()),
                 ("autocomplete.filter_special", "0", not c.isalnum())]
        active = [ok for key, default, ok in rules if self.store.setting(key, default) == "1"]
        return not active or any(active)

    # ------------------------------------------------------------ input
    @property
    def current(self) -> str:
        return "".join(self._word)

    def reset(self) -> None:
        self._word.clear()
        self._corrected = False

    def feed_key(self, key: str) -> None:
        if key == "backspace":
            if self._word:
                self._word.pop()
                self._corrected = True
        else:
            self.reset()

    def feed_char(self, ch: str) -> str | None:
        """Returns the word that was just completed and learned (for tests)."""
        if WORD_CHARS.match(ch):
            self._word.append(ch)
            return None
        word, corrected = self.current, self._corrected
        self.reset()
        self.last_was_correction = False
        if not self.enabled() or len(word) < self.MIN_WORD or not self.allowed(word):
            return None
        if corrected and self.store.setting("autocomplete.learn_corrections", "0") != "1":
            return None
        self.counts[word] = self.counts.get(word, 0) + 1
        self.last_was_correction = corrected
        self._dirty += 1
        if self._dirty >= 20:
            self.save()
        return word

    def suggest(self, prefix: str, min_chars: int = 3) -> str | None:
        """Most used learned word that starts with prefix and is longer than it."""
        if not self.enabled() or len(prefix) < max(1, min_chars):
            return None
        low = prefix.casefold()
        best = None
        for w, n in self.counts.items():
            if len(w) > len(prefix) and w.casefold().startswith(low) and self.allowed(w):
                key = (n, -len(w))
                if best is None or key > best[0]:
                    best = (key, w)
        if best is None:
            return None
        word = best[1]
        return prefix + word[len(prefix):]       # keep what the user typed, complete the rest
