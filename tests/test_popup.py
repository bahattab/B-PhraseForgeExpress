import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from phraseforge.db import Store
from phraseforge.models import Folder, Phrase, Trigger, TriggerKind


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def _rows(panel):
    from phraseforge.ui.popup import ROLE_ID, ROLE_KIND
    return [(panel.list.item(i).data(ROLE_KIND), panel.list.item(i).data(ROLE_ID), panel.list.item(i).text())
            for i in range(panel.list.count())]


def test_root_order_folders_specials_then_phrases(app, store):
    from phraseforge.ui.popup import CLIPBOARD, LAST_USED, ROLE_QK, ROLE_RIGHT, PhrasePopup
    store.add_folder(Folder("Zeta"))
    store.add_folder(Folder("Alpha"))
    p2 = store.add_phrase(Phrase("b phrase", "x"))
    p1 = store.add_phrase(Phrase("a phrase", "x", triggers=[Trigger(TriggerKind.AUTOTEXT, "ap#")]))
    pop = PhrasePopup(store)
    pop.refresh()
    rows = _rows(pop)
    assert [r[2] for r in rows] == ["Alpha", "Clipboard Cache", "Last Used", "Zeta", "a phrase", "b phrase"]
    assert rows[1][1] == CLIPBOARD and rows[2][1] == LAST_USED
    assert pop.visible_phrase_ids() == [p1.id, p2.id]
    # default menu.contents = Description - QuickKey
    assert pop.list.item(0).data(ROLE_QK) == "NumPad1" and pop.list.item(4).data(ROLE_RIGHT) == ""
    store.set_setting("menu.contents", "description_autotext")
    pop.show_at(10, 10, caret=None)
    assert pop.list.item(4).data(ROLE_RIGHT) == "[ap#]" and not pop.list.item(4).data(ROLE_QK)
    pop.hide_all(force=True)


def test_menu_sorting(app, store):
    from phraseforge.ui.popup import PhrasePopup
    a = store.add_phrase(Phrase("item 10", "x", sort=1))
    b = store.add_phrase(Phrase("item 2", "x", sort=3))
    c = store.add_phrase(Phrase("item 1", "x", sort=2))
    store.record_use(b.id)
    store.record_use(b.id)
    store.record_use(a.id)
    pop = PhrasePopup(store)
    store.set_setting("features.last_used_folder", "0")
    store.set_setting("clipboard_history.enabled", "0")
    for settings, want in (
            ({"menu.sort_by": "description", "menu.sort_method": "alpha", "menu.sort_order": "asc"}, [c, a, b]),
            ({"menu.sort_method": "numeric"}, [c, b, a]),
            ({"menu.sort_order": "desc"}, [a, b, c]),
            ({"menu.sort_by": "usage", "menu.sort_order": "desc"}, [b, a, c]),
            ({"menu.sort_enabled": "0"}, [a, c, b])):          # manual order (sort field)
        for k, v in settings.items():
            store.set_setting(k, v)
        pop._load_settings()
        pop.refresh()
        assert pop.visible_phrase_ids() == [p.id for p in want], settings


def test_hide_restricted_off_shows_all(app, store):
    from phraseforge.ui.popup import PhrasePopup
    w = store.add_folder(Folder("WordOnly", apps_include="winword.exe"))
    store.add_phrase(Phrase("in word", "x", folder_id=w.id))
    store.set_setting("menu.hide_restricted", "0")
    pop = PhrasePopup(store)
    pop.app_exe = "notepad.exe"
    pop.refresh()
    assert "WordOnly" in [r[2] for r in _rows(pop)]


def test_quickkeys_confirm_and_search_hotkeys(app, store):
    from phraseforge.ui.popup import PhrasePopup, quickkey_label
    store.set_setting("features.last_used_folder", "0")
    store.set_setting("clipboard_history.enabled", "0")
    a = store.add_phrase(Phrase("a", "x"))
    b = store.add_phrase(Phrase("b", "x"))
    pop = PhrasePopup(store)
    pop.refresh()
    chosen = []
    pop.phrase_chosen.connect(chosen.append)
    # default QuickKeys: keypad digits, no modifier
    assert pop.handle_key(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_2, Qt.KeypadModifier, "2"))
    assert chosen == [b.id]
    # confirm hotkey (default Tab) inserts the selected row
    pop.refresh()
    pop.list.setCurrentRow(0)
    assert pop.handle_key(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Tab, Qt.NoModifier))
    assert chosen == [b.id, a.id]
    # search hotkey (default F3) opens quick search
    pop.refresh()
    assert pop.handle_key(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_F3, Qt.NoModifier))
    assert pop.header.currentWidget() is pop.search_bar
    pop.end_search()
    # letters with Ctrl
    store.set_setting("menu.quickkey_keys", "letters")
    store.set_setting("menu.quickkey_modifier", "ctrl")
    pop._load_settings()
    pop.refresh()
    assert pop.handle_key(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_A, Qt.ControlModifier, "a"))
    assert chosen[-1] == a.id
    assert quickkey_label("fkeys", 11) == "F12" and quickkey_label("digits", 9) == ""


def test_quick_search_options(app, store):
    from phraseforge.ui.popup import PhrasePopup
    f = store.add_folder(Folder("Sub"))
    store.add_phrase(Phrase("Greeting", "hello there"))
    store.add_phrase(Phrase("Nested Greeting", "x", folder_id=f.id))
    pop = PhrasePopup(store)
    assert [r[2] for r in pop.search_entries("hello")] == []          # descriptions only
    store.set_setting("quicksearch.descriptions", "0")
    pop._load_settings()
    assert [r[2] for r in pop.search_entries("hello")] == ["Greeting"]
    store.set_setting("quicksearch.subfolders", "0")
    pop._load_settings()
    assert [r[2] for r in pop.search_entries("greeting")] == ["Greeting"]
    store.set_setting("quicksearch.match_case", "1")
    pop._load_settings()
    assert pop.search_entries("greeting") == []


def test_position_and_fallback(app, store):
    from PySide6.QtGui import QCursor
    from phraseforge.ui.popup import PhrasePopup
    pop = PhrasePopup(store)
    assert pop.placement(5, 6, (100, 200)) == ("caret", 100, 200)
    mode, x, y = pop.placement(5, 6, None)            # no caret -> fallback (mouse)
    c = QCursor.pos()
    assert (mode, x, y) == ("mouse", c.x(), c.y())
    store.set_setting("menu.position_fallback", "center")
    pop._load_settings()
    assert pop.placement(5, 6, None)[0] == "center"
    store.set_setting("menu.position", "mouse")
    pop._load_settings()
    assert pop.placement(5, 6, (100, 200))[0] == "mouse"


def test_appearance_preview_and_dim(app, store):
    import json
    from phraseforge.ui.popup import PhrasePopup
    p = store.add_phrase(Phrase("Sig", "Best regards"))
    store.set_setting("menu.appearance", json.dumps({"background": "#ffeecc", "description": "#112233",
                                                     "font": "Arial,12,-1,5,400,0,0,0,0,0"}))
    store.set_setting("ui.theme", "light")
    pop = PhrasePopup(store)
    pop.refresh()
    assert pop.colors["background"] == "#ffeecc" and pop.colors["description"] == "#112233"
    assert pop.menu_font.startswith("Arial,12")
    from phraseforge.ui import pe_style
    old_qss, old_font, old_style = app.styleSheet(), app.font(), app.style().name()
    try:
        pe_style.apply(app)                     # app-wide QSS must not override the menu font
        pop.apply_appearance()
        pop.refresh()
        app.processEvents()
        assert pop.list.font().family() == "Arial" and pop.list.font().pointSize() == 12
    finally:                                    # don't leak the app style into other tests
        app.setStyleSheet(old_qss)
        app.setFont(old_font)
        app.setStyle(old_style)
    item = next(pop.list.item(i) for i in range(pop.list.count()) if pop.list.item(i).text() == "Sig")
    assert item.toolTip() == "Best regards"
    store.set_setting("menu.show_preview", "0")
    store.set_setting("ui.theme", "dark")
    pop._load_settings()
    pop.refresh()
    item = next(pop.list.item(i) for i in range(pop.list.count()) if pop.list.item(i).text() == "Sig")
    assert item.toolTip() == ""
    assert pop.colors["background"] != "#ffeecc"              # dimmed in dark mode
    store.set_setting("menu.dim_dark", "0")
    pop._load_settings()
    assert pop.colors["background"] == "#ffeecc"


def test_submenu_cascade_and_choose(app, store):
    from phraseforge.ui.popup import PhrasePopup
    f = store.add_folder(Folder("Mail"))
    sub = store.add_folder(Folder("Replies", parent_id=f.id))
    p = store.add_phrase(Phrase("Thanks", "thank you", folder_id=sub.id))
    pop = PhrasePopup(store)
    pop.refresh()
    item = next(pop.list.item(i) for i in range(pop.list.count()) if pop.list.item(i).text() == "Mail")
    s1 = pop.open_submenu(pop, item)
    assert [r[2] for r in _rows(s1)] == ["Replies"]
    s2 = pop.open_submenu(s1, s1.list.item(0))
    assert len(pop.subs) == 2 and [r[1] for r in _rows(s2)] == [p.id]
    chosen = []
    pop.phrase_chosen.connect(chosen.append)
    s2._activate(s2.list.item(0))
    assert chosen == [p.id] and pop.subs == []


def test_clipboard_cache_and_last_used(app, store):
    from phraseforge.ui.popup import CLIPBOARD, LAST_USED, PhrasePopup
    store.add_clipboard("copied text")
    p = store.add_phrase(Phrase("Used one", "u"))
    store.record_use(p.id)
    pop = PhrasePopup(store)
    pop.refresh()
    items = {pop.list.item(i).data(Qt.UserRole + 1): pop.list.item(i) for i in range(pop.list.count())}
    clip = pop.open_submenu(pop, items[CLIPBOARD])
    got = []
    pop.clipboard_chosen.connect(got.append)
    clip._activate(clip.list.item(0))
    assert got == ["copied text"]
    last = pop.open_submenu(pop, items[LAST_USED])
    assert [r[1] for r in _rows(last)] == [p.id]


def test_quick_search_highlight_and_enter(app, store):
    from phraseforge.ui.popup import ROLE_QUERY, PhrasePopup, highlight_spans
    f = store.add_folder(Folder("Skills"))
    a = store.add_phrase(Phrase("Install skill", "x", folder_id=f.id))
    store.add_phrase(Phrase("Other", "x"))
    pop = PhrasePopup(store)
    pop.refresh()
    pop.search.setText("skill")
    rows = _rows(pop)
    assert rows[0][2] == "Skills" and rows[1][1] == a.id
    assert pop.list.item(1).data(ROLE_QUERY) == "skill"
    assert pop.header.currentWidget() is pop.search_bar
    assert highlight_spans("Install Skill now", "skill") == [("Install ", False), ("Skill", True), (" now", False)]
    chosen = []
    pop.phrase_chosen.connect(chosen.append)
    pop.list.setCurrentRow(1)
    pop.eventFilter(pop.search, QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
    assert chosen == [a.id]
    pop.end_search()
    assert pop.header.currentWidget() is pop.band


def test_hidden_and_restricted(app, store):
    from phraseforge.ui.popup import PhrasePopup
    store.add_folder(Folder("Hidden", show_in_popup=False))
    w = store.add_folder(Folder("WordOnly", apps_include="winword.exe"))
    store.add_phrase(Phrase("in word", "x", folder_id=w.id))
    pop = PhrasePopup(store)
    pop.app_exe = "notepad.exe"
    pop.refresh()
    names = [r[2] for r in _rows(pop)]
    assert "Hidden" not in names and "WordOnly" not in names
    pop.app_exe = "winword.exe"
    pop.refresh()
    assert "WordOnly" in [r[2] for r in _rows(pop)]


def test_settings_and_new_phrase(app, store):
    from phraseforge.ui.popup import PhrasePopup
    store.set_setting("menu.width", "420")
    store.set_setting("features.last_used_folder", "0")
    for i in range(6):
        store.add_phrase(Phrase(f"p{i}", "x"))
    pop = PhrasePopup(store)
    pop.max_items = 3
    pop.refresh()
    assert pop.width() == 420
    assert pop.list.height() == 3 * 32 and not pop.up_arrow.isHidden()
    assert "Last Used" not in [r[2] for r in _rows(pop)]
    got = []
    pop.new_phrase_requested.connect(lambda: got.append(pop.new_phrase_folder_id))
    pop.footer.clicked.emit()
    assert got == [None]


def test_typed_letter_quick_jump_or_search(app, store):
    from phraseforge.ui.popup import PhrasePopup
    store.add_phrase(Phrase("apple", "x"))
    store.add_phrase(Phrase("hello world", "x"))
    pop = PhrasePopup(store)
    pop.refresh()
    # Quick Jump on (default): typing jumps to the matching row
    pop.handle_key(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_H, Qt.NoModifier, "h"))
    assert pop.search.text() == "" and pop.list.currentItem().text() == "hello world"
    # Quick Jump off: typing starts a search
    store.set_setting("quicksearch.quick_jump", "0")
    pop._load_settings()
    pop.handle_key(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_H, Qt.NoModifier, "h"))
    assert pop.search.text() == "h"


def test_show_at_folder(app, store):
    from phraseforge.ui.popup import CLIPBOARD, LAST_USED, PhrasePopup
    f = store.add_folder(Folder("Mail"))
    sub = store.add_folder(Folder("Replies", parent_id=f.id))
    p = store.add_phrase(Phrase("Thanks", "t", folder_id=f.id))
    store.add_phrase(Phrase("Top level", "x"))
    store.add_clipboard("clip text")
    pop = PhrasePopup(store)
    pop.show_at(10, 10, caret=None, folder=str(f.id))          # numeric str works too
    assert [r[2] for r in _rows(pop)] == ["Replies", "Thanks"]
    assert pop.band.title == "Mail" and not pop.band.wordmark
    got = []
    pop.new_phrase_requested.connect(lambda: got.append(pop.new_phrase_folder_id))
    pop.footer.clicked.emit()
    assert got == [f.id]
    pop.show_at(10, 10, caret=None, folder=CLIPBOARD)
    assert [r[2] for r in _rows(pop)] == ["clip text"] and pop.band.title == "Clipboard Cache"
    store.record_use(p.id)
    pop.show_at(10, 10, caret=None, folder=LAST_USED)
    assert [r[1] for r in _rows(pop)] == [p.id]
    pop.show_at(10, 10, caret=None)                              # back to the normal menu
    assert pop.band.wordmark and "Top level" in [r[2] for r in _rows(pop)]
    pop.show_at(10, 10, caret=None, folder=99999)                # unknown folder -> normal menu
    assert pop.folder_key is None
    pop.hide_all(force=True)
    assert sub.id


def test_last_used_cap_and_clipboard_switch(app, store):
    from phraseforge.ui.popup import LAST_USED, CLIPBOARD, PhrasePopup
    for i in range(5):
        p = store.add_phrase(Phrase(f"u{i}", "x"))
        store.record_use(p.id)
    store.set_setting("last_used.max", "2")
    pop = PhrasePopup(store)
    assert len(pop.last_used_phrases()) == 2
    store.set_setting("clipboard_history.enabled", "0")
    pop._load_settings()
    pop.refresh()
    ids = [r[1] for r in _rows(pop)]
    assert CLIPBOARD not in ids and LAST_USED in ids


def test_stats_math(app, store):
    from phraseforge.ui.stats_window import StatsWindow, format_duration, time_saved_minutes
    assert time_saved_minutes(1560, 156) == 10
    assert format_duration(0.2) == "less than a minute"
    assert format_duration(61) == "1 hour, 1 minute"
    assert format_duration(4 * 1440 + 20 * 60 + 45) == "4 days, 20 hours, 45 minutes"
    p = store.add_phrase(Phrase("S", "s"))
    store.record_use(p.id, app="notepad.exe", chars=3120)
    store.set_setting("stats.typing_speed", "156")
    store.set_setting("stats.hourly_wage", "30")
    w = StatsWindow(store)
    assert "1 phrases (3120 chars) saved you a total of 20 minutes" in w.total_label.text()
    assert "10.00" in w.total_label.text()          # money saved at 30/hour
    w.speed.setValue(200)
    w.usage.setChecked(False)
    w.accept()
    assert store.setting("stats.typing_speed") == "200" and store.setting("features.usage_statistics") == "0"
    assert w.top.rowCount() == 1


def test_typing_test_cpm(app):
    from phraseforge.ui.stats_window import compute_cpm
    assert compute_cpm(100, 30) == 200
    assert compute_cpm(0, 0) == 0


def test_about_tray_wizard_clipboard(app, store):
    from phraseforge.ui.about_dialog import AboutDialog
    from phraseforge.ui.clipboard_window import ClipboardWindow
    from phraseforge.ui.icons import app_icon
    from phraseforge.ui.tray import Tray
    from phraseforge.ui.wizard import FirstRunWizard
    d = AboutDialog()
    assert "PhraseForge" in d.version_label.text() and "Capture2Text" in d.credits_text()
    t = Tray(app_icon())
    got = []
    t.toggle_pause.connect(got.append)
    t.pause_action.setChecked(True)
    assert got == [True]
    store.add_clipboard("one")
    store.add_clipboard("two")
    cw = ClipboardWindow(store)
    cw.refresh()
    assert cw.list.count() == 2
    wz = FirstRunWizard(store)
    wz.popup_hotkey.set_value("ctrl+shift+p")
    wz.apply()
    assert set(store.setting("popup.hotkey").split("+")) == {"ctrl", "shift", "p"}
