"""Dynamic folders (PRD FR-DYN-01, gap G-22): a folder whose phrases come from a source
and are kept up to date when the source changes.

Sources
  text      a .txt file: one phrase per non-empty line
  table     a .csv / .tsv file or an Excel sheet (.xlsx, first sheet or `sheet`): one phrase
            per row. A header row naming the columns (Description, Content, Autotext ...,
            the same names as the CSV import) maps them; otherwise column A is the
            description and the other cells the content.
  folder    the files in a folder on disk (subfolders with `recursive`): one phrase per
            file; Word/RTF/text files give their text (`link` = {#document} with the path,
            read again on every use), images {#image}
  sqlite    a query on an SQLite database file, opened read-only
  odbc      a query on an ODBC data source (SQL Server, Access, ...), SELECT only

The phrases are stored like any other (so the phrase menu, search and autotext work
with them unchanged) and are tagged "dynamic". A refresh adds new items, updates
changed ones in place (same phrase, so its usage statistics stay) and removes items
that left the source. Edits made by hand to a dynamic folder's phrases are replaced at
the next refresh. Items are refreshed when the file changes, and queries every
`ttl_s` seconds (default 300), or with Refresh now.

Safety: a dynamic folder's settings are part of the phrase file and travel with a cloud
sync or a shared phrase file, so a source is read only on a PC where the user approved
it (setting dynamic.approved.<folder id> = fingerprint of the source; device settings
are never synced). Without it, a synced folder could read any file on this PC into
phrases and upload them. New and changed items are quarantined like an import, so
their {#run}-type macros wait for approval. At most MAX_ITEMS items are read.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from phraseforge.models import Phrase, Trigger, TriggerKind

log = logging.getLogger(__name__)

SOURCES = ("text", "table", "folder", "sqlite", "odbc")
MAX_ITEMS = 5000
MAX_CONTENT = 200_000
TAG = "dynamic"
TABLES = """
CREATE TABLE IF NOT EXISTS dynamic_folders (
  folder_id INTEGER PRIMARY KEY REFERENCES folders(id) ON DELETE CASCADE, config TEXT NOT NULL,
  last_refresh REAL DEFAULT 0, last_stamp TEXT DEFAULT '', last_error TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS dynamic_items (
  folder_id INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE, item_key TEXT NOT NULL,
  phrase_id INTEGER NOT NULL REFERENCES phrases(id) ON DELETE CASCADE, fp TEXT NOT NULL,
  PRIMARY KEY (folder_id, item_key));
"""


class DynamicError(Exception):
    pass


@dataclass
class DynamicConfig:
    source: str                      # one of SOURCES
    path: str = ""                   # file / folder / database file, or the ODBC connection string
    query: str = ""                  # sqlite / odbc
    sheet: str = ""                  # Excel sheet name ("" = first)
    columns: dict = field(default_factory=dict)   # {"description": "Name", "content": "Text", "autotext": "Code"}
    recursive: bool = False          # folder
    link: bool = False               # folder: {#document "path"} instead of a copy of the text
    ttl_s: int = 300                 # queries are run again after this many seconds

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:32]

    @classmethod
    def from_json(cls, text: str) -> "DynamicConfig":
        d = json.loads(text)
        names = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in names})


@dataclass
class Item:
    key: str
    description: str
    content: str
    autotext: str = ""

    def fp(self) -> str:
        return hashlib.sha256(json.dumps([self.description, self.content, self.autotext]).encode()).hexdigest()


# ---------------------------------------------------------------- reading the sources
def _label(text: str) -> str:
    from phraseforge.importers.files import _label as lab
    return lab(text)


def _keyed(items: list[Item]) -> list[Item]:
    """Make keys unique (two rows with the same description get #2, #3 ...)."""
    seen: dict[str, int] = {}
    out = []
    for it in items:
        n = seen.get(it.key, 0) + 1
        seen[it.key] = n
        if n > 1:
            it.key = f"{it.key}#{n}"
        out.append(it)
    return out


def _rows_to_items(rows: list[list[str]], columns: dict) -> list[Item]:
    """Table rows (first row may be a header) -> items, with an optional explicit column map."""
    from phraseforge.importers.files import _table_phrases
    if rows and columns:
        header = [str(h).strip() for h in rows[0]]
        lower = [h.casefold() for h in header]
        renamed = list(header)
        for field_name, col in columns.items():
            if not col:
                continue
            want = str(col).strip().casefold()
            if want in lower:
                renamed[lower.index(want)] = field_name.capitalize()
            elif want.isdigit() and int(want) - 1 < len(renamed):
                renamed[int(want) - 1] = field_name.capitalize()
        rows = [renamed] + rows[1:]
    items = []
    for p in _table_phrases(rows):
        if not (p.content or "").strip():
            continue                                  # a row without text would be an empty phrase
        at = next((t.value for t in p.triggers if t.kind == TriggerKind.AUTOTEXT), "")
        items.append(Item(p.description.casefold(), p.description, p.content[:MAX_CONTENT], at))
    return items


def _csv_rows(path: Path) -> list[list[str]]:
    from phraseforge.importers.phraseexpress import _dialect, _read_text
    text = _read_text(path)
    return [r for r in csv.reader(io.StringIO(text), _dialect(text)) if any(c.strip() for c in r)]


def _check_query(q: str) -> str:
    q = (q or "").strip().rstrip(";")
    if not q.lower().startswith(("select", "with")) or ";" in q:
        raise DynamicError("only a single SELECT query is allowed")
    return q


def _query_rows(cur, query: str) -> list[list[str]]:
    cur.execute(_check_query(query))
    header = [d[0] for d in cur.description or []]
    rows = [header]
    for r in cur.fetchmany(MAX_ITEMS):
        rows.append(["" if v is None else str(v) for v in r])
    return rows


def read_items(cfg: DynamicConfig, odbc_connect=None) -> list[Item]:
    """The items the source holds now."""
    src = cfg.source
    path = cfg.path if src == "odbc" else _env_path(cfg.path)    # %USERPROFILE%\\... works for files
    if src not in SOURCES:
        raise DynamicError(f"unknown source {src!r}")
    if src == "text":
        from phraseforge.importers.phraseexpress import _read_text
        lines = [ln.strip() for ln in _read_text(path).splitlines()]
        items = [Item(ln.casefold(), _label(ln), ln) for ln in lines if ln]
    elif src == "table":
        p = Path(path)
        if p.suffix.lower() in (".xlsx", ".xlsm"):
            from phraseforge.importers.files import xlsx_rows
            sheets = xlsx_rows(p)
            pick = [rows for name, rows in sheets if not cfg.sheet or name == cfg.sheet]
            if not pick:
                raise DynamicError(f"no sheet named {cfg.sheet!r}")
            rows = pick[0]
        else:
            rows = _csv_rows(p)
        items = _rows_to_items(rows, cfg.columns)
    elif src == "folder":
        from phraseforge.importers.files import IMAGE_EXT, RTF_EXT, WORD_EXT, file_text
        root = Path(path)
        if not root.is_dir():
            raise DynamicError(f"folder not found: {path}")
        files = sorted(root.rglob("*") if cfg.recursive else root.iterdir())
        items = []
        for f in files:
            if not f.is_file() or f.name.startswith(("~$", ".")):
                continue
            ext = f.suffix.lower()
            rel = f.relative_to(root).as_posix()
            q = '"' + str(f).replace('"', '\\"') + '"'
            if ext in IMAGE_EXT:
                content = "{#image " + q + "}"
            elif ext in WORD_EXT + RTF_EXT:
                content = "{#document " + q + "}" if cfg.link else file_text(f)[:MAX_CONTENT]
            elif ext in (".txt", ".md", ".html", ".htm"):
                content = "{#document " + q + "}" if cfg.link else \
                    f.read_bytes()[:MAX_CONTENT * 4].decode("utf-8-sig", errors="replace")[:MAX_CONTENT]
            else:
                continue
            items.append(Item(rel.casefold(), f.stem, content))
            if len(items) >= MAX_ITEMS:
                break
    elif src == "sqlite":
        p = Path(path)
        if not p.is_file():
            raise DynamicError(f"database not found: {path}")
        conn = sqlite3.connect(f"{p.resolve().as_uri()}?mode=ro", uri=True)
        try:
            rows = _query_rows(conn.cursor(), cfg.query)
        finally:
            conn.close()
        items = _rows_to_items(rows, cfg.columns or {"description": rows[0][0] if rows and rows[0] else ""})
    else:
        if odbc_connect is None:
            try:
                import pyodbc  # type: ignore
            except ImportError as e:
                raise DynamicError("pyodbc is not installed") from e
            odbc_connect = lambda cs: pyodbc.connect(cs, readonly=True, timeout=10)   # noqa: E731
        conn = odbc_connect(path)
        try:
            rows = _query_rows(conn.cursor(), cfg.query)
        finally:
            conn.close()
        items = _rows_to_items(rows, cfg.columns or {"description": rows[0][0] if rows and rows[0] else ""})
    return _keyed(items)[:MAX_ITEMS]


def source_stamp(cfg: DynamicConfig) -> str:
    """Changes when a file source changes ("" for queries, which go by ttl_s)."""
    p = Path(_env_path(cfg.path))
    try:
        if cfg.source in ("text", "table"):
            st = p.stat()
            return f"{st.st_mtime_ns}:{st.st_size}"
        if cfg.source == "folder":
            parts = []
            for f in (p.rglob("*") if cfg.recursive else p.iterdir()):
                if f.is_file():
                    st = f.stat()
                    parts.append(f"{f}:{st.st_mtime_ns}:{st.st_size}")
            return hashlib.sha256("|".join(sorted(parts)).encode()).hexdigest()
    except OSError:
        return "missing"
    return ""


# ---------------------------------------------------------------- the folders
def _tables(store) -> None:
    with store.lock:
        store.conn.executescript(TABLES)


def config(store, folder_id: int) -> DynamicConfig | None:
    _tables(store)
    with store.lock:
        r = store.conn.execute("SELECT config FROM dynamic_folders WHERE folder_id=?", (folder_id,)).fetchone()
    return DynamicConfig.from_json(r[0]) if r else None


def dynamic_folder_ids(store) -> list[int]:
    _tables(store)
    with store.lock:
        return [r[0] for r in store.conn.execute("SELECT folder_id FROM dynamic_folders")]


def approved(store, folder_id: int, cfg: DynamicConfig | None = None) -> bool:
    cfg = cfg or config(store, folder_id)
    return cfg is not None and store.setting(f"dynamic.approved.{folder_id}", "") == cfg.fingerprint()


def set_config(store, folder_id: int, cfg: DynamicConfig) -> None:
    """Make a folder dynamic (or change its source) and approve that source on this PC."""
    if cfg.source not in SOURCES:
        raise DynamicError(f"unknown source {cfg.source!r}")
    if cfg.source in ("sqlite", "odbc"):
        _check_query(cfg.query)
    _tables(store)
    with store.lock, store.conn:
        store.conn.execute("INSERT INTO dynamic_folders (folder_id, config) VALUES (?, ?) ON CONFLICT(folder_id) "
                           "DO UPDATE SET config=excluded.config, last_refresh=0, last_stamp=''",
                           (folder_id, json.dumps(asdict(cfg))))
    store.set_setting(f"dynamic.approved.{folder_id}", cfg.fingerprint())


def remove(store, folder_id: int, delete_phrases: bool = False) -> None:
    """Make the folder an ordinary one again (its phrases stay unless delete_phrases)."""
    _tables(store)
    with store.lock:
        ids = [r[0] for r in store.conn.execute("SELECT phrase_id FROM dynamic_items WHERE folder_id=?", (folder_id,))]
    if delete_phrases:
        for pid in ids:
            store.delete_phrase(pid)
    with store.lock, store.conn:
        store.conn.execute("DELETE FROM dynamic_items WHERE folder_id=?", (folder_id,))
        store.conn.execute("DELETE FROM dynamic_folders WHERE folder_id=?", (folder_id,))
    store.set_setting(f"dynamic.approved.{folder_id}", "")


def status(store, folder_id: int) -> dict:
    _tables(store)
    with store.lock:
        r = store.conn.execute("SELECT last_refresh, last_error FROM dynamic_folders WHERE folder_id=?",
                               (folder_id,)).fetchone()
        n = store.conn.execute("SELECT COUNT(*) FROM dynamic_items WHERE folder_id=?", (folder_id,)).fetchone()[0]
    return {"items": n, "last_refresh": r[0] if r else 0, "error": (r[1] if r else "") or ""}


def due(store, folder_id: int, now: float | None = None) -> bool:
    cfg = config(store, folder_id)
    if cfg is None:
        return False
    with store.lock:
        r = store.conn.execute("SELECT last_refresh, last_stamp FROM dynamic_folders WHERE folder_id=?",
                               (folder_id,)).fetchone()
    last, stamp = (r[0] or 0, r[1] or "") if r else (0, "")
    if not last:
        return True
    if cfg.source in ("sqlite", "odbc"):
        return (now or time.time()) - last >= max(30, int(cfg.ttl_s or 300))
    return source_stamp(cfg) != stamp


def refresh(store, folder_id: int, odbc_connect=None, now: float | None = None) -> tuple[int, int, int]:
    """Bring the folder's phrases in line with its source. Returns (added, updated, removed)."""
    cfg = config(store, folder_id)
    if cfg is None:
        raise DynamicError("not a dynamic folder")
    if not approved(store, folder_id, cfg):
        raise DynamicError("this folder's source has not been approved on this PC; open Dynamic folder "
                           "settings and save them to approve it")
    stamp = source_stamp(cfg)
    try:
        items = read_items(cfg, odbc_connect)
    except Exception as e:
        with store.lock, store.conn:
            store.conn.execute("UPDATE dynamic_folders SET last_error=?, last_refresh=? WHERE folder_id=?",
                               (str(e)[:500], now or time.time(), folder_id))
        raise DynamicError(str(e)) from e
    with store.lock:
        known = {k: (pid, fp) for k, pid, fp in store.conn.execute(
            "SELECT item_key, phrase_id, fp FROM dynamic_items WHERE folder_id=?", (folder_id,))}
    added = updated = removed = 0
    keep = set()
    with store.policy_bypass(), store.quarantine_writes("imported"):
        for it in items:
            keep.add(it.key)
            trig = [Trigger(TriggerKind.AUTOTEXT, it.autotext)] if it.autotext else []
            old = known.get(it.key)
            p = store.get_phrase(old[0]) if old else None
            if p is None:
                p = store.add_phrase(Phrase(it.description, it.content, folder_id=folder_id, tags=[TAG], triggers=trig))
                added += 1
            elif old[1] != it.fp() or p.folder_id != folder_id:
                p.description, p.content, p.folder_id, p.triggers = it.description, it.content, folder_id, trig
                if TAG not in p.tags:
                    p.tags = list(p.tags) + [TAG]
                store.update_phrase(p, record_history=False)
                updated += 1
            else:
                continue
            with store.lock, store.conn:
                store.conn.execute("INSERT OR REPLACE INTO dynamic_items VALUES (?, ?, ?, ?)",
                                   (folder_id, it.key, p.id, it.fp()))
        for key, (pid, _fp) in known.items():
            if key not in keep:
                if store.get_phrase(pid) is not None:
                    store.delete_phrase(pid)
                removed += 1
                with store.lock, store.conn:
                    store.conn.execute("DELETE FROM dynamic_items WHERE folder_id=? AND item_key=?", (folder_id, key))
    with store.lock, store.conn:
        store.conn.execute("UPDATE dynamic_folders SET last_refresh=?, last_stamp=?, last_error='' WHERE folder_id=?",
                           (now or time.time(), stamp, folder_id))
    return added, updated, removed


def refresh_due(store, odbc_connect=None) -> list[tuple[int, str]]:
    """Refresh every approved dynamic folder that is due. Returns [(folder id, error)] for failures."""
    errors = []
    for fid in dynamic_folder_ids(store):
        if store.get_folder(fid) is None or not approved(store, fid):
            continue
        try:
            if due(store, fid):
                refresh(store, fid, odbc_connect)
        except Exception as e:
            log.warning("dynamic folder %s: %s", fid, e)
            errors.append((fid, str(e)))
    return errors


def _env_path(p: str) -> str:
    return os.path.expandvars(os.path.expanduser(p))
