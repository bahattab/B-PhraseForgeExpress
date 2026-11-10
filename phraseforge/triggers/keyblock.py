"""Keyboard blocking during output (PRD FR-TRG-06).

While PhraseForge types a phrase, keys the user presses would land in the middle of it.
KeyBlocker holds them back and, when the output is finished, types them in the order they
were pressed (Settings > Text Insertion: "Keys pressed while a phrase is typed": replay,
discard, or let through).

Only physical keys are held: keys sent by other programs pass. A key-up is held only when
its key-down was, so a key the user was already holding when output started is released
normally. Blocking ends by itself after MAX_BLOCK_S, so a stuck output never takes the
keyboard away.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)

MODES = ("replay", "discard", "off")
MAX_BLOCK_S = 30.0          # longest time keys are held for one output
MAX_HELD = 512              # key events kept for replay; more are dropped


class KeyBlocker:
    def __init__(self, replay: Callable[[list[tuple[int, bool]]], None],
                 set_native: Callable[[bool], None] | None = None,
                 clock: Callable[[], float] = time.monotonic, start_worker: bool = True):
        self._replay = replay                   # sends [(vk, down), ...] as injected keys
        self.set_native = set_native            # turns the native hook's own blocking on/off
        self._clock = clock
        self.mode = "replay"
        self._lock = threading.Lock()
        self._active = False
        self._since = 0.0
        self._queue: list[tuple[int, bool]] = []
        self._held_down: set[int] = set()       # keys whose down was held: hold their up too
        self._native_lock = threading.Lock()   # orders the on/off calls to the native hook
        self._replaying = threading.Lock()     # held while keys are sent again
        self._wake = threading.Event()
        self.dropped = 0
        if start_worker:
            threading.Thread(target=self._worker, name="pf-key-replay", daemon=True).start()

    # ---------------------------------------------------------------- output start / end
    def begin(self) -> None:
        if self.mode == "off":
            return
        with self._replaying:                  # a replay still running finishes before this output
            pass
        with self._native_lock:
            with self._lock:
                self._active = True
                self._since = self._clock()
            self._native(True)

    def end(self) -> None:
        with self._lock:
            self._active = False
        self._wake.set()

    def _blocking(self) -> bool:
        """Called with the lock held. Also True while held keys wait to be replayed, so a
        key pressed now cannot overtake them."""
        if self._active and self._clock() - self._since > MAX_BLOCK_S:
            log.warning("output took longer than %.0f s: keys are no longer held", MAX_BLOCK_S)
            self._active = False
            self._wake.set()
        return self._active or bool(self._queue)

    # ---------------------------------------------------------------- hook side
    def feed(self, vk: int, down: bool, injected: bool = False, blocked: bool = False,
             late: bool = False) -> bool:
        """One key event from the hook. True = swallow it (it was held).
        blocked: the native hook already swallowed it. late: it already reached the program."""
        if self.mode == "off" and not blocked:
            return False
        if injected or late:
            return False
        with self._lock:
            if down:
                if not (blocked or self._blocking()):
                    self._held_down.discard(vk)     # its up now belongs to this passed down
                    return False
                self._held_down.add(vk)
            elif vk in self._held_down:
                self._held_down.discard(vk)
            elif not blocked:
                return False
            if self.mode == "replay":
                if len(self._queue) < MAX_HELD:
                    self._queue.append((vk, down))
                else:
                    self.dropped += 1
        self._wake.set()
        return True

    # ---------------------------------------------------------------- replay
    def _native(self, on: bool) -> None:
        """Called with _native_lock held. Always sent, so a restarted hook gets it again."""
        if self.set_native is None:
            return
        try:
            self.set_native(on)
        except Exception:      # noqa: BLE001 - the Python side still holds keys
            log.exception("native key blocking not changed")

    def flush(self) -> bool:
        """Replay what is held once output has ended. Returns True when nothing is left."""
        with self._replaying:
            with self._lock:
                if self._active and self._clock() - self._since <= MAX_BLOCK_S:
                    return False
                self._active = False
                batch, self._queue = self._queue, []
            if batch:
                try:
                    self._replay(batch)
                except Exception:  # noqa: BLE001
                    log.exception("held keys could not be replayed")
        with self._native_lock:
            with self._lock:
                done = not self._queue and not self._active
            if done:                            # rechecked: a new output may have begun meanwhile
                self._native(False)
        return done

    def _worker(self) -> None:
        while True:
            self._wake.wait(0.5)
            self._wake.clear()
            while not self.flush():
                if self._active:
                    break
