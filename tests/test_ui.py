import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from phraseforge.db import Store, hash_password
from phraseforge.host import FormField
from phraseforge.models import Folder, OutputMode, Phrase, Trigger, TriggerKind


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def test_theme_icons_tray(app):
    from phraseforge.ui.icons import app_icon
    from phraseforge.ui.theme import apply_theme
    from phraseforge.ui.tray import Tray
    apply_theme(app, "dark", "en")
    apply_theme(app, "light", "en")
    icon = app_icon()
    assert not icon.isNull()
    t = Tray(icon)
    got = []
    t.toggle_pause.connect(got.append)
    t.pause_action.setChecked(True)
    assert got == [True]


def _item(w, kind, id_=None):
    from phraseforge.ui.tree_panel import ROLE_ID, ROLE_KIND
    return next(i for i in w._all_items() if i.data(0, ROLE_KIND) == kind and i.data(0, ROLE_ID) == id_)


def test_main_window_shell_ribbon_and_tree(app, store):
    from phraseforge.ui.main_window import MainWindow
    from phraseforge.ui.tree_panel import ROLE_KIND
    w = MainWindow(store)
    assert w.windowTitle().startswith("PhraseForge v")
    assert {"phrases", "view", "help"} <= set(w.ribbon.tabs)
    groups = list(w.ribbon.tabs["phrases"].groups)
    assert groups == ["Insert", "Sync", "Edit", "Clipboard", "Languages", "Import / Export"]
    tops = [w.tree.topLevelItem(i).data(0, ROLE_KIND) for i in range(w.tree.topLevelItemCount())]
    assert tops == ["last_used", "clipboard_cache", "root"]
    texts = [a.text() for a in w.file_menu.actions() if a.text()]
    for t in ("Open", "Save As...", "Restore from backup", "Settings", "Migration Assistant", "Exit"):
        assert t in texts
    assert w.search.placeholderText() == "Search in Description [F3]"
    w.close()


def test_new_items_and_operations(app, store):
    from phraseforge.ui.main_window import MainWindow
    f = store.add_folder(Folder("Work"))
    w = MainWindow(store)
    w.select_folder(f.id)
    assert w.sel_kind == "folder" and w.selected_folder_id() == f.id
    p = w.new_phrase()
    assert w.current.id == p.id and store.get_phrase(p.id).folder_id == f.id
    sub = w.new_folder("Sub")
    assert sub.parent_id == f.id
    # duplicate / move / toggle / delete
    dup = w.duplicate_phrase(p.id)
    assert dup.description.endswith("(copy)")
    w.move_item("phrase", dup.id, None)
    assert store.get_phrase(dup.id).folder_id is None
    w.move_item("folder", f.id, sub.id)          # into its own child: refused
    assert store.get_folder(f.id).parent_id is None
    w.toggle_enabled("phrase", dup.id)
    assert not store.get_phrase(dup.id).enabled
    w.delete_item("phrase", dup.id, confirm=False)
    assert store.get_phrase(dup.id) is None
    # cut / paste moves, copy / paste duplicates
    q = store.add_phrase(Phrase("Q", "q"))
    w.refresh_tree()
    w.select_phrase(q.id)
    w.clip_items("cut")
    w.select_folder(sub.id)
    w.paste_items()
    assert store.get_phrase(q.id).folder_id == sub.id
    w.select_phrase(q.id)
    w.clip_items("copy")
    w.select_folder(f.id)
    w.paste_items()
    assert any(x.description.startswith("Q") for x in store.phrases(f.id))
    w.close()


def test_up_down_color_and_context_menus(app, store):
    from phraseforge.ui.main_window import MainWindow
    from phraseforge.ui.tree_panel import item_colors
    a = store.add_phrase(Phrase("A", "a"))
    b = store.add_phrase(Phrase("B", "b"))
    w = MainWindow(store)
    w.select_phrase(b.id)
    w.move_up_down(-1)
    assert [p.id for p in store.phrases(None)] == [b.id, a.id]
    w.set_color("#ff0000")
    assert item_colors(store) == {f"phrase:{b.id}": "#ff0000"}
    pm = [x.text() for x in w.build_context_menu("phrase", b.id).actions() if x.text()]
    assert pm[:2] == ["Open in tab", "Add new..."] and "Properties" in pm and "Delete" in pm
    f = store.add_folder(Folder("F"))
    fm = {x.text(): x for x in w.build_context_menu("folder", f.id).actions() if x.text()}
    assert fm["Enable triggers"].isChecked() and fm["Show in phrase menu"].isChecked()
    assert "Bulk edit" in fm
    w.close()


def test_search_scope_and_three_columns(app, store):
    from phraseforge.ui.main_window import MainWindow
    from phraseforge.ui.tree_panel import ROLE_ID, ROLE_KIND
    f = store.add_folder(Folder("Mail"))
    p = store.add_phrase(Phrase("Signature", "Best regards", folder_id=f.id,
                                triggers=[Trigger(TriggerKind.AUTOTEXT, "sig#")]))
    w = MainWindow(store)
    w.search.setText("regards")
    w._apply_search()
    assert [i.data(0, ROLE_ID) for i in w._all_items()] == []      # default scope: description only
    w.set_search_scope("all", "Search everywhere")
    assert [i.data(0, ROLE_ID) for i in w._all_items()] == [p.id]
    w.search.setText("")
    w._apply_search()
    w.set_columns(3)
    assert store.setting("view.layout") == "three"
    assert all(i.data(0, ROLE_KIND) != "phrase" for i in w._all_items())
    w.select_folder(f.id)
    rows = [w.phrase_list.list.topLevelItem(i) for i in range(w.phrase_list.list.topLevelItemCount())]
    assert [r.text(0) for r in rows] == ["..", "Signature"] and rows[1].text(1) == "sig#"
    w.select_phrase(p.id)
    assert w.sel_kind == "phrase" and w.sel_id == p.id
    w.set_columns(2)
    w.close()


def test_navigation_history_and_breadcrumb(app, store):
    from phraseforge.ui.main_window import MainWindow
    f = store.add_folder(Folder("Top"))
    g = store.add_folder(Folder("Inner", parent_id=f.id))
    p = store.add_phrase(Phrase("Deep", "x", folder_id=g.id))
    w = MainWindow(store)
    w.select_folder(f.id)
    w.select_phrase(p.id)
    assert "Top" in w.breadcrumb.text() and "Inner" in w.breadcrumb.text()
    w.nav_back()
    assert (w.sel_kind, w.sel_id) == ("folder", f.id)
    w.nav_forward()
    assert (w.sel_kind, w.sel_id) == ("phrase", p.id)
    titles = [t for _, _, t, _ in w.recent_items()]
    assert titles[0] == "Deep"
    w.close()


def test_preview_text_without_macros_falls_back(app, store):
    from phraseforge.ui.main_window import preview_text
    assert preview_text(store, "plain") == "plain"


def test_locked_folder_hides_children(app, store):
    from phraseforge.ui.main_window import MainWindow
    from phraseforge.ui.tree_panel import ROLE_KIND
    f = store.add_folder(Folder("Secret", password_hash=hash_password("pw")))
    store.add_phrase(Phrase("hidden", "x", folder_id=f.id))
    w = MainWindow(store)
    assert all(i.data(0, ROLE_KIND) != "phrase" for i in w._all_items())
    w.unlocked.add(f.id)
    w.refresh_tree()
    assert any(i.data(0, ROLE_KIND) == "phrase" for i in w._all_items())


def test_folder_dialog_apply(app):
    from phraseforge.ui.main_window import FolderDialog
    d = FolderDialog(Folder("A"))
    d.inc.setText("winword.exe")
    d.pw.setText("secret")
    f = d.apply()
    assert f.apps_include == "winword.exe" and f.password_hash == hash_password("secret")


def test_main_dialogs(app, store, tmp_path):
    from phraseforge.ui.main_dialogs import (
        FindReplaceDialog, MoveToDialog, ProgramRestrictionsDialog, RestoreBackupDialog, print_html,
    )
    f = store.add_folder(Folder("F"))
    store.add_folder(Folder("G", parent_id=f.id))
    p = store.add_phrase(Phrase("Hello world", "say hello", folder_id=f.id,
                                triggers=[Trigger(TriggerKind.AUTOTEXT, "hw#")]))
    # program restrictions round trip
    d = ProgramRestrictionsDialog("x", "winword.exe", "", None)
    d.rows[-1][1].setEditText("excel.exe")
    assert d.values() == ("winword.exe, excel.exe", "")
    # move-to tree excludes the folder being moved and filters
    m = MoveToDialog(store, "F", moving_folder_id=f.id)
    assert m.tree.topLevelItem(0).childCount() == 0
    m2 = MoveToDialog(store, "p")
    m2.filter.setText("g")
    assert m2.tree.topLevelItem(0).child(0).isHidden() is False
    # find & replace in a folder subtree
    fr = FindReplaceDialog(store, "F", folder_id=f.id)
    fr.find.setText("hello")
    assert fr.search() == [p.id]
    fr.replace.setText("hi")
    assert fr.replace_all() == 2
    assert store.get_phrase(p.id).content == "say hi"
    html = print_html(store, [store.get_phrase(p.id)])
    assert "Description:" in html and "hw#" in html
    # restore dialog lists backups
    b1 = tmp_path / "a.db"
    b1.write_bytes(b"x")
    r = RestoreBackupDialog([b1])
    assert r.count.text() == "1 archived files:" and r.selected() == b1


def test_textexpander_import_handler(app, store, tmp_path):
    from phraseforge.ui.main_window import MainWindow
    from phraseforge.ui.tree_panel import ROLE_ID, ROLE_KIND
    csv = tmp_path / "te.csv"
    csv.write_text('ty#,"Thank you!"\nd#,"Today is %Y-%m-%d"\n', encoding="utf-8")
    w = MainWindow(store)
    rep = w.import_textexpander_path(str(csv), show_message=False)
    assert rep is not None and rep.imported == 2
    assert "Imported 2" in w.last_import_summary
    autotexts = {t.value for t in store.triggers(TriggerKind.AUTOTEXT)}
    assert {"ty#", "d#"} <= autotexts
    cur = w.tree.currentItem()
    assert cur is not None and cur.data(0, ROLE_KIND) == "folder" and cur.data(0, ROLE_ID) == rep.folder_id


def test_clipboard_cache_and_last_used_nodes(app, store):
    from phraseforge.ui.main_window import MainWindow
    from phraseforge.ui.tree_panel import ROLE_KIND
    store.add_clipboard("copied text")
    p = store.add_phrase(Phrase("Used", "u"))
    store.record_use(p.id)
    w = MainWindow(store)
    cc = _item(w, "clipboard_cache")
    assert cc.childCount() == 1 and cc.child(0).text(0) == "copied text"
    lu = _item(w, "last_used")
    assert lu.childCount() == 1 and lu.child(0).text(0) == "Used"
    new = w.clip_to_phrase(cc.child(0).data(0, Qt.UserRole + 1))
    assert store.get_phrase(new.id).content == "copied text"
    w.close()


def test_feature_switches_hide_special_nodes_and_cap_last_used(app, store):
    from phraseforge.ui.main_window import MainWindow
    from phraseforge.ui.tree_panel import ROLE_KIND
    for i in range(4):
        p = store.add_phrase(Phrase(f"u{i}", "x"))
        store.record_use(p.id)
    store.set_setting("last_used.max", "2")
    w = MainWindow(store)
    assert _item(w, "last_used").childCount() == 2
    store.set_setting("features.usage_statistics", "0")
    w._refresh_timer.stop()
    w.refresh_tree()
    hint = _item(w, "last_used").child(0)
    assert hint.data(0, ROLE_KIND) == "hint" and "Usage statistics" in hint.text(0)
    store.set_setting("features.last_used_folder", "0")
    store.set_setting("clipboard_history.enabled", "0")
    w._refresh_timer.stop()
    w.refresh_tree()
    tops = [w.tree.topLevelItem(i).data(0, ROLE_KIND) for i in range(w.tree.topLevelItemCount())]
    assert tops == ["root"]
    w.close()


def test_new_phrase_focus_follows_prompt_setting(app, store):
    from phraseforge.ui.main_window import MainWindow
    w = MainWindow(store)
    w.show()
    w.new_phrase()
    app.processEvents()
    desc = getattr(w.editor, "description", None)
    if desc is not None:
        assert desc.hasFocus() and desc.selectedText() == "New phrase"
    store.set_setting("display.prompt_after_new_phrase", "0")
    w.new_phrase()
    app.processEvents()
    ce = getattr(w.editor, "content_edit", None)
    if ce is not None:
        assert ce.hasFocus()
    w.close()


def test_popup_filtering_and_app_rules(app, store):
    from phraseforge.ui.popup import PhrasePopup
    f = store.add_folder(Folder("Word", apps_include="winword.exe"))
    hidden = store.add_folder(Folder("NoPopup", show_in_popup=False))
    a = store.add_phrase(Phrase("Alpha greeting", "hello", triggers=[Trigger(TriggerKind.AUTOTEXT, "al#")]))
    b = store.add_phrase(Phrase("Beta", "bye", folder_id=f.id))
    c = store.add_phrase(Phrase("Gamma", "g", folder_id=hidden.id))
    store.record_use(a.id)
    pop = PhrasePopup(store)
    chosen = []
    pop.phrase_chosen.connect(chosen.append)
    pop.app_exe = "notepad.exe"
    pop.refresh()
    assert pop.visible_phrase_ids() == [a.id]
    pop.search.setText("e")
    assert b.id not in pop.visible_phrase_ids() and c.id not in pop.visible_phrase_ids()
    pop.app_exe = "winword.exe"
    pop.refresh()
    assert b.id in pop.visible_phrase_ids()
    pop.search.setText("al#")
    pop.eventFilter(pop.search, QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
    assert chosen == [a.id]


def test_form_dialog_all_kinds(app):
    from phraseforge.ui.dialogs import ChooseDialog, FormDialog, InputDialog
    fields = [FormField("edit", "name", "Name", "Bob"), FormField("memo", "notes", default="x\ny"),
              FormField("combo", "color", options=["red", "blue"], default="blue"),
              FormField("checkbox", "ok", default="true"), FormField("radio", "size", options=["S", "M"], default="M"),
              FormField("date", "when", default="2026-01-02"), FormField("number", "n", default="3"),
              FormField("label", "info", default="Hello")]
    d = FormDialog("T", fields)
    v = d.values()
    assert v == {"name": "Bob", "notes": "x\ny", "color": "blue", "ok": True, "size": "M",
                 "when": "2026-01-02", "n": 3}
    i = InputDialog("p", "def")
    assert i.value() == "def"
    c = ChooseDialog("c", ["one", "two"], multi=False)
    c.filter.setText("tw")
    assert c.selected() == ["two"]


def test_hotkey_recorder(app):
    from phraseforge.ui.widgets import HotkeyEdit
    h = HotkeyEdit()
    h.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_K, Qt.ControlModifier | Qt.AltModifier))
    assert h.chord() == "ctrl+alt+k"
    h.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_F5, Qt.ShiftModifier))
    assert h.chord() == "shift+f5"


def test_settings_save(app, store):
    from phraseforge.ui.settings_dialog import SettingsDialog
    d = SettingsDialog(store)
    d.theme.setCurrentText("dark")
    d.paste_threshold.setValue(99)
    d.popup_hotkey.setText("ctrl+shift+p")
    d.excluded.setPlainText("KeePass.exe\n")
    d.ai_provider.setCurrentText("anthropic")
    d.save()
    assert store.setting("ui.theme") == "dark"
    assert store.setting("output.paste_threshold") == "99"
    assert store.setting("popup.hotkey") == "ctrl+shift+p"
    assert store.setting("ai.provider") == "anthropic"
    assert store.excluded_apps() == {"keepass.exe"}
    assert store.setting("autotext.delimiters") == store.settings()["autotext.delimiters"]


def test_other_windows(app, store):
    from phraseforge.ui.clipboard_window import ClipboardWindow
    from phraseforge.ui.region_select import RegionSelector
    from phraseforge.ui.stats_window import StatsWindow
    from phraseforge.ui.suggestions_dialog import SuggestionsDialog
    from phraseforge.ui.wizard import FirstRunWizard
    store.add_clipboard("first")
    store.add_clipboard("second")
    cw = ClipboardWindow(store)
    cw.refresh()
    assert cw.list.count() == 2
    cw.search.setText("fir")
    assert cw.list.count() == 1
    p = store.add_phrase(Phrase("S", "s"))
    store.record_use(p.id, app="notepad.exe", chars=5)
    sw = StatsWindow(store)
    assert sw.top.rowCount() == 1
    for _ in range(3):
        store.bump_suggestion("see you tomorrow")
    sd = SuggestionsDialog(store)
    assert sd.list.count() == 1
    np_ = sd.create_phrase("see you tomorrow", "syt#")
    assert store.get_phrase(np_.id).triggers[0].value == "syt#"
    sd.refresh()
    assert sd.list.count() == 0
    wz = FirstRunWizard(store)
    wz.apply()
    assert store.setting("app.first_run_done") == "1"
    assert any(p.description == "OCR Arabic text from screen" for p in store.phrases())
    rs = RegionSelector()
    assert len(rs.overlays) >= 1
    rs.finish(None)
    assert rs.result is None


def test_arabic_translation():
    from phraseforge.ui import i18n
    i18n.set_language("ar")
    try:
        assert i18n.tr("Save") == "حفظ"
        assert i18n.tr("unknown text") == "unknown text"
    finally:
        i18n.set_language("en")


def test_tools_tab_runs_app_commands(app, store):
    from phraseforge.ui.main_window import MainWindow
    sent = []
    w = MainWindow(store, on_command=sent.append)
    assert "tools" in w.ribbon.tabs
    assert set(w.tool_buttons) == {"onenote_send_clipboard", "onenote_clip", "quick_note", "new_sticky_note",
                                   "ocr", "open_sticky_notes", "file_search"}
    for cmd, b in w.tool_buttons.items():
        assert b.isEnabled()
        b.click()
    assert sent == list(w.tool_buttons)
    w.close()
    # without an app to run them (e.g. opened alone) the buttons are disabled
    w2 = MainWindow(store)
    assert not any(b.isEnabled() for b in w2.tool_buttons.values())
    w2.close()


def test_flat_list_and_fit_columns_in_both_layouts(app, store):
    """Flat list used to do nothing in three columns; fit columns did nothing in two."""
    from phraseforge.models import Folder, Phrase
    from phraseforge.ui.main_window import MainWindow
    from phraseforge.ui.tree_panel import ROLE_KIND
    f = store.add_folder(Folder("Sub"))
    store.add_phrase(Phrase("Inside a folder with a fairly long description", "x", folder_id=f.id))
    store.add_phrase(Phrase("At the top", "y"))
    w = MainWindow(store)
    w.set_columns(3)
    w.toggle_flat()
    lst = w.phrase_list.list
    rows = [(lst.topLevelItem(i).data(0, ROLE_KIND), lst.topLevelItem(i).text(0))
            for i in range(lst.topLevelItemCount())]
    assert all(k == "phrase" for k, _ in rows)
    assert {"Inside a folder with a fairly long description", "At the top"} <= {t for _, t in rows}
    lst.setColumnWidth(0, 40)
    w.btn_fit.click()
    assert lst.columnWidth(0) > 40
    w.toggle_flat()
    assert not w.panel.flat
    w.set_columns(2)
    w.tree.setColumnWidth(0, 30)
    w.btn_fit.click()
    assert w.tree.columnWidth(0) > 30
    w.close()


def test_back_in_three_columns_user_menu_and_support(app, store):
    from phraseforge.models import Folder, Phrase
    from phraseforge.ui.main_window import MainWindow
    f = store.add_folder(Folder("A"))
    store.add_phrase(Phrase("P1", "x", folder_id=f.id))
    q = store.add_phrase(Phrase("P2", "y"))
    w = MainWindow(store)
    w._quiet_updates = True
    w.set_columns(3)
    w.select_folder(f.id)
    w.select_phrase(q.id)
    assert (w.sel_kind, w.sel_id) == ("phrase", q.id)
    w.act_back.trigger()                 # used to leave the phrase open (tree item unchanged)
    assert w.sel_kind == "root"
    w.act_back.trigger()
    assert (w.sel_kind, w.sel_id) == ("folder", f.id)
    w.act_forward.trigger()
    w.act_forward.trigger()
    assert (w.sel_kind, w.sel_id) == ("phrase", q.id)
    menu = w.user_button.menu()          # the account button had no action at all
    texts = [a.text() for a in menu.actions()]
    assert "Open data folder" in texts and "Get support..." in texts
    w.get_support()
    labels = {b.text() for b in w._support_box.buttons()}
    assert {"User guide", "Open data folder", "Copy diagnostic info", "Report a problem"} <= labels
    assert "PhraseForge" in w.diagnostic_info()
    w.close()
