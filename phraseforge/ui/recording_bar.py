"""The small always-on-top bar shown while the macro recorder runs."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from phraseforge.ui.i18n import tr


class RecordingBar(QWidget):
    stop_clicked = Signal()

    def __init__(self, recorder, parent=None):
        super().__init__(parent, Qt.Tool | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.recorder = recorder
        self.setObjectName("RecordingBar")
        self.setStyleSheet("#RecordingBar { background: #b3261e; } QLabel { color: white; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 4, 4)
        self.label = QLabel()
        lay.addWidget(self.label)
        self.stop_button = QPushButton(tr("Stop"))
        self.stop_button.clicked.connect(self.stop_clicked.emit)
        lay.addWidget(self.stop_button)
        self._started = time.monotonic()
        self._timer = QTimer(self, interval=500)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh()

    def refresh(self) -> None:
        secs = int(time.monotonic() - self._started)
        self.label.setText("● " + tr("Recording {time} · {n} steps · stop with {key}").format(
            time=f"{secs // 60}:{secs % 60:02d}", n=len(self.recorder.events), key=self.recorder.stop_chord))
        self.label.setToolTip(tr("Keys typed in password fields are left out when the program says "
                                 "the field is one; to be sure, stop recording before you type a password."))

    def place(self) -> None:
        """Top centre of the primary screen."""
        scr = self.screen().availableGeometry() if self.screen() else None
        self.adjustSize()
        if scr is not None:
            self.move(scr.center().x() - self.width() // 2, scr.top() + 8)


class RecordingController:
    """Start → bar shown, triggers paused, hooks on; the stop hotkey or Stop → hooks off,
    on_done(macro text). session_factory(recorder) returns an object with start()/stop()
    (platform.record_hook.RecordSession on Windows; a fake in tests)."""

    def __init__(self, store, on_done, post=None, session_factory=None, triggers=None, password_check=None,
                 password_watch=None):
        from phraseforge.recorder import Recorder
        self.store = store
        self.on_done = on_done
        self.post = post or (lambda fn: fn())           # run on the UI thread (hook threads call stop)
        self.session_factory = session_factory
        self.triggers = triggers
        self.recorder = Recorder(store.setting, password_check=password_check)
        self.session = None
        self.bar: RecordingBar | None = None
        self._was_paused = False
        # watch(recorder) -> PasswordWatch: password fields that only UI Automation knows (R159)
        self.password_watch = password_watch
        self._watch = None

    @property
    def active(self) -> bool:
        return self.session is not None

    def start(self) -> None:
        if self.active:
            return
        factory = self.session_factory
        if factory is None:
            from phraseforge.platform.record_hook import RecordSession
            triggers = self.triggers

            def factory(rec):                        # keys from the app's native hook (R173)
                return RecordSession(rec, triggers=triggers)
        self.recorder.on_stop = lambda: self.post(self.finish)
        if self.triggers is not None:                   # typing while recording must not expand autotext
            self._was_paused = self.triggers.paused
            self.triggers.paused = True
        self.session = factory(self.recorder)
        self.bar = RecordingBar(self.recorder)
        self.bar.stop_clicked.connect(self.finish)
        self.bar.place()
        self.bar.show()
        try:
            self.session.start()
            self._watch = self._make_watch()
            if self._watch is not None:
                self._watch.start()
        except Exception:                            # noqa: BLE001 - no stuck bar left on screen (R158)
            try:
                self.session.stop()
            except Exception:                        # noqa: BLE001
                pass
            self._watch = None
            self.session = None
            if self.triggers is not None:
                self.triggers.paused = self._was_paused
            self.bar.close()
            self.bar = None
            raise

    def _make_watch(self):
        if self.password_watch is not None:
            return self.password_watch(self.recorder)
        import os
        if os.name != "nt" or self.session_factory is not None:   # tests' fake sessions: no COM
            return None
        from phraseforge.platform import caret
        from phraseforge.recorder import PasswordWatch
        return PasswordWatch(self.recorder, caret.focused_is_password)

    def finish(self) -> str | None:
        if not self.active:
            return None
        if self._watch is not None:                 # its last check runs before the macro is made
            try:
                self._watch.stop()
            except Exception:                       # noqa: BLE001
                pass
            self._watch = None
        text = self.recorder.stop() if self.recorder.recording else self.recorder.macro()
        try:
            self.session.stop()
        finally:
            self.session = None
            if self.triggers is not None:
                self.triggers.paused = self._was_paused
            if self.bar is not None:
                self.bar.close()
                self.bar = None
        self.recorder.events.clear()                # the keystrokes do not stay in memory (R50)
        self.on_done(text)
        return text
