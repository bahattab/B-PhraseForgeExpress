"""Shared phrase database (PRD FR-SYN-05, G-25, stage 1): the server tables and revisions,
two clients exchanging folders and phrases, conflicts, deletions, safety, the SQL dialects,
connection strings, the service and the dialog.

The two-client tests run on SQLite files. Set PHRASEFORGE_TEST_PG to a libpq connection
string of a PostgreSQL superuser (e.g. "host=127.0.0.1 port=5432 user=postgres") with
login roles alice/alice-pw and bob/bob-pw to run them on a real PostgreSQL as well."""
import os
import sqlite3
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from phraseforge import policy
from phraseforge.db import Store
from phraseforge.models import Folder, Phrase, Trigger, TriggerKind
from phraseforge.shared import connect as sc
from phraseforge.shared import service
from phraseforge.shared.mirror import CONFLICT_SUFFIX, Mirror
from phraseforge.shared.server import DIALECTS, Conflict, RemotePhrase, SharedError, SharedServer


@pytest.fixture(autouse=True)
def no_policy():
    policy.set_current(policy.NO_POLICY)
    yield
    policy.set_current(None)


# ---------------------------------------------------------------- backends
def sqlite_backend(tmp_path):
    path = tmp_path / "shared.db"

    def open_as(user):
        return SharedServer(sqlite3.connect(str(path)), "sqlite", user=user)
    s = open_as("admin")
    s.ensure_schema()
    s.close()
    return open_as


PG = os.environ.get("PHRASEFORGE_TEST_PG", "")


def pg_backend():
    psycopg = pytest.importorskip("psycopg")
    name = "pf_" + uuid.uuid4().hex[:10]
    admin = psycopg.connect(PG, autocommit=True)
    admin.execute(f"CREATE DATABASE {name} OWNER alice")
    base = dict(x.split("=", 1) for x in PG.split())
    host, port = base.get("host", "127.0.0.1"), base.get("port", "5432")

    def open_as(user):
        conn = psycopg.connect(host=host, port=port, dbname=name, user=user, password=user + "-pw")
        return SharedServer(conn, "postgresql")
    a = open_as("alice")
    a.ensure_schema()                                       # alice is the administrator
    a.close()
    g = psycopg.connect(host=host, port=port, dbname=name, user="alice", password="alice-pw", autocommit=True)
    g.execute("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO bob")
    g.close()

    def cleanup():
        admin.execute(f"DROP DATABASE {name} WITH (FORCE)")
        admin.close()
    open_as.cleanup = cleanup
    return open_as


@pytest.fixture(params=["sqlite"] + (["postgresql"] if PG else []))
def backend(request, tmp_path):
    if request.param == "sqlite":
        b = sqlite_backend(tmp_path)
        b.users = ("alice", "bob")
        yield b
    else:
        b = pg_backend()
        b.users = ("alice", "bob")
        yield b
        b.cleanup()


class Client:
    """One PhraseForge: its own local store, connected as one user."""

    def __init__(self, backend, user):
        self.store = Store(":memory:")
        self.server = backend(user)
        self.mirror = Mirror(self.store, self.server)

    def sync(self):
        return self.mirror.sync()

    @property
    def root(self):
        return self.mirror.root_id()

    def phrases(self):
        return {p.description: p for p in self.store.phrases()}

    def close(self):
        self.server.close()
        self.store.close()


@pytest.fixture
def two(backend):
    a, b = Client(backend, backend.users[0]), Client(backend, backend.users[1])
    yield a, b
    a.close()
    b.close()


# ---------------------------------------------------------------- server
def test_revisions_grow_and_updates_need_the_last_seen_revision(backend):
    s = backend(backend.users[0])
    fid, r1 = s.create_folder("Team", None)
    pid, r2 = s.create_phrase(RemotePhrase(0, fid, "Hi", "Hello", "text", [{"kind": "autotext", "value": "hi#"}]))
    assert r2 == r1 + 1 and s.current_rev() == r2
    r3 = s.update_phrase(RemotePhrase(pid, fid, "Hi", "Hello!", "text", [{"kind": "autotext", "value": "hi#"}]), r2)
    with pytest.raises(Conflict):
        s.update_phrase(RemotePhrase(pid, fid, "Hi", "stale"), r2)       # someone saw r2, it is r3 now
    folders, phrases, top = s.changes_since(r1)
    assert top == r3 and [p.content for p in phrases] == ["Hello!"] and folders == []   # a failed update used no rev
    assert phrases[0].modified_by == backend.users[0] and phrases[0].triggers[0]["value"] == "hi#"
    r4 = s.delete_folder(fid, r1)
    _f, phrases, _ = s.changes_since(r3)
    assert phrases[0].deleted and phrases[0].rev == r4                   # deleting a folder deletes its phrases
    s.close()


def test_schema_is_idempotent_and_refuses_a_newer_one(backend):
    s = backend(backend.users[0])
    s.ensure_schema()
    assert s.ready()
    cur = s.conn.cursor()
    cur.execute(s.d.sql("UPDATE pf_meta SET v = ? WHERE k = 'schema'"), ("99",))
    s.conn.commit()
    with pytest.raises(SharedError, match="newer"):
        s.ensure_schema()
    s.close()


# ---------------------------------------------------------------- two clients
def test_two_users_exchange_folders_and_phrases(two):
    a, b = two
    team = a.store.add_folder(Folder("Team", parent_id=a.root))
    sub = a.store.add_folder(Folder("Replies", parent_id=team.id))
    a.store.add_phrase(Phrase("Thanks", "شكرًا لكم", folder_id=sub.id,
                              triggers=[Trigger(TriggerKind.AUTOTEXT, "thx#")]))
    a.store.add_phrase(Phrase("Local only", "not shared"))               # outside the Shared folder
    res = a.sync()
    assert res.pushed == 3 and res.user == a.server.user()
    res = b.sync()
    assert res.pulled == 3
    got = b.phrases()["Thanks"]
    assert got.content == "شكرًا لكم" and [t.value for t in got.triggers] == ["thx#"]
    assert b.store.get_folder(got.folder_id).name == "Replies"
    assert b.store.get_folder(b.store.get_folder(got.folder_id).parent_id).name == "Team"
    assert "Local only" not in b.phrases()
    assert b.store.quarantine_origin(got.id) == "synced"                  # written by someone else
    # b edits, a receives; nothing is sent back and forth again
    got.content = "Thank you!"
    b.store.update_phrase(got)
    assert b.sync().pushed == 1
    assert a.sync().pulled == 1 and a.phrases()["Thanks"].content == "Thank you!"
    assert a.sync().pulled == 0 and a.sync().pushed == 0 and b.sync().pushed == 0


def test_conflicting_edits_keep_both_texts(two):
    a, b = two
    a.store.add_phrase(Phrase("Offer", "v1", folder_id=a.root))
    a.sync()
    b.sync()
    pa, pb = a.phrases()["Offer"], b.phrases()["Offer"]
    pa.content = "edited by a"
    a.store.update_phrase(pa)
    pb.content = "edited by b"
    b.store.update_phrase(pb)
    a.sync()
    res = b.sync()                                     # the server has a's edit: it wins, b's is kept
    assert res.conflicts == ["Offer"]
    ph = b.phrases()
    assert ph["Offer"].content == "edited by a" and ph["Offer" + CONFLICT_SUFFIX].content == "edited by b"
    a.sync()
    assert a.phrases()["Offer" + CONFLICT_SUFFIX].content == "edited by b"    # nothing lost for anyone


def test_deletions_travel_but_local_edits_survive(two):
    a, b = two
    f = a.store.add_folder(Folder("Old", parent_id=a.root))
    a.store.add_phrase(Phrase("Gone", "x", folder_id=f.id))
    a.store.add_phrase(Phrase("Keep", "y", folder_id=a.root))
    a.sync()
    b.sync()
    a.store.delete_phrase(a.phrases()["Keep"].id)
    a.store.delete_folder(f.id)
    assert a.sync().deleted == 3                      # the phrase, its folder and the phrase in it
    kept = b.phrases()["Gone"]
    kept.content = "edited by b before it was deleted"
    b.store.update_phrase(kept)
    b.sync()
    ph = b.phrases()
    assert "Keep" not in ph and ph["Gone"].content.startswith("edited by b")
    assert ph["Gone"].folder_id == b.root                              # rescued from the deleted folder
    a.sync()
    assert a.phrases()["Gone"].content.startswith("edited by b")       # and shared again


def test_moving_a_phrase_out_of_shared_deletes_it_there(two):
    a, b = two
    a.store.add_phrase(Phrase("Move", "m", folder_id=a.root))
    a.sync()
    b.sync()
    p = a.phrases()["Move"]
    p.folder_id = None
    a.store.update_phrase(p)
    a.sync()
    b.sync()
    assert "Move" not in b.phrases() and "Move" in a.phrases()


def test_deleting_the_local_shared_folder_deletes_nothing_on_the_server(two):
    a, b = two
    a.store.add_phrase(Phrase("Precious", "p", folder_id=a.root))
    a.sync()
    a.store.delete_folder(a.root)                      # the user removes the whole Shared folder
    res = a.sync()
    assert res.deleted == 0 and a.phrases()["Precious"].folder_id == a.root   # pulled again
    b.sync()
    assert "Precious" in b.phrases()


def test_shared_phrases_arrive_even_when_editing_is_disabled(two):
    a, b = two
    a.store.add_phrase(Phrase("Policy", "from IT", folder_id=a.root))
    a.sync()
    root = b.root
    policy.set_current(policy.parse("editing_disabled = true", "t"))
    b.sync()
    assert b.phrases()["Policy"].folder_id == root


# ---------------------------------------------------------------- dialects and connections
def test_sql_server_dialect():
    d = DIALECTS["sqlserver"]
    assert d.create_table("pf_x", "a INT").startswith("IF OBJECT_ID(N'pf_x', N'U') IS NULL CREATE TABLE pf_x")
    assert d.insert_returning_id("pf_phrases", ["a", "b"]) == \
        "INSERT INTO pf_phrases (a, b) OUTPUT INSERTED.id VALUES (?, ?)"
    assert "NVARCHAR(MAX)" in " ".join(d.schema()) and d.whoami == "SELECT SUSER_SNAME()"
    p = DIALECTS["postgresql"]
    assert p.sql("SELECT ? WHERE x = ?") == "SELECT %s WHERE x = %s"
    assert p.insert_returning_id("t", ["a"]) == "INSERT INTO t (a) VALUES (%s) RETURNING id"


def test_connection_strings():
    cs = sc.sqlserver_connection_string("sql01\\PHRASES", "PhraseForge", "windows", port="1433")
    assert cs == ("DRIVER={ODBC Driver 18 for SQL Server};SERVER=sql01\\PHRASES,1433;DATABASE=PhraseForge;"
                  "Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=no;APP=PhraseForge")
    cs = sc.sqlserver_connection_string("db", "Phrases DB", "password", "ali", "p;w}d", trust_cert=True)
    assert "DATABASE={Phrases DB}" in cs and "UID=ali" in cs and "PWD={p;w}}d}" in cs
    assert "TrustServerCertificate=yes" in cs
    old = sc.sqlserver_connection_string("db", "x", "windows", encrypt=False, driver="SQL Server")
    assert "Encrypt" not in old
    with pytest.raises(SharedError, match="cannot encrypt"):      # R37: never silently unencrypted
        sc.sqlserver_connection_string("db", "x", "windows", driver="SQL Server")
    assert sc.pick_driver(["SQL Server", "ODBC Driver 17 for SQL Server"]) == "ODBC Driver 17 for SQL Server"
    with pytest.raises(SharedError, match="ODBC Driver 18"):
        sc.pick_driver([])
    pg = sc.postgresql_params("pg01", "phrases", "password", "ali", "secret", "5433")
    assert pg["user"] == "ali" and pg["password"] == "secret" and pg["port"] == 5433
    assert pg["sslmode"] == "verify-full"                           # R37: the certificate is checked
    assert sc.postgresql_params("pg01", "p", "windows", trust_cert=True)["sslmode"] == "require"
    win = sc.postgresql_params("pg01", "phrases", "windows", encrypt=False)
    assert "password" not in win and win["user"] and win["sslmode"] == "prefer"


def test_connect_checks_the_settings():
    vals = {}
    get = lambda k, d="": vals.get(k, d)
    with pytest.raises(SharedError, match="server"):
        sc.connect(get)
    vals.update({"shared.server": "s", "shared.database": "d", "shared.auth": "password"})
    with pytest.raises(SharedError, match="user name"):
        sc.connect(get)
    vals.update({"shared.engine": "oracle"})
    with pytest.raises(SharedError, match="unknown"):
        sc.connect(get)
    vals.update({"shared.engine": "postgresql", "shared.user": "u"})

    def boom():
        raise OSError("connection refused")
    with pytest.raises(SharedError, match="Could not connect to PostgreSQL on s: connection refused"):
        sc.connect(get, {"postgresql": boom})


@pytest.mark.skipif(not PG, reason="PHRASEFORGE_TEST_PG not set")
def test_postgresql_password_is_checked_by_the_server():
    base = dict(x.split("=", 1) for x in PG.split())
    vals = {"shared.engine": "postgresql", "shared.server": base.get("host", "127.0.0.1"),
            "shared.port": base.get("port", "5432"), "shared.database": "postgres", "shared.auth": "password",
            "shared.user": "bob", "shared.password": "wrong", "shared.encrypt": "0"}
    with pytest.raises(SharedError, match="password authentication failed"):
        sc.connect(lambda k, d="": vals.get(k, d))
    vals["shared.password"] = "bob-pw"
    s = sc.connect(lambda k, d="": vals.get(k, d))
    assert s.user() == "bob"
    s.close()


# ---------------------------------------------------------------- service and dialog
def _settings(store):
    for k, v in {"shared.enabled": "1", "shared.engine": "postgresql", "shared.server": "s",
                 "shared.database": "d", "shared.auth": "windows"}.items():
        store.set_setting(k, v)


def test_service_sync_create_tables_and_errors(tmp_path, monkeypatch):
    path = tmp_path / "svc.db"
    monkeypatch.setattr(service, "connect",
                        lambda setting, connectors=None: SharedServer(sqlite3.connect(str(path)), "sqlite", "me"))
    store = Store(":memory:")
    _settings(store)
    assert service.enabled(store) and service.interval_s(store) == 60
    store.set_setting("shared.interval", "5")
    assert service.interval_s(store) == 15
    with pytest.raises(SharedError, match="Create tables"):
        service.sync(store)
    assert service.create_tables(store) == "me"
    assert service.test_connection(store) == ("me", True)
    store.add_phrase(Phrase("x", "y", folder_id=Mirror(store, SharedServer(sqlite3.connect(":memory:"), "sqlite",
                                                                            "me")).root_id()))
    res = service.sync(store)
    assert res.pushed == 1 and store.setting("shared.last_sync")
    lock = service._lock(store)
    lock.acquire()
    assert service.sync(store) is None                 # one sync at a time
    lock.release()


def test_password_is_stored_sealed_and_kept_on_this_pc():
    from phraseforge.db import SECRET_SETTINGS, is_device_setting
    assert "shared.password" in SECRET_SETTINGS and is_device_setting("shared.server")


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_dialog_saves_tests_creates_tables_and_syncs(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from phraseforge.ui.shared_dialog import SharedDialog
    path = tmp_path / "dlg.db"
    seen = []

    def fake_connect(setting, connectors=None):
        seen.append((setting("shared.engine", ""), setting("shared.auth", ""), setting("shared.password", "")))
        return SharedServer(sqlite3.connect(str(path)), "sqlite", "ali")
    monkeypatch.setattr(service, "connect", fake_connect)
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2])))
    store = Store(":memory:")
    d = SharedDialog(store)
    assert not d.user.isEnabled()                      # Windows sign-in by default
    d.engine.setCurrentIndex(d.engine.findData("postgresql"))
    d.auth.setCurrentIndex(d.auth.findData("password"))
    assert d.user.isEnabled()
    d.server.setText("pg01")
    d.user.setText("ali")
    d.password.setText("s3cret")
    d.enabled.setChecked(True)
    d.test()
    assert "do not exist yet" in d.status.text() and seen[-1] == ("postgresql", "password", "s3cret")
    d.sync_now()
    assert warned and "Create tables" in warned[-1]
    d.create_tables()
    assert "ready" in d.status.text()
    res = d.sync_now()
    assert res is not None and "Connected as ali" in d.status.text()
    d.accept()
    assert store.setting("shared.enabled") == "1" and store.setting("shared.server") == "pg01"
    raw = store.conn.execute("SELECT value FROM settings WHERE key='shared.password'").fetchone()[0]
    assert raw != "s3cret" and store.setting("shared.password") == "s3cret"


def test_shared_database_button(app):
    from phraseforge.ui.main_window import MainWindow
    w = MainWindow(Store(":memory:"))
    assert "Shared database" in w.ribbon.tabs["phrases"].groups["Sync"].buttons


def test_concurrent_writers_get_distinct_revisions_and_nothing_is_missed(backend):
    import threading
    first = backend(backend.users[0])
    fid, start = first.create_folder("Busy", None)
    first.close()
    errors = []

    def writer(user, n):
        s = backend(user)
        if s.d.name == "sqlite":
            s.conn.execute("PRAGMA busy_timeout = 10000")
        try:
            for i in range(n):
                s.create_phrase(RemotePhrase(0, fid, f"{user}-{i}", "x"))
        except Exception as e:                       # pragma: no cover - reported below
            errors.append(e)
        finally:
            s.close()
    threads = [threading.Thread(target=writer, args=(u, 25)) for u in backend.users]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    reader = backend(backend.users[0])
    _f, phrases, top = reader.changes_since(start)
    revs = [p.rev for p in phrases]
    assert len(phrases) == 50 and len(set(revs)) == 50 and top == start + 50 and sorted(revs) == revs
    reader.close()
