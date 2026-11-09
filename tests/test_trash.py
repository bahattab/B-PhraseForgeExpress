"""Trash, template folders and phrase comments (G-18: FR-DAT-02, -03, -04)."""
import sqlite3

import pytest

from phraseforge.cloud.sync import CloudSync, FolderRemote
from phraseforge.db import Store
from phraseforge.models import Folder, Phrase, Trigger, TriggerKind


def autotext(v):
    return Trigger(TriggerKind.AUTOTEXT, v)


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "p.db")
    yield s
    s.close()


def test_a_trashed_phrase_comes_back_with_everything(store):
    f = store.add_folder(Folder("Mail"))
    p = store.add_phrase(Phrase("Greeting", "Hello", folder_id=f.id, tags=["mail"], triggers=[autotext("hii")]))
    store.set_phrase_version(p.id, "de", "Hallo")
    store.add_comment(p.id, "check the tone", author="ana")
    p.content = "Hello there"
    store.update_phrase(p)                     # one history entry
    store.quarantine(p.id, "imported")
    uid = store.conn.execute("SELECT uid FROM phrases WHERE id=?", (p.id,)).fetchone()[0]
    tid = store.trash_phrase(p.id)
    assert store.get_phrase(p.id) is None and not store.triggers()
    items = store.trash_items()
    assert [(i["kind"], i["name"], i["parent_name"]) for i in items] == [("phrase", "Greeting", "Mail")]
    kind, new_id = store.restore_trash(tid)
    q = store.get_phrase(new_id)
    assert (kind, q.folder_id, q.content, q.tags) == ("phrase", f.id, "Hello there", ["mail"])
    assert [t.value for t in q.triggers] == ["hii"]
    assert store.phrase_versions(new_id) == {"de": ("Hallo", "text")}
    assert [c["text"] for c in store.comments(new_id)] == ["check the tone"]
    assert store.history(new_id)
    assert store.quarantine_origin(new_id) == "imported"   # still waits for approval
    assert store.conn.execute("SELECT uid FROM phrases WHERE id=?", (new_id,)).fetchone()[0] == uid
    assert store.trash_items() == []


def test_a_trashed_folder_comes_back_with_its_tree(store):
    top = store.add_folder(Folder("Top"))
    sub = store.add_folder(Folder("Sub", parent_id=top.id))
    store.add_phrase(Phrase("A", "a", folder_id=top.id))
    store.add_phrase(Phrase("B", "b", folder_id=sub.id))
    tid = store.trash_folder(top.id)
    assert store.folders() == [] and store.phrases() == []
    assert store.trash_items()[0]["count"] == 2
    kind, fid = store.restore_trash(tid)
    assert kind == "folder" and store.get_folder(fid).name == "Top"
    assert [f.name for f in store.folders(fid)] == ["Sub"]
    assert sorted(p.description for p in store.phrases()) == ["A", "B"]


def test_restore_into_the_top_level_when_the_folder_is_gone(store):
    f = store.add_folder(Folder("Gone"))
    p = store.add_phrase(Phrase("Orphan", "o", folder_id=f.id))
    tid = store.trash_phrase(p.id)
    store.delete_folder(f.id)
    _, new_id = store.restore_trash(tid)
    assert store.get_phrase(new_id).folder_id is None


def test_old_entries_are_purged(store):
    p = store.add_phrase(Phrase("Old", "o"))
    store.trash_phrase(p.id)
    store.conn.execute("UPDATE trash SET deleted_at='2000-01-01T00:00:00'")
    store.conn.commit()
    q = store.add_phrase(Phrase("New", "n"))
    store.trash_phrase(q.id)
    assert store.purge_trash() == 1
    assert [i["name"] for i in store.trash_items()] == ["New"]
    store.set_setting("trash.days", "0")             # 0 = keep forever
    store.conn.execute("UPDATE trash SET deleted_at='2000-01-01T00:00:00'")
    assert store.purge_trash() == 0
    store.delete_trash()
    assert store.trash_items() == []


def test_the_trash_stays_on_this_pc(tmp_path):
    a, b = Store(tmp_path / "A.db"), Store(tmp_path / "B.db")
    sa = CloudSync(a, FolderRemote(tmp_path / "cloud"), device="A")
    sb = CloudSync(b, FolderRemote(tmp_path / "cloud"), device="B")
    p = a.add_phrase(Phrase("Run", "{#run calc.exe}"))
    a.add_phrase(Phrase("Keep", "k"))
    a.trash_phrase(p.id)
    sa.sync()
    r = sb.sync()
    sb.apply_pull(r.pulled_file, r.remote_rev)
    assert b.trash_items() == []                 # the deleted phrase did not travel in the trash
    b_own = b.add_phrase(Phrase("B's", "b"))
    b.trash_phrase(b_own.id)
    a.add_phrase(Phrase("More", "m"))
    sa.sync()
    r = sb.sync()
    sb.apply_pull(r.pulled_file, r.remote_rev)
    assert [i["name"] for i in b.trash_items()] == ["B's"]   # a pull keeps this PC's trash
    a.close()
    b.close()


def test_template_folders(store):
    t = store.add_folder(Folder("Templates", is_template=True))
    sub = store.add_folder(Folder("Letters", parent_id=t.id))
    tpl = store.add_phrase(Phrase("Letter", "Dear {#input Name},", folder_id=sub.id, tags=["letter"],
                                  triggers=[autotext("lt")]))
    store.set_phrase_version(tpl.id, "ar", "عزيزي")
    normal = store.add_phrase(Phrase("Hi", "hi", triggers=[autotext("hi")]))
    assert store.get_folder(t.id).is_template
    assert [x.phrase_id for x in store.triggers()] == [normal.id]        # templates never expand
    assert [p.description for p in store.template_phrases()] == ["Letter"]
    work = store.add_folder(Folder("Work"))
    p = store.new_from_template(tpl.id, work.id)
    assert (p.folder_id, p.content, p.tags, p.triggers) == (work.id, "Dear {#input Name},", ["letter"], [])
    assert store.phrase_versions(p.id) == {"ar": ("عزيزي", "text")}
    t2 = store.get_folder(t.id)
    t2.is_template = False
    store.update_folder(t2)
    assert len(store.triggers()) == 2


def test_template_flag_survives_an_old_database(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.executescript("""CREATE TABLE folders (id INTEGER PRIMARY KEY, parent_id INTEGER, name TEXT NOT NULL,
        sort INTEGER DEFAULT 0, enabled INTEGER DEFAULT 1, apps_include TEXT DEFAULT '', apps_exclude TEXT DEFAULT '',
        password_hash TEXT DEFAULT '', show_in_popup INTEGER DEFAULT 1);
        CREATE TABLE phrases (id INTEGER PRIMARY KEY, folder_id INTEGER, description TEXT NOT NULL,
        content TEXT DEFAULT '', content_format TEXT DEFAULT 'text', output_mode TEXT DEFAULT 'auto',
        apps_include TEXT DEFAULT '', apps_exclude TEXT DEFAULT '', enabled INTEGER DEFAULT 1, sort INTEGER DEFAULT 0,
        use_count INTEGER DEFAULT 0, last_used TEXT, created TEXT, modified TEXT, notes TEXT DEFAULT '');
        INSERT INTO folders (name) VALUES ('F');""")
    con.commit()
    con.close()
    s = Store(db)
    f = s.folders()[0]
    assert f.is_template is False
    f.is_template = True
    s.update_folder(f)
    assert s.get_folder(f.id).is_template
    s.close()


def test_comments(store):
    p = store.add_phrase(Phrase("P", "p"))
    c1 = store.add_comment(p.id, "first", author="ana")
    store.add_comment(p.id, "second", author="bo")
    assert store.comment_counts() == {p.id: 2}
    store.resolve_comment(c1)
    assert store.comment_counts() == {p.id: 1}
    assert [(c["author"], c["resolved"]) for c in store.comments(p.id)] == [("ana", 1), ("bo", 0)]
    store.delete_comment(c1)
    assert [c["text"] for c in store.comments(p.id)] == ["second"]
    with pytest.raises(ValueError):
        store.add_comment(p.id, "   ")
    store.delete_phrase(p.id)
    assert store.conn.execute("SELECT count(*) FROM phrase_comments").fetchone()[0] == 0


def test_comments_and_template_flag_merge_between_pcs(tmp_path):
    a, b = Store(tmp_path / "A.db"), Store(tmp_path / "B.db")
    sa = CloudSync(a, FolderRemote(tmp_path / "cloud"), device="A")
    sb = CloudSync(b, FolderRemote(tmp_path / "cloud"), device="B")

    def run(cs):
        r = cs.sync()
        if r.action in ("pulled", "merged"):
            cs.apply_pull(r.pulled_file, r.remote_rev)
        return r
    f = a.add_folder(Folder("T"))
    p = a.add_phrase(Phrase("P", "p"))
    run(sa)
    run(sb)
    fa = a.get_folder(f.id)
    fa.is_template = True
    a.update_folder(fa)
    a.add_comment(p.id, "from A", author="a")
    pb = b.find_phrase("P")
    b.add_comment(pb.id, "from B", author="b")
    run(sa)
    assert run(sb).action == "merged"
    run(sa)
    for st in (a, b):
        assert sorted(c["text"] for c in st.comments(st.find_phrase("P").id)) == ["from A", "from B"]
        assert next(x for x in st.folders() if x.name == "T").is_template
    a.close()
    b.close()


def test_dialogs(store):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from phraseforge.ui.trash_dialog import CommentsDialog, TemplatePicker, TrashDialog
    p = store.add_phrase(Phrase("Gone", "g"))
    store.trash_phrase(p.id)
    d = TrashDialog(store)
    assert d.list.topLevelItemCount() == 1
    d.list.topLevelItem(0).setSelected(True)
    d.restore()
    assert d.restored and store.find_phrase("Gone") is not None
    t = store.add_folder(Folder("Tpl", is_template=True))
    store.add_phrase(Phrase("Form", "x", folder_id=t.id))
    picker = TemplatePicker(store)
    picker.accept()
    assert picker.chosen == store.find_phrase("Form").id
    c = CommentsDialog(store, store.find_phrase("Gone").id)
    c.text.setPlainText("note")
    c.add()
    assert c.list.topLevelItemCount() == 1
