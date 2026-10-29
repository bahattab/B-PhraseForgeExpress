"""SQLite storage for folders, phrases, triggers, tags, variables, history,
statistics, clipboard history, settings and learning suggestions.

Thread-safety: one Store per thread, or guard with Store.lock. The Store uses
check_same_thread=False plus an RLock so the hook thread can read safely.
"""
from __future__ import annotations

import base64
import functools
import hashlib
import hmac
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable

from phraseforge.models import (
    AutotextMode, ClipboardEntry, Folder, OutputMode, Phrase, Trigger, TriggerKind,
)

SCHEMA_VERSION = 2

# v2: triggers may belong to a phrase, a folder or a special folder, and carry
# PhraseExpress options; phrases get an output target; folders get notes.
TRIGGERS_TABLE = """
CREATE TABLE IF NOT EXISTS {name} (
  id INTEGER PRIMARY KEY,
  phrase_id INTEGER REFERENCES phrases(id) ON DELETE CASCADE,
  folder_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
  special TEXT DEFAULT '',
  kind TEXT NOT NULL, value TEXT NOT NULL, mode TEXT DEFAULT 'delimiter',
  case_sensitive INTEGER DEFAULT 0, word_start_only INTEGER DEFAULT 1, enabled INTEGER DEFAULT 1,
  word_pos TEXT DEFAULT '', exec_mode TEXT DEFAULT '', lead_delim TEXT DEFAULT '',
  trail_delim TEXT DEFAULT '', remove_trailing INTEGER DEFAULT 0, window_scope TEXT DEFAULT '');
"""
TRIGGER_COLUMNS = ("phrase_id", "folder_id", "special", "kind", "value", "mode", "case_sensitive",
                   "word_start_only", "enabled", "word_pos", "exec_mode", "lead_delim", "trail_delim",
                   "remove_trailing", "window_scope")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS folders (
  id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
  name TEXT NOT NULL, sort INTEGER DEFAULT 0, enabled INTEGER DEFAULT 1,
  apps_include TEXT DEFAULT '', apps_exclude TEXT DEFAULT '',
  password_hash TEXT DEFAULT '', show_in_popup INTEGER DEFAULT 1, notes TEXT DEFAULT '',
  output_target TEXT DEFAULT 'current', output_target_arg TEXT DEFAULT '',
  abbrev_prefix TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS phrases (
  id INTEGER PRIMARY KEY, folder_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
  description TEXT NOT NULL, content TEXT DEFAULT '', content_format TEXT DEFAULT 'text',
  output_mode TEXT DEFAULT 'auto', apps_include TEXT DEFAULT '', apps_exclude TEXT DEFAULT '',
  enabled INTEGER DEFAULT 1, sort INTEGER DEFAULT 0, use_count INTEGER DEFAULT 0,
  last_used TEXT, created TEXT, modified TEXT, notes TEXT DEFAULT '',
  output_target TEXT DEFAULT 'current', output_target_arg TEXT DEFAULT '');
""" + TRIGGERS_TABLE.format(name="triggers") + """
CREATE INDEX IF NOT EXISTS ix_triggers_kind ON triggers(kind);
CREATE TABLE IF NOT EXISTS tags (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS phrase_tags (
  phrase_id INTEGER REFERENCES phrases(id) ON DELETE CASCADE,
  tag_id INTEGER REFERENCES tags(id) ON DELETE CASCADE, PRIMARY KEY (phrase_id, tag_id));
CREATE TABLE IF NOT EXISTS vars (scope TEXT, name TEXT, value TEXT, PRIMARY KEY (scope, name));
CREATE TABLE IF NOT EXISTS phrase_history (
  id INTEGER PRIMARY KEY, phrase_id INTEGER, saved TEXT, description TEXT, content TEXT);
CREATE TABLE IF NOT EXISTS usage_log (
  id INTEGER PRIMARY KEY, phrase_id INTEGER, used TEXT, app TEXT, chars INTEGER, trigger TEXT);
CREATE TABLE IF NOT EXISTS clipboard (
  id INTEGER PRIMARY KEY, text TEXT, created TEXT, source_app TEXT DEFAULT '', pinned INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS suggestions (
  text TEXT PRIMARY KEY, count INTEGER DEFAULT 0, last_seen TEXT, dismissed INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS excluded_apps (exe TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS phrase_versions (
  phrase_id INTEGER REFERENCES phrases(id) ON DELETE CASCADE, lang TEXT NOT NULL,
  content TEXT DEFAULT '', content_format TEXT DEFAULT 'text', modified TEXT,
  PRIMARY KEY (phrase_id, lang));
CREATE TABLE IF NOT EXISTS phrase_quarantine (
  phrase_id INTEGER PRIMARY KEY REFERENCES phrases(id) ON DELETE CASCADE,
  origin TEXT DEFAULT 'imported', added TEXT);
CREATE TABLE IF NOT EXISTS sticky_notes (
  id INTEGER PRIMARY KEY, text TEXT DEFAULT '', html TEXT DEFAULT '', color TEXT DEFAULT 'yellow',
  x INTEGER, y INTEGER, w INTEGER DEFAULT 300, h INTEGER DEFAULT 300,
  visible INTEGER DEFAULT 1, on_top INTEGER DEFAULT 0, created TEXT, updated TEXT);
"""

DEFAULT_SETTINGS = {
    "autotext.delimiters": " \t\n.,;:!?)]}'\"",
    "autotext.enabled": "1",
    "popup.hotkey": "ctrl+alt+space",
    "ocr.hotkey": "ctrl+alt+o",
    "clipboard_history.hotkey": "ctrl+alt+v",
    "filesearch.hotkey": "ctrl+alt+f",
    "promptboost.hotkey": "ctrl+alt+b",    # Boost prompt: improve the selected prompt in any program     # Search files (Listary-style launcher)
    "filesearch.enabled": "1",
    "filesearch.roots": "",               # one folder per line; empty = Start menu, Desktop, Documents, Downloads
    "filesearch.refresh_minutes": "30",
    "ocr.language": "Auto",
    "output.paste_threshold": "40",       # AUTO mode pastes text longer than this
    "output.restore_clipboard": "1",
    "clipboard_history.max": "200",
    "clipboard_history.enabled": "1",
    "date.format": "yyyy-MM-dd",
    "time.format": "HH:mm",
    "date.weekend": "sat,sun",
    "learning.enabled": "1",
    "learning.min_length": "12",
    "learning.min_count": "3",
    "ai.provider": "openai",              # openai | anthropic | gemini | openrouter | opencode | kilocode | ollama | gpt4all
    "ai.model": "",
    "ai.openai_key": "",
    "ai.anthropic_key": "",
    "ai.openrouter_key": "",
    "ai.gemini_key": "",
    "ai.opencode_key": "",
    "ai.kilocode_key": "",
    "ai.mistral_key": "",                 # Mistral OCR (PDF/image to Markdown, optional screen OCR engine)
    "ai.ollama_url": "http://localhost:11434",
    "ai.gpt4all_url": "http://localhost:4891/v1",
    "ai.deepl_key": "",
    "ui.theme": "system",
    "ui.language": "en",
    "app.start_with_windows": "0",
    "app.first_run_done": "0",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _parse_dt(v):
    try:
        return datetime.fromisoformat(v) if v else None
    except ValueError:
        return None


# Folder passwords: salted scrypt (stdlib). Stored as "scrypt$n$r$p$salt$hash" (base64).
# Older unsalted SHA-256 hashes (64 hex chars) still verify and are replaced with
# scrypt on the next successful unlock (see needs_rehash).
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 15, 8, 1


def _scrypt(pw: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(pw.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=128 * 1024 * 1024, dklen=32)


def hash_password(pw: str) -> str:
    if not pw:
        return ""
    salt = os.urandom(16)
    h = _scrypt(pw, salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${b64(salt)}${b64(h)}"


def verify_password(pw: str, stored: str) -> bool:
    if not stored:
        return True
    if stored.startswith("scrypt$"):
        try:
            _, n, r, p, salt, h = stored.split("$")
            got = _scrypt(pw, base64.b64decode(salt), int(n), int(r), int(p))
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(got, base64.b64decode(h))
    legacy = hashlib.sha256(("phraseforge:" + pw).encode()).hexdigest()
    return hmac.compare_digest(legacy, stored)


def needs_rehash(stored: str) -> bool:
    return bool(stored) and not stored.startswith(f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}$")


# API keys are encrypted with Windows DPAPI before they are written, so a copied
# database file does not reveal them (other platforms: stored base64-encoded only).
SECRET_SETTINGS = frozenset({"ai.openai_key", "ai.anthropic_key", "ai.openrouter_key", "ai.deepl_key",
                             "ai.gemini_key", "ai.opencode_key", "ai.kilocode_key", "ai.mistral_key",
                             "net.proxy_password"})
_SEALED = "dpapi:"


def _seal(value: str) -> str:
    from phraseforge.cloud.secure import protect
    if not value or value.startswith(_SEALED):
        return value
    return _SEALED + base64.b64encode(protect(value.encode("utf-8"))).decode("ascii")


def _unseal(value: str) -> str:
    from phraseforge.cloud.secure import unprotect
    if not value.startswith(_SEALED):
        return value                      # empty, or saved before encryption existed
    try:
        return unprotect(base64.b64decode(value[len(_SEALED):])).decode("utf-8")
    except (OSError, ValueError):
        return ""                         # sealed by another Windows user or PC


def untrusted_import(fn):
    """Decorator for importer entry points fn(store, ...): every phrase they create or
    change is quarantined as "imported" (see security.py)."""
    @functools.wraps(fn)
    def wrapper(store, *args, **kwargs):
        cm = getattr(store, "quarantine_writes", None)
        if cm is None:
            return fn(store, *args, **kwargs)
        with cm("imported"):
            return fn(store, *args, **kwargs)
    return wrapper


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self.lock = threading.RLock()
        self._qlocal = threading.local()     # quarantine_writes() context, per thread
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self._migrate_schema()       # before SCHEMA: old tables need columns its indexes may use
        self.conn.executescript(SCHEMA)
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
            for k, v in DEFAULT_SETTINGS.items():
                self.conn.execute("INSERT OR IGNORE INTO settings VALUES (?, ?)", (k, v))
        self._seal_plain_secrets()           # keys saved by older versions
        self._listeners: list = []
        self._migrate_extras()
        self._migrate_ocr_auto()

    # ------------------------------------------------------------ migrations
    def _seal_plain_secrets(self) -> None:
        """Encrypt secrets stored in plain text (older versions, or an old backup that was
        restored), then overwrite the freed pages so the old values are gone from the file."""
        with self.lock:
            rows = [(k, v) for k, v in self.conn.execute("SELECT key, value FROM settings")
                    if k in SECRET_SETTINGS and v and not v.startswith(_SEALED)]
            if not rows:
                return
            self.conn.execute("PRAGMA secure_delete = ON")
            with self.conn:
                for k, v in rows:
                    self.conn.execute("UPDATE settings SET value=? WHERE key=?", (_seal(v), k))
            if self.path != ":memory:":
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self.conn.execute("VACUUM")
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def _columns(self, table: str) -> set[str]:
        return {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}

    def _migrate_schema(self) -> None:
        """v1 -> v2, idempotent. Safe on a fresh (empty) database."""
        c = self.conn
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='phrases'").fetchone():
            return                                   # fresh database: SCHEMA creates v2 tables
        fcols = self._columns("folders")
        if "notes" not in fcols:
            c.execute("ALTER TABLE folders ADD COLUMN notes TEXT DEFAULT ''")
        if "output_target" not in fcols:
            c.execute("ALTER TABLE folders ADD COLUMN output_target TEXT DEFAULT 'current'")
        if "output_target_arg" not in fcols:
            c.execute("ALTER TABLE folders ADD COLUMN output_target_arg TEXT DEFAULT ''")
        if "abbrev_prefix" not in fcols:
            c.execute("ALTER TABLE folders ADD COLUMN abbrev_prefix TEXT DEFAULT ''")
        cols = self._columns("phrases")
        if "output_target" not in cols:
            c.execute("ALTER TABLE phrases ADD COLUMN output_target TEXT DEFAULT 'current'")
        if "output_target_arg" not in cols:
            c.execute("ALTER TABLE phrases ADD COLUMN output_target_arg TEXT DEFAULT ''")
        tcols = self._columns("triggers")
        if tcols and "folder_id" not in tcols:
            # phrase_id was NOT NULL: SQLite can only relax that by rebuilding the table
            c.commit()
            c.execute("PRAGMA foreign_keys = OFF")
            try:
                with c:
                    c.executescript(TRIGGERS_TABLE.format(name="triggers_v2"))
                    keep = [k for k in ("id",) + TRIGGER_COLUMNS if k in tcols]
                    c.execute(f"INSERT INTO triggers_v2 ({','.join(keep)}) SELECT {','.join(keep)} FROM triggers")
                    c.execute("DROP TABLE triggers")
                    c.execute("ALTER TABLE triggers_v2 RENAME TO triggers")
            finally:
                c.execute("PRAGMA foreign_keys = ON")
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='meta'").fetchone():
            c.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        c.commit()

    def _migrate_ocr_auto(self) -> None:
        """0.5.1: the OCR language detects itself. A stored "English" was the old default,
        so switch it to "Auto" once; a language chosen after that is kept."""
        if self.setting("ocr.auto_migrated", "") == "1":
            return
        if self.setting("ocr.language", "") in ("English", "en", "en-US"):
            self.set_setting("ocr.language", "Auto")
        self.set_setting("ocr.auto_migrated", "1")

    def _migrate_extras(self) -> None:
        """Move the old JSON setting ui.trigger_extras into real columns (once)."""
        raw = self.setting("ui.trigger_extras", "")
        if not raw:
            return
        try:
            data = json.loads(raw)
        except ValueError:
            data = {}
        from phraseforge.triggers.rows import row_to_trigger   # pure helpers, no Qt
        for owner, extra in (data or {}).items():
            if not isinstance(extra, dict):
                continue
            rows = extra.get("rows") or []
            triggers = [t for t in (row_to_trigger(r) for r in rows) if t is not None]
            kind, _, ident = owner.partition(":")
            try:
                if kind == "p" and (p := self.get_phrase(int(ident))):
                    if rows:
                        p.triggers = triggers
                    if extra.get("output_target"):
                        p.output_target = extra["output_target"]
                    if extra.get("output_program"):
                        p.output_target_arg = extra["output_program"]
                    self.update_phrase(p, record_history=False)
                elif kind == "f" and (f := self.get_folder(int(ident))):
                    f.notes = extra.get("notes", f.notes)
                    if extra.get("output_target"):
                        f.output_target = extra["output_target"]
                        f.output_target_arg = extra.get("output_program", "") or f.output_target_arg
                    self.update_folder(f)
                    if rows:
                        self.set_folder_triggers(f.id, triggers)
                elif kind == "s" and rows:
                    self.set_special_triggers(ident, triggers)
            except (ValueError, sqlite3.Error):
                continue
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM settings WHERE key='ui.trigger_extras'")

    # ------------------------------------------------------------ change events
    def on_change(self, callback) -> None:
        """callback(kind: str, id: int|None) after any write. kind in
        folder|phrase|setting|var|clipboard|suggestion|sticky|usage. May be called on any
        thread (usage comes from the expansion thread)."""
        self._listeners.append(callback)

    def _changed(self, kind: str, id_: int | None = None) -> None:
        for cb in list(self._listeners):
            try:
                cb(kind, id_)
            except Exception:  # listeners must not break storage
                pass

    closed = False

    def close(self) -> None:
        self.closed = True
        self.conn.close()

    # ------------------------------------------------------------ folders
    def add_folder(self, f: Folder) -> Folder:
        with self.lock, self.conn:
            cur = self.conn.execute(
                "INSERT INTO folders (parent_id,name,sort,enabled,apps_include,apps_exclude,password_hash,"
                "show_in_popup,notes,output_target,output_target_arg,abbrev_prefix) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (f.parent_id, f.name, f.sort, int(f.enabled), f.apps_include, f.apps_exclude,
                 f.password_hash, int(f.show_in_popup), f.notes, f.output_target or "current",
                 f.output_target_arg or "", f.abbrev_prefix or ""))
            f.id = cur.lastrowid
            if f.triggers:
                self._write_owner_triggers("folder_id", f.id, f.triggers)
        self._changed("folder", f.id)
        return f

    def update_folder(self, f: Folder) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                "UPDATE folders SET parent_id=?,name=?,sort=?,enabled=?,apps_include=?,apps_exclude=?,"
                "password_hash=?,show_in_popup=?,notes=?,output_target=?,output_target_arg=?,abbrev_prefix=? "
                "WHERE id=?",
                (f.parent_id, f.name, f.sort, int(f.enabled), f.apps_include, f.apps_exclude,
                 f.password_hash, int(f.show_in_popup), f.notes, f.output_target or "current",
                 f.output_target_arg or "", f.abbrev_prefix or "", f.id))
        self._changed("folder", f.id)

    # folder / special-folder triggers (a folder trigger opens that folder's popup menu)
    def folder_triggers(self, folder_id: int) -> list[Trigger]:
        with self.lock:
            return [self._row_trigger(r) for r in self.conn.execute(
                "SELECT * FROM triggers WHERE folder_id=? ORDER BY id", (folder_id,))]

    def set_folder_triggers(self, folder_id: int, triggers: list[Trigger]) -> None:
        with self.lock, self.conn:
            self._write_owner_triggers("folder_id", folder_id, triggers)
        self._changed("folder", folder_id)

    def special_triggers(self, special: str) -> list[Trigger]:
        with self.lock:
            return [self._row_trigger(r) for r in self.conn.execute(
                "SELECT * FROM triggers WHERE special=? ORDER BY id", (special,))]

    def set_special_triggers(self, special: str, triggers: list[Trigger]) -> None:
        with self.lock, self.conn:
            self._write_owner_triggers("special", special, triggers)
        self._changed("folder", None)

    def delete_folder(self, folder_id: int) -> None:
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM folders WHERE id=?", (folder_id,))
        self._changed("folder", folder_id)

    def _row_folder(self, r) -> Folder:
        keys = r.keys()
        return Folder(id=r["id"], parent_id=r["parent_id"], name=r["name"], sort=r["sort"],
                      enabled=bool(r["enabled"]), apps_include=r["apps_include"],
                      apps_exclude=r["apps_exclude"], password_hash=r["password_hash"],
                      show_in_popup=bool(r["show_in_popup"]),
                      notes=(r["notes"] or "") if "notes" in keys else "",
                      output_target=(r["output_target"] or "current") if "output_target" in keys else "current",
                      output_target_arg=(r["output_target_arg"] or "") if "output_target_arg" in keys else "",
                      abbrev_prefix=(r["abbrev_prefix"] or "") if "abbrev_prefix" in keys else "")

    def get_folder(self, folder_id: int) -> Folder | None:
        with self.lock:
            r = self.conn.execute("SELECT * FROM folders WHERE id=?", (folder_id,)).fetchone()
            if not r:
                return None
            f = self._row_folder(r)
            f.triggers = self.folder_triggers(f.id)
        return f

    def folders(self, parent_id: int | None = ..., ) -> list[Folder]:  # type: ignore[assignment]
        """All folders, or children of parent_id (None = top level)."""
        with self.lock:
            if parent_id is ...:
                rows = self.conn.execute("SELECT * FROM folders ORDER BY sort, name").fetchall()
            elif parent_id is None:
                rows = self.conn.execute("SELECT * FROM folders WHERE parent_id IS NULL ORDER BY sort, name").fetchall()
            else:
                rows = self.conn.execute("SELECT * FROM folders WHERE parent_id=? ORDER BY sort, name", (parent_id,)).fetchall()
        return [self._row_folder(r) for r in rows]

    def folder_chain(self, folder_id: int | None) -> list[Folder]:
        """Folder and its ancestors, innermost first."""
        out = []
        while folder_id is not None:
            f = self.get_folder(folder_id)
            if not f:
                break
            out.append(f)
            folder_id = f.parent_id
        return out

    # ------------------------------------------------------------ phrases
    def add_phrase(self, p: Phrase, record_history: bool = False) -> Phrase:
        now = _now()
        p.created = p.created or now
        p.modified = now
        with self.lock, self.conn:
            cur = self.conn.execute(
                "INSERT INTO phrases (folder_id,description,content,content_format,output_mode,apps_include,"
                "apps_exclude,enabled,sort,use_count,last_used,created,modified,notes,output_target,"
                "output_target_arg) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (p.folder_id, p.description, p.content, p.content_format, OutputMode(p.output_mode).value,
                 p.apps_include, p.apps_exclude, int(p.enabled), p.sort, p.use_count, p.last_used,
                 p.created, p.modified, p.notes, p.output_target or "current", p.output_target_arg or ""))
            p.id = cur.lastrowid
            self._write_triggers(p)
            self._write_tags(p)
            self._quarantine_if_untrusted(p.id)
        self._changed("phrase", p.id)
        return p

    def update_phrase(self, p: Phrase, record_history: bool = True) -> None:
        with self.lock, self.conn:
            if record_history:
                old = self.conn.execute("SELECT description, content FROM phrases WHERE id=?", (p.id,)).fetchone()
                if old and (old["content"] != p.content or old["description"] != p.description):
                    self.conn.execute(
                        "INSERT INTO phrase_history (phrase_id,saved,description,content) VALUES (?,?,?,?)",
                        (p.id, _now(), old["description"], old["content"]))
            p.modified = _now()
            self.conn.execute(
                "UPDATE phrases SET folder_id=?,description=?,content=?,content_format=?,output_mode=?,"
                "apps_include=?,apps_exclude=?,enabled=?,sort=?,modified=?,notes=?,output_target=?,"
                "output_target_arg=? WHERE id=?",
                (p.folder_id, p.description, p.content, p.content_format, OutputMode(p.output_mode).value,
                 p.apps_include, p.apps_exclude, int(p.enabled), p.sort, p.modified, p.notes,
                 p.output_target or "current", p.output_target_arg or "", p.id))
            self._write_triggers(p)
            self._write_tags(p)
            self._quarantine_if_untrusted(p.id)
        self._changed("phrase", p.id)

    # ------------------------------------------------------------ untrusted phrases (security.py)
    @contextmanager
    def quarantine_writes(self, origin: str = "imported"):
        """Phrases created or changed on this thread inside the block are quarantined."""
        stack = self._qlocal.__dict__.setdefault("stack", [])
        stack.append(origin)
        try:
            yield
        finally:
            stack.pop()

    def _quarantine_if_untrusted(self, phrase_id: int) -> None:
        """Caller holds the lock (inside the write transaction)."""
        stack = getattr(self._qlocal, "stack", None)
        if stack and phrase_id is not None:
            self.conn.execute("INSERT OR REPLACE INTO phrase_quarantine VALUES (?,?,?)",
                              (phrase_id, stack[-1], _now()))

    def quarantine(self, phrase_id: int, origin: str = "imported") -> None:
        with self.lock, self.conn:
            self.conn.execute("INSERT OR REPLACE INTO phrase_quarantine VALUES (?,?,?)", (phrase_id, origin, _now()))

    def release_quarantine(self, phrase_id: int) -> None:
        """The user approved this phrase (or edited it themselves)."""
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM phrase_quarantine WHERE phrase_id=?", (phrase_id,))

    def quarantine_origin(self, phrase_id: int | None) -> str | None:
        """"imported" / "synced" if the phrase is not approved on this PC, else None."""
        if phrase_id is None:
            return None
        with self.lock:
            r = self.conn.execute("SELECT origin FROM phrase_quarantine WHERE phrase_id=?", (phrase_id,)).fetchone()
        return r[0] if r else None

    def quarantined(self) -> dict[int, str]:
        with self.lock:
            return {r[0]: r[1] for r in self.conn.execute("SELECT phrase_id, origin FROM phrase_quarantine")}

    def phrase_fingerprints(self) -> dict[int, str]:
        """phrase id -> hash of everything that runs (content of every language version)."""
        with self.lock:
            rows = self.conn.execute("SELECT id, content, content_format FROM phrases").fetchall()
            versions: dict[int, list] = {}
            for r in self.conn.execute(
                    "SELECT phrase_id, lang, content, content_format FROM phrase_versions ORDER BY phrase_id, lang"):
                versions.setdefault(r[0], []).append((r[1], r[2], r[3]))
        out = {}
        for r in rows:
            blob = json.dumps([r[1], r[2], versions.get(r[0], [])], ensure_ascii=False)
            out[r[0]] = hashlib.sha256(blob.encode("utf-8")).hexdigest()
        return out

    def delete_phrase(self, phrase_id: int) -> None:
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM phrases WHERE id=?", (phrase_id,))
        self._changed("phrase", phrase_id)

    def _write_triggers(self, p: Phrase) -> None:
        self._write_owner_triggers("phrase_id", p.id, p.triggers)

    def _write_owner_triggers(self, owner_col: str, owner, triggers: list[Trigger]) -> None:
        """Replace all triggers of one owner (phrase_id / folder_id / special). Caller holds the lock."""
        assert owner_col in ("phrase_id", "folder_id", "special")
        self.conn.execute(f"DELETE FROM triggers WHERE {owner_col}=?", (owner,))
        for t in triggers:
            t.sync_legacy()
            t.phrase_id = owner if owner_col == "phrase_id" else None
            t.folder_id = owner if owner_col == "folder_id" else None
            t.special = owner if owner_col == "special" else ""
            cur = self.conn.execute(
                f"INSERT INTO triggers ({','.join(TRIGGER_COLUMNS)}) VALUES ({','.join('?' * len(TRIGGER_COLUMNS))})",
                (t.phrase_id, t.folder_id, t.special, TriggerKind(t.kind).value, t.value,
                 AutotextMode(t.mode).value, int(t.case_sensitive), int(t.word_start_only), int(t.enabled),
                 t.word_pos, t.exec_mode, t.lead_delim, t.trail_delim, int(t.remove_trailing), t.window_scope))
            t.id = cur.lastrowid

    def _write_tags(self, p: Phrase) -> None:
        self.conn.execute("DELETE FROM phrase_tags WHERE phrase_id=?", (p.id,))
        for name in {t.strip() for t in p.tags if t.strip()}:
            self.conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
            tid = self.conn.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()[0]
            self.conn.execute("INSERT INTO phrase_tags VALUES (?,?)", (p.id, tid))

    def _row_phrase(self, r) -> Phrase:
        p = Phrase(id=r["id"], folder_id=r["folder_id"], description=r["description"], content=r["content"],
                   content_format=r["content_format"], output_mode=OutputMode(r["output_mode"]),
                   apps_include=r["apps_include"], apps_exclude=r["apps_exclude"], enabled=bool(r["enabled"]),
                   sort=r["sort"], use_count=r["use_count"], last_used=r["last_used"], created=r["created"],
                   modified=r["modified"], notes=r["notes"],
                   output_target=r["output_target"] or "current", output_target_arg=r["output_target_arg"] or "")
        p.triggers = [self._row_trigger(t) for t in self.conn.execute(
            "SELECT * FROM triggers WHERE phrase_id=? ORDER BY id", (p.id,))]
        p.tags = [t[0] for t in self.conn.execute(
            "SELECT tags.name FROM tags JOIN phrase_tags ON tags.id=phrase_tags.tag_id WHERE phrase_id=? ORDER BY name",
            (p.id,))]
        return p

    @staticmethod
    def _row_trigger(r) -> Trigger:
        return Trigger(id=r["id"], phrase_id=r["phrase_id"], kind=TriggerKind(r["kind"]), value=r["value"],
                       mode=AutotextMode(r["mode"]), case_sensitive=bool(r["case_sensitive"]),
                       word_start_only=bool(r["word_start_only"]), enabled=bool(r["enabled"]),
                       folder_id=r["folder_id"], special=r["special"] or "", word_pos=r["word_pos"] or "",
                       exec_mode=r["exec_mode"] or "", lead_delim=r["lead_delim"] or "",
                       trail_delim=r["trail_delim"] or "", remove_trailing=bool(r["remove_trailing"]),
                       window_scope=r["window_scope"] or "")

    def get_phrase(self, phrase_id: int) -> Phrase | None:
        with self.lock:
            r = self.conn.execute("SELECT * FROM phrases WHERE id=?", (phrase_id,)).fetchone()
            return self._row_phrase(r) if r else None

    def find_phrase(self, description: str) -> Phrase | None:
        """Exact (case-insensitive) description match, used by {#insert}."""
        with self.lock:
            r = self.conn.execute("SELECT * FROM phrases WHERE description=? COLLATE NOCASE LIMIT 1",
                                  (description,)).fetchone()
            return self._row_phrase(r) if r else None

    def phrase_folder_map(self) -> dict[int, int | None]:
        """phrase id -> folder id, without loading the phrases."""
        with self.lock:
            return {r[0]: r[1] for r in self.conn.execute("SELECT id, folder_id FROM phrases")}

    def phrases(self, folder_id: int | None = ...) -> list[Phrase]:  # type: ignore[assignment]
        with self.lock:
            if folder_id is ...:
                rows = self.conn.execute("SELECT * FROM phrases ORDER BY sort, description").fetchall()
            elif folder_id is None:
                rows = self.conn.execute("SELECT * FROM phrases WHERE folder_id IS NULL ORDER BY sort, description").fetchall()
            else:
                rows = self.conn.execute("SELECT * FROM phrases WHERE folder_id=? ORDER BY sort, description",
                                         (folder_id,)).fetchall()
            return [self._row_phrase(r) for r in rows]

    def search(self, query: str, limit: int = 50) -> list[Phrase]:
        """Search description, content, autotext and tags. Most used first."""
        q = f"%{query}%"
        with self.lock:
            rows = self.conn.execute(
                "SELECT DISTINCT p.* FROM phrases p LEFT JOIN triggers t ON t.phrase_id=p.id "
                "LEFT JOIN phrase_tags pt ON pt.phrase_id=p.id LEFT JOIN tags g ON g.id=pt.tag_id "
                "WHERE p.description LIKE ? OR p.content LIKE ? OR t.value LIKE ? OR g.name LIKE ? "
                "ORDER BY p.use_count DESC, p.description LIMIT ?", (q, q, q, q, limit)).fetchall()
            return [self._row_phrase(r) for r in rows]

    def triggers(self, kind: TriggerKind | None = None, owners: str = "phrase") -> list[Trigger]:
        """Enabled triggers of enabled phrases inside enabled folders.
        owners: "phrase" (default, as before), "all" adds folder and special-folder triggers."""
        with self.lock:
            sql = ("SELECT t.* FROM triggers t JOIN phrases p ON p.id=t.phrase_id "
                   "WHERE t.enabled=1 AND p.enabled=1")
            args: tuple = ()
            if kind is not None:
                sql += " AND t.kind=?"
                args = (TriggerKind(kind).value,)
            rows = self.conn.execute(sql, args).fetchall()
            out = [self._row_trigger(r) for r in rows]
            extra = []
            if owners == "all":
                sql = "SELECT * FROM triggers WHERE enabled=1 AND phrase_id IS NULL"
                if kind is not None:
                    sql += " AND kind=?"
                extra = [self._row_trigger(r) for r in self.conn.execute(sql, args).fetchall()]
        out = [t for t in out if self.phrase_folder_enabled(t.phrase_id)]
        for t in extra:
            if t.folder_id is not None:
                chain = self.folder_chain(t.folder_id)
                if chain and all(f.enabled for f in chain):
                    out.append(t)
            elif t.special:
                out.append(t)
        return out

    def phrase_folder_enabled(self, phrase_id: int) -> bool:
        with self.lock:
            r = self.conn.execute("SELECT folder_id FROM phrases WHERE id=?", (phrase_id,)).fetchone()
        if not r:
            return False
        return all(f.enabled for f in self.folder_chain(r["folder_id"]))

    def phrase_allowed_in_app(self, phrase_id: int, exe: str) -> bool:
        """Apply phrase + folder include/exclude lists and global exclusions."""
        exe = (exe or "").lower()
        if exe and exe in self.excluded_apps():
            return False
        p = self.get_phrase(phrase_id)
        if not p:
            return False
        scopes = [(p.apps_include, p.apps_exclude)] + [
            (f.apps_include, f.apps_exclude) for f in self.folder_chain(p.folder_id)]
        for inc, exc in scopes:
            inc_l = [a.strip().lower() for a in inc.split(",") if a.strip()]
            exc_l = [a.strip().lower() for a in exc.split(",") if a.strip()]
            if exe in exc_l:
                return False
            if inc_l and exe not in inc_l:
                return False
        return True

    def history(self, phrase_id: int) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT * FROM phrase_history WHERE phrase_id=? ORDER BY id DESC", (phrase_id,))]

    # ------------------------------------------------------------ usage stats
    def record_use(self, phrase_id: int, app: str = "", chars: int = 0, trigger: str = "") -> None:
        now = _now()
        with self.lock, self.conn:
            self.conn.execute("UPDATE phrases SET use_count=use_count+1, last_used=? WHERE id=?", (now, phrase_id))
            self.conn.execute("INSERT INTO usage_log (phrase_id,used,app,chars,trigger) VALUES (?,?,?,?,?)",
                              (phrase_id, now, app, chars, trigger))
        self._changed("usage", phrase_id)       # e.g. the main window's Last Used folder

    def stats(self) -> dict:
        with self.lock:
            c = self.conn
            total = c.execute("SELECT COUNT(*), COALESCE(SUM(chars),0) FROM usage_log").fetchone()
            top = [dict(r) for r in c.execute(
                "SELECT p.id, p.description, COUNT(u.id) AS uses, COALESCE(SUM(u.chars),0) AS chars FROM usage_log u "
                "JOIN phrases p ON p.id=u.phrase_id GROUP BY p.id ORDER BY uses DESC LIMIT 20")]
            per_day = [dict(r) for r in c.execute(
                "SELECT substr(used,1,10) AS day, COUNT(*) AS uses, SUM(chars) AS chars FROM usage_log "
                "GROUP BY day ORDER BY day DESC LIMIT 30")]
            per_app = [dict(r) for r in c.execute(
                "SELECT app, COUNT(*) AS uses FROM usage_log GROUP BY app ORDER BY uses DESC LIMIT 20")]
            counts = c.execute("SELECT (SELECT COUNT(*) FROM phrases), (SELECT COUNT(*) FROM folders)").fetchone()
        return {"expansions": total[0], "chars_saved": total[1], "top": top, "per_day": per_day,
                "per_app": per_app, "phrase_count": counts[0], "folder_count": counts[1]}

    # ------------------------------------------------------------ variables
    def get_var(self, name: str, scope: str = "global") -> str:
        with self.lock:
            r = self.conn.execute("SELECT value FROM vars WHERE scope=? AND name=?", (scope, name)).fetchone()
        return r[0] if r else ""

    def set_var(self, name: str, value: str, scope: str = "global") -> None:
        with self.lock, self.conn:
            self.conn.execute("INSERT OR REPLACE INTO vars VALUES (?,?,?)", (scope, name, value))
        self._changed("var")

    def all_vars(self) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute("SELECT * FROM vars ORDER BY scope, name")]

    # ------------------------------------------------------------ settings
    def setting(self, key: str, default: str = "") -> str:
        with self.lock:
            r = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if not r:
            return default
        return _unseal(r[0]) if key in SECRET_SETTINGS else r[0]

    def set_setting(self, key: str, value: str) -> None:
        value = _seal(str(value)) if key in SECRET_SETTINGS else str(value)
        with self.lock, self.conn:
            self.conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, value))
        self._changed("setting")

    def settings(self) -> dict[str, str]:
        with self.lock:
            return {r[0]: _unseal(r[1]) if r[0] in SECRET_SETTINGS else r[1]
                    for r in self.conn.execute("SELECT key, value FROM settings")}

    # ------------------------------------------------------------ language versions
    # PhraseExpress-style: one phrase, several language versions. The phrase's own
    # content is the default version; phrase_versions holds the others.
    def phrase_languages(self) -> list[str]:
        """Languages offered for phrase versions (setting phrase.languages, JSON list)."""
        try:
            v = json.loads(self.setting("phrase.languages", "[]") or "[]")
        except ValueError:
            return []
        return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []

    def set_phrase_languages(self, langs: Iterable[str]) -> None:
        seen: list[str] = []
        for x in langs:
            x = str(x).strip()
            if x and x.lower() not in (s.lower() for s in seen):
                seen.append(x)
        self.set_setting("phrase.languages", json.dumps(seen, ensure_ascii=False))

    def phrase_versions(self, phrase_id: int) -> dict[str, tuple[str, str]]:
        """{language: (content, content_format)} for a phrase (default version excluded)."""
        with self.lock:
            rows = self.conn.execute("SELECT lang, content, content_format FROM phrase_versions "
                                     "WHERE phrase_id=? ORDER BY lang", (phrase_id,)).fetchall()
        return {r[0]: (r[1] or "", r[2] or "text") for r in rows}

    def set_phrase_version(self, phrase_id: int, lang: str, content: str, content_format: str = "text") -> None:
        lang = (lang or "").strip()
        if not lang:
            raise ValueError("language is required")
        with self.lock, self.conn:
            self.conn.execute("INSERT OR REPLACE INTO phrase_versions VALUES (?,?,?,?,?)",
                              (phrase_id, lang, content, content_format or "text", _now()))
            self._quarantine_if_untrusted(phrase_id)
        self._changed("phrase", phrase_id)

    def delete_phrase_version(self, phrase_id: int, lang: str) -> None:
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM phrase_versions WHERE phrase_id=? AND lang=?", (phrase_id, lang))
        self._changed("phrase", phrase_id)

    def phrase_text(self, p: Phrase, lang: str = "") -> tuple[str, str]:
        """(content, format) of the version in `lang`; the default version when `lang` is
        empty or the phrase has no such version."""
        if lang and p.id is not None:
            for k, v in self.phrase_versions(p.id).items():
                if k.lower() == lang.lower():
                    return v
        return p.content, p.content_format

    def excluded_apps(self) -> set[str]:
        with self.lock:
            return {r[0] for r in self.conn.execute("SELECT exe FROM excluded_apps")}

    def set_excluded_apps(self, exes: Iterable[str]) -> None:
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM excluded_apps")
            for e in {e.strip().lower() for e in exes if e.strip()}:
                self.conn.execute("INSERT INTO excluded_apps VALUES (?)", (e,))
        self._changed("setting")

    # ------------------------------------------------------------ clipboard history
    def add_clipboard(self, text: str, source_app: str = "") -> None:
        if not text:
            return
        mx = int(self.setting("clipboard_history.max", "200") or 200)
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM clipboard WHERE text=? AND pinned=0", (text,))
            self.conn.execute("INSERT INTO clipboard (text,created,source_app) VALUES (?,?,?)",
                              (text, _now(), source_app))
            self.conn.execute(
                "DELETE FROM clipboard WHERE pinned=0 AND id NOT IN "
                "(SELECT id FROM clipboard WHERE pinned=0 ORDER BY id DESC LIMIT ?)", (mx,))
        self._changed("clipboard")

    def clipboard_entries(self, limit: int = 200) -> list[ClipboardEntry]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM clipboard ORDER BY pinned DESC, id DESC LIMIT ?", (limit,)).fetchall()
        return [ClipboardEntry(id=r["id"], text=r["text"], created=r["created"], source_app=r["source_app"],
                               pinned=bool(r["pinned"])) for r in rows]

    def clipboard_at(self, index: int) -> str:
        with self.lock:
            r = self.conn.execute("SELECT text FROM clipboard ORDER BY id DESC LIMIT 1 OFFSET ?", (index,)).fetchone()
        return r[0] if r else ""

    def pin_clipboard(self, entry_id: int, pinned: bool) -> None:
        with self.lock, self.conn:
            self.conn.execute("UPDATE clipboard SET pinned=? WHERE id=?", (int(pinned), entry_id))
        self._changed("clipboard")

    # ---------------------------------------------------------- sticky notes
    _NOTE_COLS = ("id", "text", "html", "color", "x", "y", "w", "h", "visible", "on_top", "created", "updated")
    _NOTE_EDITABLE = ("text", "html", "color", "x", "y", "w", "h", "visible", "on_top")

    def _note(self, r):
        from phraseforge.stickynotes import StickyNote
        d = dict(zip(self._NOTE_COLS, r))
        return StickyNote(id=d["id"], text=d["text"] or "", theme=d["color"] or "yellow", html=d["html"] or "",
                          x=d["x"], y=d["y"], w=d["w"] or 300, h=d["h"] or 300, visible=bool(d["visible"]),
                          on_top=bool(d["on_top"]),
                          created=_parse_dt(d["created"]), updated=_parse_dt(d["updated"]))

    def sticky_notes(self) -> list:
        """PhraseForge's own sticky notes, most recently changed first."""
        with self.lock:
            rows = self.conn.execute(
                f"SELECT {', '.join(self._NOTE_COLS)} FROM sticky_notes ORDER BY updated DESC, id DESC").fetchall()
        return [self._note(r) for r in rows]

    def sticky_note(self, note_id: int):
        with self.lock:
            r = self.conn.execute(f"SELECT {', '.join(self._NOTE_COLS)} FROM sticky_notes WHERE id=?",
                                  (note_id,)).fetchone()
        return self._note(r) if r else None

    def add_sticky_note(self, text: str = "", html: str = "", color: str = "yellow", **fields):
        now = _now()
        vals = {k: v for k, v in fields.items() if k in self._NOTE_EDITABLE}
        vals.update(text=text, html=html, color=color)
        cols = list(vals) + ["created", "updated"]
        with self.lock, self.conn:
            cur = self.conn.execute(
                f"INSERT INTO sticky_notes ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                [int(v) if isinstance(v, bool) else v for v in vals.values()] + [now, now])
            nid = cur.lastrowid
        self._changed("sticky", nid)
        return self.sticky_note(nid)

    def update_sticky_note(self, note_id: int, touch: bool = True, **fields) -> None:
        """touch=False keeps the 'updated' time (window moved/resized/shown, not edited)."""
        vals = {k: (int(v) if isinstance(v, bool) else v) for k, v in fields.items() if k in self._NOTE_EDITABLE}
        if not vals:
            return
        if touch:
            vals["updated"] = _now()
        with self.lock, self.conn:
            self.conn.execute(f"UPDATE sticky_notes SET {', '.join(k + '=?' for k in vals)} WHERE id=?",
                              [*vals.values(), note_id])
        self._changed("sticky", note_id)

    def delete_sticky_note(self, note_id: int) -> None:
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM sticky_notes WHERE id=?", (note_id,))
        self._changed("sticky", note_id)

    def delete_clipboard(self, entry_id: int) -> None:
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM clipboard WHERE id=?", (entry_id,))
        self._changed("clipboard")

    def clear_clipboard(self, keep_pinned: bool = True) -> None:
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM clipboard" + (" WHERE pinned=0" if keep_pinned else ""))
        self._changed("clipboard")

    # ------------------------------------------------------------ learning suggestions
    def bump_suggestion(self, text: str) -> int:
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO suggestions (text,count,last_seen) VALUES (?,1,?) "
                "ON CONFLICT(text) DO UPDATE SET count=count+1, last_seen=excluded.last_seen", (text, _now()))
            n = self.conn.execute("SELECT count FROM suggestions WHERE text=?", (text,)).fetchone()[0]
        return n

    def suggestions(self, min_count: int = 3) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT * FROM suggestions WHERE dismissed=0 AND count>=? ORDER BY count DESC", (min_count,))]

    def dismiss_suggestion(self, text: str) -> None:
        with self.lock, self.conn:
            self.conn.execute("UPDATE suggestions SET dismissed=1 WHERE text=?", (text,))
        self._changed("suggestion")

    # ------------------------------------------------------------ bulk
    def export_dict(self) -> dict:
        """Full portable snapshot (used by io_formats and backups)."""
        return {
            "format": "phraseforge", "version": SCHEMA_VERSION, "exported": _now(),
            "folders": [{**{k: v for k, v in vars(f).items() if k != "triggers"},
                         "triggers": [t.to_dict() for t in self.folder_triggers(f.id)]}
                        for f in self.folders()],
            "phrases": [{**{k: v for k, v in vars(p).items() if k != "triggers"},
                         "output_mode": OutputMode(p.output_mode).value,
                         "triggers": [t.to_dict() for t in p.triggers],
                         "versions": {lang: {"content": c, "content_format": f}
                                      for lang, (c, f) in self.phrase_versions(p.id).items()}}
                        for p in self.phrases()],
            "special_triggers": {s: [t.to_dict() for t in self.special_triggers(s)]
                                 for s in ("last_used", "clipboard_cache") if self.special_triggers(s)},
            "vars": self.all_vars(),
            "excluded_apps": sorted(self.excluded_apps()),
        }

    def restore_from(self, path: str | Path, untrusted: str | None = None) -> None:
        """Replace all data with a backup file, in place on the open connection.

        untrusted="synced"/"imported": the file came from elsewhere (cloud pull, a phrase file
        the user opened). This PC's quarantine list is kept, the file's own list is ignored,
        and every phrase the file adds or changes is quarantined (security.py). Without it
        (restoring this PC's own backup) the backup's list is used as it is."""
        before = self.phrase_fingerprints() if untrusted else {}
        keep_q = self.quarantined() if untrusted else {}
        with self.lock:
            src = sqlite3.connect(str(path))
            src.backup(self.conn)
            src.close()
            self.conn.execute("PRAGMA foreign_keys = ON")
            self._migrate_schema()        # a backup/sync copy may come from an older version
            self.conn.executescript(SCHEMA)
        if untrusted:
            after = self.phrase_fingerprints()
            with self.lock, self.conn:
                self.conn.execute("DELETE FROM phrase_quarantine")
                for pid, fp in after.items():
                    origin = keep_q.get(pid) or (untrusted if before.get(pid) != fp else None)
                    if origin:
                        self.conn.execute("INSERT INTO phrase_quarantine VALUES (?,?,?)", (pid, origin, _now()))
        self._migrate_extras()
        self._seal_plain_secrets()        # an old backup may hold plain-text keys
        for kind in ("folder", "phrase", "setting", "var", "clipboard", "sticky"):
            self._changed(kind)

    def backup_to(self, path: str | Path) -> None:
        with self.lock:
            dst = sqlite3.connect(str(path))
            with dst:
                self.conn.backup(dst)
            dst.close()


def json_dumps(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, indent=2)
