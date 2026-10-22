"""Import / export and backup.

Formats:
  JSON   - full fidelity (Store.export_dict layout): folders tree, phrases, triggers, tags, vars, excluded apps.
  CSV    - columns: description, autotext, content, folder  (folder path "A/B/C", hotkey optional column)
  Text   - a directory tree: one sub-directory per folder, one <description>.txt per phrase.
  Backup - SQLite copy in paths.backups_dir(); restore() copies a backup over the live database file.
"""
from __future__ import annotations

import csv
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from phraseforge import paths
from phraseforge.db import Store, json_dumps
from phraseforge.models import AutotextMode, Folder, OutputMode, Phrase, Trigger, TriggerKind

_FOLDER_FIELDS = ("name", "parent_id", "sort", "enabled", "apps_include", "apps_exclude", "password_hash",
                  "show_in_popup")
_PHRASE_FIELDS = ("description", "content", "content_format", "output_mode", "apps_include", "apps_exclude",
                  "enabled", "sort", "notes", "use_count", "last_used", "created")


# ------------------------------------------------------------------ JSON
def export_json(store: Store, path: str | Path) -> int:
    d = store.export_dict()
    Path(path).write_text(json_dumps(d), encoding="utf-8")
    return len(d["phrases"])


def import_dict(store: Store, d: dict, into_folder_id: int | None = None) -> dict[str, int]:
    """Import an export_dict() snapshot. Folder ids are remapped; new folders are created under
    into_folder_id (top level when None). Returns counts."""
    if d.get("format") not in (None, "phraseforge"):
        raise ValueError("not a PhraseForge export")
    id_map: dict[int | None, int | None] = {None: into_folder_id}
    pending = list(d.get("folders", []))
    known = {f["id"] for f in pending}
    while pending:
        progressed = False
        for f in list(pending):
            parent = f.get("parent_id")
            if parent is not None and parent not in known:
                parent = None          # dangling parent -> attach at import root
            if parent in id_map:
                kw = {k: f[k] for k in _FOLDER_FIELDS if k in f and k != "parent_id"}
                nf = store.add_folder(Folder(**kw, parent_id=id_map[parent]))
                id_map[f["id"]] = nf.id
                pending.remove(f)
                progressed = True
        if not progressed:     # cycle in input: attach remainder at root
            for f in pending:
                f["parent_id"] = None
            known = set()
    n = 0
    for p in d.get("phrases", []):
        kw = {k: p[k] for k in _PHRASE_FIELDS if k in p}
        if "output_mode" in kw:
            kw["output_mode"] = OutputMode(kw["output_mode"])
        triggers = [Trigger(kind=TriggerKind(t["kind"]), value=t["value"], mode=AutotextMode(t.get("mode", "delimiter")),
                            case_sensitive=bool(t.get("case_sensitive", False)),
                            word_start_only=bool(t.get("word_start_only", True)),
                            enabled=bool(t.get("enabled", True))) for t in p.get("triggers", [])]
        store.add_phrase(Phrase(**kw, folder_id=id_map.get(p.get("folder_id"), into_folder_id),
                                tags=list(p.get("tags", [])), triggers=triggers))
        n += 1
    for v in d.get("vars", []):
        store.set_var(v["name"], v["value"], v.get("scope", "global"))
    if d.get("excluded_apps"):
        store.set_excluded_apps(store.excluded_apps() | set(d["excluded_apps"]))
    return {"folders": len(id_map) - 1, "phrases": n}


def import_json(store: Store, path: str | Path, into_folder_id: int | None = None) -> dict[str, int]:
    return import_dict(store, json.loads(Path(path).read_text(encoding="utf-8")), into_folder_id)


# ------------------------------------------------------------------ helpers
def folder_path(store: Store, folder_id: int | None) -> str:
    return "/".join(f.name for f in reversed(store.folder_chain(folder_id)))


def ensure_folder_path(store: Store, path: str, root_id: int | None = None) -> int | None:
    parent = root_id
    for name in [p.strip() for p in re.split(r"[\\/]", path or "") if p.strip()]:
        existing = next((f for f in store.folders(parent) if f.name == name), None)
        parent = existing.id if existing else store.add_folder(Folder(name, parent_id=parent)).id
    return parent


# ------------------------------------------------------------------ CSV
CSV_COLUMNS = ["description", "autotext", "content", "folder", "hotkey"]


def export_csv(store: Store, path: str | Path) -> int:
    phrases = store.phrases()
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_COLUMNS)
        for p in phrases:
            at = next((t.value for t in p.triggers if t.kind == TriggerKind.AUTOTEXT), "")
            hk = next((t.value for t in p.triggers if t.kind == TriggerKind.HOTKEY), "")
            w.writerow([p.description, at, p.content, folder_path(store, p.folder_id), hk])
    return len(phrases)


def import_csv(store: Store, path: str | Path, into_folder_id: int | None = None) -> int:
    n = 0
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        return 0
    header = [h.strip().lower() for h in rows[0]]
    has_header = "description" in header or "content" in header
    cols = header if has_header else CSV_COLUMNS[:len(rows[0])]
    for row in rows[1:] if has_header else rows:
        rec = dict(zip(cols, row))
        content = rec.get("content", "")
        desc = rec.get("description") or content[:40] or "Phrase"
        triggers = []
        if rec.get("autotext"):
            triggers.append(Trigger(TriggerKind.AUTOTEXT, rec["autotext"]))
        if rec.get("hotkey"):
            triggers.append(Trigger(TriggerKind.HOTKEY, rec["hotkey"]))
        fid = ensure_folder_path(store, rec.get("folder", ""), into_folder_id)
        store.add_phrase(Phrase(desc, content, folder_id=fid, triggers=triggers))
        n += 1
    return n


# ------------------------------------------------------------------ plain text tree
def _safe(name: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return s[:120] or "untitled"


def export_text_folder(store: Store, directory: str | Path) -> int:
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in store.phrases():
        d = root.joinpath(*[_safe(f.name) for f in reversed(store.folder_chain(p.folder_id))])
        d.mkdir(parents=True, exist_ok=True)
        base, i = _safe(p.description), 1
        target = d / f"{base}.txt"
        while target.exists():
            i += 1
            target = d / f"{base} ({i}).txt"
        target.write_text(p.content, encoding="utf-8")
        n += 1
    return n


def import_text_folder(store: Store, directory: str | Path, into_folder_id: int | None = None) -> int:
    root = Path(directory)
    n = 0
    for f in sorted(root.rglob("*.txt")):
        rel = f.relative_to(root).parent
        fid = ensure_folder_path(store, str(rel) if str(rel) != "." else "", into_folder_id)
        store.add_phrase(Phrase(f.stem, f.read_text(encoding="utf-8", errors="replace"), folder_id=fid))
        n += 1
    return n


# ------------------------------------------------------------------ backup / restore
def backup(store: Store, directory: str | Path | None = None) -> Path:
    d = Path(directory) if directory else paths.backups_dir()
    d.mkdir(parents=True, exist_ok=True)
    target = d / f"phrases-{datetime.now():%Y%m%d-%H%M%S}.db"
    i = 1
    while target.exists():
        i += 1
        target = d / f"phrases-{datetime.now():%Y%m%d-%H%M%S}-{i}.db"
    store.backup_to(target)
    return target


def restore(store_path: str | Path, backup_path: str | Path) -> None:
    """Overwrite the database at store_path with backup_path. Close any Store on store_path first."""
    bp = Path(backup_path)
    if not bp.is_file():
        raise FileNotFoundError(backup_path)
    src = sqlite3.connect(f"file:{bp}?mode=ro", uri=True)
    try:
        src.execute("SELECT count(*) FROM phrases").fetchone()   # sanity check
        dst = sqlite3.connect(str(store_path))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def list_backups(directory: str | Path | None = None) -> list[Path]:
    d = Path(directory) if directory else paths.backups_dir()
    return sorted(d.glob("phrases-*.db"), reverse=True)


# ---------------------------------------------------------------- dispatch by file type
def import_file(store: Store, path: str | Path, into_folder_id: int | None = None):
    """Import .json, .csv, a .textexpander group file, or a folder of .txt files."""
    p = Path(path)
    ext = p.suffix.lower()
    if p.is_dir():
        return import_text_folder(store, p, into_folder_id)
    if ext == ".json":
        return import_json(store, p, into_folder_id)
    if ext == ".csv":
        return import_csv(store, p, into_folder_id)
    if ext == ".textexpander":
        from phraseforge.importers.textexpander import import_textexpander_file
        return import_textexpander_file(store, p).imported
    if ext == ".txt":
        return import_text_folder(store, p.parent, into_folder_id)
    raise ValueError(f"Unsupported file type: {ext or p.name}")


def export_file(store: Store, path: str | Path):
    """Export by extension: .json, .csv, or .txt (writes a folder of .txt files next to it)."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext == ".csv":
        return export_csv(store, p)
    if ext == ".txt":
        return export_text_folder(store, p.with_suffix(""))
    return export_json(store, p if ext == ".json" else p.with_suffix(".json"))
