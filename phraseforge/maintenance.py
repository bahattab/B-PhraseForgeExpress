"""Maintenance tools (PRD G-27, FR-UI-01): duplicate finder, backup compare, check and compact.

  find_duplicates  phrases with the same text (anywhere in the tree) and abbreviations used
                   by more than one phrase
  compare          what changed between a backup and now (or between two backups): phrases
                   added, removed and changed, matched by their stable uid (row id for
                   backups from versions before uids)
  check / compact  SQLite integrity check, and VACUUM to give back the space of deleted
                   phrases (an encrypted phrase file is compacted in memory and saved)
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from phraseforge.models import TriggerKind


@dataclass
class DuplicateGroup:
    kind: str                     # "content" | "autotext"
    key: str                      # the shared text (shortened) or the abbreviation
    phrase_ids: list[int] = field(default_factory=list)


def _norm(text: str) -> str:
    return "\n".join(line.rstrip() for line in (text or "").strip().splitlines())


def find_duplicates(store, include_empty: bool = False) -> list[DuplicateGroup]:
    """Groups of two or more phrases with the same text, and abbreviations shared by several
    phrases. Language versions count as part of the text."""
    by_text: dict[str, list] = {}
    for p in store.phrases():
        text = _norm(p.content)
        if not text and not include_empty:
            continue
        versions = store.phrase_versions(p.id)
        h = hashlib.sha256(json.dumps([p.content_format, text, sorted(versions.items())],
                                      ensure_ascii=False).encode("utf-8")).hexdigest()
        by_text.setdefault(h, []).append(p)
    groups = []
    for ps in by_text.values():
        if len(ps) > 1:
            ps.sort(key=lambda p: (p.folder_id or 0, p.sort, p.id))
            first = _norm(ps[0].content).replace("\n", " ")
            groups.append(DuplicateGroup("content", first[:80] + ("…" if len(first) > 80 else ""),
                                         [p.id for p in ps]))
    by_abbr: dict[str, set] = {}
    with store.lock:                         # every abbreviation, also of switched-off phrases
        rows = store.conn.execute("SELECT phrase_id, value, case_sensitive FROM triggers "
                                  "WHERE kind=? AND phrase_id IS NOT NULL", (TriggerKind.AUTOTEXT.value,)).fetchall()
    for pid, value, cs in rows:
        key = value if cs else value.lower()
        by_abbr.setdefault(key, set()).add(pid)
    for abbr, ids in sorted(by_abbr.items()):
        if len(ids) > 1:
            groups.append(DuplicateGroup("autotext", abbr, sorted(ids)))
    return groups


# ---------------------------------------------------------------- backup compare
@dataclass
class Change:
    kind: str                     # "added" | "removed" | "changed"
    description: str
    folder: str                   # folder path, "" = top level
    fields: list[str] = field(default_factory=list)   # what changed
    uid: str = ""
    old: dict | None = None       # the phrase as it was in the older copy
    new: dict | None = None


FIELD_NAMES = {"description": "description", "content": "text", "folder": "folder", "triggers": "triggers",
               "tags": "tags", "versions": "language versions", "enabled": "enabled", "notes": "notes",
               "output_mode": "output", "output_target": "output target", "output_target_arg": "output target",
               "apps_include": "programs", "apps_exclude": "programs", "sort": "order"}
COMPARED = ("description", "content", "folder", "triggers", "tags", "versions", "enabled", "notes", "output_mode",
            "output_target", "output_target_arg", "apps_include", "apps_exclude")


def _folder_path(state, uid) -> str:
    names, seen = [], set()
    while uid is not None and uid in state.folders and uid not in seen:
        seen.add(uid)
        names.append(state.folders[uid]["name"])
        uid = state.folders[uid]["parent"]
    return " / ".join(reversed(names))


def _current_copy(store) -> Path:
    fd, name = tempfile.mkstemp(prefix="pf-cmp-", suffix=".db")
    os.close(fd)
    # an encrypted phrase file's copy stays encrypted: a plain one in %TEMP% held every phrase (R80)
    store.backup_to(name, keep_encryption=True)
    return Path(name)


def compare(older: str | Path, newer=None, key=None) -> list[Change]:
    """What changed from `older` (a backup file) to `newer` (another backup file, or a Store:
    the phrases now). key: the vault key, for backups encrypted like the phrase file."""
    from phraseforge.cloud import merge
    tmp = None
    if newer is not None and not isinstance(newer, (str, Path)):
        key = key if key is not None else getattr(newer, "vault_key", None)
        tmp = newer = _current_copy(newer)
    try:
        a = merge.read_state(older, key, allow_rowids=True)
        b = merge.read_state(newer, key, allow_rowids=True)
    finally:
        if tmp is not None:
            from phraseforge import vault
            if vault.is_encrypted(tmp):
                tmp.unlink(missing_ok=True)
            else:
                vault.wipe(tmp)
    out: list[Change] = []
    fpath_a = {u: _folder_path(a, u) for u in a.folders}
    fpath_b = {u: _folder_path(b, u) for u in b.folders}
    for u, rec in b.phrases.items():
        old = a.phrases.get(u)
        if old is None:
            out.append(Change("added", rec["description"], fpath_b.get(rec["folder"], ""), uid=u, new=rec))
            continue
        diff = []
        for f in COMPARED:
            va = fpath_a.get(old["folder"], "") if f == "folder" else old.get(f)
            vb = fpath_b.get(rec["folder"], "") if f == "folder" else rec.get(f)
            if va != vb and FIELD_NAMES[f] not in diff:
                diff.append(FIELD_NAMES[f])
        if diff:
            out.append(Change("changed", rec["description"], fpath_b.get(rec["folder"], ""), diff, u, old, rec))
    for u, rec in a.phrases.items():
        if u not in b.phrases:
            out.append(Change("removed", rec["description"], fpath_a.get(rec["folder"], ""), uid=u, old=rec))
    order = {"removed": 0, "changed": 1, "added": 2}
    out.sort(key=lambda c: (order[c.kind], c.folder.lower(), c.description.lower()))
    return out


def restore_phrase(store, change: Change, folder_id: int | None = None):
    """Put the backup's version of a removed or changed phrase back as a new phrase (the
    current one, if any, stays). It is quarantined like any phrase from a file."""
    from phraseforge.models import OutputMode, Phrase, Trigger
    rec = change.old
    if rec is None:
        raise ValueError("Only removed or changed phrases can be taken from the backup.")
    p = Phrase(description=rec["description"], content=rec["content"][0], content_format=rec["content"][1],
               folder_id=folder_id, output_mode=OutputMode(rec["output_mode"]), apps_include=rec["apps_include"],
               apps_exclude=rec["apps_exclude"], enabled=bool(rec["enabled"]), notes=rec["notes"],
               output_target=rec["output_target"], output_target_arg=rec["output_target_arg"],
               tags=list(rec["tags"]),
               triggers=[] if change.kind == "changed" else [Trigger.from_dict(t) for t in json.loads(rec["triggers"] or "[]")])
    with store.quarantine_writes("imported"):
        store.add_phrase(p)
        for lang, (c, cf) in json.loads(rec.get("versions") or "{}").items():
            store.set_phrase_version(p.id, lang, c, cf)
    return p


# ---------------------------------------------------------------- check and compact
def check(store) -> list[str]:
    """Problems SQLite finds in the phrase database ([] = all good)."""
    with store.lock:
        rows = [r[0] for r in store.conn.execute("PRAGMA integrity_check")]
        fk = list(store.conn.execute("PRAGMA foreign_key_check"))
    problems = [r for r in rows if r != "ok"]
    if fk:
        problems.append(f"{len(fk)} rows point to items that no longer exist")
    return problems


def size_of(store) -> int:
    with store.lock:
        return store.conn.execute("PRAGMA page_count").fetchone()[0] * store.conn.execute(
            "PRAGMA page_size").fetchone()[0]


def compact(store) -> tuple[int, int]:
    """VACUUM the database: (bytes before, bytes after)."""
    before = size_of(store)
    with store.lock:
        store.conn.commit()
        store.conn.execute("VACUUM")
        if store.path != ":memory:" and getattr(store, "vault_key", None) is None:
            store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    if getattr(store, "vault_key", None) is not None:
        store._saved_changes = -1                 # an encrypted file: save the compacted copy
        store.flush()
    return before, size_of(store)
