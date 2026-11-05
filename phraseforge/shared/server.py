"""The shared phrase database on a server: SQL Server or PostgreSQL (SQLite for tests).

Several PhraseForge clients read and write the same folders and phrases there
(PhraseExpress's "SQL client" mode, PRD FR-SYN-05, gap G-25). Every client keeps
a local copy (shared/mirror.py) and exchanges only what changed:

  pf_rev      one row; its counter grows by one for every change. A writer
              increments it inside its own transaction, so writers take turns
              on that row and revisions become visible in the order they were
              given: a client that has seen revision N needs only rows > N.
  pf_folders  id, parent_id, name, sort_order, rev, deleted, modified_by, modified
  pf_phrases  id, folder_id, description, content, content_format, triggers (JSON),
              rev, deleted, modified_by, modified

Rows are never removed, only marked deleted, so other clients learn of deletions.
Updates name the revision the writer last saw; when someone else changed the row
in between, Conflict is raised and nothing is written.

Who made a change is what the database says about the connection (SQL Server
SUSER_SNAME(), PostgreSQL current_user): a Windows login (integrated security)
or a database login with a password. The database checks the password, so
PhraseForge stores no password hashes of its own.

Stage 2 adds
  pf_acl      folder_id (NULL = the whole database), principal (a login, a group /
              role, or "*" for everyone), kind ('user'/'group'), can_read,
              can_write, can_admin (only at the top level: may change pf_acl)
  pf_history  one row per change: who, when, and the folder or phrase as it was
              after the change, so an earlier version can be restored

The nearest folder (the folder itself, then its parents, then the top level)
that has entries for the login or one of its groups decides; administrators
may do everything. These permissions are applied by PhraseForge, not by the
database: anyone who can connect with another program can still read and
change the tables. Use database permissions for that (docs/shared-database.md).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

SCHEMA_VERSION = 2          # 1: folders and phrases; 2: + pf_acl (permissions), pf_history

EVERYONE = "*"              # pf_acl principal that matches every login


class Conflict(Exception):
    """The row changed on the server since the writer last saw it."""


class PermissionDenied(Exception):
    """The folder's permissions do not allow this login to do that."""


class SharedError(Exception):
    """The shared database is not reachable or not set up."""


# ---------------------------------------------------------------- dialects
@dataclass(frozen=True)
class Dialect:
    name: str
    qmark: bool                  # parameters written as ? (pyodbc, sqlite3) or %s (psycopg)
    identity: str                # primary key column type
    text: str                    # unlimited text
    short: str                   # up to 400 characters
    whoami: str                  # SQL returning the login of this connection

    def sql(self, statement: str) -> str:
        return statement if self.qmark else statement.replace("?", "%s")

    def create_table(self, table: str, body: str) -> str:
        if self.name == "sqlserver":
            return f"IF OBJECT_ID(N'{table}', N'U') IS NULL CREATE TABLE {table} ({body})"
        return f"CREATE TABLE IF NOT EXISTS {table} ({body})"

    def insert_returning_id(self, table: str, cols: list[str]) -> str:
        marks = ", ".join("?" for _ in cols)
        names = ", ".join(cols)
        if self.name == "sqlserver":
            return self.sql(f"INSERT INTO {table} ({names}) OUTPUT INSERTED.id VALUES ({marks})")
        return self.sql(f"INSERT INTO {table} ({names}) VALUES ({marks}) RETURNING id")

    def schema(self) -> list[str]:
        t, s, idc = self.text, self.short, self.identity
        common = (f"rev BIGINT NOT NULL, deleted SMALLINT NOT NULL DEFAULT 0, modified_by {s}, "
                  "modified VARCHAR(40)")
        return [
            self.create_table("pf_acl", f"id {idc}, folder_id BIGINT, principal {s} NOT NULL, "
                                        "kind VARCHAR(16) NOT NULL DEFAULT 'user', can_read SMALLINT NOT NULL DEFAULT 1, "
                                        "can_write SMALLINT NOT NULL DEFAULT 0, can_admin SMALLINT NOT NULL DEFAULT 0, "
                                        f"{common}"),
            self.create_table("pf_history", f"id {idc}, item_kind VARCHAR(16) NOT NULL, item_id BIGINT NOT NULL, "
                                            f"rev BIGINT NOT NULL, action VARCHAR(16) NOT NULL, parent_id BIGINT, "
                                            f"name {s}, content {t}, content_format VARCHAR(16), triggers {t}, "
                                            f"changed_by {s}, changed VARCHAR(40)"),
            self.create_table("pf_meta", "k VARCHAR(64) NOT NULL PRIMARY KEY, v VARCHAR(400)"),
            self.create_table("pf_rev", "id INT NOT NULL PRIMARY KEY, rev BIGINT NOT NULL"),
            self.create_table("pf_folders", f"id {idc}, parent_id BIGINT, name {s} NOT NULL, "
                                            f"sort_order INT NOT NULL DEFAULT 0, {common}"),
            self.create_table("pf_phrases", f"id {idc}, folder_id BIGINT, description {s} NOT NULL, "
                                            f"content {t}, content_format VARCHAR(16) NOT NULL DEFAULT 'text', "
                                            f"triggers {t}, {common}"),
        ]


DIALECTS = {
    "sqlserver": Dialect("sqlserver", True, "BIGINT IDENTITY(1,1) NOT NULL PRIMARY KEY", "NVARCHAR(MAX)",
                         "NVARCHAR(400)", "SELECT SUSER_SNAME()"),
    "postgresql": Dialect("postgresql", False, "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY", "TEXT",
                          "VARCHAR(400)", "SELECT current_user"),
    "sqlite": Dialect("sqlite", True, "INTEGER PRIMARY KEY AUTOINCREMENT", "TEXT", "VARCHAR(400)", ""),
}


# ---------------------------------------------------------------- rows
@dataclass
class RemoteFolder:
    id: int
    parent_id: int | None
    name: str
    sort_order: int = 0
    rev: int = 0
    deleted: bool = False
    modified_by: str = ""


@dataclass
class RemotePhrase:
    id: int
    folder_id: int | None
    description: str
    content: str = ""
    content_format: str = "text"
    triggers: list[dict] = field(default_factory=list)
    rev: int = 0
    deleted: bool = False
    modified_by: str = ""


@dataclass
class AclEntry:
    id: int
    folder_id: int | None
    principal: str
    kind: str = "user"
    can_read: bool = True
    can_write: bool = False
    can_admin: bool = False
    rev: int = 0


@dataclass
class HistoryEntry:
    id: int
    item_kind: str
    item_id: int
    rev: int
    action: str                 # create | update | delete | restore
    parent_id: int | None
    name: str
    content: str
    content_format: str
    triggers: list[dict]
    changed_by: str
    changed: str


@dataclass(frozen=True)
class Rights:
    read: bool
    write: bool


# SQL that lists the groups / roles of the current login
GROUPS_SQL = {
    "sqlserver": "SELECT name FROM sys.login_token WHERE type IN ('WINDOWS GROUP', 'SERVER ROLE')",
    "postgresql": "SELECT rolname FROM pg_roles WHERE pg_has_role(current_user, oid, 'member') "
                  "AND rolname <> current_user",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- server
class SharedServer:
    """One connection to the shared database (DB-API 2 connection + dialect)."""

    def __init__(self, conn, dialect: str | Dialect, user: str = "", groups: list[str] | None = None):
        self.conn = conn
        self.d = DIALECTS[dialect] if isinstance(dialect, str) else dialect
        self._user = user
        self._groups = groups                       # None: ask the server
        self._acl_cache: tuple[int, list[AclEntry]] | None = None

    # ---- basics
    def _exec(self, cur, statement: str, params=()):
        cur.execute(self.d.sql(statement), tuple(params))
        return cur

    def user(self) -> str:
        """The login the database sees for this connection."""
        if not self._user and self.d.whoami:
            cur = self.conn.cursor()
            try:
                cur.execute(self.d.whoami)
                self._user = str(cur.fetchone()[0] or "")
            finally:
                cur.close()
            self.conn.commit()
        return self._user

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def ready(self) -> bool:
        """Whether the tables exist (created by ensure_schema)."""
        cur = self.conn.cursor()
        try:
            cur.execute("SELECT v FROM pf_meta WHERE k = 'schema'")
            row = cur.fetchone()
            return row is not None and int(row[0]) >= SCHEMA_VERSION
        except Exception:
            return False
        finally:
            cur.close()
            try:
                self.conn.rollback()
            except Exception:
                pass

    def ensure_schema(self) -> None:
        """Create the tables if they are missing (needs the right to create tables)."""
        self.user()                                  # before the transaction: user() commits
        cur = self.conn.cursor()
        try:
            for statement in self.d.schema():
                cur.execute(statement)
            self._exec(cur, "SELECT COUNT(*) FROM pf_rev")
            if not cur.fetchone()[0]:
                self._exec(cur, "INSERT INTO pf_rev (id, rev) VALUES (1, 0)")
            self._exec(cur, "SELECT v FROM pf_meta WHERE k = 'schema'")
            row = cur.fetchone()
            if row is None:
                self._exec(cur, "INSERT INTO pf_meta (k, v) VALUES ('schema', ?)", (str(SCHEMA_VERSION),))
            elif int(row[0]) > SCHEMA_VERSION:
                raise SharedError(f"the shared database was set up by a newer PhraseForge (schema {row[0]})")
            elif int(row[0]) < SCHEMA_VERSION:
                self._exec(cur, "UPDATE pf_meta SET v = ? WHERE k = 'schema'", (str(SCHEMA_VERSION),))
            self._exec(cur, "SELECT COUNT(*) FROM pf_acl WHERE deleted = 0")
            if not cur.fetchone()[0]:
                # first set-up (or an upgrade from stage 1): whoever creates the tables
                # administers them, and everyone keeps reading and writing as before
                rev = self._next_rev(cur)
                for principal, kind, w, a in ((self.user(), "user", 1, 1), (EVERYONE, "group", 1, 0)):
                    cur.execute(self.d.insert_returning_id(
                        "pf_acl", ["folder_id", "principal", "kind", "can_read", "can_write", "can_admin", "rev",
                                   "deleted", "modified_by", "modified"]),
                        (None, principal, kind, 1, w, a, rev, 0, self.user(), _now()))
                    cur.fetchone()
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cur.close()

    def _next_rev(self, cur) -> int:
        # The UPDATE locks the counter row until commit: writers take turns here.
        self._exec(cur, "UPDATE pf_rev SET rev = rev + 1 WHERE id = 1")
        self._exec(cur, "SELECT rev FROM pf_rev WHERE id = 1")
        return int(cur.fetchone()[0])

    def current_rev(self) -> int:
        cur = self.conn.cursor()
        try:
            self._exec(cur, "SELECT rev FROM pf_rev WHERE id = 1")
            row = cur.fetchone()
            return int(row[0]) if row else 0
        finally:
            cur.close()
            self.conn.commit()

    def _write(self, fn):
        self.user()                                  # resolved first: it commits, which would end the transaction
        self.groups()
        cur = self.conn.cursor()
        try:
            out = fn(cur)
            self.conn.commit()
            return out
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cur.close()

    # ---- who may do what
    def groups(self) -> list[str]:
        """Groups / roles of this login, as the server reports them."""
        if self._groups is None:
            sql = GROUPS_SQL.get(self.d.name)
            found: list[str] = []
            if sql:
                cur = self.conn.cursor()
                try:
                    cur.execute(sql)
                    found = [str(r[0]) for r in cur.fetchall() if r[0]]
                except Exception:
                    found = []
                finally:
                    cur.close()
                    try:
                        self.conn.commit()
                    except Exception:
                        pass
            self._groups = found
        return self._groups

    def _principals(self) -> set[str]:
        return {self.user().casefold(), EVERYONE} | {g.casefold() for g in self.groups()}

    def acl(self, cur=None) -> list[AclEntry]:
        own = cur is None
        cur = cur or self.conn.cursor()
        try:
            self._exec(cur, "SELECT id, folder_id, principal, kind, can_read, can_write, can_admin, rev FROM pf_acl "
                            "WHERE deleted = 0 ORDER BY id")
            return [AclEntry(int(r[0]), None if r[1] is None else int(r[1]), r[2] or "", r[3] or "user",
                             bool(r[4]), bool(r[5]), bool(r[6]), int(r[7])) for r in cur.fetchall()]
        finally:
            if own:
                cur.close()
                self.conn.commit()

    def _parents(self, cur) -> dict[int, int | None]:
        self._exec(cur, "SELECT id, parent_id FROM pf_folders WHERE deleted = 0")
        return {int(r[0]): None if r[1] is None else int(r[1]) for r in cur.fetchall()}

    def is_admin(self, cur=None, acl: list[AclEntry] | None = None) -> bool:
        mine = self._principals()
        entries = acl if acl is not None else self.acl(cur)
        return any(e.can_admin and e.folder_id is None and e.principal.casefold() in mine for e in entries)

    def rights_for(self, folder_id: int | None, acl: list[AclEntry], parents: dict[int, int | None]) -> Rights:
        """Rights of this login in a folder (None = the top level)."""
        mine = self._principals()
        if self.is_admin(acl=acl):
            return Rights(True, True)
        by_folder: dict[int | None, list[AclEntry]] = {}
        for e in acl:
            if e.principal.casefold() in mine:
                by_folder.setdefault(e.folder_id, []).append(e)
        node, seen = folder_id, set()
        while True:
            if node in by_folder:
                es = by_folder[node]
                return Rights(any(e.can_read or e.can_write for e in es), any(e.can_write for e in es))
            if node is None or node in seen:
                return Rights(False, False)
            seen.add(node)
            node = parents.get(node)

    def rights(self) -> tuple[dict[int | None, Rights], bool]:
        """({folder id or None: rights}, is administrator) for every live folder."""
        cur = self.conn.cursor()
        try:
            acl, parents = self.acl(cur), self._parents(cur)
            out = {fid: self.rights_for(fid, acl, parents) for fid in list(parents) + [None]}
            return out, self.is_admin(acl=acl)
        finally:
            cur.close()
            self.conn.commit()

    def _require_write(self, cur, folder_id: int | None) -> None:
        if not self.rights_for(folder_id, self.acl(cur), self._parents(cur)).write:
            raise PermissionDenied(f"{self.user()} may not change folder {folder_id if folder_id is not None else '(top)'}")

    def _history(self, cur, kind: str, item_id: int, rev: int, action: str, parent_id, name: str,
                 content: str = "", content_format: str = "", triggers=None) -> None:
        self._exec(cur, "INSERT INTO pf_history (item_kind, item_id, rev, action, parent_id, name, content, "
                        "content_format, triggers, changed_by, changed) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (kind, item_id, rev, action, parent_id, name, content, content_format,
                    json.dumps(triggers or [], ensure_ascii=False), self.user(), _now()))

    def _folder_of_phrase(self, cur, phrase_id: int) -> int | None:
        self._exec(cur, "SELECT folder_id FROM pf_phrases WHERE id = ?", (phrase_id,))
        r = cur.fetchone()
        if r is None:
            raise Conflict(f"phrase {phrase_id} does not exist")
        return None if r[0] is None else int(r[0])

    def _parent_of_folder(self, cur, folder_id: int) -> int | None:
        self._exec(cur, "SELECT parent_id FROM pf_folders WHERE id = ?", (folder_id,))
        r = cur.fetchone()
        if r is None:
            raise Conflict(f"folder {folder_id} does not exist")
        return None if r[0] is None else int(r[0])

    # ---- reading
    def acl_rev(self) -> int:
        """Newest revision of any permission entry (deleted ones included)."""
        cur = self.conn.cursor()
        try:
            self._exec(cur, "SELECT MAX(rev) FROM pf_acl")
            r = cur.fetchone()
            return int(r[0]) if r and r[0] is not None else 0
        finally:
            cur.close()
            self.conn.commit()

    def changes_since(self, rev: int) -> tuple[list[RemoteFolder], list[RemotePhrase], int]:
        """Folders and phrases changed after revision rev (deleted ones included), and the
        newest revision included in the answer. Only what this login may read is returned."""
        cur = self.conn.cursor()
        try:
            self._exec(cur, "SELECT rev FROM pf_rev WHERE id = 1")
            top = int(cur.fetchone()[0])
            acl, parents = self.acl(cur), self._parents(cur)
            readable = {fid for fid in list(parents) + [None] if self.rights_for(fid, acl, parents).read}
            self._exec(cur, "SELECT id, parent_id, name, sort_order, rev, deleted, modified_by FROM pf_folders "
                            "WHERE rev > ? AND rev <= ? ORDER BY rev", (rev, top))
            folders = [RemoteFolder(int(r[0]), None if r[1] is None else int(r[1]), r[2] or "", int(r[3] or 0),
                                    int(r[4]), bool(r[5]), r[6] or "") for r in cur.fetchall()]
            folders = [f for f in folders if f.deleted or f.id in readable]
            self._exec(cur, "SELECT id, folder_id, description, content, content_format, triggers, rev, deleted, "
                            "modified_by FROM pf_phrases WHERE rev > ? AND rev <= ? ORDER BY rev", (rev, top))
            phrases = []
            for r in cur.fetchall():
                try:
                    trig = json.loads(r[5] or "[]")
                except ValueError:
                    trig = []
                rp = RemotePhrase(int(r[0]), None if r[1] is None else int(r[1]), r[2] or "", r[3] or "",
                                  r[4] or "text", trig if isinstance(trig, list) else [], int(r[6]), bool(r[7]),
                                  r[8] or "")
                if rp.deleted or rp.folder_id in readable:
                    phrases.append(rp)
            return folders, phrases, top
        finally:
            cur.close()
            self.conn.commit()

    # ---- folders
    def create_folder(self, name: str, parent_id: int | None, sort_order: int = 0) -> tuple[int, int]:
        """(id, rev) of the new folder."""
        def go(cur):
            self._require_write(cur, parent_id)
            rev = self._next_rev(cur)
            cur.execute(self.d.insert_returning_id(
                "pf_folders", ["parent_id", "name", "sort_order", "rev", "deleted", "modified_by", "modified"]),
                (parent_id, name, sort_order, rev, 0, self.user(), _now()))
            fid = int(cur.fetchone()[0])
            self._history(cur, "folder", fid, rev, "create", parent_id, name)
            return fid, rev
        return self._write(go)

    def update_folder(self, folder_id: int, expected_rev: int, name: str, parent_id: int | None,
                      sort_order: int = 0) -> int:
        def go(cur):
            self._require_write(cur, folder_id)
            if parent_id != self._parent_of_folder(cur, folder_id):
                self._require_write(cur, parent_id)          # moving: the new place must be writable too
            rev = self._next_rev(cur)
            self._exec(cur, "UPDATE pf_folders SET name = ?, parent_id = ?, sort_order = ?, rev = ?, "
                            "modified_by = ?, modified = ? WHERE id = ? AND rev = ? AND deleted = 0",
                       (name, parent_id, sort_order, rev, self.user(), _now(), folder_id, expected_rev))
            if cur.rowcount != 1:
                raise Conflict(f"folder {folder_id} changed on the server")
            self._history(cur, "folder", folder_id, rev, "update", parent_id, name)
            return rev
        return self._write(go)

    def delete_folder(self, folder_id: int, expected_rev: int) -> int:
        """Mark the folder, its subfolders and their phrases deleted."""
        def go(cur):
            self._require_write(cur, folder_id)
            rev = self._next_rev(cur)
            self._exec(cur, "UPDATE pf_folders SET deleted = 1, rev = ?, modified_by = ?, modified = ? "
                            "WHERE id = ? AND rev = ? AND deleted = 0",
                       (rev, self.user(), _now(), folder_id, expected_rev))
            if cur.rowcount != 1:
                raise Conflict(f"folder {folder_id} changed on the server")
            self._history(cur, "folder", folder_id, rev, "delete", None, "")
            todo, seen = [folder_id], {folder_id}
            while todo:
                fid = todo.pop()
                self._exec(cur, "UPDATE pf_phrases SET deleted = 1, rev = ?, modified_by = ?, modified = ? "
                                "WHERE folder_id = ? AND deleted = 0", (rev, self.user(), _now(), fid))
                self._exec(cur, "SELECT id FROM pf_folders WHERE parent_id = ? AND deleted = 0", (fid,))
                children = [int(r[0]) for r in cur.fetchall() if int(r[0]) not in seen]
                for c in children:
                    self._exec(cur, "UPDATE pf_folders SET deleted = 1, rev = ?, modified_by = ?, modified = ? "
                                    "WHERE id = ?", (rev, self.user(), _now(), c))
                seen.update(children)
                todo += children
            return rev
        return self._write(go)

    # ---- phrases
    def create_phrase(self, p: RemotePhrase) -> tuple[int, int]:
        def go(cur):
            self._require_write(cur, p.folder_id)
            rev = self._next_rev(cur)
            cur.execute(self.d.insert_returning_id(
                "pf_phrases", ["folder_id", "description", "content", "content_format", "triggers", "rev",
                               "deleted", "modified_by", "modified"]),
                (p.folder_id, p.description, p.content, p.content_format,
                 json.dumps(p.triggers, ensure_ascii=False), rev, 0, self.user(), _now()))
            pid = int(cur.fetchone()[0])
            self._history(cur, "phrase", pid, rev, "create", p.folder_id, p.description, p.content,
                          p.content_format, p.triggers)
            return pid, rev
        return self._write(go)

    def update_phrase(self, p: RemotePhrase, expected_rev: int) -> int:
        def go(cur):
            old_folder = self._folder_of_phrase(cur, p.id)
            self._require_write(cur, old_folder)
            if p.folder_id != old_folder:
                self._require_write(cur, p.folder_id)
            rev = self._next_rev(cur)
            self._exec(cur, "UPDATE pf_phrases SET folder_id = ?, description = ?, content = ?, content_format = ?, "
                            "triggers = ?, rev = ?, modified_by = ?, modified = ? "
                            "WHERE id = ? AND rev = ? AND deleted = 0",
                       (p.folder_id, p.description, p.content, p.content_format,
                        json.dumps(p.triggers, ensure_ascii=False), rev, self.user(), _now(), p.id, expected_rev))
            if cur.rowcount != 1:
                raise Conflict(f"phrase {p.id} changed on the server")
            self._history(cur, "phrase", p.id, rev, "update", p.folder_id, p.description, p.content,
                          p.content_format, p.triggers)
            return rev
        return self._write(go)

    def delete_phrase(self, phrase_id: int, expected_rev: int) -> int:
        def go(cur):
            self._require_write(cur, self._folder_of_phrase(cur, phrase_id))
            rev = self._next_rev(cur)
            self._exec(cur, "UPDATE pf_phrases SET deleted = 1, rev = ?, modified_by = ?, modified = ? "
                            "WHERE id = ? AND rev = ? AND deleted = 0",
                       (rev, self.user(), _now(), phrase_id, expected_rev))
            if cur.rowcount != 1:
                raise Conflict(f"phrase {phrase_id} changed on the server")
            self._history(cur, "phrase", phrase_id, rev, "delete", None, "")
            return rev
        return self._write(go)

    def get_phrase(self, phrase_id: int) -> RemotePhrase | None:
        """The phrase as it is now on the server (None if it never existed or may not be read)."""
        cur = self.conn.cursor()
        try:
            self._exec(cur, "SELECT id, folder_id, description, content, content_format, triggers, rev, deleted, "
                            "modified_by FROM pf_phrases WHERE id = ?", (phrase_id,))
            r = cur.fetchone()
            if r is None:
                return None
            folder = None if r[1] is None else int(r[1])
            if not self.rights_for(folder, self.acl(cur), self._parents(cur)).read:
                return None
            try:
                trig = json.loads(r[5] or "[]")
            except ValueError:
                trig = []
            return RemotePhrase(int(r[0]), folder, r[2] or "", r[3] or "", r[4] or "text",
                                trig if isinstance(trig, list) else [], int(r[6]), bool(r[7]), r[8] or "")
        finally:
            cur.close()
            self.conn.commit()

    # ---- history
    def history(self, kind: str, item_id: int) -> list[HistoryEntry]:
        """Versions of a phrase or folder, newest first (empty if it may not be read)."""
        cur = self.conn.cursor()
        try:
            if kind == "phrase":
                self._exec(cur, "SELECT folder_id FROM pf_phrases WHERE id = ?", (item_id,))
            else:
                self._exec(cur, "SELECT parent_id FROM pf_folders WHERE id = ?", (item_id,))
            r = cur.fetchone()
            if r is None:
                return []
            place = None if r[0] is None else int(r[0])
            if kind == "folder":
                place = item_id
            if not self.rights_for(place, self.acl(cur), self._parents(cur)).read:
                return []
            self._exec(cur, "SELECT id, item_kind, item_id, rev, action, parent_id, name, content, content_format, "
                            "triggers, changed_by, changed FROM pf_history WHERE item_kind = ? AND item_id = ? "
                            "ORDER BY rev DESC, id DESC", (kind, item_id))
            out = []
            for h in cur.fetchall():
                try:
                    trig = json.loads(h[9] or "[]")
                except ValueError:
                    trig = []
                out.append(HistoryEntry(int(h[0]), h[1], int(h[2]), int(h[3]), h[4], None if h[5] is None else int(h[5]),
                                        h[6] or "", h[7] or "", h[8] or "text", trig if isinstance(trig, list) else [],
                                        h[10] or "", h[11] or ""))
            return out
        finally:
            cur.close()
            self.conn.commit()

    def restore_phrase(self, history_id: int) -> int:
        """Make an earlier version of a phrase the current one (also brings a deleted phrase back).
        Returns the new revision."""
        def go(cur):
            self._exec(cur, "SELECT item_kind, item_id, action, parent_id, name, content, content_format, triggers "
                            "FROM pf_history WHERE id = ?", (history_id,))
            h = cur.fetchone()
            if h is None or h[0] != "phrase" or h[2] == "delete":
                raise SharedError("this version cannot be restored")
            pid, folder = int(h[1]), None if h[3] is None else int(h[3])
            self._require_write(cur, folder)
            self._require_write(cur, self._folder_of_phrase(cur, pid))
            self._exec(cur, "SELECT COUNT(*) FROM pf_folders WHERE id = ? AND deleted = 0", (folder,))
            if folder is not None and not cur.fetchone()[0]:
                raise SharedError("the folder of that version was deleted")
            rev = self._next_rev(cur)
            self._exec(cur, "UPDATE pf_phrases SET folder_id = ?, description = ?, content = ?, content_format = ?, "
                            "triggers = ?, deleted = 0, rev = ?, modified_by = ?, modified = ? WHERE id = ?",
                       (folder, h[4], h[5], h[6], h[7], rev, self.user(), _now(), pid))
            try:
                trig = json.loads(h[7] or "[]")
            except ValueError:
                trig = []
            self._history(cur, "phrase", pid, rev, "restore", folder, h[4] or "", h[5] or "", h[6] or "text", trig)
            return rev
        return self._write(go)

    # ---- permissions (administrators)
    def _require_admin(self, cur) -> None:
        if not self.is_admin(cur):
            raise PermissionDenied(f"{self.user()} is not an administrator of the shared database")

    def add_acl(self, e: AclEntry) -> int:
        if e.can_admin and e.folder_id is not None:
            raise SharedError("administrators are set for the whole database, not for one folder")
        if e.kind not in ("user", "group"):
            raise SharedError("kind must be user or group")

        def go(cur):
            self._require_admin(cur)
            rev = self._next_rev(cur)
            cur.execute(self.d.insert_returning_id(
                "pf_acl", ["folder_id", "principal", "kind", "can_read", "can_write", "can_admin", "rev", "deleted",
                           "modified_by", "modified"]),
                (e.folder_id, e.principal.strip(), e.kind, int(e.can_read or e.can_write), int(e.can_write),
                 int(e.can_admin), rev, 0, self.user(), _now()))
            return int(cur.fetchone()[0])
        return self._write(go)

    def remove_acl(self, acl_id: int) -> None:
        def go(cur):
            self._require_admin(cur)
            rev = self._next_rev(cur)
            self._exec(cur, "UPDATE pf_acl SET deleted = 1, rev = ?, modified_by = ?, modified = ? "
                            "WHERE id = ? AND deleted = 0", (rev, self.user(), _now(), acl_id))
            if cur.rowcount != 1:
                raise Conflict(f"permission entry {acl_id} is gone")
            if not any(e.can_admin and e.folder_id is None for e in self.acl(cur)):
                raise SharedError("this would leave the shared database without an administrator")
        self._write(go)
