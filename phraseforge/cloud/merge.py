"""Change-set sync: merge two PCs' edits instead of asking "keep mine or theirs" (G-24, FR-SYN-01).

When the phrases changed on this PC *and* in the cloud since the last sync, sync.py used to
stop and ask which copy to keep. Now it compares three copies of the data:

    base     the copy both sides last agreed on (saved next to the database after every sync)
    local    this PC now
    remote   the cloud copy now

and merges them item by item and field by field. Folders, phrases and sticky notes are
matched by their uid (db.py), never by row id, because two PCs give out row ids
independently. For every field:

    changed on one side only      that side's value
    changed the same way on both  that value
    changed differently on both   the newer edit wins (the phrase's "modified" time; for
                                  folders and notes this PC wins). The losing text is kept in
                                  the phrase's history, so nothing is lost.

New items from both sides are kept. An item deleted on one side stays deleted, unless the
other side edited it: then the edit wins and the item comes back. A phrase kept in a folder
the other side deleted brings that folder back. Variables, shared settings, excluded
programs and the triggers of the special folders merge the same way, per key.

Folders and phrases that each PC fills by itself (the shared database mirror, dynamic
folders) are not merged: this PC keeps its own and ignores the other PC's.

Not merged: the usage log (statistics stay per PC). Phrase history is combined.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from phraseforge.db import Store, is_device_setting
from phraseforge.models import Folder, OutputMode, Phrase, Trigger

FOLDER_FIELDS = ("name", "parent", "sort", "enabled", "apps_include", "apps_exclude", "password_hash",
                 "show_in_popup", "notes", "output_target", "output_target_arg", "abbrev_prefix", "triggers")
PHRASE_FIELDS = ("description", "content", "folder", "output_mode", "apps_include", "apps_exclude",
                 "enabled", "sort", "notes", "output_target", "output_target_arg", "triggers", "tags",
                 "versions")
NOTE_FIELDS = ("text", "html", "color", "x", "y", "w", "h", "visible", "on_top")
TRIGGER_SKIP = ("id", "phrase_id", "folder_id", "special")
MISSING = object()


class CannotMerge(Exception):
    """The copies cannot be merged (a copy from an older PhraseForge without uids)."""


@dataclass
class State:
    folders: dict = field(default_factory=dict)      # uid -> record
    phrases: dict = field(default_factory=dict)
    notes: dict = field(default_factory=dict)
    ids: dict = field(default_factory=dict)          # ("folder"|"phrase"|"note", uid) -> row id
    managed: set = field(default_factory=set)        # ("folder"|"phrase", uid) filled by this PC itself
    vars: dict = field(default_factory=dict)         # (scope, name) -> value
    settings: dict = field(default_factory=dict)     # shared settings only
    excluded: set = field(default_factory=set)
    special: dict = field(default_factory=dict)      # special folder -> triggers (json)
    suggestions: dict = field(default_factory=dict)  # text -> count
    history: dict = field(default_factory=dict)      # phrase uid -> {(saved, description, content)}
    dynamic: dict = field(default_factory=dict)      # folder uid -> config (json text)



def _now() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")

def _tables(con) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _cols(con, table: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def _trigger_rows(con, where: str, arg) -> str:
    rows = con.execute(f"SELECT * FROM triggers WHERE {where}=? ORDER BY id", (arg,)).fetchall()
    return json.dumps([{k: r[k] for k in r.keys() if k not in TRIGGER_SKIP} for r in rows], sort_keys=True)


def read_state(path: str | Path, key=None) -> State:
    """Everything the merge compares, keyed by uid. Raises CannotMerge for copies without uids.
    key: the vault key, for a copy encrypted like the phrase file (the saved base)."""
    from phraseforge import vault
    con = vault.connect(path, key)
    con.row_factory = sqlite3.Row
    try:
        tables = _tables(con)
        if not {"folders", "phrases"} <= tables or "uid" not in _cols(con, "folders") \
                or "uid" not in _cols(con, "phrases"):
            raise CannotMerge("This copy was saved by an older PhraseForge.")
        st = State()
        fuid: dict[int, str] = {}
        for r in con.execute("SELECT * FROM folders ORDER BY id"):
            fuid[r["id"]] = r["uid"] or f"row:{r['id']}"
        for r in con.execute("SELECT * FROM folders ORDER BY id"):
            u = fuid[r["id"]]
            st.ids[("folder", u)] = r["id"]
            st.folders[u] = {
                "name": r["name"], "parent": fuid.get(r["parent_id"]) if r["parent_id"] is not None else None,
                "sort": r["sort"], "enabled": int(r["enabled"]), "apps_include": r["apps_include"] or "",
                "apps_exclude": r["apps_exclude"] or "", "password_hash": r["password_hash"] or "",
                "show_in_popup": int(r["show_in_popup"]), "notes": r["notes"] or "",
                "output_target": r["output_target"] or "current", "output_target_arg": r["output_target_arg"] or "",
                "abbrev_prefix": r["abbrev_prefix"] or "", "triggers": _trigger_rows(con, "folder_id", r["id"])}
        has_versions = "phrase_versions" in tables
        puid: dict[int, str] = {}
        for r in con.execute("SELECT * FROM phrases ORDER BY id"):
            u = r["uid"] or f"row:{r['id']}"
            puid[r["id"]] = u
            st.ids[("phrase", u)] = r["id"]
            tags = sorted(t[0] for t in con.execute(
                "SELECT tags.name FROM tags JOIN phrase_tags ON tags.id=phrase_tags.tag_id WHERE phrase_id=?",
                (r["id"],)))
            versions = {}
            if has_versions:
                versions = {v["lang"]: [v["content"] or "", v["content_format"] or "text"] for v in con.execute(
                    "SELECT lang, content, content_format FROM phrase_versions WHERE phrase_id=?", (r["id"],))}
            st.phrases[u] = {
                "description": r["description"], "content": [r["content"] or "", r["content_format"] or "text"],
                "folder": fuid.get(r["folder_id"]) if r["folder_id"] is not None else None,
                "output_mode": r["output_mode"], "apps_include": r["apps_include"] or "",
                "apps_exclude": r["apps_exclude"] or "", "enabled": int(r["enabled"]), "sort": r["sort"],
                "notes": r["notes"] or "", "output_target": r["output_target"] or "current",
                "output_target_arg": r["output_target_arg"] or "",
                "triggers": _trigger_rows(con, "phrase_id", r["id"]), "tags": tags,
                "versions": json.dumps(versions, sort_keys=True),
                "_use_count": r["use_count"] or 0, "_last_used": r["last_used"], "_created": r["created"],
                "_modified": r["modified"] or ""}
        if "sticky_notes" in tables and "uid" in _cols(con, "sticky_notes"):
            for r in con.execute("SELECT * FROM sticky_notes ORDER BY id"):
                u = r["uid"] or f"row:{r['id']}"
                st.ids[("note", u)] = r["id"]
                st.notes[u] = {**{k: r[k] for k in NOTE_FIELDS}, "_created": r["created"],
                               "_updated": r["updated"] or ""}
        # items each PC fills by itself
        if "shared_map" in tables:
            for kind, lid in con.execute("SELECT kind, local_id FROM shared_map"):
                u = (fuid if kind == "folder" else puid).get(lid)
                if u:
                    st.managed.add((kind, u))
        if "shared_state" in tables:
            r = con.execute("SELECT v FROM shared_state WHERE k='root'").fetchone()
            if r and str(r[0]).isdigit() and int(r[0]) in fuid:
                st.managed.add(("folder", fuid[int(r[0])]))
        if "dynamic_items" in tables:
            for (pid,) in con.execute("SELECT phrase_id FROM dynamic_items"):
                if pid in puid:
                    st.managed.add(("phrase", puid[pid]))
        if "dynamic_folders" in tables:
            for fid, cfg in con.execute("SELECT folder_id, config FROM dynamic_folders"):
                if fid in fuid:
                    st.dynamic[fuid[fid]] = cfg
        st.vars = {(r[0], r[1]): r[2] for r in con.execute("SELECT scope, name, value FROM vars")}
        st.settings = {k: v for k, v in con.execute("SELECT key, value FROM settings") if not is_device_setting(k)}
        if "excluded_apps" in tables:
            st.excluded = {r[0] for r in con.execute("SELECT exe FROM excluded_apps")}
        for s in ("last_used", "clipboard_cache"):
            st.special[s] = _trigger_rows(con, "special", s)
        if "suggestions" in tables:
            st.suggestions = {r[0]: r[1] for r in con.execute("SELECT text, count FROM suggestions")}
        if "phrase_history" in tables:
            for pid, saved, d, c in con.execute("SELECT phrase_id, saved, description, content FROM phrase_history"):
                if pid in puid:
                    st.history.setdefault(puid[pid], set()).add((saved, d, c))
        return st
    finally:
        con.close()


# ---------------------------------------------------------------- three-way merge
def _pick(b, l, r):
    """(value, conflict) for one field: conflict = both sides changed it differently."""
    if l == r:
        return l, False
    if l == b:
        return r, False
    if r == b:
        return l, False
    return MISSING, True


def merge_values(base: dict, local: dict, remote: dict) -> dict:
    """Key -> value merge (variables, settings, special triggers). Deleted = absent."""
    out = {}
    for k in set(base) | set(local) | set(remote):
        v, conflict = _pick(base.get(k, MISSING), local.get(k, MISSING), remote.get(k, MISSING))
        if conflict:
            v = local.get(k, MISSING)           # this PC wins a tie on plain values
            if v is MISSING:
                v = remote.get(k, MISSING)
        if v is not MISSING:
            out[k] = v
    return out


def merge_sets(base: set, local: set, remote: set) -> set:
    return (local & remote) | (local - base) | (remote - base)


def merge_items(base: dict, local: dict, remote: dict, fields: tuple, stamp: str | None,
                managed: set, kind: str, losers: list | None = None) -> dict:
    """uid -> merged record (records of `fields` plus the local/remote extras)."""
    out = {}
    for u in set(base) | set(local) | set(remote):
        b, l, r = base.get(u), local.get(u), remote.get(u)
        if (kind, u) in managed:
            if l is not None:
                out[u] = l                       # filled by this PC itself: keep this PC's
            continue
        same = lambda x, y: all(x.get(f) == y.get(f) for f in fields)  # noqa: E731
        if l is not None and r is not None:
            bb = b or {}
            rec = dict(l)
            # a stamp from the future (forged to win every conflict) counts as now (R54)
            r_stamp = min(r.get(stamp) or "", _now()) if stamp else ""
            remote_newer = bool(stamp) and r_stamp > (l.get(stamp) or "")
            lost = False
            for f in fields:
                v, conflict = _pick(bb.get(f, MISSING), l.get(f), r.get(f))
                if conflict:
                    v = r.get(f) if remote_newer else l.get(f)
                    lost = True
                rec[f] = v
            if lost and losers is not None:
                losers.append((u, l if remote_newer else r))
            if stamp:
                rec[stamp] = max(l.get(stamp) or "", r_stamp)
            if kind == "phrase":
                rec["_use_count"] = l["_use_count"] + max(0, r["_use_count"] - bb.get("_use_count", 0))
                rec["_last_used"] = max(l["_last_used"] or "", r["_last_used"] or "") or None
            out[u] = rec
        elif l is not None:
            if b is None or not same(l, b):
                out[u] = l                       # new here, or edited here while deleted there
        elif r is not None:
            if b is None or not same(r, b):
                out[u] = dict(r)                 # new there, or edited there while deleted here
    return out


@dataclass
class Merged:
    folders: dict
    phrases: dict
    notes: dict
    vars: dict
    settings: dict
    excluded: set
    special: dict
    losers: list
    summary: dict


def merge(base: State, local: State, remote: State) -> Merged:
    managed = base.managed | local.managed | remote.managed
    losers: list = []
    folders = merge_items(base.folders, local.folders, remote.folders, FOLDER_FIELDS, None, managed, "folder")
    phrases = merge_items(base.phrases, local.phrases, remote.phrases, PHRASE_FIELDS, "_modified", managed,
                          "phrase", losers)
    notes = merge_items(base.notes, local.notes, remote.notes, NOTE_FIELDS, "_updated", managed, "note")

    # a folder kept by the merge needs its parent; a phrase needs its folder
    def ensure(u):
        seen = set()
        while u is not None and u not in folders and u not in seen:
            seen.add(u)
            src = remote.folders.get(u) or base.folders.get(u) or local.folders.get(u)
            if src is None or ("folder", u) in managed:
                return False
            folders[u] = dict(src)
            u = src["parent"]
        return True
    for u, rec in list(folders.items()):
        if not ensure(rec["parent"]):
            rec["parent"] = None
    for rec in phrases.values():
        if rec["folder"] is not None and not ensure(rec["folder"]):
            rec["folder"] = None
    # moves on both sides can make a loop: cut it at the root. Each folder is walked once,
    # so a deep chain in a crafted copy costs linear time, not folders x depth (R53)
    done: set = set()
    for u in list(folders):
        path, on_path, cur = [], set(), u
        while cur is not None and cur in folders and cur not in done:
            if cur in on_path:
                folders[cur]["parent"] = None
                break
            on_path.add(cur)
            path.append(cur)
            cur = folders[cur]["parent"]
        done.update(path)
    for rec in folders.values():
        if rec["parent"] is not None and rec["parent"] not in folders:
            rec["parent"] = None

    settings = merge_values(base.settings, local.settings, remote.settings)
    summary = {
        "added": sum(1 for u in phrases if u not in local.phrases),
        "removed": sum(1 for u in local.phrases if u not in phrases and ("phrase", u) not in managed),
        "changed": sum(1 for u, rec in phrases.items() if u in local.phrases
                       and any(rec[f] != local.phrases[u][f] for f in PHRASE_FIELDS)),
        "conflicts": len(losers),
    }
    return Merged(folders, phrases, notes, merge_values(base.vars, local.vars, remote.vars), settings,
                  merge_sets(base.excluded, local.excluded, remote.excluded),
                  merge_values(base.special, local.special, remote.special), losers, summary)


# ---------------------------------------------------------------- writing the result
def _triggers(js: str) -> list[Trigger]:
    return [Trigger.from_dict(d) for d in json.loads(js or "[]")]


def _set_uid(store: Store, table: str, row_id: int, uid: str) -> None:
    if not uid.startswith("row:"):
        store.conn.execute(f"UPDATE {table} SET uid=? WHERE id=?", (uid, row_id))


def apply(store: Store, local: State, remote: State, m: Merged) -> None:
    """Turn `store` (a copy of this PC's data, so `local` describes it) into the merged data."""
    conn = store.conn
    fid: dict[str, int] = {u: local.ids[("folder", u)] for u in local.folders}

    depths: dict = {}

    def depth(u):
        chain, cur = [], u
        while cur is not None and cur in m.folders and cur not in depths and cur not in chain:
            chain.append(cur)
            cur = m.folders[cur]["parent"]
        d = depths.get(cur, -1) if cur in depths else -1
        for x in reversed(chain):
            d += 1
            depths[x] = d
        return depths.get(u, 0)

    with store.policy_bypass():
        for u in sorted(m.folders, key=depth):                       # parents first
            rec = m.folders[u]
            f = Folder(name=rec["name"], parent_id=fid.get(rec["parent"]) if rec["parent"] else None,
                       sort=rec["sort"], enabled=bool(rec["enabled"]), apps_include=rec["apps_include"],
                       apps_exclude=rec["apps_exclude"], password_hash=rec["password_hash"],
                       show_in_popup=bool(rec["show_in_popup"]), notes=rec["notes"],
                       output_target=rec["output_target"], output_target_arg=rec["output_target_arg"],
                       abbrev_prefix=rec["abbrev_prefix"])
            old = local.folders.get(u)
            if old is None:
                store.add_folder(f)
                fid[u] = f.id
                with store.lock, conn:
                    _set_uid(store, "folders", f.id, u)
                store.set_folder_triggers(f.id, _triggers(rec["triggers"]))
                if u in remote.dynamic:                              # its source; approved per PC
                    with store.lock, conn:
                        conn.execute("CREATE TABLE IF NOT EXISTS dynamic_folders (folder_id INTEGER PRIMARY KEY "
                                     "REFERENCES folders(id) ON DELETE CASCADE, config TEXT NOT NULL, "
                                     "last_refresh REAL DEFAULT 0, last_stamp TEXT DEFAULT '', "
                                     "last_error TEXT DEFAULT '')")
                        conn.execute("INSERT OR REPLACE INTO dynamic_folders (folder_id, config) VALUES (?,?)",
                                     (f.id, remote.dynamic[u]))
            elif any(rec[k] != old[k] for k in FOLDER_FIELDS):
                f.id = fid[u]
                store.update_folder(f)
                if rec["triggers"] != old["triggers"]:
                    store.set_folder_triggers(f.id, _triggers(rec["triggers"]))

        pid: dict[str, int] = {}
        for u, rec in m.phrases.items():
            old = local.phrases.get(u)
            if old is not None and not any(rec[k] != old[k] for k in PHRASE_FIELDS) \
                    and rec["_use_count"] == old["_use_count"]:
                pid[u] = local.ids[("phrase", u)]
                continue
            p = store.get_phrase(local.ids[("phrase", u)]) if old is not None else Phrase(description="")
            p.description = rec["description"]
            p.content, p.content_format = rec["content"]
            p.folder_id = fid.get(rec["folder"]) if rec["folder"] else None
            p.output_mode = OutputMode(rec["output_mode"])
            p.apps_include, p.apps_exclude = rec["apps_include"], rec["apps_exclude"]
            p.enabled, p.sort, p.notes = bool(rec["enabled"]), rec["sort"], rec["notes"]
            p.output_target, p.output_target_arg = rec["output_target"], rec["output_target_arg"]
            p.triggers = _triggers(rec["triggers"])
            p.tags = list(rec["tags"])
            if old is None:
                p.created = rec["_created"]
                store.add_phrase(p)
            else:
                store.update_phrase(p, record_history=False)
            pid[u] = p.id
            with store.lock, conn:
                if old is None:
                    _set_uid(store, "phrases", p.id, u)
                conn.execute("UPDATE phrases SET modified=?, use_count=?, last_used=? WHERE id=?",
                             (rec["_modified"] or None, rec["_use_count"], rec["_last_used"], p.id))
                if old is None or rec["versions"] != old["versions"]:
                    conn.execute("DELETE FROM phrase_versions WHERE phrase_id=?", (p.id,))
                    for lang, (c, cf) in json.loads(rec["versions"]).items():
                        conn.execute("INSERT INTO phrase_versions VALUES (?,?,?,?,?)",
                                     (p.id, lang, c, cf, rec["_modified"] or None))
        with store.lock, conn:
            for u, lost in m.losers:                                 # the edit that lost stays in history
                if u in pid:
                    conn.execute("INSERT INTO phrase_history (phrase_id,saved,description,content) VALUES (?,?,?,?)",
                                 (pid[u], lost.get("_modified") or None, lost["description"], lost["content"][0]))
            for u, rows in remote.history.items():
                if u in pid:
                    for row in rows - local.history.get(u, set()):
                        conn.execute("INSERT INTO phrase_history (phrase_id,saved,description,content) "
                                     "VALUES (?,?,?,?)", (pid[u], *row))
        for u in local.phrases:
            if u not in m.phrases:
                store.delete_phrase(local.ids[("phrase", u)])
        for u in local.folders:
            if u not in m.folders:
                store.delete_folder(local.ids[("folder", u)])

        with store.lock, conn:
            for u, rec in m.notes.items():
                vals = [rec[k] for k in NOTE_FIELDS]
                old = local.notes.get(u)
                if old is None:
                    conn.execute(f"INSERT INTO sticky_notes ({', '.join(NOTE_FIELDS)}, created, updated, uid) "
                                 f"VALUES ({', '.join('?' * len(NOTE_FIELDS))}, ?, ?, ?)",
                                 (*vals, rec["_created"], rec["_updated"], None if u.startswith("row:") else u))
                elif any(rec[k] != old[k] for k in NOTE_FIELDS):
                    conn.execute(f"UPDATE sticky_notes SET {', '.join(k + '=?' for k in NOTE_FIELDS)}, updated=? "
                                 "WHERE id=?", (*vals, rec["_updated"], local.ids[("note", u)]))
            for u in local.notes:
                if u not in m.notes:
                    conn.execute("DELETE FROM sticky_notes WHERE id=?", (local.ids[("note", u)],))
            conn.execute("DELETE FROM vars")
            conn.executemany("INSERT INTO vars VALUES (?,?,?)", [(s, n, v) for (s, n), v in m.vars.items()])
            for k in local.settings:
                if k not in m.settings:
                    conn.execute("DELETE FROM settings WHERE key=?", (k,))
            conn.executemany("INSERT OR REPLACE INTO settings VALUES (?,?)", list(m.settings.items()))
        store.set_excluded_apps(m.excluded)
        for s, js in m.special.items():
            if js != local.special.get(s):
                store.set_special_triggers(s, _triggers(js))
        store.merge_suggestions(remote.suggestions)
