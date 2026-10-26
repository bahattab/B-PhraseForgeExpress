"""OneNote UI: picker, settings page, phrase output target, macro dialog, tray, import.

Uses a fake OneNote client; never touches the real OneNote.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from phraseforge.db import Store
from phraseforge.models import Phrase
from phraseforge.onenote import Node


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def tree():
    page1 = Node("p1", "Meeting notes", "page", "Work/Projects/Meeting notes")
    page2 = Node("p2", "Ideas", "page", "Work/Projects/Ideas")
    sec = Node("s1", "Projects", "section", "Work/Projects", [page1, page2])
    grp_sec = Node("s2", "Recipes", "section", "Work/Home/Recipes",
                   [Node("p3", "Soup", "page", "Work/Home/Recipes/Soup")])
    grp = Node("g1", "Home", "group", "Work/Home", [grp_sec])
    return [Node("n1", "Work", "notebook", "Work", [sec, grp])]


class FakeClient:
    def __init__(self, fail=False):
        self.fail = fail

    def notebooks(self):
        if self.fail:
            raise RuntimeError("OneNote not installed")
        return tree()


def picker(mode, **kw):
    from phraseforge.ui.onenote_picker import OneNotePicker
    return OneNotePicker(None, mode=mode, client_factory=lambda: FakeClient(**kw), synchronous=True)


def find_item(dlg, path):
    from phraseforge.ui.onenote_picker import ROLE_REF
    return next(it for it in dlg._items() if it.data(0, ROLE_REF) == path)


def test_picker_target_mode_selects_pages_and_sections(app):
    dlg = picker("target")
    assert dlg.stack.currentIndex() == 1
    dlg.tree.setCurrentItem(find_item(dlg, "Work/Projects/Ideas"))
    assert dlg.selected_ref() == "Work/Projects/Ideas" and dlg.ok.isEnabled()
    dlg.tree.setCurrentItem(find_item(dlg, "Work/Projects"))
    assert dlg.selected_ref() == "Work/Projects"
    dlg.tree.setCurrentItem(find_item(dlg, "Work"))         # notebooks are not targets
    assert dlg.selected_ref() is None


def test_picker_page_mode_only_pages(app):
    dlg = picker("page")
    dlg.tree.setCurrentItem(find_item(dlg, "Work/Projects"))
    assert dlg.selected_ref() is None
    dlg.tree.setCurrentItem(find_item(dlg, "Work/Home/Recipes/Soup"))
    assert dlg.selected_ref() == "Work/Home/Recipes/Soup"


def test_picker_preselects_current(app):
    from phraseforge.ui.onenote_picker import OneNotePicker
    dlg = OneNotePicker(None, mode="target", current="work\\projects\\ideas",
                        client_factory=lambda: FakeClient(), synchronous=True)
    assert dlg.selected_ref() == "Work/Projects/Ideas"


def test_picker_import_mode_checks_containers(app):
    dlg = picker("import")
    paths = {find_item(dlg, p).text(0) for p in ("Work", "Work/Projects", "Work/Home/Recipes")}
    assert paths == {"Work", "Projects", "Recipes"}
    with pytest.raises(StopIteration):                     # pages are not listed for import
        find_item(dlg, "Work/Projects/Ideas")
    find_item(dlg, "Work/Home").setCheckState(0, Qt.Checked)
    assert find_item(dlg, "Work/Home/Recipes").checkState(0) == Qt.Checked   # children follow
    find_item(dlg, "Work/Projects").setCheckState(0, Qt.Checked)
    assert sorted(dlg.checked_refs()) == ["Work/Home", "Work/Projects"]
    assert dlg.ok.isEnabled()
    find_item(dlg, "Work").setCheckState(0, Qt.Checked)
    assert dlg.checked_refs() == ["Work"]                  # top-most only


def test_picker_filter(app):
    dlg = picker("target")
    dlg.filter.setText("soup")
    assert not find_item(dlg, "Work/Home/Recipes/Soup").isHidden()
    assert find_item(dlg, "Work/Projects/Ideas").isHidden()


def test_picker_error_and_retry(app):
    dlg = picker("target", fail=True)
    assert dlg.stack.currentIndex() == 0
    assert "not available" in dlg.status.text() and dlg.retry.isVisibleTo(dlg)
    dlg.client_factory = lambda: FakeClient()
    dlg.load()
    assert dlg.stack.currentIndex() == 1


def test_settings_onenote_page_round_trip(app):
    from phraseforge.ui.settings_dialog import SettingsDialog, pages
    from phraseforge.ui.settings_schema import SCHEMA
    for k in ("onenote.exe", "onenote.default_target", "onenote.send_hotkey", "onenote.clip_hotkey",
              "onenote.clip_tool", "onenote.clip_action", "onenote.include_ocr"):
        assert k in SCHEMA
    assert SCHEMA["onenote.clip_tool"] == "phraseforge" and SCHEMA["onenote.clip_action"] == "image"
    assert pages().index("onenote") == pages().index("ocr") + 1
    s = Store(":memory:")
    d = SettingsDialog(s, page="onenote")
    d.onenote_target.setText("Work/Projects")
    d.onenote_clip_tool.setCurrentText("onenote")
    d.onenote_clip_action.setCurrentText("both")
    d.save()
    assert s.setting("onenote.default_target") == "Work/Projects"
    assert s.setting("onenote.clip_tool") == "onenote"
    assert s.setting("onenote.clip_action") == "both"


def test_phrase_editor_onenote_target_round_trip(app):
    from phraseforge.ui.phrase_editor import OutputTargetRow, PhraseEditor
    s = Store(":memory:")
    p = s.add_phrase(Phrase("P", "text"))
    ed = PhraseEditor(s)
    ed.load(p.id)
    row: OutputTargetRow = ed.output_target
    row.set("onenote", "")
    assert row.browse.isVisibleTo(row)

    class FakePicker:
        def __init__(self, parent):
            pass

        def exec(self):
            return True

        def selected_ref(self):
            return "Work/Projects/Ideas"

    row.picker_factory = FakePicker
    row._browse_onenote()
    assert row.target_arg() == "Work/Projects/Ideas"
    ed.save()
    got = s.get_phrase(p.id)
    assert (got.output_target, got.output_target_arg) == ("onenote", "Work/Projects/Ideas")
    ed.load(p.id)
    assert ed.output_target.target() == "onenote"
    row.set("clipboard")
    assert not row.browse.isVisibleTo(row)


def test_macro_dialog_onenote(app):
    from phraseforge.ui.macro_specs import SPECS, build_onenote
    assert build_onenote({"page": "Work/Projects/Ideas"}) == '{#onenote "Work/Projects/Ideas"}'
    assert build_onenote({"page": "A/B/C", "title": True, "ocr": True}) == '{#onenote "A/B/C" -title -ocr}'
    sp = SPECS["onenote_page"]
    assert sp.parse(["A/B/C"], {"title": ""}) == {"page": "A/B/C", "title": True, "ocr": False}
    from phraseforge.ui.macro_ui import MENUS, display_name
    ext = next(m for m in MENUS if m[0] == "External data")
    assert "onenote_page" in ext[2]
    assert display_name('{#onenote "A/B/C"}')


def test_macro_dialog_opens_and_builds(app):
    from phraseforge.ui.macro_dialog_kit import MacroDialog
    from phraseforge.ui.macro_specs import SPECS
    dlg = MacroDialog(SPECS["onenote_page"])
    dlg.set_values({"page": "Work/Projects/Ideas", "title": True})
    text = dlg.build_text()
    assert text.startswith('{#onenote "Work/Projects/Ideas" -title')
    from phraseforge.macros.parser import parse
    assert parse(text)                                     # valid PhraseForge macro syntax


def test_tray_onenote_items(app):
    from phraseforge.ui.tray import Tray
    t = Tray()
    t._before_show()
    assert not t.onenote_send_action.isVisible()            # hidden until the app wires them
    hits = []
    t.onenote_send_clipboard.connect(lambda: hits.append("send"))
    t.onenote_clip.connect(lambda: hits.append("clip"))
    t._before_show()
    assert t.onenote_send_action.isVisible() and t.onenote_clip_action.isVisible()
    t.onenote_send_action.trigger()
    t.onenote_clip_action.trigger()
    assert hits == ["send", "clip"]


def test_main_window_import_onenote(app, monkeypatch):
    from phraseforge.ui import main_window as mw
    s = Store(":memory:")
    w = mw.MainWindow(s)
    calls = {}

    class Rep:
        imported = 3
        folder_id = None
        errors = ["Work/Projects/Broken: read error"]

    def fake_import(store, client, refs, include_ocr=False, progress=None):
        calls["refs"], calls["ocr"] = refs, include_ocr
        assert progress(1, 3, "Ideas") is True
        f = store.add_folder(__import__("phraseforge.models", fromlist=["Folder"]).Folder("Work"))
        Rep.folder_id = f.id
        return Rep

    import types, sys
    fake_mod = types.ModuleType("phraseforge.importers.onenote")
    fake_mod.import_nodes = fake_import
    monkeypatch.setitem(sys.modules, "phraseforge.importers.onenote", fake_mod)
    rep = w.import_onenote_refs(["Work/Projects"], lambda: FakeClient(), show_message=False)
    assert rep.imported == 3 and calls["refs"] == ["Work/Projects"] and calls["ocr"] is False
    assert "Imported 3 OneNote page(s)" in w.last_import_summary and "could not be read" in w.last_import_summary
    assert w.selected_folder_id() == Rep.folder_id
