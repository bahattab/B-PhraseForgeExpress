"""Customizable quick toolbar: show/hide any Tools command, move left/right, persist the order."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from phraseforge.db import Store
from phraseforge.ui import quick_toolbar as qtb


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def _bar_keys(w):
    return [w._quick_key_of(a) for a in w.quickbar.actions() if w._quick_key_of(a)]


def test_default_bar_is_unchanged(app, store):
    from phraseforge.ui.main_window import MainWindow
    w = MainWindow(store)
    assert _bar_keys(w) == qtb.DEFAULT
    w.close()


def test_every_tools_command_can_be_added(app, store):
    from phraseforge.ui.main_window import MainWindow
    sent = []
    w = MainWindow(store, on_command=sent.append)
    catalog = [k for k, _, _ in w.quick_catalog()]
    for key in ("ocr", "prompt_optimizer", "quick_note", "settings", "pause", "language"):
        assert key in catalog
    w.show_on_quickbar("ocr")
    w.show_on_quickbar("prompt_optimizer")
    assert _bar_keys(w)[-2:] == ["ocr", "prompt_optimizer"]
    w._quick_action("ocr").trigger()                    # runs like the Tools button (no tray: app command)
    assert sent == ["ocr"]
    w.show_on_quickbar("back", False)
    assert "back" not in _bar_keys(w)
    w.close()
    w2 = MainWindow(store)                              # kept for the next start
    assert _bar_keys(w2) == ["forward", "sync", "new_folder", "new_phrase", "columns", "ocr", "prompt_optimizer"]
    w2.close()


def test_move_left_and_right(app, store):
    from phraseforge.ui.main_window import MainWindow
    w = MainWindow(store)
    w.move_on_quickbar("sync", "left")
    assert _bar_keys(w)[:3] == ["back", "sync", "forward"]
    w.move_on_quickbar("back", "left")                 # already first: unchanged
    assert _bar_keys(w)[0] == "back"
    w.move_on_quickbar("sync", "right")
    assert _bar_keys(w)[:3] == ["back", "forward", "sync"]
    w.setLayoutDirection(Qt.RightToLeft)                # Arabic: the first button is on the right
    w.move_on_quickbar("sync", "left")
    assert _bar_keys(w)[:4] == ["back", "forward", "new_folder", "sync"]
    w.reset_quickbar()
    assert _bar_keys(w) == qtb.DEFAULT
    w.close()


def test_menu_ticks_show_and_hide(app, store):
    from phraseforge.ui.main_window import MainWindow
    w = MainWindow(store)
    w._fill_quick_menu()
    acts = {a.text(): a for a in w.quick_menu.actions() if a.isCheckable()}
    acts["Statistics"].setChecked(True)
    assert _bar_keys(w)[-1] == "statistics"
    w._fill_quick_menu()
    acts = {a.text(): a for a in w.quick_menu.actions() if a.isCheckable()}
    assert acts["Statistics"].isChecked()
    acts["Statistics"].setChecked(False)
    assert "statistics" not in _bar_keys(w)
    w.close()


def test_navigation_works_when_back_is_hidden(app, store):
    from phraseforge.ui.main_window import MainWindow
    store.set_setting(qtb.SETTING, '["sync"]')
    w = MainWindow(store)
    assert _bar_keys(w) == ["sync"]
    w._update_nav_actions() if hasattr(w, "_update_nav_actions") else None
    assert w.act_back is not None and w.act_forward is not None
    w.close()


def test_bad_setting_falls_back_to_default(store):
    store.set_setting(qtb.SETTING, "not json")
    assert qtb.load(store, set(qtb.DEFAULT)) == qtb.DEFAULT
    store.set_setting(qtb.SETTING, '["sync", "sync", "gone", 5]')
    assert qtb.load(store, set(qtb.DEFAULT)) == ["sync"]


def test_dialog_add_remove_move(app):
    catalog = list(qtb.BUILTIN) + [("ocr", "OCR to clipboard", "m_ocr")]
    d = qtb.QuickToolbarDialog(catalog, ["back", "sync"])
    d.available.setCurrentRow([d.available.item(i).data(Qt.UserRole)
                               for i in range(d.available.count())].index("ocr"))
    d.add()
    assert d.keys() == ["back", "sync", "ocr"]
    d.move("left")                                      # the added item stays selected
    assert d.keys() == ["back", "ocr", "sync"]
    d.shown.setCurrentRow(0)
    d.remove()
    assert d.keys() == ["ocr", "sync"]
    d.reset_btn.click()
    assert d.keys() == qtb.DEFAULT
