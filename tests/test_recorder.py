"""Macro recorder (PRD FR-REC-01, T-REC-01 without Windows): events -> macro text, the stop
hotkey, password fields, the replay macros it writes, and the recording controller."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from phraseforge.host import KeyAction, MouseAction, SleepAction, TextAction
from phraseforge.macros import MacroEngine
from phraseforge.recorder import (
    RecClick, RecKey, Recorder, RecWheel, chord_of, norm_chord, to_macro, wheel_delta,
)
from tests.fakehost import FakeHost

WIN, CTRL, SHIFT, ALT = 0x5B, 0x11, 0x10, 0x12


def k(t, vk, char=None, *mods):
    return RecKey(t, vk, char, frozenset(mods))


def typed(t0, text, step=0.05):
    return [k(t0 + i * step, ord(c.upper()) if c.isalpha() else 0x20, c) for i, c in enumerate(text)]


def test_win_r_notepad_enter_hello():
    """The PRD acceptance sequence: Win+R, notepad, Enter, type hello."""
    ev = [k(0, WIN, None, "win"), k(0.1, ord("R"), None, "win")] + typed(0.6, "notepad") + \
        [k(1.0, 0x0D)] + typed(2.5, "hello")
    assert to_macro(ev) == "{#key win+r}{#sleep 500}notepad{#key enter}{#sleep 1500}hello"


def test_text_runs_corrections_shortcuts_and_special_keys():
    ev = typed(0, "helo") + [k(0.2, 0x08)] + typed(0.21, "lo") + [
        k(0.3, ord("S"), None, "ctrl"), k(0.31, 0x25), k(0.32, 0x70), k(0.33, 0x0D, None, "shift"),
        k(0.34, 0x09), k(0.35, ord("Q"), "@", "ctrl", "alt"),          # AltGr+Q types @
        k(0.36, 0x31, "{"), k(0.37, 0x1B), k(0.38, 0x08)]               # Backspace with no text: a key
    assert to_macro(ev) == ("hello{#key ctrl+s}{#key left}{#key f1}{#key shift+enter}{#key tab}@{{"
                            "{#key escape}{#key backspace}")


def test_pauses_are_dropped_or_capped():
    ev = [k(0, 0x41, "a"), k(0.2, 0x42, "b"), k(1.0, 0x43, "c"), k(60, 0x44, "d")]
    assert to_macro(ev) == "ab{#sleep 800}c{#sleep 2000}d"
    assert to_macro(ev, min_pause_ms=1000, max_pause_ms=0) == "abc{#sleep 59000}d"


def test_mouse_clicks_double_clicks_relative_and_wheel():
    ev = [RecClick(0, "left", 100, 200, 10, 20), RecClick(0.2, "left", 102, 201, 12, 21),   # double
          RecClick(1.0, "right", 300, 400, 30, 40),
          RecWheel(1.1, -120), RecWheel(1.15, -120), RecWheel(1.2, 120)]
    assert to_macro(ev, min_pause_ms=5000) == ("{#mouse dblclick -x 100 -y 200}{#mouse rclick -x 300 -y 400}"
                                               "{#mouse wheel -delta -240}{#mouse wheel -delta 120}")
    assert to_macro(ev[:1], window_relative=True) == "{#mouse click -x 10 -y 20 -relative 1}"
    far = [RecClick(0, "left", 0, 0), RecClick(0.1, "left", 50, 0)]                       # too far apart
    assert to_macro(far, min_pause_ms=5000) == "{#mouse click -x 0 -y 0}{#mouse click -x 50 -y 0}"


def test_helpers():
    assert chord_of(k(0, 0x7B, None, "shift", "ctrl")) == "ctrl+shift+f12"
    assert norm_chord("Shift + Ctrl + F12") == "ctrl+shift+f12"
    assert wheel_delta(0x00780000) == 120 and wheel_delta(0xFF880000) == -120


# ---------------------------------------------------------------- recorder
def test_recorder_stops_on_the_hotkey_and_skips_password_fields():
    t = [0.0]

    def clock():
        t[0] += 0.05
        return t[0]
    pw = [False]
    stopped = []
    r = Recorder(clock=clock, password_check=lambda: pw[0])
    r.on_stop = lambda: stopped.append(True)
    assert r.key(0x41, "a", set()) is False and r.events == []        # not started: nothing
    r.start()
    r.key(0x41, "a", set())
    pw[0] = True
    r.key(0x42, "s", set())                                            # typed into a password box
    pw[0] = False
    r.click("left", 5, 6, (1, 2))
    r.wheel(-120)
    r.key(CTRL, None, {"ctrl"})
    r.key(SHIFT, None, {"ctrl", "shift"})
    assert r.key(0x7B, None, {"ctrl", "shift"}) is True                # the stop hotkey is swallowed
    assert stopped == [True] and not r.recording and r.skipped_passwords == 1
    assert r.macro() == "a{#mouse click -x 5 -y 6}{#mouse wheel -delta -120}"


def test_recorder_settings():
    vals = {"recorder.stop_hotkey": "alt+f9", "recorder.record_mouse": "0", "recorder.window_relative": "1"}
    r = Recorder(lambda key, d="": vals.get(key, d))
    r.start()
    r.click("left", 1, 1, (0, 0))
    assert r.events == [] and r.stop_chord == "alt+f9"
    assert r.key(0x78, None, {"alt"}) is True


# ---------------------------------------------------------------- replay
def test_the_written_macro_replays_as_actions():
    text = to_macro([k(0, WIN, None, "win"), k(0.1, ord("R"), None, "win")] + typed(1, "calc") +
                    [k(1.3, 0x0D), RecClick(3, "left", 7, 8, 1, 2), RecWheel(3.1, -120)], window_relative=True)
    acts = MacroEngine(FakeHost()).expand(text)
    assert acts == [KeyAction("win+r"), SleepAction(900), TextAction("calc"), KeyAction("enter"),
                    SleepAction(1700), MouseAction("click", 1, 2, relative=True), MouseAction("wheel", delta=-120)]


def test_mouse_macro_options():
    e = MacroEngine(FakeHost())
    assert e.expand("{#mouse wheel}") == [MouseAction("wheel", delta=-120)]
    assert "unknown mouse action" in e.expand_to_text("{#mouse spin}")
    assert "mouse:" in e.expand_to_text("{#mouse click -x abc}")


def test_output_moves_relative_clicks_to_the_window_and_scrolls():
    from phraseforge.platform.output import OutputExecutor
    calls = []

    class SI:
        def foreground_origin(self):
            return 100, 50

        def mouse_click(self, x, y, button="left", double=False):
            calls.append(("click", x, y, button, double))

        def mouse_move(self, x, y):
            calls.append(("move", x, y))

        def mouse_wheel(self, d):
            calls.append(("wheel", d))

        def __getattr__(self, name):
            return lambda *a, **k: None
    from tests.test_output_services import FakeCB
    ex = OutputExecutor(lambda k, d="": d)
    ex.sendinput, ex.clipboard = SI(), FakeCB([])
    ex.execute([MouseAction("click", 5, 6, relative=True), MouseAction("wheel", 1, 2, delta=240),
                MouseAction("dblclick", 9, 9)])
    assert calls == [("click", 105, 56, "left", False), ("move", 1, 2), ("wheel", 240),
                     ("click", 9, 9, "left", True)]


# ---------------------------------------------------------------- controller
@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class FakeSession:
    def __init__(self, recorder):
        self.recorder, self.started, self.stopped = recorder, False, False

    def start(self):
        self.recorder.start()
        self.started = True

    def stop(self):
        self.stopped = True


class FakeTriggers:
    paused = False


def test_controller_pauses_triggers_and_returns_the_macro(app):
    from phraseforge.db import Store
    from phraseforge.ui.recording_bar import RecordingController
    done, trig = [], FakeTriggers()
    sessions = []

    def factory(r):
        sessions.append(FakeSession(r))
        return sessions[-1]
    ctl = RecordingController(Store(":memory:"), done.append, session_factory=factory, triggers=trig)
    ctl.start()
    assert ctl.active and trig.paused and ctl.bar.isVisible() and sessions[0].started
    ctl.recorder.key(0x48, "h", set())
    ctl.recorder.key(0x49, "i", set())
    ctl.bar.refresh()
    assert "2 steps" in ctl.bar.label.text() and "ctrl+shift+f12" in ctl.bar.label.text()
    ctl.bar.stop_button.click()                                         # Stop button
    assert done == ["hi"] and not ctl.active and not trig.paused and sessions[0].stopped
    ctl.start()
    ctl.recorder.key(0x7B, None, {"ctrl", "shift"})                    # the hotkey ends it too
    assert done == ["hi", ""] and not ctl.active


def test_record_macro_button(app):
    from phraseforge.db import Store
    from phraseforge.ui.main_window import MainWindow
    cmds = []
    w = MainWindow(Store(":memory:"), on_command=cmds.append)
    w.ribbon.tabs["phrases"].groups["Insert"].buttons["Record macro"].click()
    assert cmds == ["record_macro"]
