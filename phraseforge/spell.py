"""Spell checking for the phrase editor (PRD FR-EDT-01, gap G-20).

Hunspell dictionaries are read with spylls (pure Python, MPL-2.0), so nothing
native has to be built for Windows. The dictionaries are not shipped with
PhraseForge: their licenses differ (SCOWL for US English, LGPL, GPL, the
Ayaspell tri-license for Arabic ...), so the user downloads each one from the
LibreOffice dictionaries repository into <data>/dictionaries/.

One dictionary is used per script, so Arabic and English can be mixed in one
phrase: words with Arabic letters go to setting spell.arabic, all other words
to spell.latin. A dictionary loads in a background thread (the Arabic one takes
about 13 s); until it is ready its words count as correct.

Settings:
  spell.enabled     "1" (default) / "0"
  spell.latin       dictionary code for Latin-script words (default en_US, "" = off)
  spell.arabic      dictionary code for Arabic-script words (default ar, "" = off)
  spell.user_words  JSON list of words added with "Add to dictionary"
"""
from __future__ import annotations

import json
import logging
import re
import threading
import weakref
from pathlib import Path
from typing import Callable

from phraseforge import paths

log = logging.getLogger(__name__)

SOURCE = "https://raw.githubusercontent.com/LibreOffice/dictionaries/master/"

# code -> (name, path of <name>.aff/.dic in the LibreOffice repository, script, license note)
DICTIONARIES: dict[str, tuple[str, str, str, str]] = {
    "en_US": ("English (US)", "en/en_US", "latin", "SCOWL (permissive)"),
    "en_GB": ("English (UK)", "en/en_GB", "latin", "LGPL"),
    "de_DE": ("German", "de/de_DE_frami", "latin", "GPL 2 or 3"),
    "es_ES": ("Spanish", "es/es_ES", "latin", "see README"),
    "it_IT": ("Italian", "it_IT/it_IT", "latin", "see README"),
    "pt_BR": ("Portuguese (Brazil)", "pt_BR/pt_BR", "latin", "see README"),
    "tr_TR": ("Turkish", "tr_TR/tr_TR", "latin", "see README"),
    "ar": ("Arabic", "ar/ar", "arabic", "Ayaspell (GPL/LGPL/MPL)"),
    "fa_IR": ("Persian", "fa_IR/fa-IR", "arabic", "see README"),
}

WORD_RE = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")
# spans never checked: URLs, e-mail addresses, file paths, words joined to digits
SKIP_RE = re.compile(r"(?:https?://|www\.)\S+|\S+@\S+\.\S+|[A-Za-z]:\\\S*|\S*\d\S*")
_ARABIC = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_HARAKAT = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")   # marks and tatweel


def dictionaries_dir() -> Path:
    p = paths.data_dir() / "dictionaries"
    p.mkdir(parents=True, exist_ok=True)
    return p


def installed(code: str) -> bool:
    if code not in DICTIONARIES:          # settings can arrive by sync: never build a path from them
        return False
    base = dictionaries_dir() / code
    return base.with_suffix(".aff").is_file() and base.with_suffix(".dic").is_file()


def download(code: str, client_factory: Callable | None = None) -> Path:
    """Fetch <code>.aff and .dic from the LibreOffice repository. Returns the base path.
    Files are written under a temporary name first, so a failed download leaves nothing."""
    if code not in DICTIONARIES:
        raise ValueError(f"unknown dictionary {code!r}")
    import httpx
    from phraseforge.net import client_kwargs
    repo_path = DICTIONARIES[code][1]
    base = dictionaries_dir() / code
    make = client_factory or (lambda: httpx.Client(timeout=120, follow_redirects=True, **client_kwargs()))
    parts = []
    with make() as c:
        for ext in (".aff", ".dic"):
            r = c.get(SOURCE + repo_path + ext)
            r.raise_for_status()
            if not r.content:
                raise ValueError(f"empty {ext} file for {code}")
            parts.append((base.with_suffix(ext), r.content))
    for target, data in parts:
        tmp = target.with_suffix(target.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(target)
    return base


def script_of(word: str) -> str:
    return "arabic" if _ARABIC.search(word) else "latin"


def normalize(word: str) -> str:
    """What is looked up: Arabic marks and tatweel removed, curly apostrophe made straight."""
    return _HARAKAT.sub("", word).replace("’", "'")


def words(text: str):
    """(start, length, word) for each word worth checking in text."""
    skip = [(m.start(), m.end()) for m in SKIP_RE.finditer(text)]
    for m in WORD_RE.finditer(text):
        s, e = m.start(), m.end()
        if len(m.group()) < 2 or any(a <= s < b or a < e <= b for a, b in skip):
            continue
        yield s, e - s, m.group()


class SpellChecker:
    """Dictionaries per script, a lookup cache, and the user's own words."""

    def __init__(self, setting: Callable[[str, str], str], set_setting: Callable[[str, str], None] | None = None,
                 loader: Callable[[str], object] | None = None):
        self.setting = setting
        self.set_setting = set_setting
        self._loader = loader or self._load_files
        self._dicts: dict[str, object] = {}
        self._loading: set[str] = set()
        self._failed: dict[str, str] = {}
        self._suggested: dict[tuple[str, str], list[str]] = {}   # finished suggestion searches
        self._searching: set[tuple[str, str]] = set()            # searches running in the background
        self._cache: dict[tuple[str, str], bool] = {}
        self._ignored: set[str] = set()
        self._conf: tuple[bool, str, str, frozenset[str]] | None = None   # settings, read once
        self._lock = threading.Lock()
        self.listeners: list[Callable[[str], None]] = []   # called (from any thread) when a dictionary is ready

    # ---------------------------------------------------------------- settings
    def _settings(self) -> tuple[bool, str, str, frozenset[str]]:
        if self._conf is None:
            try:
                v = json.loads(self.setting("spell.user_words", "[]") or "[]")
            except ValueError:
                v = []
            user = frozenset(normalize(str(w)) for w in v) if isinstance(v, list) else frozenset()
            self._conf = (self.setting("spell.enabled", "1") == "1",
                          self.setting("spell.latin", "en_US") or "",
                          self.setting("spell.arabic", "ar") or "", user)
        return self._conf

    def refresh(self) -> None:
        """Re-read the spell.* settings (after Settings closes)."""
        self._conf = None

    def enabled(self) -> bool:
        return self._settings()[0]

    def code_for(self, script: str) -> str:
        """The dictionary for a script; "" (off) for a code that is not in DICTIONARIES."""
        s = self._settings()
        code = s[2] if script == "arabic" else s[1]
        return code if code in DICTIONARIES else ""

    def user_words(self) -> set[str]:
        return set(self._settings()[3])

    def add_word(self, word: str) -> None:
        w = normalize(word)
        if self.set_setting:
            self.set_setting("spell.user_words", json.dumps(sorted(self.user_words() | {w}), ensure_ascii=False))
        self._ignored.add(w)
        self.refresh()

    def ignore(self, word: str) -> None:
        """Ignore all: this word counts as correct until PhraseForge closes."""
        self._ignored.add(normalize(word))

    # ---------------------------------------------------------------- dictionaries
    @staticmethod
    def _load_files(code: str):
        from spylls.hunspell import Dictionary
        return Dictionary.from_files(str(dictionaries_dir() / code))

    def status(self, code: str) -> str:
        """"ready", "loading", "missing" or "error: ..."."""
        if code in self._dicts:
            return "ready"
        if code in self._failed:
            return "error: " + self._failed[code]
        if code in self._loading:
            return "loading"
        return "missing" if not installed(code) else "not loaded"

    def dictionary(self, code: str, wait: bool = False):
        """The loaded dictionary, or None while it loads (started in the background)."""
        if not code:
            return None
        d = self._dicts.get(code)
        if d is not None or code in self._failed:
            return d
        with self._lock:
            start = code not in self._loading and code not in self._dicts
            if start:
                if not installed(code) and self._loader is self._load_files:
                    return None
                self._loading.add(code)
        if start:
            t = threading.Thread(target=self._load, args=(code,), name=f"spell-{code}", daemon=True)
            t.start()
            if wait:
                t.join()
        return self._dicts.get(code)

    def _load(self, code: str) -> None:
        try:
            d = self._loader(code)
            with self._lock:
                self._dicts[code] = d
                self._cache = {k: v for k, v in self._cache.items() if k[0] != code}
        except Exception as e:          # bad or partial file: report it in Settings, check nothing
            log.exception("loading dictionary %s failed", code)
            self._failed[code] = str(e) or type(e).__name__
        finally:
            self._loading.discard(code)
        for fn in list(self.listeners):
            try:
                fn(code)
            except Exception:
                log.exception("spell listener failed")

    def reload(self, code: str) -> None:
        """Forget a dictionary (after a new download) so the next check loads it again."""
        with self._lock:
            self._dicts.pop(code, None)
            self._failed.pop(code, None)
            self._cache = {k: v for k, v in self._cache.items() if k[0] != code}
            self._suggested = {k: v for k, v in self._suggested.items() if k[0] != code}

    # ---------------------------------------------------------------- checking
    def is_misspelled(self, word: str) -> bool:
        if not self.enabled():
            return False
        w = normalize(word)
        if len(w) < 2 or w in self._ignored or w in self._settings()[3]:
            return False
        code = self.code_for(script_of(w))
        d = self.dictionary(code)
        if d is None:
            return False
        key = (code, w)
        hit = self._cache.get(key)
        if hit is None:
            hit = not (d.lookup(w) or (w[:1].isupper() and d.lookup(w.lower())))
            self._cache[key] = hit
        return hit

    MAX_SEARCHES = 3          # a slow word must not hold up suggestions for the next one

    def suggest_within(self, word: str, timeout: float = 0.4, limit: int = 6) -> list[str] | None:
        """Suggestions found within `timeout` seconds, or None if the search is still running.
        Hunspell suggestions can take seconds for a long Arabic word (30 s measured), so the
        search runs in a background thread and its result is kept: the menu opens at once,
        and the next right-click on the word shows what was found."""
        w = normalize(word)
        key = (self.code_for(script_of(w)), w)
        if key in self._suggested:
            return self._suggested[key]
        with self._lock:
            busy = key in self._searching or len(self._searching) >= self.MAX_SEARCHES
            if not busy:
                self._searching.add(key)
        if busy:          # already running, or too many slow ones: a later click shows the result
            return None
        done = threading.Event()

        def work():
            try:
                if len(self._suggested) > 500:
                    self._suggested.clear()
                self._suggested[key] = self.suggest(word, limit)
            except Exception:
                log.exception("spelling suggestions failed")
                self._suggested[key] = []
            finally:
                with self._lock:
                    self._searching.discard(key)
                done.set()
        threading.Thread(target=work, name="spell-suggest", daemon=True).start()
        done.wait(timeout)
        return self._suggested.get(key)

    def suggest(self, word: str, limit: int = 6) -> list[str]:
        w = normalize(word)
        d = self.dictionary(self.code_for(script_of(w)))
        if d is None:
            return []
        out = []
        for s in d.suggest(w):
            if s not in out:
                out.append(s)
            if len(out) >= limit:
                break
        return out


_CHECKERS: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def checker_for(store) -> SpellChecker:
    """One checker per store, so a dictionary loads once for every editor."""
    c = _CHECKERS.get(store)
    if c is None:
        c = SpellChecker(store.setting, getattr(store, "set_setting", None))
        _CHECKERS[store] = c
    return c
