"""Learned auto-skip (PRD FR-TRG-05).

When the user undoes the same phrase's autotext (Backspace right after it expanded) at least
`triggers.skip_threshold` times (default 3) within 7 days in the same program, that phrase's
autotext stops firing in that program. The tray says so and one click brings it back; so does
restore() (Settings > Autotext lists what is skipped).

The record is kept on this PC only (settings autoskip.log / autoskip.off, device settings):
which programs a person types in differs from PC to PC.
"""
from __future__ import annotations

import json
import threading
import time

WINDOW_S = 7 * 24 * 3600
LOG_KEY = "autoskip.log"
OFF_KEY = "autoskip.off"


def _app(exe: str) -> str:
    return (exe or "").strip().lower()


class AutoSkip:
    def __init__(self, store, clock=time.time):
        self.store = store
        self._clock = clock
        self._lock = threading.Lock()
        self._off: set[tuple[int, str]] = set()
        self.reload()

    def _load(self, key: str) -> list:
        try:
            data = json.loads(self.store.setting(key, "") or "[]")
        except ValueError:
            return []
        return data if isinstance(data, list) else []

    def reload(self) -> None:
        with self._lock:
            self._off = {(int(p), str(a)) for p, a in (x for x in self._load(OFF_KEY)
                                                       if isinstance(x, list) and len(x) == 2)}

    @property
    def enabled(self) -> bool:
        return self.store.setting("triggers.autoskip", "1") == "1"

    @property
    def threshold(self) -> int:
        try:
            return max(1, int(self.store.setting("triggers.skip_threshold", "3") or 3))
        except ValueError:
            return 3

    def blocked(self, phrase_id: int, exe: str) -> bool:
        return (int(phrase_id), _app(exe)) in self._off

    def skipped(self) -> list[tuple[int, str]]:
        return sorted(self._off)

    def record_undo(self, phrase_id: int, exe: str) -> bool:
        """Count one undo; True when this one switched the autotext off for that program."""
        if not self.enabled or not _app(exe):
            return False
        now, key = self._clock(), (int(phrase_id), _app(exe))
        with self._lock:
            log = [e for e in self._load(LOG_KEY)
                   if isinstance(e, list) and len(e) == 3 and now - float(e[2]) <= WINDOW_S]
            log.append([key[0], key[1], now])
            hits = sum(1 for p, a, _ in log if (int(p), a) == key)
            turned_off = hits >= self.threshold and key not in self._off
            if turned_off:
                self._off.add(key)
                log = [e for e in log if (int(e[0]), e[1]) != key]
                self.store.set_setting(OFF_KEY, json.dumps(sorted([list(k) for k in self._off])))
            self.store.set_setting(LOG_KEY, json.dumps(log[-500:]))
        return turned_off

    def restore(self, phrase_id: int, exe: str) -> None:
        key = (int(phrase_id), _app(exe))
        with self._lock:
            self._off.discard(key)
            self.store.set_setting(OFF_KEY, json.dumps(sorted([list(k) for k in self._off])))
