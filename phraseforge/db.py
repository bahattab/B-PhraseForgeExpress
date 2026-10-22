"""SQLite storage for folders, phrases, triggers, tags, variables, history,
statistics, clipboard history, settings and learning suggestions.

Thread-safety: one Store per thread, or guard with Store.lock. The Store uses
check_same_thread=False plus an RLock so the hook thread can read safely.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Iterable

from phraseforge.models import (
    AutotextMode, ClipboardEntry, Folder, OutputMode, Phrase, Trigger, TriggerKind,
)

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS folders (
  id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
  name TEXT NOT NULL, sort INTEGER DEFAULT 0, enabled INTEGER DEFAULT 1,
  apps_include TEXT DEFAULT '', apps_exclude TEXT DEFAULT '',
  password_hash TEXT DEFAULT '', show_in_popup INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS phrases (
  id INTEGER PRIMARY KEY, folder_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
  description TEXT NOT NULL, content TEXT DEFAULT '', content_format TEXT DEFAULT 'text',
  output_mode TEXT DEFAULT 'auto', apps_include TEXT DEFAULT '', apps_exclude TEXT DEFAULT '',
  enabled INTEGER DEFAULT 1, sort INTEGER DEFAULT 0, use_count INTEGER DEFAULT 0,
  last_used TEXT, created TEXT, modified TEXT, notes TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS triggers (
  id INTEGER PRIMARY KEY, phrase_id INTEGER NOT NULL REFERENCES phrases(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, value TEXT NOT NULL, mode TEXT DEFAULT 'delimiter',
  case_sensitive INTEGER DEFAULT 0, word_start_only INTEGER DEFAULT 1, enabled INTEGER DEFAULT 1);
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
"""

DEFAULT_SETTINGS = {
    "autotext.delimiters": " \t\n.,;:!?)]}'\"",
    "autotext.enabled": "1",
    "popup.hotkey": "ctrl+alt+space",
    "ocr.hotkey": "ctrl+alt+o",
    "clipboard_history.hotkey": "ctrl+alt+v",
    "ocr.cli_path": r"C:\Program Files\00 - Capture2Text v4.6.3 - Arabic\Capture2Text_CLI.exe",
    "ocr.language": "English",
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
    "ai.provider": "openai",              # openai | anthropic | ollama | openrouter
    "ai.model": "",
    "ai.openai_key": "",
    "ai.anthropic_key": "",
    "ai.openrouter_key": "",
    "ai.ollama_url": "http://localhost:11434",
    "ui.theme": "system",
    "ui.language": "en",
    "app.start_with_windows": "0",
    "app.first_run_done": "0",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def hash_password(pw: str) -> str:
    return hashlib.sha256(("phraseforge:" + pw).encode()).hexdigest() if pw else ""


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
            for k, v in DEFAULT_SETTINGS.items():
                self.conn.execute("INSERT OR IGNORE INTO settings VALUES (?, ?)", (k, v))
        self._listeners: list = []

    # ------------------------------------------------------------ change events
    def on_change(self, callback) -> None:
        """callback(kind: str, id: int|None) after any write. kind in
        folder|phrase|setting|var|clipboard|suggestion."""
        self._listeners.append(callback)

    def _changed(self, kind: str, id_: int | None = None) -> None:
        for cb in list(self._listeners):
            try:
                cb(kind, id_)
            except Exception:  # listeners must not break storage
                pass

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------ folders
    def add_folder(self, f: Folder) -> Folder:
        with self.lock, self.conn:
            cur = self.conn.execute(
                "INSERT INTO folders (parent_id,name,sort,enabled,apps_include,apps_exclude,password_hash,show_in_popup)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (f.parent_id, f.name, f.sort, int(f.enabled), f.apps_include, f.apps_exclude,
                 f.password_hash, int(f.show_in_popup)))
            f.id = cur.lastrowid
        self._changed("folder", f.id)
        return f

    def update_folder(self, f: Folder) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                "UPDATE folders SET parent_id=?,name=?,sort=?,enabled=?,apps_include=?,apps_exclude=?,"
                "password_hash=?,show_in_popup=? WHERE id=?",
                (f.parent_id, f.name, f.sort, int(f.enabled), f.apps_include, f.apps_exclude,
                 f.password_hash, int(f.show_in_popup), f.id))
        self._changed("folder", f.id)

    def delete_folder(self, folder_id: int) -> None:
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM folders WHERE id=?", (folder_id,))
        self._changed("folder", folder_id)

    def _row_folder(self, r) -> Folder:
        return Folder(id=r["id"], parent_id=r["parent_id"], name=r["name"], sort=r["sort"],
                      enabled=bool(r["enabled"]), apps_include=r["apps_include"],
                      apps_exclude=r["apps_exclude"], password_hash=r["password_hash"],
                      show_in_popup=bool(r["show_in_popup"]))

    def get_folder(self, folder_id: int) -> Folder | None:
        with self.lock:
            r = self.conn.execute("SELECT * FROM folders WHERE id=?", (folder_id,)).fetchone()
        return self._row_folder(r) if r else None

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
                "apps_exclude,enabled,sort,use_count,last_used,created,modified,notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (p.folder_id, p.description, p.content, p.content_format, OutputMode(p.output_mode).value,
                 p.apps_include, p.apps_exclude, int(p.enabled), p.sort, p.use_count, p.last_used,
                 p.created, p.modified, p.notes))
            p.id = cur.lastrowid
            self._write_triggers(p)
            self._write_tags(p)
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
                "apps_include=?,apps_exclude=?,enabled=?,sort=?,modified=?,notes=? WHERE id=?",
                (p.folder_id, p.description, p.content, p.content_format, OutputMode(p.output_mode).value,
                 p.apps_include, p.apps_exclude, int(p.enabled), p.sort, p.modified, p.notes, p.id))
            self._write_triggers(p)
            self._write_tags(p)
        self._changed("phrase", p.id)

    def delete_phrase(self, phrase_id: int) -> None:
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM phrases WHERE id=?", (phrase_id,))
        self._changed("phrase", phrase_id)

    def _write_triggers(self, p: Phrase) -> None:
        self.conn.execute("DELETE FROM triggers WHERE phrase_id=?", (p.id,))
        for t in p.triggers:
            cur = self.conn.execute(
                "INSERT INTO triggers (phrase_id,kind,value,mode,case_sensitive,word_start_only,enabled)"
                " VALUES (?,?,?,?,?,?,?)",
                (p.id, TriggerKind(t.kind).value, t.value, AutotextMode(t.mode).value,
                 int(t.case_sensitive), int(t.word_start_only), int(t.enabled)))
            t.id, t.phrase_id = cur.lastrowid, p.id

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
                   modified=r["modified"], notes=r["notes"])
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
                       word_start_only=bool(r["word_start_only"]), enabled=bool(r["enabled"]))

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

    def triggers(self, kind: TriggerKind | None = None) -> list[Trigger]:
        """Enabled triggers of enabled phrases inside enabled folders."""
        with self.lock:
            sql = ("SELECT t.* FROM triggers t JOIN phrases p ON p.id=t.phrase_id "
                   "WHERE t.enabled=1 AND p.enabled=1")
            args: tuple = ()
            if kind is not None:
                sql += " AND t.kind=?"
                args = (TriggerKind(kind).value,)
            rows = self.conn.execute(sql, args).fetchall()
            out = [self._row_trigger(r) for r in rows]
        return [t for t in out if self.phrase_folder_enabled(t.phrase_id)]

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
        return r[0] if r else default

    def set_setting(self, key: str, value: str) -> None:
        with self.lock, self.conn:
            self.conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, str(value)))
        self._changed("setting")

    def settings(self) -> dict[str, str]:
        with self.lock:
            return {r[0]: r[1] for r in self.conn.execute("SELECT key, value FROM settings")}

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
            "folders": [vars(f) for f in self.folders()],
            "phrases": [{**{k: v for k, v in vars(p).items() if k != "triggers"},
                         "output_mode": OutputMode(p.output_mode).value,
                         "triggers": [{**vars(t), "kind": TriggerKind(t.kind).value,
                                       "mode": AutotextMode(t.mode).value} for t in p.triggers]}
                        for p in self.phrases()],
            "vars": self.all_vars(),
            "excluded_apps": sorted(self.excluded_apps()),
        }

    def restore_from(self, path: str | Path) -> None:
        """Replace all data with a backup file, in place on the open connection."""
        with self.lock:
            src = sqlite3.connect(str(path))
            src.backup(self.conn)
            src.close()
            self.conn.execute("PRAGMA foreign_keys = ON")
        for kind in ("folder", "phrase", "setting", "var", "clipboard"):
            self._changed(kind)

    def backup_to(self, path: str | Path) -> None:
        with self.lock:
            dst = sqlite3.connect(str(path))
            with dst:
                self.conn.backup(dst)
            dst.close()


def json_dumps(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, indent=2)
