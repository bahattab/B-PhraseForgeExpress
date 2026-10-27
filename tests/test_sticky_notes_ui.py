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
