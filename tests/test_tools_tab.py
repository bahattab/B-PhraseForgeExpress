"""Main window Tools tab = the tray menu's items, grouped (and run through the tray).

Also: the Last Used folder refreshes when a phrase is used (usage recorded on another thread).
"""
import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from phraseforge.db import Store
from phraseforge.models import Phrase

TRAY_KEYS = ["open_main", "new_phrase_from_clipboard", "edit_last_phrase", "popup", "clipboard_history",
             "ocr", "ocr_language", "file_search", "prompt_tower", "prompt_optimizer",
             "onenote_send_clipboard", "onenote_clip", "quick_note", "new_sticky_note", "open_sticky_notes",
             "statistics", "settings", "about", "language", "app_enabled", "pause", "quit"]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def _tray():
    from phraseforge.ui.tray import Tray
    t = Tray()
    fired = []
    for sig in ("open_main", "new_phrase_from_clipboard", "edit_last_phrase", "show_popup", "clipboard_history",
                "ocr_to_clipboard", "file_search", "prompt_tower", "prompt_optimizer", "onenote_send_clipboard",
                "onenote_clip", "quick_note", "new_sticky_note", "open_sticky_notes", "show_statistics",
                "settings", "quit"):
        getattr(t, sig).connect(lambda *_a, s=sig: fired.append(s))
    t.toggle_pause.connect(lambda on: fired.append(("pause", on)))
    t.language.connect(lambda c: fired.append(("language", c)))
    t.app_enabled.connect(lambda exe, on: fired.append(("app_enabled", exe, on)))
    t.ocr_language.connect(lambda l: fired.append(("ocr_language", l)))
    return t, fired


def test_tray_registers_every_item(app):
    t, _ = _tray()
    assert list(t.items) == TRAY_KEYS


def test_tools_tab_has_every_tray_item_grouped(app, store):
    from phraseforge.ui.main_window import MainWindow
    t, _ = _tray()
    w = MainWindow(store, on_command=lambda c: None, tray=t)
    keys = [k for _g, cols in w.TOOLS_TAB for col in cols for k, _l, _i in col]
    assert [k for k in keys if k != "ocr_file"] == TRAY_KEYS          # same items, same order
    groups = list(w.ribbon.tabs["tools"].groups)
    assert groups == ["PhraseForge", "Tools", "OneNote and notes", "Program", "Options"]
    # the two old large OneNote buttons are gone: everything is a small button now
    assert all(b.objectName() == "RibbonSmall" for b in w.tool_buttons.values())
    w.close()


def test_tools_buttons_trigger_the_tray_items(app, store):
    from phraseforge.ui.main_window import MainWindow
    t, fired = _tray()
    sent = []
    w = MainWindow(store, on_command=sent.append, tray=t)
    plain = ["open_main", "new_phrase_from_clipboard", "edit_last_phrase", "popup", "clipboard_history", "ocr",
             "file_search", "prompt_tower", "prompt_optimizer", "onenote_send_clipboard", "onenote_clip",
             "quick_note", "new_sticky_note", "open_sticky_notes", "statistics", "settings", "quit"]
    for k in plain:
        assert w.tool_buttons[k].isEnabled() or k in ("statistics", "onenote_send_clipboard", "onenote_clip"), k
        w.run_tool(k)
    assert fired == ["open_main", "new_phrase_from_clipboard", "edit_last_phrase", "show_popup",
                     "clipboard_history", "ocr_to_clipboard", "file_search", "prompt_tower", "prompt_optimizer",
                     "onenote_send_clipboard", "onenote_clip", "quick_note", "new_sticky_note",
                     "open_sticky_notes", "show_statistics", "settings", "quit"]
    w.run_tool("ocr_file")                       # not in the tray: the app command
    assert sent == ["ocr_file"]
    w.close()


def test_buttons_follow_tray_visibility(app, store):
    """OneNote and Statistics items are only usable once the app wired them (like the tray)."""
    from phraseforge.ui.main_window import MainWindow
    from phraseforge.ui.tray import Tray
    t = Tray()                                   # nothing connected
    w = MainWindow(store, tray=t)
    for k in ("onenote_send_clipboard", "onenote_clip", "statistics"):
        assert not w.tool_buttons[k].isEnabled(), k
    t.onenote_clip.connect(lambda: None)
    w.refresh_tools()
    assert w.tool_buttons["onenote_clip"].isEnabled()
    w.close()


def test_pause_and_enabled_in_toggles(app, store):
    from phraseforge.ui.main_window import MainWindow
    t, fired = _tray()
    t.last_app_provider = lambda: ("claude.exe", "Claude")
    t.excluded_provider = lambda: set()
    w = MainWindow(store, tray=t)
    w.refresh_tools()
    b = w.tool_buttons["app_enabled"]
    assert b.isEnabled() and b.text() == 'Enabled in "Claude"' and b.isChecked()
    b.click()
    assert ("app_enabled", "claude.exe", False) in fired and not b.isChecked()
    p = w.tool_buttons["pause"]
    p.click()
    assert ("pause", True) in fired and p.isChecked() and t.pause_action.isChecked()
    t.pause_action.setChecked(False)            # changed from the tray: the button follows
    assert not p.isChecked()
    # without a last program the item is unavailable, as in the tray
    t.last_app_provider = lambda: None
    w.refresh_tools()
    assert not w.tool_buttons["app_enabled"].isEnabled()
    w.close()


def test_menus_are_the_tray_submenus(app, store):
    from phraseforge.ui.main_window import MainWindow
    t, fired = _tray()
    t.ocr_languages_provider = lambda: (["Auto", "ar", "en-US"], "Auto")
    t.language_provider = lambda: "ar"
    w = MainWindow(store, tray=t)
    w.refresh_tools()
    ocr_b, lang_b = w.tool_buttons["ocr_language"], w.tool_buttons["language"]
    assert ocr_b.menu() is t.ocr_lang_menu and lang_b.menu() is t.language_menu
    assert ocr_b.isEnabled()
    t.ocr_lang_menu.aboutToShow.emit()           # opened from the ribbon: filled like the tray
    acts = t.ocr_lang_menu.actions()
    assert [a.text() for a in acts] == ["Auto", "ar", "en-US"] and acts[0].isChecked()
    acts[1].trigger()
    t.language_menu.aboutToShow.emit()
    assert [a.isChecked() for a in t.language_menu.actions()] == [False, True]
    t.language_menu.actions()[0].trigger()
    assert ("ocr_language", "ar") in fired and ("language", "en") in fired
    w.close()


def test_last_used_refreshes_when_a_phrase_is_used(app, store):
    """Reported: Last Used did not update. Usage was recorded without telling the window."""
    from phraseforge.ui.main_window import MainWindow
    p = store.add_phrase(Phrase("Greeting", "hello"))
    w = MainWindow(store)
    w._refresh_timer.setInterval(0)

    def last_used_children():
        for i in range(w.tree.topLevelItemCount()):
            it = w.tree.topLevelItem(i)
            if it.data(0, 0x0100) == "last_used" or it.text(0) == "Last Used":
                return [it.child(j).text(0) for j in range(it.childCount())]
        return None
    assert last_used_children() == []
    th = threading.Thread(target=lambda: store.record_use(p.id, app="notepad.exe", chars=5))
    th.start()
    th.join()                                     # recorded on another thread, like the expansion worker
    for _ in range(50):
        app.processEvents()
        if last_used_children():
            break
    assert last_used_children() == ["Greeting"]
    w.close()
