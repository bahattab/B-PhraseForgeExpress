"""PhraseExpress-style tray icon clicks (from its published docs)."""
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")


@pytest.fixture
def store():
    from phraseforge.db import Store
    s = Store(":memory:")
    yield s
    s.close()


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_tray_clicks_follow_phraseexpress(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QSystemTrayIcon

    from phraseforge.ui.tray import Tray
    t = Tray()
    hits = []
    t.open_main.connect(lambda: hits.append("main"))
    t.show_popup.connect(lambda: hits.append("popup"))
    t.settings.connect(lambda: hits.append("settings"))
    t.toggle_pause.connect(lambda on: hits.append(("pause", on)))
    none = Qt.KeyboardModifier.NoModifier
    trig, dbl = QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick

    assert t.handle_click(trig, none) == "main"           # default keeps the old behaviour
    t.left_click = "popup"
    assert t.handle_click(trig, none) == "popup"
    assert t.handle_click(dbl, none) == "main"
    assert t.handle_click(trig, Qt.KeyboardModifier.ControlModifier) == "pause"
    assert t.handle_click(trig, Qt.KeyboardModifier.ControlModifier) == "pause"
    assert t.handle_click(trig, Qt.KeyboardModifier.AltModifier) == "settings"
    assert t.handle_click(QSystemTrayIcon.Context, none) == ""
    assert hits == ["main", "popup", "main", ("pause", True), ("pause", False), "settings"]


def test_app_applies_left_click_setting(qapp, store):
    from phraseforge.app import PhraseForgeApp
    from phraseforge.ui.settings_schema import SCHEMA
    assert SCHEMA["tray.left_click_popup"] == "0"
    fake = SimpleNamespace(store=store, tray=SimpleNamespace(left_click="main"))
    PhraseForgeApp._apply_tray_click(fake)
    assert fake.tray.left_click == "main"
    store.set_setting("tray.left_click_popup", "1")
    PhraseForgeApp._apply_tray_click(fake)
    assert fake.tray.left_click == "popup"
