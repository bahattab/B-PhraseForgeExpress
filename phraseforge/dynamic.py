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
import re
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from phraseforge.models import Phrase, Trigger, TriggerKind

log = logging.getLogger(__name__)

SOURCES = ("text", "table", "folder", "sqlite", "odbc")
MAX_ITEMS = 5000
MAX_CONTENT = 200_000
MAX_FILE_BYTES = 20 * 1024 * 1024    # a text/table/Excel source or one file in a folder (R49)
MAX_SCAN = 20_000                    # folder entries looked at per read or change check (R62)
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


_SQL_LITERAL = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|\[[^\]]*\]|--[^\n]*|/\*.*?\*/", re.S)
_SQL_WRITE = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|grant|revoke|deny|exec|execute|into|truncate|"
    r"openrowset|opendatasource|openquery|openxml|bulk|backup|restore|declare|use|shutdown|dbcc|kill|"
    r"attach|detach|pragma|vacuum|reindex|waitfor|xp_\w*|sp_\w*)\b", re.I)


def _check_query(q: str) -> str:
    """One SELECT (or WITH ... SELECT). T-SQL needs no ";" between statements, so the words
    that write, run procedures or reach other servers are refused outside quoted text
    (security R48). The database login should still be read-only: this check is a guard,
    not a sandbox."""
    q = (q or "").strip().rstrip(";").strip()
    bare = _SQL_LITERAL.sub(" ", q)
    if not bare.lstrip().lower().startswith(("select", "with")) or ";" in bare:
        raise DynamicError("only a single SELECT query is allowed")
    bad = _SQL_WRITE.search(bare)
    if bad:
        raise DynamicError(f"only a single SELECT query is allowed ({bad.group(0)} is not)")
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
    if src in ("text", "table"):
        _check_size(Path(path))
    if src == "text":
        from phraseforge.importers.phraseexpress import _read_text
        items = []
        for ln in _read_text(path).splitlines():
            ln = ln.strip()
            if ln:
                items.append(Item(ln.casefold(), _label(ln), ln[:MAX_CONTENT]))
                if len(items) >= MAX_ITEMS:
                    break
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
        base = root.resolve()
        items = []
        for f in sorted(_scan(root, cfg.recursive)):
            if f.is_symlink() or not f.is_file() or f.name.startswith(("~$", ".")):
                continue                            # a link could point anywhere on the PC (R60)
            try:
                if not f.resolve().is_relative_to(base) or f.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            if any(c in f.name for c in '{}"'):
                continue                            # would break out of {#document "..."} (R61)
            ext = f.suffix.lower()
            rel = f.relative_to(root).as_posix()
            q = '"' + str(f).replace('"', '\\"') + '"'
            if ext in IMAGE_EXT:
                content = "{#image " + q + "}"
            elif ext in WORD_EXT + RTF_EXT:
                content = "{#document " + q + "}" if cfg.link else file_text(f)[:MAX_CONTENT]
            elif ext in (".txt", ".md", ".html", ".htm"):
                content = "{#document " + q + "}" if cfg.link else _head(f)
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


def _check_size(p: Path) -> None:
    try:
        size = p.stat().st_size
    except OSError as e:
        raise DynamicError(f"cannot read {p}: {e}") from e
    if size > MAX_FILE_BYTES:
        raise DynamicError(f"{p.name} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")


def _head(f: Path) -> str:
    with open(f, "rb") as fh:
        return fh.read(MAX_CONTENT * 4).decode("utf-8-sig", errors="replace")[:MAX_CONTENT]


def _scan(root: Path, recursive: bool):
    """Files under root, at most MAX_SCAN entries, without following directory links."""
    seen = 0
    todo = [root]
    while todo:
        d = todo.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    seen += 1
                    if seen > MAX_SCAN:
                        return
                    p = Path(e.path)
                    if e.is_dir(follow_symlinks=False):
                        if recursive:
                            todo.append(p)
                    else:
                        yield p
        except OSError:
            continue


def source_stamp(cfg: DynamicConfig) -> str:
    """Changes when a file source changes ("" for queries, which go by ttl_s)."""
    p = Path(_env_path(cfg.path))
    try:
        if cfg.source in ("text", "table"):
            st = p.stat()
            return f"{st.st_mtime_ns}:{st.st_size}"
        if cfg.source == "folder":
            parts = []
            for f in _scan(p, cfg.recursive):
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


def _stored(cfg: DynamicConfig) -> str:
    """The config as written to the phrase file. An ODBC connection string can hold a
    password and names this PC's servers: it stays on this PC, sealed (security R46)."""
    d = asdict(cfg)
    if cfg.source == "odbc":
        d["path"] = ""
    return json.dumps(d)


def config(store, folder_id: int) -> DynamicConfig | None:
    _tables(store)
    with store.lock:
        r = store.conn.execute("SELECT config FROM dynamic_folders WHERE folder_id=?", (folder_id,)).fetchone()
    if not r:
        return None
    cfg = DynamicConfig.from_json(r[0])
    if cfg.source == "odbc":
        local = store.setting(f"dynamic.conn.{folder_id}", "")
        if cfg.path and not local and approved_fp(store, folder_id) in (_fingerprint(store, folder_id, cfg),
                                                                          cfg.fingerprint()):
            # written by 0.6.7: move this PC's own connection string out of the file
            store.set_setting(f"dynamic.conn.{folder_id}", cfg.path)
            local = cfg.path
            with store.lock, store.conn:
                store.conn.execute("UPDATE dynamic_folders SET config=? WHERE folder_id=?", (_stored(cfg), folder_id))
        cfg.path = local
    return cfg


def dynamic_folder_ids(store) -> list[int]:
    _tables(store)
    with store.lock:
        return [r[0] for r in store.conn.execute("SELECT folder_id FROM dynamic_folders")]


def _fingerprint(store, folder_id: int, cfg: DynamicConfig) -> str:
    """The approval covers this source in this folder: the folder's uid is part of it, so a
    new folder that reuses a deleted folder's id does not inherit its approval (R59)."""
    uid = ""
    try:
        with store.lock:
            r = store.conn.execute("SELECT uid FROM folders WHERE id=?", (folder_id,)).fetchone()
        uid = (r[0] or "") if r else ""
    except Exception:                               # an old store without uids
        pass
    return hashlib.sha256((cfg.fingerprint() + ":" + uid).encode()).hexdigest()[:32]


def approved_fp(store, folder_id: int) -> str:
    return store.setting(f"dynamic.approved.{folder_id}", "")


def approved(store, folder_id: int, cfg: DynamicConfig | None = None) -> bool:
    cfg = cfg or config(store, folder_id)
    if cfg is None:
        return False
    have, want = approved_fp(store, folder_id), _fingerprint(store, folder_id, cfg)
    if have and have == cfg.fingerprint() and store.get_folder(folder_id) is not None:
        store.set_setting(f"dynamic.approved.{folder_id}", want)   # approved by 0.6.7: add the uid
        return True
    return bool(have) and have == want


def _editable(store) -> None:
    from phraseforge import policy
    if policy.current().editing_disabled:            # a dynamic folder writes phrases (R47)
        raise policy.PolicyError(policy.current().notice("Editing phrases"))


def set_config(store, folder_id: int, cfg: DynamicConfig, approve: bool = True) -> None:
    """Make a folder dynamic (or change its source) and, with approve, approve that source
    on this PC. A source that came from elsewhere is approved only with approve_source()."""
    _editable(store)
    if cfg.source not in SOURCES:
        raise DynamicError(f"unknown source {cfg.source!r}")
    if cfg.source in ("sqlite", "odbc"):
        _check_query(cfg.query)
    _tables(store)
    with store.lock, store.conn:
        store.conn.execute("INSERT INTO dynamic_folders (folder_id, config) VALUES (?, ?) ON CONFLICT(folder_id) "
                           "DO UPDATE SET config=excluded.config, last_refresh=0, last_stamp=''",
                           (folder_id, _stored(cfg)))
    if cfg.source == "odbc":
        store.set_setting(f"dynamic.conn.{folder_id}", cfg.path)
    if approve:
        store.set_setting(f"dynamic.approved.{folder_id}", _fingerprint(store, folder_id, cfg))


def approve_source(store, folder_id: int) -> None:
    """Approve the source as it is stored now (after the user confirmed it)."""
    _editable(store)
    cfg = config(store, folder_id)
    if cfg is not None:
        store.set_setting(f"dynamic.approved.{folder_id}", _fingerprint(store, folder_id, cfg))


def remove(store, folder_id: int, delete_phrases: bool = False) -> None:
    """Make the folder an ordinary one again (its phrases stay unless delete_phrases)."""
    _editable(store)
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
    store.set_setting(f"dynamic.conn.{folder_id}", "")


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
    if not items and known:
        # a source that is empty for a moment (being rewritten, a share that is offline)
        # must not delete the folder's phrases and their statistics (R62)
        msg = "the source returned nothing; the phrases were kept"
        with store.lock, store.conn:
            store.conn.execute("UPDATE dynamic_folders SET last_error=?, last_refresh=? WHERE folder_id=?",
                               (msg, now or time.time(), folder_id))
        raise DynamicError(msg)
    added = updated = removed = 0
    keep = set()
    # a source set up before the administrator locked editing keeps feeding its folder (IT can
    # hand out phrases that way); setting one up or changing it is refused under the lock
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
    for key in [k for k in store.settings() if k.startswith(("dynamic.approved.", "dynamic.conn."))]:
        fid = key.rsplit(".", 1)[-1]
        if fid.isdigit() and store.get_folder(int(fid)) is None and store.setting(key, ""):
            store.set_setting(key, "")                # the folder is gone: so is its approval (R59)
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
