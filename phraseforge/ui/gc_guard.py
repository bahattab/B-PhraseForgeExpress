"""Run Python's cyclic garbage collector on the GUI thread only (R160).

The collector normally runs in whichever thread allocates when a threshold is crossed.
PhraseForge has many background threads (the keyboard hook, the expansion worker, plugin
readers, the network filter, sync). A reference cycle that holds a Qt object could then be
freed on one of them, and Qt objects must be destroyed on the thread that owns them: that
crashes the program at random (an access violation, or Qt aborting). The test suite showed
exactly this. Here automatic collection is switched off and a timer on the GUI thread does
the same work, using the same thresholds.
"""
from __future__ import annotations

import gc

from PySide6.QtCore import QObject, QTimer

INTERVAL_MS = 500


class GuiGarbageCollector(QObject):
    def __init__(self, parent=None, interval_ms: int = INTERVAL_MS):
        super().__init__(parent)
        self.threshold = gc.get_threshold()
        self.timer = QTimer(self)
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self.check)

    def start(self) -> None:
        gc.disable()
        self.timer.start()

    def stop(self) -> None:
        self.timer.stop()
        gc.enable()

    def check(self) -> int | None:
        """Collect the oldest generation whose count passed its threshold, like Python would."""
        c0, c1, c2 = gc.get_count()
        t0, t1, t2 = self.threshold
        gen = 2 if c2 > t2 else 1 if c1 > t1 else 0 if c0 > t0 else None
        if gen is not None:
            gc.collect(gen)
        return gen


_guard: GuiGarbageCollector | None = None


def install(app) -> GuiGarbageCollector:
    """Call once, on the GUI thread, after the QApplication exists."""
    global _guard
    if _guard is None:
        _guard = GuiGarbageCollector(app)
        _guard.start()
    return _guard
