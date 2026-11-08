"""Change-set sync (G-24): two PCs that both edited between syncs get both sets of edits."""
import sqlite3

import pytest

from phraseforge.cloud import merge as mg
from phraseforge.cloud.sync import CloudSync, FolderRemote
from phraseforge.db import Store
from phraseforge.models import Folder, Phrase


@pytest.fixture
def two_pcs(tmp_path):
    def make(name):
        store = Store(tmp_path / f"{name}.db")
        return store, CloudSync(store, FolderRemote(tmp_path / "cloud"), device=name)
    return make("A"), make("B")


def run(cs):
    res = cs.sync()
    if res.action in ("pulled", "merged"):
        cs.apply_pull(res.pulled_file, res.remote_rev)
    return res


def by_desc(store):
    return {p.description: p for p in store.phrases()}


def in_sync(a, sa, b, sb):
    """Both PCs end up with the same data and agree that nothing is left to do."""
    run(sa)
    run(sb)
    assert sa.sync().action == "unchanged" and sb.sync().action == "unchanged"
    return by_desc(a), by_desc(b)


def start(two_pcs, *phrases):
    (a, sa), (b, sb) = two_pcs
    for p in phrases:
        a.add_phrase(p)
    assert run(sa).action == "pushed"
    assert run(sb).action == "pulled"
    return a, sa, b, sb


def test_new_phrases_on_both_pcs_are_merged(two_pcs):
    a, sa, b, sb = start(two_pcs, Phrase("Base", "x"))
    a.add_phrase(Phrase("From A", "a"))
    b.add_phrase(Phrase("From B", "b"))
    assert run(sa).action == "pushed"
    res = run(sb)
    assert res.action == "merged" and res.summary["added"] == 1 and res.summary["conflicts"] == 0
    pa, pb = in_sync(a, sa, b, sb)
    assert sorted(pa) == sorted(pb) == ["Base", "From A", "From B"]


def test_different_fields_of_one_phrase_both_survive(two_pcs):
    a, sa, b, sb = start(two_pcs, Phrase("Greeting", "Hello"))
    pa = a.find_phrase("Greeting")
    pa.description = "Greeting (formal)"
    a.update_phrase(pa)
    pb = b.find_phrase("Greeting")
    pb.content = "Good morning"
    pb.tags = ["mail"]
    b.update_phrase(pb)
    run(sa)
    assert run(sb).action == "merged"
    da, db_ = in_sync(a, sa, b, sb)
    for d in (da, db_):
        p = d["Greeting (formal)"]
        assert p.content == "Good morning" and p.tags == ["mail"]


def test_same_field_newer_edit_wins_and_loser_is_in_history(two_pcs):
    a, sa, b, sb = start(two_pcs, Phrase("Sig", "v1"))
    pa = a.find_phrase("Sig")
    pa.content = "from A"
    a.update_phrase(pa)
    pb = b.find_phrase("Sig")
    pb.content = "from B"
    b.update_phrase(pb)
    a.conn.execute("UPDATE phrases SET modified='2030-01-02T00:00:00' WHERE id=?", (pa.id,))   # A edited later
    a.conn.commit()
    b.conn.execute("UPDATE phrases SET modified='2030-01-01T00:00:00' WHERE id=?", (pb.id,))
    b.conn.commit()
    run(sa)
    res = run(sb)
    assert res.action == "merged" and res.summary["conflicts"] == 1
    p = b.find_phrase("Sig")
    assert p.content == "from A"
    assert "from B" in [h["content"] for h in b.history(p.id)]
    da, db_ = in_sync(a, sa, b, sb)
    assert da["Sig"].content == db_["Sig"].content == "from A"


def test_delete_stays_deleted_unless_the_other_pc_edited_it(two_pcs):
    a, sa, b, sb = start(two_pcs, Phrase("Old", "o"), Phrase("Edited", "e"), Phrase("Keep", "k"))
    a.delete_phrase(a.find_phrase("Old").id)
    a.delete_phrase(a.find_phrase("Edited").id)
    pb = b.find_phrase("Edited")
    pb.content = "edited on B"
    b.update_phrase(pb)
    b.add_phrase(Phrase("New on B", "n"))
    run(sa)
    assert run(sb).action == "merged"
    da, db_ = in_sync(a, sa, b, sb)
    assert sorted(da) == sorted(db_) == ["Edited", "Keep", "New on B"]
    assert da["Edited"].content == "edited on B"


def test_phrase_added_to_a_folder_the_other_pc_deleted_brings_it_back(two_pcs):
    (a, sa), (b, sb) = two_pcs
    f = a.add_folder(Folder("Work"))
    a.add_phrase(Phrase("In work", "w", folder_id=f.id))
    run(sa)
    run(sb)
    a.delete_folder(f.id)
    fb = next(x for x in b.folders() if x.name == "Work")
    b.add_phrase(Phrase("Also in work", "w2", folder_id=fb.id))
    run(sa)
    assert run(sb).action == "merged"
    da, db_ = in_sync(a, sa, b, sb)
    assert sorted(da) == sorted(db_) == ["Also in work"]
    for st in (a, b):
        p = st.find_phrase("Also in work")
        assert st.get_folder(p.folder_id).name == "Work"


def test_folder_moves_and_renames_merge(two_pcs):
    (a, sa), (b, sb) = two_pcs
    x = a.add_folder(Folder("X"))
    a.add_folder(Folder("Y"))
    run(sa)
    run(sb)
    fx = next(f for f in a.folders() if f.name == "X")
    fx.name = "X renamed"
    a.update_folder(fx)
    yb = next(f for f in b.folders() if f.name == "Y")
    xb = next(f for f in b.folders() if f.name == "X")
    yb.parent_id = xb.id                       # B moves Y into X
    b.update_folder(yb)
    run(sa)
    assert run(sb).action == "merged"
    in_sync(a, sa, b, sb)
    for st in (a, b):
        names = {f.id: f.name for f in st.folders()}
        y = next(f for f in st.folders() if f.name == "Y")
        assert names[y.parent_id] == "X renamed"
    assert x.id                                 # (A's own row id is unchanged)


def test_variables_settings_and_notes_merge(two_pcs):
    a, sa, b, sb = start(two_pcs, Phrase("P", "p"))
    a.set_var("company", "ACME")
    a.set_setting("date.format", "dd.MM.yyyy")
    b.set_var("city", "Riyadh")
    b.set_setting("time.format", "hh:mm")
    b.add_sticky_note("note from B")
    run(sa)
    assert run(sb).action == "merged"
    in_sync(a, sa, b, sb)
    for st in (a, b):
        assert st.get_var("company") == "ACME" and st.get_var("city") == "Riyadh"
        assert st.setting("date.format") == "dd.MM.yyyy" and st.setting("time.format") == "hh:mm"
        assert [n["text"] if isinstance(n, dict) else n.text for n in st.sticky_notes()] == ["note from B"]


def test_phrases_brought_by_the_merge_need_approval(two_pcs):
    a, sa, b, sb = start(two_pcs, Phrase("P", "p"))
    b.release_quarantine(b.find_phrase("P").id)
    a.add_phrase(Phrase("Run", "{#run notepad.exe}"))
    b.add_phrase(Phrase("Mine", "m"))
    run(sa)
    assert run(sb).action == "merged"
    q = b.quarantined()
    assert b.find_phrase("Run").id in q
    assert b.find_phrase("Mine").id not in q


def test_device_settings_and_clipboard_stay_put(two_pcs):
    a, sa, b, sb = start(two_pcs, Phrase("P", "p"))
    a.add_phrase(Phrase("A", "a"))
    b.add_phrase(Phrase("B", "b"))
    b.add_clipboard("B's clipboard")
    b.set_setting("ocr.cli_path", r"D:\B\cli.exe")
    run(sa)
    assert run(sb).action == "merged"
    assert [e.text for e in b.clipboard_entries()] == ["B's clipboard"]
    assert b.setting("ocr.cli_path") == r"D:\B\cli.exe"


def test_without_a_common_copy_it_still_asks(two_pcs):
    (a, sa), (b, sb) = two_pcs
    a.add_phrase(Phrase("From A", "a"))
    run(sa)
    b.add_phrase(Phrase("B's own", "b"))       # first sync on B: there is no common copy yet
    assert sb.sync().action == "conflict"


def test_merge_can_be_turned_off(two_pcs):
    a, sa, b, sb = start(two_pcs, Phrase("Base", "x"))
    b.set_setting("sync.merge", "0")
    a.add_phrase(Phrase("From A", "a"))
    b.add_phrase(Phrase("From B", "b"))
    run(sa)
    assert sb.sync().action == "conflict"


def test_items_each_pc_fills_itself_are_not_merged(two_pcs):
    (a, sa), (b, sb) = two_pcs
    a.add_folder(Folder("Dyn"))
    run(sa)
    run(sb)
    for st in (a, b):                            # both PCs refreshed the same dynamic folder
        f = next(x for x in st.folders() if x.name == "Dyn")
        p = st.add_phrase(Phrase("Row 1", "r", folder_id=f.id))
        st.conn.execute("CREATE TABLE IF NOT EXISTS dynamic_items (folder_id INTEGER, item_key TEXT, "
                        "phrase_id INTEGER, fp TEXT)")
        st.conn.execute("INSERT INTO dynamic_items VALUES (?,?,?,?)", (f.id, "1", p.id, ""))
        st.conn.commit()
    b.add_phrase(Phrase("Mine", "m"))
    run(sa)
    assert run(sb).action == "merged"
    assert sorted(p.description for p in b.phrases()) == ["Mine", "Row 1"]


def test_old_copies_without_ids_get_them_and_cannot_be_merged(tmp_path):
    old = tmp_path / "old.db"
    con = sqlite3.connect(old)
    con.executescript("""
        CREATE TABLE folders (id INTEGER PRIMARY KEY, parent_id INTEGER, name TEXT NOT NULL, sort INTEGER DEFAULT 0,
          enabled INTEGER DEFAULT 1, apps_include TEXT DEFAULT '', apps_exclude TEXT DEFAULT '',
          password_hash TEXT DEFAULT '', show_in_popup INTEGER DEFAULT 1);
        CREATE TABLE phrases (id INTEGER PRIMARY KEY, folder_id INTEGER, description TEXT NOT NULL,
          content TEXT DEFAULT '', content_format TEXT DEFAULT 'text', output_mode TEXT DEFAULT 'auto',
          apps_include TEXT DEFAULT '', apps_exclude TEXT DEFAULT '', enabled INTEGER DEFAULT 1,
          sort INTEGER DEFAULT 0, use_count INTEGER DEFAULT 0, last_used TEXT, created TEXT, modified TEXT,
          notes TEXT DEFAULT '');
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO phrases (description, content) VALUES ('one', '1'), ('two', '2');
    """)
    con.commit()
    con.close()
    with pytest.raises(mg.CannotMerge):
        mg.read_state(old)
    s = Store(old)                                # opening it upgrades it
    uids = [r[0] for r in s.conn.execute("SELECT uid FROM phrases")]
    assert len(set(uids)) == 2 and all(uids)
    s.close()
    assert len(mg.read_state(old).phrases) == 2


def test_merge_values_and_sets():
    assert mg.merge_values({"a": 1, "b": 2}, {"a": 1, "b": 3}, {"b": 2, "c": 4}) == {"b": 3, "c": 4}
    assert mg.merge_sets({"x", "y"}, {"x", "z"}, {"y", "w", "x"}) == {"x", "z", "w"}
