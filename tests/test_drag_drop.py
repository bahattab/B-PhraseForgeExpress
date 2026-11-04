"""Drag & drop between the middle list ("Folders and phrases") and the folder tree."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication

from phraseforge.db import Store
from phraseforge.models import Folder, Phrase
from phraseforge.ui.tree_panel import ROLE_ID, ROLE_KIND, item_mime, read_item_mime


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def setup(app):
    from phraseforge.ui.main_window import MainWindow
    s = Store(":memory:")
    s.set_setting("view.layout", "three")
    a = s.add_folder(Folder("Alpha"))
    b = s.add_folder(Folder("Beta"))
    p = s.add_phrase(Phrase("Greeting", "Hello", folder_id=a.id))
    w = MainWindow(s)
    w.resize(1000, 600)
    w.show()
    app.processEvents()
    yield s, w, a, b, p
    w.close()
    s.close()


def _drop(widget, item, mime):
    pos = QPointF(widget.visualItemRect(item).center()) if item is not None else QPointF(5, widget.height() - 5)
    ev = QDropEvent(pos, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
    widget.dropEvent(ev)
    return ev


def _find(widget, kind, id_):
    for i in range(widget.topLevelItemCount()):
        it = widget.topLevelItem(i)
        if it.data(0, ROLE_KIND) == kind and it.data(0, ROLE_ID) == id_:
            return it
        stack = [it]
        while stack:
            cur = stack.pop()
            if cur.data(0, ROLE_KIND) == kind and cur.data(0, ROLE_ID) == id_:
                return cur
            stack.extend(cur.child(j) for j in range(cur.childCount()))
    return None


def test_list_items_carry_drag_data(setup):
    s, w, a, b, p = setup
    w.phrase_list.show_folder("folder", a.id)
    it = _find(w.phrase_list.list, "phrase", p.id)
    md = w.phrase_list.list.mimeData([it])
    assert read_item_mime(md) == ("phrase", p.id) and md.text() == "Greeting"
    up = _find(w.phrase_list.list, "up", None) if False else w.phrase_list.list.topLevelItem(0)
    assert up.data(0, ROLE_KIND) == "up" and w.phrase_list.list.mimeData([up]) is None


def test_drop_phrase_from_list_onto_tree_folder(setup):
    s, w, a, b, p = setup
    w.refresh_tree()
    target = _find(w.panel.tree, "folder", b.id)
    assert target is not None
    ev = _drop(w.panel.tree, target, item_mime("phrase", p.id))
    assert ev.isAccepted()
    assert s.get_phrase(p.id).folder_id == b.id


def test_drop_onto_folder_row_and_up_row_in_list(setup):
    s, w, a, b, p = setup
    sub = s.add_folder(Folder("Sub", parent_id=a.id))
    w.phrase_list.show_folder("folder", a.id)
    row = _find(w.phrase_list.list, "folder", sub.id)
    _drop(w.phrase_list.list, row, item_mime("phrase", p.id))
    assert s.get_phrase(p.id).folder_id == sub.id
    w.phrase_list.show_folder("folder", sub.id)
    up = w.phrase_list.list.topLevelItem(0)
    _drop(w.phrase_list.list, up, item_mime("phrase", p.id))
    assert s.get_phrase(p.id).folder_id == a.id


def test_clipboard_entry_dropped_on_folder_becomes_phrase(setup):
    s, w, a, b, p = setup
    s.add_clipboard("Copied line one\nmore text")
    entry = s.clipboard_entries(1)[0]
    w.refresh_tree()
    _drop(w.panel.tree, _find(w.panel.tree, "folder", b.id), item_mime("clip", entry.id))
    made = [x for x in s.phrases(b.id)]
    assert len(made) == 1 and made[0].description == "Copied line one" and "more text" in made[0].content


def test_folder_cannot_be_dropped_into_itself(setup):
    s, w, a, b, p = setup
    w.refresh_tree()
    _drop(w.panel.tree, _find(w.panel.tree, "folder", a.id), item_mime("folder", a.id))
    assert s.get_folder(a.id).parent_id is None
