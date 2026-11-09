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
import logging
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable

from phraseforge import policy, vault
from phraseforge.models import (
    AutotextMode, ClipboardEntry, Folder, OutputMode, Phrase, Trigger, TriggerKind,
)

log = logging.getLogger(__name__)

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

# Change-set sync (cloud/merge.py) recognizes the same folder, phrase or note on two PCs by
# this id, which never changes and travels with the sync copy. Rows inserted without one get
# one from the trigger, so no insert statement has to know about it.
UID_TABLES = ("folders", "phrases", "sticky_notes")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS folders (
  id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
  name TEXT NOT NULL, sort INTEGER DEFAULT 0, enabled INTEGER DEFAULT 1,
  apps_include TEXT DEFAULT '', apps_exclude TEXT DEFAULT '',
  password_hash TEXT DEFAULT '', show_in_popup INTEGER DEFAULT 1, notes TEXT DEFAULT '',
  output_target TEXT DEFAULT 'current', output_target_arg TEXT DEFAULT '',
  abbrev_prefix TEXT DEFAULT '', uid TEXT, is_template INTEGER DEFAULT 0,
  text_before TEXT DEFAULT '', text_after TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS phrases (
  id INTEGER PRIMARY KEY, folder_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
  description TEXT NOT NULL, content TEXT DEFAULT '', content_format TEXT DEFAULT 'text',
  output_mode TEXT DEFAULT 'auto', apps_include TEXT DEFAULT '', apps_exclude TEXT DEFAULT '',
  enabled INTEGER DEFAULT 1, sort INTEGER DEFAULT 0, use_count INTEGER DEFAULT 0,
  last_used TEXT, created TEXT, modified TEXT, notes TEXT DEFAULT '',
  output_target TEXT DEFAULT 'current', output_target_arg TEXT DEFAULT '', uid TEXT);
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
CREATE TABLE IF NOT EXISTS trash (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, name TEXT, deleted_at TEXT NOT NULL,
  parent_uid TEXT, parent_name TEXT, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS phrase_comments (
  id INTEGER PRIMARY KEY, phrase_id INTEGER NOT NULL REFERENCES phrases(id) ON DELETE CASCADE,
  author TEXT DEFAULT '', created TEXT, text TEXT NOT NULL, resolved INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_comments_phrase ON phrase_comments(phrase_id);
CREATE TABLE IF NOT EXISTS sticky_notes (
  id INTEGER PRIMARY KEY, text TEXT DEFAULT '', html TEXT DEFAULT '', color TEXT DEFAULT 'yellow',
  x INTEGER, y INTEGER, w INTEGER DEFAULT 300, h INTEGER DEFAULT 300,
  visible INTEGER DEFAULT 1, on_top INTEGER DEFAULT 0, created TEXT, updated TEXT, uid TEXT);
""" + "".join(f"""
CREATE UNIQUE INDEX IF NOT EXISTS ix_{t}_uid ON {t}(uid);
UPDATE {t} SET uid=lower(hex(randomblob(16))) WHERE uid IS NULL OR uid='';
CREATE TRIGGER IF NOT EXISTS {t}_uid AFTER INSERT ON {t} WHEN NEW.uid IS NULL OR NEW.uid='' BEGIN
  UPDATE {t} SET uid=lower(hex(randomblob(16))) WHERE id=NEW.id; END;
""" for t in UID_TABLES)

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
    "sync.merge": "1",                    # merge edits made on two PCs (cloud/merge.py)
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
                             "net.proxy_password", "shared.password", "sync.passphrase"})
# Settings sealed the same way, by prefix: a dynamic folder's ODBC connection string can
# hold a password (dynamic.conn.<folder id>, security R46).
SECRET_PREFIXES = ("dynamic.conn.",)


def is_secret_setting(key: str) -> bool:
    return key in SECRET_SETTINGS or key.startswith(SECRET_PREFIXES)
_SEALED = "dpapi:"

# Settings that belong to this PC: never uploaded by sync, and kept when data comes from
# elsewhere (sync pull, a phrase file opened with File > Open). Besides PC state they include
# everything that decides where data and keys go or what program runs: a synced or opened
# copy must not send this PC's API keys to another server, set a proxy, lift the {#http}
# guard, move backups or logs, or swap the programs behind the file-search actions.
DEVICE_SETTING_PREFIXES = (
    "sync.", "gdrive.", "backup.cloud_", "backup.directory", "ocr.cli_path", "ocr.log_file",
    "app.start_with_windows", "app.first_run_done", "ui.item_colors", "ui.trigger_extras",
    "updates.last_check", "updates.notified_version", "net.", "onenote.exe",
    "filesearch.actions", "filesearch.commands", "filesearch.roots", "sound.", "shared.", "recorder.", "dynamic.",
    *sorted(SECRET_SETTINGS))
DEVICE_SETTING_SUFFIXES = ("_url", "_endpoint", "_path", "_file", ".file", ".exe", "_dir", "_directory")


# {#var name} / {#get name}: a phrase's privileged call can be built from global variables, which
# sync and import also bring. Their values are part of the phrase's fingerprint, so a pull that
# changes one sends the phrase back for approval (security.py).
_VAR_REF = re.compile(r"""\{#(?:var|get)\s+(?:"([^"]*)"|'([^']*)'|([^\s{}]+))""", re.I)
_DYNAMIC_VAR = re.compile(r"\{#(?:var|get)\s*\{", re.I)


def _read_vars(texts: list[str], global_vars: dict[str, str]) -> list:
    """Sorted (name, value) of the global variables these phrase texts read. A name built at run
    time ({#var {#...}}) could be any variable, so then all of them count."""
    if any(_DYNAMIC_VAR.search(t) for t in texts):
        return sorted(global_vars.items())
    names = {next(g for g in m.groups() if g is not None) for t in texts for m in _VAR_REF.finditer(t)}
    return sorted((n, global_vars.get(n, "")) for n in names)


_LINK = re.compile(r"\A\{#insert\s+-uid\s+([0-9a-f]{8,64})\}\Z")


def link_uid(content: str) -> str | None:
    """The uid a phrase link points to: its whole content is {#insert -uid <uid>} (FR-DAT-04)."""
    m = _LINK.match((content or "").strip())
    return m.group(1) if m else None


def is_device_setting(key: str) -> bool:
    return key.startswith(DEVICE_SETTING_PREFIXES) or key.endswith(DEVICE_SETTING_SUFFIXES)


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


def _editable(fn):
    """Store methods that change phrases or folders: refused while the administrator's
    policy disables editing (policy.py), except inside Store.policy_bypass() (sync pulls)."""
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        if policy.current().editing_disabled and not getattr(self._qlocal, "bypass", 0):
            raise policy.PolicyError(policy.current().notice("Editing phrases"))
        return fn(self, *args, **kwargs)
    return wrapper


class Store:
    def __init__(self, path: str | Path = ":memory:", passphrase: str | None = None):
        """passphrase: for a phrase file encrypted with one (vault.py). Opening an encrypted
        file without it raises vault.NeedPassphrase when DPAPI cannot unlock it."""
        self.path = str(path)
        self.lock = threading.RLock()
        self._qlocal = threading.local()     # quarantine_writes() context, per thread
        self.vault_key = None                # vault.Key while the file on disk is encrypted
        self._flusher = None
        if self.path != ":memory:" and vault.is_encrypted(self.path):
            data, self.vault_key = vault.read(self.path, passphrase=passphrase)
            self.conn = vault.memory_db(data)
        else:
            self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:" and self.vault_key is None:
            self.conn.execute("PRAGMA journal_mode = WAL")
        self._drop_foreign_schema()  # a file an older version pulled may still carry planted triggers
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
        if self.vault_key is not None:
            self._start_flusher()

    # ------------------------------------------------------------ encryption at rest (vault.py)
    FLUSH_SECONDS = 1.0

    @property
    def encrypted(self) -> bool:
        return self.vault_key is not None

    def _start_flusher(self) -> None:
        self._saved_changes = -1
        self._flush_stop = threading.Event()
        self.flush()

        def loop():
            while not self._flush_stop.wait(self.FLUSH_SECONDS):
                try:
                    self.flush()
                except Exception as e:   # keep trying; the next change retries the write
                    log.warning("could not save the encrypted phrase file: %s", e)
        self._flusher = threading.Thread(target=loop, name="vault-flush", daemon=True)
        self._flusher.start()

    def _stop_flusher(self) -> None:
        if self._flusher is not None:
            self._flush_stop.set()
            self._flusher.join(timeout=5)
            self._flusher = None

    def flush(self) -> None:
        """Write the in-memory database to the encrypted file if it changed since the last write."""
        if self.vault_key is None:
            return
        with self.lock:
            if self.conn.in_transaction or self.conn.total_changes == self._saved_changes:
                return
            data, n, key = self.conn.serialize(), self.conn.total_changes, self.vault_key
            vault.write(self.path, data, key)
            self._saved_changes = n

    def enable_encryption(self, passphrase: str | None = None, use_dpapi: bool = True) -> None:
        """Encrypt the phrase file on disk; from now on it is only written encrypted."""
        if self.path == ":memory:":
            raise vault.VaultError("This phrase file is not on disk.")
        if self.vault_key is not None:
            self.change_passphrase(passphrase, use_dpapi)
            return
        key = vault.Key.new(passphrase, use_dpapi)
        with self.lock:
            self.conn.commit()
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            data = self.conn.serialize()
            mem = vault.memory_db(data)
            vault.write(self.path + ".enc", data, key)
            old = self.conn
            old.close()
            for side in ("-wal", "-shm"):
                vault.wipe(self.path + side)
            vault.wipe(self.path)
            os.replace(self.path + ".enc", self.path)
            # plain copies next to the file would undo the encryption (R51): the sync base is
            # rebuilt on the next sync, the local pre-sync backup on the next pull
            p = Path(self.path)
            for extra in (p.with_name(p.stem + ".sync-base.db"), p.with_name(p.stem + ".before-sync.db")):
                if extra.exists() and not vault.is_encrypted(extra):
                    vault.wipe(extra)
            mem.row_factory = sqlite3.Row
            mem.execute("PRAGMA foreign_keys = ON")
            self.conn, self.vault_key = mem, key
        self._start_flusher()
        self._changed("setting")

    def change_passphrase(self, passphrase: str | None, use_dpapi: bool = True) -> None:
        """New passphrase (None = none), or ask for it on every start (use_dpapi=False)."""
        if self.vault_key is None:
            raise vault.VaultError("The phrase file is not encrypted.")
        with self.lock:
            self.vault_key.rewrap(passphrase, use_dpapi)
            self._saved_changes = -1
            self.flush()

    def disable_encryption(self) -> None:
        """Write the phrase file as a normal SQLite database again."""
        if self.vault_key is None:
            return
        self._stop_flusher()
        with self.lock:
            self.conn.commit()
            tmp = self.path + ".plain"
            dst = sqlite3.connect(tmp)
            with dst:
                self.conn.backup(dst)
            dst.close()
            self.conn.close()
            os.replace(tmp, self.path)
            self.conn = sqlite3.connect(self.path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.execute("PRAGMA journal_mode = WAL")
            self.vault_key = None
        self._changed("setting")

    # ------------------------------------------------------------ migrations
    def _seal_plain_secrets(self) -> None:
        """Encrypt secrets stored in plain text (older versions, or an old backup that was
        restored), then overwrite the freed pages so the old values are gone from the file."""
        with self.lock:
            rows = [(k, v) for k, v in self.conn.execute("SELECT key, value FROM settings")
                    if is_secret_setting(k) and v and not v.startswith(_SEALED)]
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

    def _drop_foreign_schema(self) -> None:
        """Drop every trigger and view in the database; SCHEMA then recreates PhraseForge's own
        uid triggers. A copied file brings its whole schema along: a trigger planted in a cloud
        copy (AFTER INSERT ON phrase_quarantine ... DELETE) turned quarantine off for good and
        travelled on with every push (security R44). trusted_schema=OFF keeps the file's
        schema from calling functions with side effects."""
        with self.lock:
            self.conn.execute("PRAGMA trusted_schema = OFF")
            rows = self.conn.execute(
                "SELECT type, name FROM sqlite_master WHERE type IN ('trigger', 'view')").fetchall()
            for kind, name in rows:
                quoted = '"' + str(name).replace('"', '""') + '"'
                self.conn.execute(f"DROP {'TRIGGER' if kind == 'trigger' else 'VIEW'} IF EXISTS {quoted}")
            self.conn.commit()

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
        if "is_template" not in fcols:
            c.execute("ALTER TABLE folders ADD COLUMN is_template INTEGER DEFAULT 0")
        for col in ("text_before", "text_after"):
            if col not in fcols:
                c.execute(f"ALTER TABLE folders ADD COLUMN {col} TEXT DEFAULT ''")
        cols = self._columns("phrases")
        if "output_target" not in cols:
            c.execute("ALTER TABLE phrases ADD COLUMN output_target TEXT DEFAULT 'current'")
        if "output_target_arg" not in cols:
            c.execute("ALTER TABLE phrases ADD COLUMN output_target_arg TEXT DEFAULT ''")
        for t in UID_TABLES:
            tc = self._columns(t)
            if tc and "uid" not in tc:
                c.execute(f"ALTER TABLE {t} ADD COLUMN uid TEXT")     # SCHEMA fills it in
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
        self._stop_flusher()
        if self.vault_key is not None:
            self.flush()
        self.closed = True
        self.conn.close()

    # ------------------------------------------------------------ folders
    @_editable
    def add_folder(self, f: Folder) -> Folder:
        with self.lock, self.conn:
            cur = self.conn.execute(
                "INSERT INTO folders (parent_id,name,sort,enabled,apps_include,apps_exclude,password_hash,"
                "show_in_popup,notes,output_target,output_target_arg,abbrev_prefix,is_template,text_before,"
                "text_after) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f.parent_id, f.name, f.sort, int(f.enabled), f.apps_include, f.apps_exclude,
                 f.password_hash, int(f.show_in_popup), f.notes, f.output_target or "current",
                 f.output_target_arg or "", f.abbrev_prefix or "", int(bool(f.is_template)),
                 f.text_before or "", f.text_after or ""))
            f.id = cur.lastrowid
            if f.triggers:
                self._write_owner_triggers("folder_id", f.id, f.triggers)
        self._changed("folder", f.id)
        return f

    @_editable
    def update_folder(self, f: Folder) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                "UPDATE folders SET parent_id=?,name=?,sort=?,enabled=?,apps_include=?,apps_exclude=?,"
                "password_hash=?,show_in_popup=?,notes=?,output_target=?,output_target_arg=?,abbrev_prefix=?,"
                "is_template=?,text_before=?,text_after=? WHERE id=?",
                (f.parent_id, f.name, f.sort, int(f.enabled), f.apps_include, f.apps_exclude,
                 f.password_hash, int(f.show_in_popup), f.notes, f.output_target or "current",
                 f.output_target_arg or "", f.abbrev_prefix or "", int(bool(f.is_template)),
                 f.text_before or "", f.text_after or "", f.id))
        self._changed("folder", f.id)

    # folder / special-folder triggers (a folder trigger opens that folder's popup menu)
    def folder_triggers(self, folder_id: int) -> list[Trigger]:
        with self.lock:
            return [self._row_trigger(r) for r in self.conn.execute(
                "SELECT * FROM triggers WHERE folder_id=? ORDER BY id", (folder_id,))]

    @_editable
    def set_folder_triggers(self, folder_id: int, triggers: list[Trigger]) -> None:
        with self.lock, self.conn:
            self._write_owner_triggers("folder_id", folder_id, triggers)
        self._changed("folder", folder_id)

    def special_triggers(self, special: str) -> list[Trigger]:
        with self.lock:
            return [self._row_trigger(r) for r in self.conn.execute(
                "SELECT * FROM triggers WHERE special=? ORDER BY id", (special,))]

    @_editable
    def set_special_triggers(self, special: str, triggers: list[Trigger]) -> None:
        with self.lock, self.conn:
            self._write_owner_triggers("special", special, triggers)
        self._changed("folder", None)

    @_editable
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
                      abbrev_prefix=(r["abbrev_prefix"] or "") if "abbrev_prefix" in keys else "",
                      is_template=bool(r["is_template"]) if "is_template" in keys else False,
                      text_before=(r["text_before"] or "") if "text_before" in keys else "",
                      text_after=(r["text_after"] or "") if "text_after" in keys else "")

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
    @_editable
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

    @_editable
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
        """Phrases created or changed on this thread inside the block are quarantined. So is any
        existing phrase whose fingerprint the block changed without touching the phrase itself
        (an imported variable it reads, its folder's output target)."""
        stack = self._qlocal.__dict__.setdefault("stack", [])
        before = self.phrase_fingerprints() if not stack else None
        stack.append(origin)
        try:
            yield
        finally:
            stack.pop()
            if before is not None:
                after = self.phrase_fingerprints()
                changed = [pid for pid, fp in before.items() if after.get(pid, fp) != fp]
                for pid in changed:
                    self.quarantine(pid, origin)

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
        """phrase id -> hash of everything that runs: the content of every language version and
        where the output goes (the phrase's and its folders' output target, which can start a
        program). A sync that changes any of it quarantines the phrase again."""
        with self.lock:
            rows = self.conn.execute("SELECT id, content, content_format, folder_id, output_target, "
                                     "output_target_arg FROM phrases").fetchall()
            global_vars = {r[0]: r[1] for r in self.conn.execute(
                "SELECT name, value FROM vars WHERE scope='global'")}
            folders = {r[0]: (r[1], r[2] or "", r[3] or "", bool(r[4]), r[5] or "", r[6] or "")
                       for r in self.conn.execute("SELECT id, parent_id, output_target, output_target_arg, "
                                                  "password_hash, text_before, text_after FROM folders")}
            versions: dict[int, list] = {}
            for r in self.conn.execute(
                    "SELECT phrase_id, lang, content, content_format FROM phrase_versions ORDER BY phrase_id, lang"):
                versions.setdefault(r[0], []).append((r[1], r[2], r[3]))
        out = {}
        for r in rows:
            chain, fid, seen, folder_texts = [], r[3], set(), []
            while fid in folders and fid not in seen:
                seen.add(fid)
                parent, target, arg, locked, before, after = folders[fid]
                entry = (target, arg, locked) if locked else (target, arg)       # leaving a lock counts (R55)
                if before or after:          # the folder's text runs with the phrase, macros included
                    entry = entry + (before, after)
                    folder_texts += [before, after]
                chain.append(entry)
                fid = parent
            texts = [r[1] or ""] + [v[1] or "" for v in versions.get(r[0], [])] + folder_texts
            blob = json.dumps([r[1], r[2], versions.get(r[0], []), r[4] or "", r[5] or "", chain,
                               _read_vars(texts, global_vars)], ensure_ascii=False)
            out[r[0]] = hashlib.sha256(blob.encode("utf-8")).hexdigest()
        return out

    @_editable
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
        return all(f.enabled and not f.is_template for f in self.folder_chain(r["folder_id"]))

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
        forced = policy.current().forced_value(key)
        if forced is not None:
            return forced                       # set by the administrator's policy file
        with self.lock:
            r = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if not r:
            return default
        return _unseal(r[0]) if is_secret_setting(key) else r[0]

    def set_setting(self, key: str, value: str) -> None:
        if policy.current().setting_locked(key):
            log.info("a setting locked by the administrator's policy was not changed")
            return
        value = _seal(str(value)) if is_secret_setting(key) else str(value)
        with self.lock, self.conn:
            self.conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, value))
        self._changed("setting")

    def settings(self) -> dict[str, str]:
        with self.lock:
            out = {r[0]: _unseal(r[1]) if is_secret_setting(r[0]) else r[1]
                   for r in self.conn.execute("SELECT key, value FROM settings")}
        pol = policy.current()
        out.update(pol.forced)
        if not pol.stats_enabled:
            out["features.usage_statistics"] = "0"
        return out

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

    @_editable
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

    @_editable
    def set_phrase_version(self, phrase_id: int, lang: str, content: str, content_format: str = "text") -> None:
        lang = (lang or "").strip()
        if not lang:
            raise ValueError("language is required")
        with self.lock, self.conn:
            self.conn.execute("INSERT OR REPLACE INTO phrase_versions VALUES (?,?,?,?,?)",
                              (phrase_id, lang, content, content_format or "text", _now()))
            self._quarantine_if_untrusted(phrase_id)
        self._changed("phrase", phrase_id)

    @_editable
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

    def merge_suggestions(self, counts: dict[str, int]) -> None:
        """Add suggestions found elsewhere (mail analysis). A text already listed keeps the
        higher count, so analyzing the same mails twice does not double it; dismissed stays dismissed."""
        if not counts:
            return
        now = _now()
        with self.lock, self.conn:
            self.conn.executemany(
                "INSERT INTO suggestions (text,count,last_seen) VALUES (?,?,?) "
                "ON CONFLICT(text) DO UPDATE SET count=MAX(count, excluded.count), last_seen=excluded.last_seen",
                [(t, int(n), now) for t, n in counts.items()])
        self._changed("suggestion")

    def clear_suggestions(self) -> None:
        """Forget all learned and mailed sentences (dismissed ones too)."""
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM suggestions")
        self._changed("suggestion")

    def dismiss_suggestion(self, text: str) -> None:
        with self.lock, self.conn:
            self.conn.execute("UPDATE suggestions SET dismissed=1 WHERE text=?", (text,))
        self._changed("suggestion")

    # ------------------------------------------------------------ trash (FR-DAT-02)
    # A deleted phrase or folder (with everything in it) is kept here as a snapshot and can be
    # put back with its id, triggers, tags, language versions, comments, history and approval
    # state. The trash belongs to this PC: it is not synced and a sync pull keeps it.
    TRASH_DAYS = 30

    def _uid(self, table: str, row_id) -> str | None:
        if row_id is None:
            return None
        r = self.conn.execute(f"SELECT uid FROM {table} WHERE id=?", (row_id,)).fetchone()
        return r[0] if r else None

    def _phrase_snapshot(self, pid: int) -> dict:
        p = self.get_phrase(pid)
        d = {k: v for k, v in vars(p).items() if k not in ("triggers", "id", "folder_id")}
        d["output_mode"] = OutputMode(p.output_mode).value
        d["triggers"] = [t.to_dict() for t in p.triggers]
        d["versions"] = {k: list(v) for k, v in self.phrase_versions(pid).items()}
        d["uid"] = self._uid("phrases", pid)
        d["quarantine"] = self.quarantine_origin(pid)
        d["comments"] = [dict(r) for r in self.conn.execute(
            "SELECT author, created, text, resolved FROM phrase_comments WHERE phrase_id=? ORDER BY id", (pid,))]
        d["history"] = [dict(r) for r in self.conn.execute(
            "SELECT saved, description, content FROM phrase_history WHERE phrase_id=? ORDER BY id", (pid,))]
        return d

    def _folder_snapshot(self, fid: int) -> dict:
        f = self.get_folder(fid)
        d = {k: v for k, v in vars(f).items() if k not in ("triggers", "id", "parent_id")}
        d["triggers"] = [t.to_dict() for t in self.folder_triggers(fid)]
        d["uid"] = self._uid("folders", fid)
        d["phrases"] = [self._phrase_snapshot(p.id) for p in self.phrases(fid)]
        d["folders"] = [self._folder_snapshot(c.id) for c in self.folders(fid)]
        return d

    @_editable
    def trash_phrase(self, phrase_id: int) -> int:
        """Delete a phrase into the trash; returns the trash entry's id."""
        with self.lock:
            p = self.get_phrase(phrase_id)
            if p is None:
                raise KeyError(phrase_id)
            parent = self.get_folder(p.folder_id) if p.folder_id is not None else None
            snap = self._phrase_snapshot(phrase_id)
            with self.conn:
                cur = self.conn.execute(
                    "INSERT INTO trash (kind,name,deleted_at,parent_uid,parent_name,data) VALUES (?,?,?,?,?,?)",
                    ("phrase", p.description, _now(), self._uid("folders", p.folder_id),
                     parent.name if parent else "", json.dumps(snap, ensure_ascii=False)))
                self.conn.execute("DELETE FROM phrases WHERE id=?", (phrase_id,))
        self._changed("phrase", phrase_id)
        return cur.lastrowid

    @_editable
    def trash_folder(self, folder_id: int) -> int:
        """Delete a folder with all its subfolders and phrases into the trash."""
        with self.lock:
            f = self.get_folder(folder_id)
            if f is None:
                raise KeyError(folder_id)
            parent = self.get_folder(f.parent_id) if f.parent_id is not None else None
            snap = self._folder_snapshot(folder_id)
            with self.conn:
                cur = self.conn.execute(
                    "INSERT INTO trash (kind,name,deleted_at,parent_uid,parent_name,data) VALUES (?,?,?,?,?,?)",
                    ("folder", f.name, _now(), self._uid("folders", f.parent_id),
                     parent.name if parent else "", json.dumps(snap, ensure_ascii=False)))
                self.conn.execute("DELETE FROM folders WHERE id=?", (folder_id,))
        self._changed("folder", folder_id)
        return cur.lastrowid

    def trash_items(self) -> list[dict]:
        """Newest first: id, kind, name, deleted_at, parent_name, count (phrases inside)."""
        with self.lock:
            rows = [dict(r) for r in self.conn.execute(
                "SELECT id, kind, name, deleted_at, parent_uid, parent_name, data FROM trash "
                "ORDER BY deleted_at DESC, id DESC")]

        def count(d):
            return len(d.get("phrases", [])) + sum(count(c) for c in d.get("folders", []))
        for r in rows:
            r["count"] = 1 if r["kind"] == "phrase" else count(json.loads(r.pop("data")))
            r.pop("data", None)
        return rows

    def _restore_phrase(self, d: dict, folder_id) -> int:
        p = Phrase(description=d["description"], content=d.get("content", ""), folder_id=folder_id,
                   content_format=d.get("content_format", "text"), output_mode=OutputMode(d.get("output_mode", "auto")),
                   apps_include=d.get("apps_include", ""), apps_exclude=d.get("apps_exclude", ""),
                   enabled=bool(d.get("enabled", True)), sort=d.get("sort", 0), tags=list(d.get("tags", [])),
                   triggers=[Trigger.from_dict(t) for t in d.get("triggers", [])],
                   use_count=d.get("use_count", 0), last_used=d.get("last_used"), created=d.get("created"),
                   notes=d.get("notes", ""), output_target=d.get("output_target", "current"),
                   output_target_arg=d.get("output_target_arg", ""))
        self.add_phrase(p)
        with self.lock, self.conn:
            uid = d.get("uid")
            if uid and not self.conn.execute("SELECT 1 FROM phrases WHERE uid=?", (uid,)).fetchone():
                self.conn.execute("UPDATE phrases SET uid=? WHERE id=?", (uid, p.id))
            self.conn.execute("UPDATE phrases SET modified=? WHERE id=?", (d.get("modified") or _now(), p.id))
            for lang, (c, cf) in (d.get("versions") or {}).items():
                self.conn.execute("INSERT OR REPLACE INTO phrase_versions VALUES (?,?,?,?,?)",
                                  (p.id, lang, c, cf, _now()))
            for c in d.get("comments", []):
                self.conn.execute("INSERT INTO phrase_comments (phrase_id,author,created,text,resolved) "
                                  "VALUES (?,?,?,?,?)", (p.id, c["author"], c["created"], c["text"], c["resolved"]))
            for h in d.get("history", []):
                self.conn.execute("INSERT INTO phrase_history (phrase_id,saved,description,content) VALUES (?,?,?,?)",
                                  (p.id, h["saved"], h["description"], h["content"]))
            # what was waiting for approval before it was deleted still waits
            self.conn.execute("DELETE FROM phrase_quarantine WHERE phrase_id=?", (p.id,))
            if d.get("quarantine"):
                self.conn.execute("INSERT INTO phrase_quarantine VALUES (?,?,?)", (p.id, d["quarantine"], _now()))
        return p.id

    def _restore_folder(self, d: dict, parent_id) -> int:
        f = Folder(name=d["name"], parent_id=parent_id,
                   **{k: d[k] for k in ("sort", "enabled", "apps_include", "apps_exclude", "password_hash",
                                        "show_in_popup", "notes", "output_target", "output_target_arg",
                                        "abbrev_prefix", "is_template", "text_before", "text_after") if k in d})
        self.add_folder(f)
        with self.lock, self.conn:
            uid = d.get("uid")
            if uid and not self.conn.execute("SELECT 1 FROM folders WHERE uid=?", (uid,)).fetchone():
                self.conn.execute("UPDATE folders SET uid=? WHERE id=?", (uid, f.id))
        if d.get("triggers"):
            self.set_folder_triggers(f.id, [Trigger.from_dict(t) for t in d["triggers"]])
        for c in d.get("folders", []):
            self._restore_folder(c, f.id)
        for p in d.get("phrases", []):
            self._restore_phrase(p, f.id)
        return f.id

    @_editable
    def restore_trash(self, trash_id: int) -> tuple[str, int]:
        """Put an item back into its folder (or the top level if that folder is gone).
        Returns (kind, new id)."""
        with self.lock:
            r = self.conn.execute("SELECT kind, parent_uid, data FROM trash WHERE id=?", (trash_id,)).fetchone()
            if r is None:
                raise KeyError(trash_id)
            parent = None
            if r["parent_uid"]:
                row = self.conn.execute("SELECT id FROM folders WHERE uid=?", (r["parent_uid"],)).fetchone()
                parent = row[0] if row else None
            d = json.loads(r["data"])
            new_id = self._restore_folder(d, parent) if r["kind"] == "folder" else self._restore_phrase(d, parent)
            with self.conn:
                self.conn.execute("DELETE FROM trash WHERE id=?", (trash_id,))
        self._changed(r["kind"], new_id)
        return r["kind"], new_id

    def delete_trash(self, trash_id: int | None = None) -> None:
        """Delete one trash entry for good, or empty the trash (None)."""
        with self.lock, self.conn:
            if trash_id is None:
                self.conn.execute("DELETE FROM trash")
            else:
                self.conn.execute("DELETE FROM trash WHERE id=?", (trash_id,))
        self._changed("trash")

    def purge_trash(self, days: int | None = None) -> int:
        """Delete trash entries older than `days` (setting trash.days, default 30; 0 = keep)."""
        if days is None:
            try:
                days = int(self.setting("trash.days", str(self.TRASH_DAYS)) or self.TRASH_DAYS)
            except ValueError:
                days = self.TRASH_DAYS
        if days <= 0:
            return 0
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        with self.lock, self.conn:
            n = self.conn.execute("DELETE FROM trash WHERE deleted_at < ?", (cutoff,)).rowcount
        return n

    # ------------------------------------------------------------ comments (FR-DAT-03)
    def comments(self, phrase_id: int) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT id, author, created, text, resolved FROM phrase_comments WHERE phrase_id=? ORDER BY id",
                (phrase_id,))]

    def comment_counts(self) -> dict[int, int]:
        """phrase id -> number of open (unresolved) comments."""
        with self.lock:
            return {r[0]: r[1] for r in self.conn.execute(
                "SELECT phrase_id, count(*) FROM phrase_comments WHERE resolved=0 GROUP BY phrase_id")}

    @_editable
    def add_comment(self, phrase_id: int, text: str, author: str | None = None) -> int:
        text = (text or "").strip()
        if not text:
            raise ValueError("A comment needs some text.")
        if author is None:
            import getpass
            try:
                author = getpass.getuser()
            except Exception:
                author = ""
        with self.lock, self.conn:
            cur = self.conn.execute("INSERT INTO phrase_comments (phrase_id,author,created,text) VALUES (?,?,?,?)",
                                    (phrase_id, author, _now(), text))
        self._changed("phrase", phrase_id)
        return cur.lastrowid

    @_editable
    def resolve_comment(self, comment_id: int, resolved: bool = True) -> None:
        with self.lock, self.conn:
            r = self.conn.execute("SELECT phrase_id FROM phrase_comments WHERE id=?", (comment_id,)).fetchone()
            self.conn.execute("UPDATE phrase_comments SET resolved=? WHERE id=?", (int(resolved), comment_id))
        self._changed("phrase", r[0] if r else None)

    @_editable
    def delete_comment(self, comment_id: int) -> None:
        with self.lock, self.conn:
            r = self.conn.execute("SELECT phrase_id FROM phrase_comments WHERE id=?", (comment_id,)).fetchone()
            self.conn.execute("DELETE FROM phrase_comments WHERE id=?", (comment_id,))
        self._changed("phrase", r[0] if r else None)

    # ------------------------------------------------------------ phrase links (FR-DAT-04)
    def phrase_uid(self, phrase_id: int) -> str | None:
        with self.lock:
            return self._uid("phrases", phrase_id)

    def phrase_by_uid(self, uid: str):
        with self.lock:
            r = self.conn.execute("SELECT id FROM phrases WHERE uid=?", (uid,)).fetchone()
        return self.get_phrase(r[0]) if r else None

    def create_link(self, phrase_id: int, folder_id: int | None) -> Phrase:
        """A phrase that always inserts the current text of phrase_id (follows its edits)."""
        target = self.get_phrase(phrase_id)
        if target is None:
            raise KeyError(phrase_id)
        uid = self.phrase_uid(phrase_id)
        return self.add_phrase(Phrase(description=target.description, content=f"{{#insert -uid {uid}}}",
                                      folder_id=folder_id))

    # ------------------------------------------------------------ folder text (FR-DAT-05)
    def folder_wrap(self, folder_id: int | None) -> tuple[str, str]:
        """(text before, text after) a phrase in this folder: the outermost folder's text comes
        first before the phrase and last after it."""
        chain = self.folder_chain(folder_id) if folder_id is not None else []
        before = "".join(f.text_before for f in reversed(chain) if f.text_before)
        after = "".join(f.text_after for f in chain if f.text_after)
        return before, after

    # ------------------------------------------------------------ templates (FR-DAT-04)
    def template_phrases(self) -> list[Phrase]:
        """Phrases inside template folders (at any depth)."""
        out = []
        for p in self.phrases():
            if p.folder_id is not None and any(f.is_template for f in self.folder_chain(p.folder_id)):
                out.append(p)
        return sorted(out, key=lambda p: p.description.lower())

    def new_from_template(self, template_id: int, folder_id: int | None) -> Phrase:
        """A new phrase with the template's text, format, output options, tags, notes and language
        versions (not its triggers: an abbreviation should not be shared by two phrases)."""
        t = self.get_phrase(template_id)
        if t is None:
            raise KeyError(template_id)
        p = Phrase(description=t.description, content=t.content, folder_id=folder_id,
                   content_format=t.content_format, output_mode=t.output_mode, apps_include=t.apps_include,
                   apps_exclude=t.apps_exclude, tags=list(t.tags), notes=t.notes,
                   output_target=t.output_target, output_target_arg=t.output_target_arg)
        self.add_phrase(p)
        for lang, (c, cf) in self.phrase_versions(template_id).items():
            self.set_phrase_version(p.id, lang, c, cf)
        if self.quarantine_origin(template_id):             # a template that waits for approval
            self.quarantine(p.id, self.quarantine_origin(template_id))
        return p

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

    @contextmanager
    def policy_bypass(self):
        """Phrase changes on this thread inside the block are allowed even when the policy
        disables editing: a sync pull is how an administrator hands out phrases."""
        self._qlocal.bypass = getattr(self._qlocal, "bypass", 0) + 1
        try:
            yield
        finally:
            self._qlocal.bypass -= 1

    def restore_from(self, path: str | Path, untrusted: str | None = None) -> None:
        """Replace all data with a backup file, in place on the open connection.

        untrusted="synced"/"imported": the file came from elsewhere (cloud pull, a phrase file
        the user opened). This PC's quarantine list is kept, the file's own list is ignored,
        and every phrase the file adds or changes is quarantined (security.py). Without it
        (restoring this PC's own backup) the backup's list is used as it is.
        While the policy disables editing only a sync pull may replace the phrases."""
        if policy.current().editing_disabled and untrusted != "synced" and not getattr(self._qlocal, "bypass", 0):
            raise policy.PolicyError(policy.current().notice("Editing phrases"))
        before = self.phrase_fingerprints() if untrusted else {}
        keep_q = self.quarantined() if untrusted else {}
        pol = policy.current()
        with self.lock:                   # raw values: API keys stay encrypted
            rows = list(self.conn.execute("SELECT key, value FROM settings"))
            keep_device = {k: v for k, v in rows if is_device_setting(k)} if untrusted else {}
            # this PC's trash stays (it is not synced, and an item in it must not arrive from elsewhere)
            keep_trash = ([tuple(r) for r in self.conn.execute(
                "SELECT id, kind, name, deleted_at, parent_uid, parent_name, data FROM trash")]
                if untrusted else None)
            # settings the administrator locked keep this PC's value, whatever the file holds:
            # a backup, an opened file or a sync pull must not unlock them (security R27)
            keep_locked = {k: v for k, v in rows if pol.setting_locked(k)}
            # folder passwords set on this PC stay, whatever the file says (R55)
            keep_pw = {}
            if untrusted and "uid" in self._columns("folders"):
                keep_pw = {u: h for u, h in self.conn.execute(
                    "SELECT uid, password_hash FROM folders WHERE password_hash IS NOT NULL AND password_hash<>''")}
        with self.lock:
            src = vault.connect(path, self.vault_key) if vault.is_encrypted(path) else sqlite3.connect(str(path))
            if self.vault_key is not None:        # in memory: load the image (a backup would copy WAL mode)
                data = src.serialize()
                src.close()
                self.conn.deserialize(vault.no_wal(data))
            else:
                src.backup(self.conn)
                src.close()
            self.conn.execute("PRAGMA foreign_keys = ON")
            self._drop_foreign_schema()   # BEFORE anything writes: the copy's triggers would run (R44)
            self._migrate_schema()        # a backup/sync copy may come from an older version
            self.conn.executescript(SCHEMA)
        # Move a legacy output-target setting into the columns BEFORE the comparison below,
        # so a synced copy cannot add a "Specific program" target after the check.
        self._migrate_extras()
        with self.lock, self.conn:
            for (k,) in self.conn.execute("SELECT key FROM settings").fetchall():
                if pol.setting_locked(k) and k not in keep_locked:
                    self.conn.execute("DELETE FROM settings WHERE key=?", (k,))
            for k, v in keep_locked.items():
                self.conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (k, v))
        if untrusted:
            with self.lock, self.conn:    # this PC's device settings win, whatever the file holds
                for (k,) in self.conn.execute("SELECT key FROM settings").fetchall():
                    if is_device_setting(k):
                        self.conn.execute("DELETE FROM settings WHERE key=?", (k,))
                for k, v in keep_device.items():
                    self.conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (k, v))
                self.conn.execute("DELETE FROM trash")
                self.conn.executemany("INSERT INTO trash VALUES (?,?,?,?,?,?,?)", keep_trash or [])
                for u, h in keep_pw.items():
                    self.conn.execute("UPDATE folders SET password_hash=? WHERE uid=?", (h, u))
            after = self.phrase_fingerprints()
            with self.lock, self.conn:
                self.conn.execute("DELETE FROM phrase_quarantine")
                for pid, fp in after.items():
                    origin = keep_q.get(pid) or (untrusted if before.get(pid) != fp else None)
                    if origin:
                        self.conn.execute("INSERT INTO phrase_quarantine VALUES (?,?,?)", (pid, origin, _now()))
        self._seal_plain_secrets()        # an old backup may hold plain-text keys
        if self.vault_key is not None:    # a backup copy may not count as a change: save now
            self._saved_changes = -1
            self.flush()
        for kind in ("folder", "phrase", "setting", "var", "clipboard", "sticky"):
            self._changed(kind)

    def backup_to(self, path: str | Path, keep_encryption: bool = False) -> None:
        """A copy of the database. keep_encryption: an encrypted phrase file's copy is encrypted
        with the same key (local backups); otherwise the copy is a plain SQLite file."""
        with self.lock:
            if keep_encryption and self.vault_key is not None:
                self.conn.commit()
                vault.write(path, self.conn.serialize(), self.vault_key)
                return
            dst = sqlite3.connect(str(path))
            with dst:
                self.conn.backup(dst)
            dst.close()


def json_dumps(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, indent=2)
