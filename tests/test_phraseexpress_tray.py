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


def test_tray_enabled_in_program_and_language(qapp):
    from phraseforge.ui.tray import Tray
    t = Tray()
    excluded = {"notepad.exe"}
    t.last_app_provider = lambda: ("notepad.exe", "Untitled - Notepad")
    t.excluded_provider = lambda: excluded
    t.language_provider = lambda: "ar"
    hits = []
    t.app_enabled.connect(lambda exe, on: hits.append((exe, on)))
    t.language.connect(lambda c: hits.append(c))
    t._before_show()
    act = t.app_toggle_action
    assert act.isVisible() and act.text() == 'Enabled in "Untitled - Notepad"'
    assert not act.isChecked()                    # notepad is excluded
    act.trigger()
    assert hits == [("notepad.exe", True)]
    checked = [a.data() for a in t.language_menu.actions() if a.isChecked()]
    assert checked == ["ar"]
    t.language_menu.actions()[0].trigger()
    assert hits[-1] == "en"
    t.last_app_provider = lambda: None
    t._before_show()
    assert not act.isVisible()


def test_app_tracks_last_program_and_toggles_exclusion(qapp, store):
    import os
    import sys

    from phraseforge.app import PhraseForgeApp
    fake = SimpleNamespace(store=store, _last_app=None)
    PhraseForgeApp._track_foreground_app(fake, ("winword.exe", "Report - Word"))
    PhraseForgeApp._track_foreground_app(fake, ("explorer.exe", ""))        # taskbar: no title
    PhraseForgeApp._track_foreground_app(fake, (os.path.basename(sys.executable).lower(), "PhraseForge"))
    assert fake._last_app == ("winword.exe", "Report - Word")
    PhraseForgeApp._set_app_enabled(fake, "winword.exe", False)
    assert "winword.exe" in store.excluded_apps()
    PhraseForgeApp._set_app_enabled(fake, "winword.exe", True)
    assert "winword.exe" not in store.excluded_apps()


def test_new_phrase_info_dialog(qapp, store):
    from phraseforge.models import Folder, TriggerKind
    from phraseforge.ui.main_dialogs import NewPhraseInfoDialog
    from phraseforge.ui.trigger_editor import TYPES
    top = store.add_folder(Folder("Work"))
    sub = store.add_folder(Folder("Mail", parent_id=top.id))
    dlg = NewPhraseInfoDialog(store, "Greeting", sub.id)
    assert dlg.windowTitle() == "Enter additional information for the new phrase..."
    assert dlg.folder_id() == sub.id
    assert [dlg.folder.itemData(i) for i in range(dlg.folder.count())] == [None, top.id, sub.id]
    labels = [a.text() for a in dlg.trigger_list.add_button.menu().actions()]
    assert labels == [label for _, label in TYPES]
    row = dlg.trigger_list.rows[0].row()
    row["value"] = "grt"
    dlg.trigger_list.rows[0].set_row(row)
    dlg.only_programs.setChecked(True)
    dlg.programs.setText("outlook.exe")
    dlg.set_folder(top.id)
    p = store.add_phrase(dlg.phrase("Hello there"))
    got = store.get_phrase(p.id)
    assert (got.description, got.content, got.folder_id, got.apps_include) == ("Greeting", "Hello there", top.id, "outlook.exe")
    assert [(t.kind, t.value) for t in got.triggers] == [(TriggerKind.AUTOTEXT, "grt")]


def test_ask_new_phrase_info_respects_setting(qapp, store):
    from phraseforge.app import PhraseForgeApp
    from phraseforge.models import Phrase
    store.set_setting("display.prompt_after_new_phrase", "0")
    p = PhraseForgeApp._ask_new_phrase_info(SimpleNamespace(store=store), Phrase("Quick", "text"))
    assert store.get_phrase(p.id).description == "Quick"
