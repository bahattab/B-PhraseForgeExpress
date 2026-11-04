"""Sticky notes built into PhraseForge: storage, note windows, list, import."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from phraseforge.db import Store  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def test_store_crud_and_events(store):
    events = []
    store.on_change(lambda k, i: events.append(k))
    n = store.add_sticky_note("Hello\nworld", color="blue", x=10, y=20)
    assert n.title == "Hello" and n.theme == "blue" and (n.x, n.y) == (10, 20) and n.visible
    store.update_sticky_note(n.id, text="Changed", html="<b>Changed</b>")
    store.update_sticky_note(n.id, touch=False, w=400, visible=False, on_top=True)
    m = store.sticky_note(n.id)
    assert (m.text, m.html, m.w, m.visible, m.on_top) == ("Changed", "<b>Changed</b>", 400, False, True)
    store.delete_sticky_note(n.id)
    assert store.sticky_note(n.id) is None and store.sticky_notes() == []
    assert events.count("sticky") == 4


def test_notes_survive_backup_restore(store, tmp_path):
    store.add_sticky_note("keep me")
    store.backup_to(tmp_path / "b.db")
    store.add_sticky_note("later")
    store.restore_from(tmp_path / "b.db")
    assert [n.text for n in store.sticky_notes()] == ["keep me"]


def test_note_window_saves_text_colour_and_formatting(app, store):
    from phraseforge.ui.sticky_notes import StickyNotesManager
    mgr = StickyNotesManager(store)
    w = mgr.new_note()
    w.edit.setPlainText("Call Ahmed\n0500000000")
    w.edit.selectAll()
    w.toggle_bold()
    w.flush()
    n = store.sticky_note(w.note_id)
    assert n.text == "Call Ahmed\n0500000000" and "font-weight" in n.html
    w.set_color("green")
    assert store.sticky_note(w.note_id).theme == "green"
    w.set_on_top(True)
    assert store.sticky_note(w.note_id).on_top
    w.close()
    assert not store.sticky_note(w.note_id).visible
    # a second note opened from this one keeps its colour
    w2 = mgr.new_note(near=w)
    assert store.sticky_note(w2.note_id).theme == "green"


def test_arabic_note(app, store):
    from phraseforge.ui.sticky_notes import StickyNotesManager
    mgr = StickyNotesManager(store)
    w = mgr.new_note("مرحبا بالعالم")
    w.flush()
    assert store.sticky_note(w.note_id).text == "مرحبا بالعالم"


def test_restore_opens_visible_notes(app, store):
    from phraseforge.ui.sticky_notes import StickyNotesManager
    store.add_sticky_note("open", x=5, y=5)
    store.add_sticky_note("closed", visible=False)
    mgr = StickyNotesManager(store)
    assert mgr.restore() == 1
    assert [w.text() for w in mgr.windows.values()] == ["open"]


def test_list_search_and_delete(app, store):
    from phraseforge.ui.sticky_notes import StickyNotesManager
    store.add_sticky_note("alpha note")
    b = store.add_sticky_note("beta note")
    mgr = StickyNotesManager(store)
    lw = mgr.show_list()
    assert lw.list.count() == 2
    lw.search.setText("beta")
    assert lw.list.count() == 1
    mgr.delete_note(b.id)
    lw.search.setText("")
    assert lw.list.count() == 1


def test_import_from_microsoft_file(app, store, tmp_path):
    import sqlite3
    from phraseforge.ui.sticky_notes import StickyNotesManager
    p = tmp_path / "plum.sqlite"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE Note (Text, Theme, Id, CreatedAt, UpdatedAt, DeletedAt)")
    con.execute("INSERT INTO Note VALUES (?,?,?,?,?,?)", ("\\id=a-1 From Microsoft", "Pink", "n1", 1, 1, None))
    con.commit()
    con.close()
    mgr = StickyNotesManager(store)
    assert mgr.import_microsoft(p) == 1
    assert mgr.import_microsoft(p) == 0          # no duplicates
    n = store.sticky_notes()[0]
    assert n.text == "From Microsoft" and n.theme == "pink"


def test_no_external_program(app):
    import inspect
    from phraseforge import stickynotes
    from phraseforge.ui import sticky_notes
    for mod in (stickynotes, sticky_notes):
        src = inspect.getsource(mod)
        assert "subprocess" not in src and "explorer" not in src.lower()


def test_running_programs_without_tasklist():
    import inspect
    from phraseforge.platform import processes
    from phraseforge.ui import macro_specs, main_dialogs
    assert "tasklist" not in inspect.getsource(main_dialogs) and "tasklist" not in inspect.getsource(macro_specs)
    names = processes.running_exes()
    if os.name == "nt":
        assert any(n.startswith("python") for n in names)
    else:
        assert names == []


def test_main_window_sticky_folder_and_note_view(app, store):
    """Clicking the Sticky Notes folder / a note in the main window used to crash (missing import)."""
    from phraseforge.ui.main_window import MainWindow, StickyNoteView
    from phraseforge.ui.tree_panel import ROLE_ID, ROLE_KIND
    n = store.add_sticky_note("Meeting at 10\nRoom 4")
    cmds = []
    w = MainWindow(store, on_command=cmds.append)
    tops = {w.tree.topLevelItem(i).data(0, ROLE_KIND): w.tree.topLevelItem(i)
            for i in range(w.tree.topLevelItemCount())}
    assert "sticky_notes" in tops
    folder = tops["sticky_notes"]
    assert folder.child(0).data(0, ROLE_ID) == n.id
    v = StickyNoteView(store, w)
    v.load(None)
    v.load(n.id)
    assert v.text.toPlainText() == "Meeting at 10\nRoom 4"
    v.open_note()
    v.open_btn.click()
    v.new_btn.click()
    assert cmds == [f"open_sticky_notes:{n.id}", "open_sticky_notes", "new_sticky_note"]
    w.tree.setCurrentItem(folder.child(0))
    w.tree.setCurrentItem(folder)
    w.close()


@pytest.mark.parametrize("columns", [2, 3])
def test_main_window_shows_sticky_notes(app, store, columns):
    """Selecting the Sticky Notes folder lists the notes (three columns) and shows the
    note view on the right; double-clicking a note in the list opens it on the desktop."""
    from phraseforge.ui.main_window import StickyNoteView, MainWindow
    from phraseforge.ui.tree_panel import ROLE_ID, ROLE_KIND
    a = store.add_sticky_note("Shopping\nmilk")
    b = store.add_sticky_note("Call Ahmed")
    cmds = []
    w = MainWindow(store, on_command=cmds.append)
    w.set_columns(columns)
    assert w.panel.select("sticky_notes", None)
    app.processEvents()
    assert isinstance(w.editor, StickyNoteView) and w.editor.caption.text() == "Sticky Notes"
    assert "2 note(s)" in w.editor.info.text()
    if columns == 3:
        lst = w.phrase_list.list
        ids = {lst.topLevelItem(i).data(0, ROLE_ID) for i in range(lst.topLevelItemCount())
               if lst.topLevelItem(i).data(0, ROLE_KIND) == "note"}
        assert ids == {a.id, b.id}
        item = next(lst.topLevelItem(i) for i in range(lst.topLevelItemCount())
                    if lst.topLevelItem(i).data(0, ROLE_ID) == a.id)
        lst.setCurrentItem(item)
        assert w.editor.text.toPlainText() == "Shopping\nmilk"
        lst.itemDoubleClicked.emit(item, 0)
        assert cmds[-1] == f"open_sticky_notes:{a.id}"
    else:
        assert w.panel.select("note", b.id)
        assert w.editor.text.toPlainText() == "Call Ahmed"
    w.close()


def test_edit_and_delete_note_in_main_window(app, store):
    """A note could only be viewed in the main window; its menu had Delete greyed out."""
    from phraseforge.ui.main_window import MainWindow, StickyNoteView
    n = store.add_sticky_note("")
    cmds = []
    w = MainWindow(store, on_command=cmds.append)
    w._quiet_updates = True
    w.set_columns(3)
    w.panel.select("sticky_notes", None)
    lst = w.phrase_list.list
    lst.setCurrentItem(lst.topLevelItem(0))
    v = w.editor
    assert isinstance(v, StickyNoteView) and not v.text.isReadOnly()
    v.text.setPlainText("Buy milk\nand bread")
    assert v.is_dirty()
    v.save()
    assert store.sticky_note(n.id).text == "Buy milk\nand bread" and v.caption.text() == "Buy milk"
    menu = w.build_context_menu("note", n.id)
    acts = {a.text(): a for a in menu.actions()}
    assert acts["Delete"].isEnabled() and "Open note" in acts and "Copy" in acts
    acts["Delete"].trigger()                      # the app deletes it (and closes its window)
    assert cmds[-1] == f"delete_sticky_note:{n.id}"
    w.on_command = None                            # without the app: deleted directly
    m = store.add_sticky_note("second")
    v.load(m.id)
    assert v.delete_note() and store.sticky_note(m.id) is None
    w.close()


def test_translate_and_pin_to_desktop(app, store):
    from phraseforge.models import Phrase
    from phraseforge.ui.main_window import MainWindow
    p = store.add_phrase(Phrase("Greeting", "Hello {#date} friend"))
    cmds = []
    w = MainWindow(store, on_command=cmds.append)
    w._quiet_updates = True
    menu = w.build_context_menu("phrase", p.id)
    acts = {a.text(): a for a in menu.actions()}
    assert "Translate [Demo]" not in acts and "Pin to desktop [Demo]" not in acts
    assert acts["Pin to desktop"].isEnabled() and acts["Translate"].menu().isEnabled()
    new = w.translate_phrase(p.id, "Arabic", translate=lambda t, lang: t.replace("Hello", "مرحبا"))
    assert new.description == "Greeting (Arabic)" and new.content == "مرحبا {#date} friend"
    assert new.folder_id == p.folder_id
    assert w.translate_phrase(p.id, "Arabic", translate=lambda t, l: 1 / 0) is None   # error shown, no copy
    note = w.pin_to_desktop(p.id)
    assert note.text == "Greeting\nHello {#date} friend" and cmds[-1] == f"open_sticky_notes:{note.id}"
    w.close()
