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
    from phraseforge.ui.popup import CLIPBOARD, LAST_USED, PhrasePopup
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
    from phraseforge.ui.popup import ROLE_RIGHT
    assert pop.list.item(4).data(ROLE_RIGHT) == "[ap#]"


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
    store.set_setting("popup.width", "420")
    store.set_setting("popup.max_items", "3")
    store.set_setting("popup.show_last_used", "0")
    for i in range(6):
        store.add_phrase(Phrase(f"p{i}", "x"))
    pop = PhrasePopup(store)
    pop.refresh()
    assert pop.width() == 420
    assert pop.list.height() == 3 * 32 and not pop.up_arrow.isHidden()
    assert "Last Used" not in [r[2] for r in _rows(pop)]
    got = []
    pop.new_phrase_requested.connect(lambda: got.append(pop.new_phrase_folder_id))
    pop.footer.clicked.emit()
    assert got == [None]


def test_typed_letter_starts_search(app, store):
    from phraseforge.ui.popup import PhrasePopup
    store.add_phrase(Phrase("hello world", "x"))
    pop = PhrasePopup(store)
    pop.refresh()
    pop.handle_key(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_H, Qt.NoModifier, "h"))
    assert pop.search.text() == "h"


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
    assert store.setting("stats.typing_speed") == "200" and store.setting("stats.enabled") == "0"
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
