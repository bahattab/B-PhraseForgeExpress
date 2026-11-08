"""Dynamic folders (PRD FR-DYN-01, T-DYN-01): text, CSV/Excel, folder, SQLite and ODBC
sources; refresh adds, updates in place and removes; approval per PC; due checks; the dialog."""
import os
import sqlite3
import time
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from phraseforge import dynamic, policy
from phraseforge.db import Store
from phraseforge.dynamic import DynamicConfig, DynamicError
from phraseforge.models import Folder, TriggerKind


@pytest.fixture(autouse=True)
def no_policy():
    policy.set_current(policy.NO_POLICY)
    yield
    policy.set_current(None)


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def folder(store, name="Dyn"):
    return store.add_folder(Folder(name)).id


def phrases(store, fid):
    return {p.description: p for p in store.phrases(fid)}


def touch_later(path, text):
    path.write_text(text, encoding="utf-8")
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))


# ---------------------------------------------------------------- sources
def test_text_file_one_phrase_per_line(tmp_path, store):
    f = tmp_path / "lines.txt"
    f.write_text("Good morning\n\nمرحبا بكم\nGood morning\n", encoding="utf-8")
    items = dynamic.read_items(DynamicConfig("text", str(f)))
    assert [(i.key, i.content) for i in items] == [
        ("good morning", "Good morning"), ("مرحبا بكم", "مرحبا بكم"), ("good morning#2", "Good morning")]


def test_csv_with_header_and_explicit_columns(tmp_path):
    f = tmp_path / "t.csv"
    f.write_text("Name;Body;Code\nHi;Hello there;hi#\nBye;See you;\n", encoding="utf-8")
    items = dynamic.read_items(DynamicConfig("table", str(f), columns={"description": "Name", "content": "Body",
                                                                       "autotext": "3"}))
    assert [(i.description, i.content, i.autotext) for i in items] == [("Hi", "Hello there", "hi#"),
                                                                     ("Bye", "See you", "")]
    g = tmp_path / "u.csv"
    g.write_text("Description,Content\nA,alpha\n", encoding="utf-8")       # header names alone
    assert [(i.description, i.content) for i in dynamic.read_items(DynamicConfig("table", str(g)))] == [("A", "alpha")]


def test_excel_sheet(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    wb.active.title = "First"
    wb.active.append(["ignored", "x"])
    ws = wb.create_sheet("Phrases")
    ws.append(["Description", "Content"])
    ws.append(["تحية", "السلام عليكم"])
    p = tmp_path / "w.xlsx"
    wb.save(p)
    items = dynamic.read_items(DynamicConfig("table", str(p), sheet="Phrases"))
    assert [(i.description, i.content) for i in items] == [("تحية", "السلام عليكم")]
    with pytest.raises(DynamicError, match="no sheet"):
        dynamic.read_items(DynamicConfig("table", str(p), sheet="Nope"))


def test_folder_on_disk(tmp_path):
    root = tmp_path / "texts"
    (root / "sub").mkdir(parents=True)
    (root / "Letter.txt").write_text("Dear customer", encoding="utf-8")
    (root / "sub" / "Deep.md").write_text("deep", encoding="utf-8")
    (root / "logo.png").write_bytes(b"\x89PNG")
    (root / "~$lock.txt").write_text("x", encoding="utf-8")
    (root / "notes.bin").write_bytes(b"\0")
    with zipfile.ZipFile(root / "Offer.docx", "w") as z:
        z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
                   '2006/main"><w:body><w:p><w:r><w:t>10% off</w:t></w:r></w:p></w:body></w:document>')
    flat = {i.description: i.content for i in dynamic.read_items(DynamicConfig("folder", str(root)))}
    assert flat["Letter"] == "Dear customer" and flat["Offer"] == "10% off" and flat["logo"].startswith("{#image ")
    assert "Deep" not in flat and "~$lock" not in flat and "notes" not in flat
    deep = {i.key for i in dynamic.read_items(DynamicConfig("folder", str(root), recursive=True, link=True))}
    assert "sub/deep.md" in deep
    linked = dynamic.read_items(DynamicConfig("folder", str(root), link=True))
    assert next(i for i in linked if i.description == "Letter").content.startswith("{#document ")


def test_sqlite_query_read_only_and_select_only(tmp_path):
    db = tmp_path / "p.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE t (name TEXT, body TEXT, code TEXT)")
    c.executemany("INSERT INTO t VALUES (?,?,?)", [("A", "alpha", "a#"), ("B", None, "")])
    c.commit()
    c.close()
    items = dynamic.read_items(DynamicConfig("sqlite", str(db), "SELECT name, body, code FROM t ORDER BY name",
                                             columns={"description": "name", "content": "body", "autotext": "code"}))
    assert [(i.description, i.content, i.autotext) for i in items] == [("A", "alpha", "a#")]   # B has no content
    for bad in ("DELETE FROM t", "SELECT 1; DROP TABLE t", "UPDATE t SET name='x'"):
        with pytest.raises(DynamicError, match="SELECT"):
            dynamic.read_items(DynamicConfig("sqlite", str(db), bad))


def test_odbc_source_through_a_connector():
    calls = []

    def connect(cs):
        calls.append(cs)
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE p (Description TEXT, Content TEXT)")
        conn.execute("INSERT INTO p VALUES ('Sig', 'Best regards')")
        return conn
    items = dynamic.read_items(DynamicConfig("odbc", "DSN=Phrases", "SELECT * FROM p"), odbc_connect=connect)
    assert calls == ["DSN=Phrases"] and [(i.description, i.content) for i in items] == [("Sig", "Best regards")]


# ---------------------------------------------------------------- refresh
def test_refresh_adds_updates_in_place_and_removes(tmp_path, store):
    f = tmp_path / "t.csv"
    f.write_text("Description,Content,Autotext\nHi,Hello,hi#\nBye,See you,\n", encoding="utf-8")
    fid = folder(store)
    dynamic.set_config(store, fid, DynamicConfig("table", str(f)))
    assert dynamic.refresh(store, fid) == (2, 0, 0)
    first = phrases(store, fid)
    assert [t.value for t in first["Hi"].triggers if t.kind == TriggerKind.AUTOTEXT] == ["hi#"]
    assert "dynamic" in first["Hi"].tags and store.quarantine_origin(first["Hi"].id) == "imported"
    store.record_use(first["Hi"].id, app="x.exe", chars=5)
    assert not dynamic.due(store, fid)                                  # file unchanged
    touch_later(f, "Description,Content\nHi,Hello again\nNew,Fresh\n")
    assert dynamic.due(store, fid)
    assert dynamic.refresh(store, fid) == (1, 1, 1)                     # New added, Hi updated, Bye removed
    now = phrases(store, fid)
    assert set(now) == {"Hi", "New"} and now["Hi"].id == first["Hi"].id and now["Hi"].content == "Hello again"
    assert now["Hi"].triggers == [] and store.get_phrase(first["Hi"].id).use_count >= 1
    assert dynamic.refresh(store, fid) == (0, 0, 0)                     # nothing changed
    assert dynamic.status(store, fid)["items"] == 2


def test_a_source_must_be_approved_on_this_pc(tmp_path, store):
    f = tmp_path / "lines.txt"
    f.write_text("secret line", encoding="utf-8")
    fid = folder(store)
    dynamic.set_config(store, fid, DynamicConfig("text", str(f)))
    store.set_setting(f"dynamic.approved.{fid}", "")                   # as after a cloud sync to another PC
    with pytest.raises(DynamicError, match="approved"):
        dynamic.refresh(store, fid)
    assert dynamic.refresh_due(store) == [] and store.phrases(fid) == []  # skipped quietly
    from phraseforge.db import is_device_setting
    assert is_device_setting(f"dynamic.approved.{fid}")                # the approval never travels
    dynamic.set_config(store, fid, DynamicConfig("text", str(f)))     # approving = saving the settings here
    assert dynamic.refresh(store, fid) == (1, 0, 0)
    cfg = dynamic.config(store, fid)
    cfg.path = str(tmp_path / "other.txt")                            # a changed source needs approval again
    with store.lock, store.conn:
        store.conn.execute("UPDATE dynamic_folders SET config=? WHERE folder_id=?",
                           (__import__("json").dumps(__import__("dataclasses").asdict(cfg)), fid))
    assert not dynamic.approved(store, fid)


def test_query_sources_follow_their_interval_and_errors_are_kept(tmp_path, store):
    db = tmp_path / "p.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE t (Description TEXT, Content TEXT)")
    c.execute("INSERT INTO t VALUES ('A','a')")
    c.commit()
    c.close()
    fid = folder(store)
    dynamic.set_config(store, fid, DynamicConfig("sqlite", str(db), "SELECT * FROM t", ttl_s=60))
    t0 = time.time()
    dynamic.refresh(store, fid, now=t0)
    assert not dynamic.due(store, fid, now=t0 + 30) and dynamic.due(store, fid, now=t0 + 61)
    db.unlink()
    with pytest.raises(DynamicError, match="not found"):
        dynamic.refresh(store, fid)
    assert "not found" in dynamic.status(store, fid)["error"]
    assert [p.description for p in store.phrases(fid)] == ["A"]       # a failed read removes nothing
    with pytest.raises(DynamicError, match="SELECT"):
        dynamic.set_config(store, fid, DynamicConfig("sqlite", str(db), "DROP TABLE t"))


def test_refresh_works_under_an_editing_lock_and_remove_keeps_phrases(tmp_path, store):
    f = tmp_path / "lines.txt"
    f.write_text("one\ntwo", encoding="utf-8")
    fid = folder(store)
    dynamic.set_config(store, fid, DynamicConfig("text", str(f)))
    policy.set_current(policy.parse("editing_disabled = true", "t"))
    assert dynamic.refresh(store, fid) == (2, 0, 0)                   # IT can feed phrases from a file
    policy.set_current(policy.NO_POLICY)
    dynamic.remove(store, fid)
    assert dynamic.config(store, fid) is None and len(store.phrases(fid)) == 2
    store.delete_folder(fid)
    assert fid not in dynamic.dynamic_folder_ids(store)


# ---------------------------------------------------------------- dialog
@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_dialog_saves_approves_and_updates(app, tmp_path, store, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from phraseforge.ui.dynamic_dialog import DynamicFolderDialog
    f = tmp_path / "t.csv"
    f.write_text("Description,Content\nHi,Hello\n", encoding="utf-8")
    fid = folder(store)
    d = DynamicFolderDialog(store, fid)
    assert "ordinary folder" in d.status.text() and not d.remove_button.isEnabled()
    d.source.setCurrentIndex(d.source.findData("sqlite"))
    assert d.query.isVisibleTo(d) and d.ttl.isVisibleTo(d)
    d.source.setCurrentIndex(d.source.findData("table"))
    assert not d.query.isVisibleTo(d) and d.sheet.isVisibleTo(d)
    d.path.setText(str(f))
    assert d.save_and_refresh() == (1, 0, 0)
    assert "1 phrases from the source" in d.status.text() and d.remove_button.isEnabled()
    assert dynamic.approved(store, fid)
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2])))
    d.path.setText(str(tmp_path / "missing.csv"))
    assert d.save_and_refresh() is None and warned
    d.make_ordinary()
    assert dynamic.config(store, fid) is None


def test_folder_menu_entry(app, store):
    from phraseforge.ui.main_window import MainWindow
    fid = folder(store)
    w = MainWindow(store)
    assert "Dynamic folder..." in [a.text() for a in w.build_context_menu("folder", fid).actions()]
