"""Shared database stage 2: folder permissions for users and groups, enforced by
PhraseForge (not by the database), and the change history with restore.

Runs on SQLite, and on PostgreSQL when PHRASEFORGE_TEST_PG is set (see test_shared.py);
there the group is a real role (pf_sales) and membership comes from the server."""
import os
import sqlite3
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from phraseforge import policy
from phraseforge.db import Store
from phraseforge.models import Folder, Phrase
from phraseforge.shared.mirror import NOT_SAVED, Mirror
from phraseforge.shared.server import (
    EVERYONE, GROUPS_SQL, AclEntry, PermissionDenied, RemotePhrase, SharedError, SharedServer,
)

PG = os.environ.get("PHRASEFORGE_TEST_PG", "")


@pytest.fixture(autouse=True)
def no_policy():
    policy.set_current(policy.NO_POLICY)
    yield
    policy.set_current(None)


def sqlite_backend(tmp_path):
    path = tmp_path / "acl.db"
    groups = {"alice": [], "bob": ["Sales"], "carol": []}

    def open_as(user):
        return SharedServer(sqlite3.connect(str(path)), "sqlite", user=user, groups=groups[user])
    return open_as


def pg_backend():
    psycopg = pytest.importorskip("psycopg")
    name = "pf_" + uuid.uuid4().hex[:10]
    admin = psycopg.connect(PG, autocommit=True)
    for role, pw in (("carol", "carol-pw"),):
        if not admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone():
            admin.execute(f"CREATE ROLE {role} LOGIN PASSWORD '{pw}'")
    if not admin.execute("SELECT 1 FROM pg_roles WHERE rolname = 'pf_sales'").fetchone():
        admin.execute("CREATE ROLE pf_sales")
    admin.execute("GRANT pf_sales TO bob")
    admin.execute(f"CREATE DATABASE {name} OWNER alice")
    base = dict(x.split("=", 1) for x in PG.split())

    def open_as(user):
        conn = psycopg.connect(host=base.get("host", "127.0.0.1"), port=base.get("port", "5432"), dbname=name,
                               user=user, password=user + "-pw")
        return SharedServer(conn, "postgresql")
    open_as.group = "pf_sales"

    def cleanup():
        admin.execute(f"DROP DATABASE {name} WITH (FORCE)")
        admin.close()
    open_as.cleanup = cleanup
    return open_as


@pytest.fixture(params=["sqlite"] + (["postgresql"] if PG else []))
def backend(request, tmp_path):
    if request.param == "sqlite":
        b = sqlite_backend(tmp_path)
        b.group = "Sales"
        b.cleanup = lambda: None
    else:
        b = pg_backend()
    a = b("alice")
    a.ensure_schema()                               # alice creates the tables: she is the administrator
    if request.param == "postgresql":
        a.conn.autocommit = True
        a.conn.execute("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO bob, carol")
        a.conn.autocommit = False
    a.close()
    yield b
    b.cleanup()


def entry(folder, who, kind="user", read=True, write=False, admin=False):
    return AclEntry(0, folder, who, kind, read, write, admin)


def lockdown(s):
    """Remove the "everyone may read and write" entry the set-up adds."""
    for e in s.acl():
        if e.principal == EVERYONE:
            s.remove_acl(e.id)


# ---------------------------------------------------------------- set-up
def test_setup_makes_the_creator_admin_and_keeps_everyone_writing(backend):
    a = backend("alice")
    acl = {(e.principal, e.can_read, e.can_write, e.can_admin) for e in a.acl()}
    assert acl == {("alice", True, True, True), (EVERYONE, True, True, False)}
    assert a.is_admin()
    b = backend("bob")
    assert not b.is_admin()
    fid, _ = b.create_folder("Open for all", None)            # stage-1 behaviour until the admin narrows it
    rights, admin = b.rights()
    assert rights[fid].write and rights[None].write and not admin
    a.close()
    b.close()


def test_upgrade_from_stage_1(tmp_path):
    path = tmp_path / "old.db"
    s = SharedServer(sqlite3.connect(str(path)), "sqlite", user="admin", groups=[])
    s.ensure_schema()
    cur = s.conn.cursor()
    cur.execute("UPDATE pf_meta SET v = '1' WHERE k = 'schema'")
    cur.execute("DELETE FROM pf_acl")
    s.conn.commit()
    assert not s.ready()                                      # a stage-1 database must be upgraded first
    s.ensure_schema()
    assert s.ready() and {e.principal for e in s.acl()} == {"admin", EVERYONE}
    s.close()


# ---------------------------------------------------------------- rights
def test_nearest_folder_decides_and_groups_count(backend):
    a = backend("alice")
    sales, _ = a.create_folder("Sales", None)
    offers, _ = a.create_folder("Offers", sales)
    hr, _ = a.create_folder("HR", None)
    lockdown(a)
    a.add_acl(entry(None, EVERYONE, "group", read=True))                    # everyone reads the top level
    a.add_acl(entry(sales, backend.group, "group", read=True, write=True))  # the Sales group writes in Sales
    a.add_acl(entry(hr, "carol", read=True, write=True))                    # only carol sees HR
    a.add_acl(entry(hr, EVERYONE, "group", read=False))
    b, c = backend("bob"), backend("carol")
    rb, _ = b.rights()
    rc, _ = c.rights()
    assert rb[sales].write and rb[offers].write                             # inherited by the subfolder
    assert not rb[hr].read and not rb[None].write and rb[None].read
    assert rc[hr].write and not rc[sales].write and rc[sales].read
    with pytest.raises(PermissionDenied):
        b.create_phrase(RemotePhrase(0, hr, "x", "y"))
    with pytest.raises(PermissionDenied):
        c.create_phrase(RemotePhrase(0, offers, "x", "y"))
    with pytest.raises(PermissionDenied):
        b.create_folder("Top", None)
    pid, rev = b.create_phrase(RemotePhrase(0, offers, "Offer", "10% off"))
    with pytest.raises(PermissionDenied):                                   # cannot move it where he may not write
        b.update_phrase(RemotePhrase(pid, hr, "Offer", "10% off"), rev)
    c.create_phrase(RemotePhrase(0, hr, "Salary", "secret"))
    _f, seen, _ = b.changes_since(0)
    assert [p.description for p in seen] == ["Offer"]                       # HR is not even sent to bob
    _f, seen, _ = c.changes_since(0)
    assert {p.description for p in seen} == {"Offer", "Salary"}
    assert b.get_phrase(pid).content == "10% off"
    for s in (a, b, c):
        s.close()


def test_only_admins_change_permissions(backend):
    a, b = backend("alice"), backend("bob")
    with pytest.raises(PermissionDenied):
        b.add_acl(entry(None, "bob", admin=True))
    with pytest.raises(SharedError, match="whole database"):
        a.add_acl(entry(5, "bob", admin=True))
    own = next(e for e in a.acl() if e.principal == "alice")
    with pytest.raises(SharedError, match="without an administrator"):
        a.remove_acl(own.id)                                              # the last administrator stays
    bob_admin = a.add_acl(entry(None, "bob", read=True, write=True, admin=True))
    assert b.is_admin()
    b.remove_acl(bob_admin)                                               # alice is still there: allowed
    assert not b.is_admin()
    a.close()
    b.close()


# ---------------------------------------------------------------- mirror
def client(backend, user):
    store = Store(":memory:")
    return store, Mirror(store, backend(user))


def test_mirror_hides_unreadable_folders_and_follows_permission_changes(backend):
    a_store, a = client(backend, "alice")
    root = a.root_id()
    hr = a_store.add_folder(Folder("HR", parent_id=root))
    a_store.add_phrase(Phrase("Salary", "secret", folder_id=hr.id))
    a_store.add_phrase(Phrase("Hello", "hi", folder_id=root))
    a.sync()
    b_store, b = client(backend, "bob")
    b.sync()
    assert {p.description for p in b_store.phrases()} == {"Salary", "Hello"}
    remote_hr = a._map("folder", local=hr.id)[1]
    a.server.add_acl(entry(remote_hr, EVERYONE, "group", read=False))      # hide HR from everyone else
    b.sync()
    assert {p.description for p in b_store.phrases()} == {"Hello"}
    assert not any(f.name == "HR" for f in b_store.folders())
    a.server.remove_acl(next(e.id for e in a.server.acl() if e.folder_id == remote_hr))
    b.sync()
    assert {p.description for p in b_store.phrases()} == {"Salary", "Hello"}   # visible again


def test_a_refused_edit_is_undone_and_kept_outside(backend):
    a_store, a = client(backend, "alice")
    root = a.root_id()
    a_store.add_phrase(Phrase("Policy", "official text", folder_id=root))
    a.sync()
    lockdown(a.server)
    a.server.add_acl(entry(None, EVERYONE, "group", read=True))            # everyone reads, only alice writes
    b_store, b = client(backend, "bob")
    b.sync()
    p = next(x for x in b_store.phrases() if x.description == "Policy")
    p.content = "bob's version"
    b_store.update_phrase(p)
    b_store.add_phrase(Phrase("New", "bob's new phrase", folder_id=b.root_id()))
    res = b.sync()
    assert sorted(res.denied) == ["New", "Policy"]
    assert b_store.get_phrase(p.id).content == "official text"            # the server's version is back
    kept = [x for x in b_store.phrases() if b_store.get_folder(x.folder_id).name == NOT_SAVED]
    assert {(x.description, x.content) for x in kept} == {("Policy", "bob's version"), ("New", "bob's new phrase")}
    assert b.sync().denied == []                                           # nothing left that is refused
    a.sync()
    assert {x.content for x in a_store.phrases()} == {"official text"}


# ---------------------------------------------------------------- history
def test_history_records_every_change_and_restores(backend):
    a = backend("alice")
    pid, r1 = a.create_phrase(RemotePhrase(0, None, "Greeting", "v1"))
    r2 = a.update_phrase(RemotePhrase(pid, None, "Greeting", "v2", "text", [{"kind": "autotext", "value": "g#"}]), r1)
    b = backend("bob")
    r3 = b.update_phrase(RemotePhrase(pid, None, "Greeting", "v3 by bob"), r2)
    b.delete_phrase(pid, r3)
    h = a.history("phrase", pid)
    assert [(x.action, x.content, x.changed_by) for x in h] == [
        ("delete", "", "bob"), ("update", "v3 by bob", "bob"), ("update", "v2", "alice"), ("create", "v1", "alice")]
    with pytest.raises(SharedError):
        a.restore_phrase(h[0].id)                                          # a deletion has nothing to restore
    a.restore_phrase(h[2].id)                                              # back to v2, undeleted
    now = a.get_phrase(pid)
    assert not now.deleted and now.content == "v2" and now.triggers[0]["value"] == "g#"
    assert a.history("phrase", pid)[0].action == "restore"
    _f, phrases, _ = b.changes_since(0)
    assert [p.content for p in phrases if p.id == pid] == ["v2"]           # everyone gets the restored version
    a.close()
    b.close()


def test_history_is_private_to_those_who_may_read(backend):
    a = backend("alice")
    hr, _ = a.create_folder("HR", None)
    pid, _ = a.create_phrase(RemotePhrase(0, hr, "Salary", "secret"))
    a.add_acl(entry(hr, EVERYONE, "group", read=False))
    b = backend("bob")
    assert b.history("phrase", pid) == [] and b.get_phrase(pid) is None
    with pytest.raises(PermissionDenied):
        b.restore_phrase(a.history("phrase", pid)[0].id)
    a.close()
    b.close()


def test_group_queries_per_server():
    assert "sys.login_token" in GROUPS_SQL["sqlserver"] and "WINDOWS GROUP" in GROUPS_SQL["sqlserver"]
    assert "pg_has_role" in GROUPS_SQL["postgresql"]


# ---------------------------------------------------------------- dialogs
@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _use(monkeypatch, backend, user):
    from phraseforge.shared import service
    monkeypatch.setattr(service, "connect", lambda setting, connectors=None: backend(user))


def test_permissions_dialog_for_admin_and_others(app, backend, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from phraseforge.ui.shared_dialog import PermissionsDialog
    a = backend("alice")
    sales, _ = a.create_folder("Sales", None)
    a.close()
    store = Store(":memory:")
    _use(monkeypatch, backend, "alice")
    d = PermissionsDialog(store)
    assert d.is_admin and d.add_button.isEnabled() and d.table.rowCount() == 2
    assert "applied by PhraseForge" in d.findChildren(type(d.status))[0].text()
    d.folder.setCurrentIndex(d.folder.findData(sales))
    d.principal.setText(backend.group)
    d.kind.setCurrentIndex(d.kind.findData("group"))
    d.access.setCurrentIndex(d.access.findData("write"))
    assert d.add() is not None and d.table.rowCount() == 3
    texts = [d.table.item(r, 0).text() for r in range(3)]
    assert "Sales" in texts and "(whole database)" in texts
    everyone_row = next(r for r in range(3) if d.table.item(r, 1).text() == "Everyone")
    d.table.selectRow(everyone_row)
    d.remove()
    assert d.table.rowCount() == 2
    _use(monkeypatch, backend, "bob")
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a_, **k: warned.append(a_[2])))
    d = PermissionsDialog(store)
    assert not d.is_admin and not d.add_button.isEnabled() and "Only administrators" in d.status.text()


def test_history_dialog_restores_for_everyone(app, backend, monkeypatch):
    from phraseforge.ui.main_window import MainWindow
    from phraseforge.ui.shared_dialog import SharedHistoryDialog
    store, m = client(backend, "alice")
    p = store.add_phrase(Phrase("Greeting", "first", folder_id=m.root_id()))
    m.sync()
    p = store.get_phrase(p.id)
    p.content = "second"
    store.update_phrase(p)
    m.sync()
    _use(monkeypatch, backend, "alice")
    d = SharedHistoryDialog(store, p.id)
    assert [d.table.item(r, 2).text() for r in range(d.table.rowCount())] == ["Changed", "Created"]
    assert d.text.toPlainText() == "second" and not d.restore_button.isEnabled()   # the newest is current
    d.table.selectRow(1)
    assert d.text.toPlainText() == "first" and d.restore_button.isEnabled()
    assert d.restore() is not None
    m.sync()
    assert store.get_phrase(p.id).content == "first"
    w = MainWindow(store)
    texts = [a.text() for a in w.build_context_menu("phrase", p.id).actions()]
    assert "Shared history..." in texts
    local = store.add_phrase(Phrase("Local", "x"))
    assert "Shared history..." not in [a.text() for a in w.build_context_menu("phrase", local.id).actions()]
