"""Several phrase libraries mounted at once (G-19, FR-DAT-06)."""
import sqlite3
import time

import pytest

from phraseforge.cloud.sync import CloudSync, FolderRemote, content_hash
from phraseforge.db import Store
from phraseforge.libraries import LibraryError, LibraryManager, ReadOnlyLibrary
from phraseforge.models import Folder, Phrase, Trigger, TriggerKind


def at(v):
    return Trigger(TriggerKind.AUTOTEXT, v)


def team_file(path, *phrases, folder=None):
    s = Store(path)
    fid = s.add_folder(Folder(folder)).id if folder else None
    for p in phrases:
        p.folder_id = fid
        s.add_phrase(p)
    s.close()
    return path


def touch_later(path):
    time.sleep(0.01)


@pytest.fixture
def me(tmp_path):
    s = Store(tmp_path / "me.db")
    yield s, LibraryManager(s)
    s.close()


def descs(store, root):
    out = []
    for p in store.phrases():
        chain = [f.id for f in store.folder_chain(p.folder_id)]
        if root in chain:
            out.append(p.description)
    return sorted(out)


def test_a_read_only_library_shows_up_and_refuses_edits(me, tmp_path):
    store, libs = me
    path = team_file(tmp_path / "team.db", Phrase("Team address", "Main St 1", triggers=[at("tadr")]),
                     folder="Sales")
    lib = libs.add("Team", str(path), "ro")
    root = libs.root(lib)
    assert store.get_folder(root).name == "Team"
    assert descs(store, root) == ["Team address"]
    assert [f.name for f in store.folders(root)] == ["Sales"]
    assert any(t.value == "tadr" for t in store.triggers())          # its abbreviations work
    p = next(x for x in store.phrases() if x.description == "Team address")
    assert store.quarantine_origin(p.id) == "library"                 # approval before privileged macros
    p.content = "changed"
    with pytest.raises(ReadOnlyLibrary, match="read-only"):
        store.update_phrase(p)
    with pytest.raises(ReadOnlyLibrary):
        store.add_phrase(Phrase("New", "n", folder_id=root))
    with pytest.raises(ReadOnlyLibrary):
        store.delete_phrase(p.id)
    with pytest.raises(ReadOnlyLibrary):
        store.trash_folder(root)
    store.add_phrase(Phrase("Mine", "m"))                             # the own phrases stay editable


def test_changes_in_the_file_are_picked_up(me, tmp_path):
    store, libs = me
    path = team_file(tmp_path / "team.db", Phrase("A", "a"), Phrase("B", "b"))
    lib = libs.add("Team", str(path))
    root = libs.root(lib)
    t = Store(path)
    a = t.find_phrase("A")
    a.content = "a2"
    t.update_phrase(a)
    t.delete_phrase(t.find_phrase("B").id)
    t.add_phrase(Phrase("C", "c"))
    t.close()
    touch_later(path)
    assert libs.refresh() == []
    assert descs(store, root) == ["A", "C"]
    assert next(p for p in store.phrases() if p.description == "A").content == "a2"
    assert libs.refresh() == []                    # unchanged file: nothing to do


def test_a_read_write_library_gets_the_edits(me, tmp_path):
    store, libs = me
    path = team_file(tmp_path / "team.db", Phrase("A", "a"), folder="Docs")
    lib = libs.add("Team", str(path), "rw")
    root = libs.root(lib)
    docs = store.folders(root)[0]
    a = next(p for p in store.phrases() if p.description == "A")
    a.content = "edited here"
    store.update_phrase(a)
    store.add_phrase(Phrase("New", "fresh", folder_id=docs.id, triggers=[at("nw")]))
    sub = store.add_folder(Folder("Sub", parent_id=root))
    store.add_phrase(Phrase("Deep", "d", folder_id=sub.id))
    t = Store(path)
    assert t.find_phrase("A").content == "edited here"
    new = t.find_phrase("New")
    assert new.content == "fresh" and [x.value for x in new.triggers] == ["nw"]
    assert t.get_folder(new.folder_id).name == "Docs"
    assert t.get_folder(t.find_phrase("Deep").folder_id).name == "Sub"
    t.close()
    store.delete_phrase(a.id)
    t = Store(path)
    assert t.find_phrase("A") is None
    t.close()
    assert libs.refresh() == []                    # our own writes are not read back as changes
    assert descs(store, root) == ["Deep", "New"]


def test_personal_phrases_win_then_the_first_library(me, tmp_path):
    store, libs = me
    store.add_phrase(Phrase("Mine", "mine", triggers=[at("hi")]))
    libs.add("One", str(team_file(tmp_path / "one.db", Phrase("One", "1", triggers=[at("hi"), at("x1")]))))
    libs.add("Two", str(team_file(tmp_path / "two.db", Phrase("Two", "2", triggers=[at("x1"), at("x2")]))))
    owners = {}
    for t in store.triggers():
        owners.setdefault(t.value, []).append(store.get_phrase(t.phrase_id).description)
    assert owners == {"hi": ["Mine"], "x1": ["One"], "x2": ["Two"]}


def test_unmount_removes_the_folder_not_the_file(me, tmp_path):
    store, libs = me
    path = team_file(tmp_path / "team.db", Phrase("A", "a"))
    lib = libs.add("Team", str(path))
    libs.remove(lib.id)
    assert store.folders() == [] and store.phrases() == []
    assert libs.libraries() == []
    t = Store(path)
    assert t.find_phrase("A") is not None
    t.close()


def test_mount_errors(me, tmp_path):
    store, libs = me
    with pytest.raises(LibraryError):
        libs.add("Missing", str(tmp_path / "nope.db"))
    with pytest.raises(LibraryError):
        libs.add("Self", store.path)
    lib = libs.add("New", str(tmp_path / "new.db"), "rw", create=True)
    store.add_phrase(Phrase("First", "f", folder_id=libs.root(lib)))
    t = Store(tmp_path / "new.db")
    assert t.find_phrase("First") is not None
    t.close()
    with pytest.raises(LibraryError, match="already"):
        libs.add("Again", str(tmp_path / "new.db"))


def test_an_old_file_without_ids_mounts_read_only(me, tmp_path):
    store, libs = me
    old = tmp_path / "old.db"
    con = sqlite3.connect(old)
    con.executescript("""CREATE TABLE folders (id INTEGER PRIMARY KEY, parent_id INTEGER, name TEXT NOT NULL,
        sort INTEGER DEFAULT 0, enabled INTEGER DEFAULT 1, apps_include TEXT DEFAULT '', apps_exclude TEXT DEFAULT '',
        password_hash TEXT DEFAULT '', show_in_popup INTEGER DEFAULT 1);
        CREATE TABLE phrases (id INTEGER PRIMARY KEY, folder_id INTEGER, description TEXT NOT NULL,
        content TEXT DEFAULT '', content_format TEXT DEFAULT 'text', output_mode TEXT DEFAULT 'auto',
        apps_include TEXT DEFAULT '', apps_exclude TEXT DEFAULT '', enabled INTEGER DEFAULT 1, sort INTEGER DEFAULT 0,
        use_count INTEGER DEFAULT 0, last_used TEXT, created TEXT, modified TEXT, notes TEXT DEFAULT '');
        CREATE TABLE triggers (id INTEGER PRIMARY KEY, phrase_id INTEGER, folder_id INTEGER, special TEXT DEFAULT '',
        kind TEXT, value TEXT, mode TEXT, case_sensitive INTEGER, word_start_only INTEGER, enabled INTEGER);
        CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT); CREATE TABLE phrase_tags (phrase_id INTEGER, tag_id INTEGER);
        CREATE TABLE vars (scope TEXT, name TEXT, value TEXT); CREATE TABLE settings (key TEXT, value TEXT);
        INSERT INTO phrases (description, content) VALUES ('Old one', 'o');""")
    con.commit()
    con.close()
    lib = libs.add("Old", str(old))
    assert descs(store, libs.root(lib)) == ["Old one"]
    assert libs.refresh(force=True) == [] and descs(store, libs.root(lib)) == ["Old one"]   # stable, no duplicates
    assert sqlite3.connect(old).execute("PRAGMA table_info(phrases)").fetchall()[-1][1] == "notes"   # not changed


def test_libraries_stay_out_of_the_cloud_and_survive_a_pull(tmp_path):
    a = Store(tmp_path / "A.db")
    la = LibraryManager(a)
    b = Store(tmp_path / "B.db")
    sa = CloudSync(a, FolderRemote(tmp_path / "cloud"), device="A")
    sb = CloudSync(b, FolderRemote(tmp_path / "cloud"), device="B")
    a.add_phrase(Phrase("Own", "o"))
    h = content_hash(a)
    lib = la.add("Team", str(team_file(tmp_path / "team.db", Phrase("Team", "t"))))
    assert content_hash(a) == h                         # mounting is not a change to sync
    r = sa.sync()
    assert r.action == "pushed"
    r = sb.sync()
    sb.apply_pull(r.pulled_file, r.remote_rev)
    assert [p.description for p in b.phrases()] == ["Own"]  # the other PC does not get A's library
    b.add_phrase(Phrase("From B", "b"))
    sb.sync()
    r = sa.sync()
    sa.apply_pull(r.pulled_file, r.remote_rev)
    assert sorted(p.description for p in a.phrases()) == ["From B", "Own", "Team"]   # kept after the pull
    root = la.root(lib)
    assert root is not None and descs(a, root) == ["Team"]
    assert la.refresh() == [] and descs(a, root) == ["Team"]
    a.close()
    b.close()


def test_dialog_and_read_only_editor(me, tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from phraseforge.ui.libraries_dialog import LibrariesDialog
    from phraseforge.ui.main_window import MainWindow
    store, libs = me
    lib = libs.add("Team", str(team_file(tmp_path / "team.db", Phrase("T", "t"))))
    d = LibrariesDialog(store)
    assert d.list.topLevelItemCount() == 1 and d.list.topLevelItem(0).text(0) == "Team"
    w = MainWindow(store)
    p = next(x for x in store.phrases() if x.description == "T")
    w.select_phrase(p.id)
    assert w._in_read_only_library("phrase", p.id) and not w.editor.isEnabled()
    assert w.save_current()                      # nothing to save, no error
    libs.set_mode(lib.id, "rw")
    assert not w._in_read_only_library("phrase", p.id)
    w.close()
    w.deleteLater()                              # gone before the store closes
    d.deleteLater()
    QApplication.processEvents()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
