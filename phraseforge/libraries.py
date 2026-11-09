"""Several phrase libraries at once (PRD G-19, FR-DAT-06).

Besides the personal phrase file, the user can mount other PhraseForge phrase files: a team
file on a shared folder, a colleague's export, a second set of their own. Each library shows
as its own top-level folder in the tree and works like any other folder: its abbreviations,
hotkeys and the phrase menu work everywhere.

How: the library's folders and phrases are mirrored into the personal phrase file under the
library's root folder and kept up to date (refresh() re-reads the file when it changed on
disk). The mirror is this PC's own:

  read-only    edits inside the library's folder are refused with a visible reason
  read-write   an edit is written back to the library file at once (last writer wins per
               phrase); other PCs see it at their next refresh

Precedence: the same abbreviation or hotkey in several places goes to the personal phrase
first, then to the library mounted first.

Safety: phrases a library adds or changes need approval on this PC before their privileged
macros run (security.py), like imported phrases. Library folders never go into the personal
cloud sync (each PC mounts its own libraries); a sync pull keeps them.

The list of libraries is a device setting (library.list); the mapping between library items
and their mirror is the table library_items.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

from phraseforge import policy
from phraseforge.models import Folder, OutputMode, Phrase, Trigger

log = logging.getLogger(__name__)

LIST_KEY = "library.list"
ROOT_KEY = "library.root."           # + library id -> folder id of its root on this PC
STAMP_KEY = "library.stamp."         # + library id -> "mtime:size" of the file at the last read
ERROR_KEY = "library.error."
# + library id -> uid of the root folder. Row ids are reused: a folder that came with a sync pull
# can get the root's old id, and was then taken for the library (stripped from pushes, deleted on
# unmount). The uid must match too (security R76).
ROOT_UID_KEY = "library.rootuid."


def _root_of(store, lib_id: str) -> int | None:
    v = store.setting(ROOT_KEY + lib_id, "")
    if not v.isdigit() or store.get_folder(int(v)) is None:
        return None
    want = store.setting(ROOT_UID_KEY + lib_id, "")
    if want:
        with store.lock:
            have = store._uid("folders", int(v))
        if have != want:
            return None
    return int(v)


def _set_root(store, lib_id: str, folder_id: int) -> None:
    store.set_setting(ROOT_KEY + lib_id, str(folder_id))
    with store.lock:
        uid = store._uid("folders", folder_id) or ""
    store.set_setting(ROOT_UID_KEY + lib_id, uid)
TABLES = """
CREATE TABLE IF NOT EXISTS library_items (
  lib TEXT NOT NULL, kind TEXT NOT NULL, uid TEXT NOT NULL, local_id INTEGER NOT NULL,
  PRIMARY KEY (lib, kind, uid));
CREATE UNIQUE INDEX IF NOT EXISTS library_items_local ON library_items (kind, local_id);
"""
PHRASE_FIELDS = ("description", "content", "content_format", "output_mode", "apps_include", "apps_exclude",
                 "enabled", "sort", "notes", "output_target", "output_target_arg")
FOLDER_FIELDS = ("name", "sort", "enabled", "apps_include", "apps_exclude", "show_in_popup", "notes",
                 "output_target", "output_target_arg", "abbrev_prefix", "is_template", "text_before", "text_after",
                 "password_hash")             # a locked folder stays locked in the mirror (R96)


class LibraryError(Exception):
    pass


class ReadOnlyLibrary(policy.PolicyError):
    """An edit inside a read-only library (shown like the administrator's refusals)."""


@dataclass
class Library:
    id: str
    name: str
    path: str
    mode: str = "ro"                  # ro | rw

    @property
    def writable(self) -> bool:
        return self.mode == "rw"


# ---------------------------------------------------------------- settings
def libraries(store) -> list[Library]:
    try:
        raw = json.loads(store.setting(LIST_KEY, "[]") or "[]")
    except ValueError:
        return []
    out = []
    for d in raw if isinstance(raw, list) else []:
        try:
            out.append(Library(str(d["id"]), str(d["name"]), str(d["path"]), "rw" if d.get("mode") == "rw" else "ro"))
        except (KeyError, TypeError):
            continue
    return out


def _save(store, libs: list[Library]) -> None:
    store.set_setting(LIST_KEY, json.dumps([asdict(x) for x in libs], ensure_ascii=False))


def root_ids(store) -> dict[str, int]:
    out = {}
    for lib in libraries(store):
        r = _root_of(store, lib.id)
        if r is not None:
            out[lib.id] = r
    return out


def _subtree(con, root_ids_: list[int]) -> set[int]:
    if not root_ids_:
        return set()
    marks = ",".join("?" * len(root_ids_))
    return {r[0] for r in con.execute(
        f"WITH RECURSIVE t(id) AS (SELECT id FROM folders WHERE id IN ({marks}) "
        f"UNION SELECT f.id FROM folders f JOIN t ON f.parent_id=t.id) SELECT id FROM t", root_ids_)}


def mirror_folder_ids(store) -> set[int]:
    """Folder ids of all library mirrors on this PC (they never go into the cloud sync)."""
    with store.lock:
        return _subtree(store.conn, list(root_ids(store).values()))


def strip_copy(con: sqlite3.Connection) -> None:
    """Remove the library mirrors from a copy of the phrase file (the sync snapshot)."""
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    roots = [int(v) for k, v in con.execute("SELECT key, value FROM settings WHERE key LIKE 'library.root.%'")
             if str(v).isdigit()]
    ids = _subtree(con, roots)
    if ids:
        # explicit deletes: a foreign-key pragma does nothing inside the caller's transaction
        marks = [(i,) for i in ids]
        con.executemany("DELETE FROM phrases WHERE folder_id=?", marks)
        con.executemany("DELETE FROM triggers WHERE folder_id=?", marks)
        con.executemany("DELETE FROM folders WHERE id=?", marks)
        for table in ("triggers", "phrase_tags", "phrase_versions", "phrase_quarantine", "phrase_comments",
                      "phrase_history"):
            if table in tables:
                con.execute(f"DELETE FROM {table} WHERE phrase_id IS NOT NULL AND phrase_id NOT IN "
                            "(SELECT id FROM phrases)")
    if "library_items" in tables:
        con.execute("DELETE FROM library_items")


# ---------------------------------------------------------------- the manager
class LibraryManager:
    def __init__(self, store):
        self.store = store
        self._local = threading.local()
        self._rank_cache: dict[int, int] | None = None
        with store.lock:
            store.conn.executescript(TABLES)
        store.write_guards.append(self._guard)
        store.trigger_rank = self._rank
        store.restore_hooks.append(self)
        store.on_change(self._on_change)

    # ------------------------------------------------ helpers
    @contextmanager
    def _mirroring(self):
        self._local.busy = getattr(self._local, "busy", 0) + 1
        try:
            with self.store.unguarded(), self.store.policy_bypass():
                yield
        finally:
            self._local.busy -= 1
            self._rank_cache = None

    def libraries(self) -> list[Library]:
        return libraries(self.store)

    def get(self, lib_id: str) -> Library | None:
        return next((x for x in self.libraries() if x.id == lib_id), None)

    def root(self, lib: Library) -> int | None:
        return _root_of(self.store, lib.id)

    def library_of_folder(self, folder_id: int | None) -> Library | None:
        if folder_id is None:
            return None
        roots = {v: k for k, v in root_ids(self.store).items()}
        for f in self.store.folder_chain(folder_id):
            if f.id in roots:
                return self.get(roots[f.id])
        return None

    def _phrase_folder(self, phrase_id) -> int | None:
        with self.store.lock:
            r = self.store.conn.execute("SELECT folder_id FROM phrases WHERE id=?", (phrase_id,)).fetchone()
        return r[0] if r else None

    def _items(self, lib_id: str, kind: str) -> dict[str, int]:
        with self.store.lock:
            return {u: i for u, i in self.store.conn.execute(
                "SELECT uid, local_id FROM library_items WHERE lib=? AND kind=?", (lib_id, kind))}

    def _uid_of_local(self, kind: str, local_id: int) -> tuple[str, str] | None:
        with self.store.lock:
            r = self.store.conn.execute("SELECT lib, uid FROM library_items WHERE kind=? AND local_id=?",
                                        (kind, local_id)).fetchone()
        return (r[0], r[1]) if r else None

    def _map(self, lib_id: str, kind: str, uid: str, local_id: int) -> None:
        with self.store.lock, self.store.conn:
            self.store.conn.execute("DELETE FROM library_items WHERE kind=? AND local_id=?", (kind, local_id))
            self.store.conn.execute("INSERT OR REPLACE INTO library_items VALUES (?,?,?,?)",
                                    (lib_id, kind, uid, local_id))

    @staticmethod
    def stamp(path: str) -> str:
        st = os.stat(path)
        return f"{int(st.st_mtime_ns)}:{st.st_size}"

    # ------------------------------------------------ mounting
    def _check_policy(self) -> None:
        """Mounting a phrase file of one's own would get round editing_disabled (security R77)."""
        from phraseforge import policy
        if policy.current().editing_disabled:
            raise policy.PolicyError(policy.current().notice("Mounting phrase libraries"))

    def add(self, name: str, path: str, mode: str = "ro", create: bool = False) -> Library:
        self._check_policy()
        path = str(Path(path))
        if any(Path(x.path) == Path(path) for x in self.libraries()):
            raise LibraryError("This phrase file is already mounted.")
        if Path(path).resolve() == Path(self.store.path).resolve():
            raise LibraryError("This is your own phrase file.")
        if create:
            if Path(path).exists():
                raise LibraryError("A file with this name already exists.")
            from phraseforge.db import Store
            Store(path).close()
        elif not Path(path).is_file():
            raise LibraryError("The phrase file was not found.")
        from phraseforge import vault
        if vault.is_encrypted(path) and not getattr(self.store, "encrypted", False):
            # its phrases would be kept decrypted in this PC's plain phrase file (R96)
            raise LibraryError("This phrase file is encrypted, but yours is not: encrypt your phrase file first "
                               "(Settings > Encryption), then mount it.")
        lib = Library(secrets.token_hex(6), name.strip() or Path(path).stem, path, "rw" if mode == "rw" else "ro")
        self._read(lib)                                  # a valid phrase file? (raises otherwise)
        _save(self.store, self.libraries() + [lib])
        self.pull(lib)
        return lib

    def remove(self, lib_id: str) -> None:
        """Unmount: the library's folder disappears from this PC; the file is not touched."""
        lib = self.get(lib_id)
        if lib is None:
            return
        root = self.root(lib)
        with self._mirroring():
            if root is not None:
                self.store.delete_folder(root)
            with self.store.lock, self.store.conn:
                self.store.conn.execute("DELETE FROM library_items WHERE lib=?", (lib_id,))
                for k in (ROOT_KEY, ROOT_UID_KEY, STAMP_KEY, ERROR_KEY):
                    self.store.conn.execute("DELETE FROM settings WHERE key=?", (k + lib_id,))
        _save(self.store, [x for x in self.libraries() if x.id != lib_id])

    def set_mode(self, lib_id: str, mode: str) -> None:
        if mode == "rw":
            self._check_policy()
        libs = self.libraries()
        for x in libs:
            if x.id == lib_id:
                x.mode = "rw" if mode == "rw" else "ro"
        _save(self.store, libs)

    def move(self, lib_id: str, step: int) -> None:
        """Change the order (and so the precedence) of the libraries."""
        libs = self.libraries()
        i = next((n for n, x in enumerate(libs) if x.id == lib_id), None)
        if i is None or not 0 <= i + step < len(libs):
            return
        libs[i], libs[i + step] = libs[i + step], libs[i]
        _save(self.store, libs)
        self._rank_cache = None

    def status(self, lib: Library) -> str:
        return self.store.setting(ERROR_KEY + lib.id, "")

    # ------------------------------------------------ reading the library file
    def _read(self, lib: Library):
        from phraseforge.cloud import merge
        try:
            return merge.read_state(lib.path, allow_rowids=True)
        except merge.CannotMerge as e:
            raise LibraryError(str(e)) from e
        except sqlite3.DatabaseError as e:
            raise LibraryError(f"Not a PhraseForge phrase file: {e}") from e

    def refresh(self, force: bool = False) -> list[tuple[Library, str]]:
        """Re-read every library whose file changed (or whose folder is missing here)."""
        errors = []
        for lib in self.libraries():
            try:
                st = self.stamp(lib.path)
                if force or self.root(lib) is None or st != self.store.setting(STAMP_KEY + lib.id, ""):
                    self.pull(lib)
            except (OSError, LibraryError, sqlite3.Error) as e:
                msg = str(e) or e.__class__.__name__
                if self.store.setting(ERROR_KEY + lib.id, "") != msg:
                    self.store.set_setting(ERROR_KEY + lib.id, msg)
                errors.append((lib, msg))
        return errors

    def _ensure_root(self, lib: Library) -> int:
        root = self.root(lib)
        if root is None:
            f = self.store.add_folder(Folder(name=lib.name))
            _set_root(self.store, lib.id, f.id)
            with self.store.lock, self.store.conn:
                self.store.conn.execute("DELETE FROM library_items WHERE lib=?", (lib.id,))
            root = f.id
        else:
            f = self.store.get_folder(root)
            if f.name != lib.name:
                f.name = lib.name
                self.store.update_folder(f)
        return root

    def pull(self, lib: Library) -> tuple[int, int, int]:
        """Mirror the library file under its root folder: (added, changed, removed) phrases."""
        state = self._read(lib)
        stamp = self.stamp(lib.path)
        added = changed = removed = 0
        store = self.store
        with self._mirroring(), store.quarantine_writes("library"):
            root = self._ensure_root(lib)
            fmap = self._items(lib.id, "folder")
            fmap = {u: i for u, i in fmap.items() if store.get_folder(i) is not None}

            def depth(u):
                d, cur, seen = 0, state.folders[u]["parent"], set()
                while cur is not None and cur in state.folders and cur not in seen:
                    seen.add(cur)
                    d, cur = d + 1, state.folders[cur]["parent"]
                return d
            for u in sorted(state.folders, key=depth):
                rec = state.folders[u]
                parent = fmap.get(rec["parent"], root) if rec["parent"] else root
                want = {k: rec[k] for k in FOLDER_FIELDS if k in rec}
                trig = [Trigger.from_dict(t) for t in json.loads(rec["triggers"] or "[]")]
                if u in fmap:
                    f = store.get_folder(fmap[u])
                    if f.parent_id != parent or any(getattr(f, k) != (bool(v) if isinstance(getattr(f, k), bool) else v)
                                                    for k, v in want.items()):
                        for k, v in want.items():
                            setattr(f, k, bool(v) if isinstance(getattr(f, k), bool) else v)
                        f.parent_id = parent
                        store.update_folder(f)
                else:
                    f = store.add_folder(Folder(parent_id=parent, **{k: (bool(v) if k in ("enabled", "show_in_popup", "is_template")
                                                                         else v) for k, v in want.items()}))
                    fmap[u] = f.id
                    self._map(lib.id, "folder", u, f.id)
                old = [(t.kind, t.value, t.enabled) for t in store.folder_triggers(f.id)]
                if old != [(t.kind, t.value, t.enabled) for t in trig]:
                    store.set_folder_triggers(f.id, trig)
            pmap = {u: i for u, i in self._items(lib.id, "phrase").items() if store.get_phrase(i) is not None}
            for u, rec in state.phrases.items():
                fid = fmap.get(rec["folder"], root) if rec["folder"] else root
                p = store.get_phrase(pmap[u]) if u in pmap else Phrase(description="")
                new = self._phrase_from(rec, p, fid)
                if u in pmap:
                    if self._differs(store.get_phrase(pmap[u]), new, store):
                        store.update_phrase(new, record_history=False)
                        changed += 1
                    self._set_versions(new.id, rec)      # a new language version alone counts too (R96)
                else:
                    store.add_phrase(new)
                    self._set_versions(new.id, rec)
                    self._map(lib.id, "phrase", u, new.id)
                    added += 1
            for u, local in pmap.items():
                if u not in state.phrases:
                    store.delete_phrase(local)
                    removed += 1
            for u, local in fmap.items():
                if u not in state.folders and store.get_folder(local) is not None:
                    store.delete_folder(local)
            with store.lock, store.conn:              # forget mappings of rows that are gone
                store.conn.execute("DELETE FROM library_items WHERE lib=? AND kind='phrase' AND local_id NOT IN "
                                   "(SELECT id FROM phrases)", (lib.id,))
                store.conn.execute("DELETE FROM library_items WHERE lib=? AND kind='folder' AND local_id NOT IN "
                                   "(SELECT id FROM folders)", (lib.id,))
        store.set_setting(STAMP_KEY + lib.id, stamp)
        if store.setting(ERROR_KEY + lib.id, ""):
            store.set_setting(ERROR_KEY + lib.id, "")
        return added, changed, removed

    @staticmethod
    def _phrase_from(rec: dict, p: Phrase, folder_id: int) -> Phrase:
        p.description = rec["description"]
        p.content, p.content_format = rec["content"]
        p.folder_id = folder_id
        p.output_mode = OutputMode(rec["output_mode"])
        p.apps_include, p.apps_exclude = rec["apps_include"], rec["apps_exclude"]
        p.enabled, p.sort, p.notes = bool(rec["enabled"]), rec["sort"], rec["notes"]
        p.output_target, p.output_target_arg = rec["output_target"], rec["output_target_arg"]
        p.triggers = [Trigger.from_dict(t) for t in json.loads(rec["triggers"] or "[]")]
        p.tags = list(rec["tags"])
        return p

    def _set_versions(self, pid: int, rec: dict) -> None:
        want = {k: tuple(v) for k, v in json.loads(rec.get("versions") or "{}").items()}
        have = self.store.phrase_versions(pid)
        if have == want:
            return
        for lang in have:
            if lang not in want:
                self.store.delete_phrase_version(pid, lang)
        for lang, (c, cf) in want.items():
            if have.get(lang) != (c, cf):
                self.store.set_phrase_version(pid, lang, c, cf)

    @staticmethod
    def _differs(old: Phrase, new: Phrase, store) -> bool:
        if old is None:
            return True
        a = [getattr(old, k) for k in PHRASE_FIELDS] + [old.folder_id, sorted(old.tags),
                                                         [(t.kind, t.value, t.enabled) for t in old.triggers]]
        b = [getattr(new, k) for k in PHRASE_FIELDS] + [new.folder_id, sorted(new.tags),
                                                         [(t.kind, t.value, t.enabled) for t in new.triggers]]
        return a != b

    # ------------------------------------------------ writing back (read-write libraries)
    def _on_change(self, kind: str, id_) -> None:
        if kind in ("phrase", "folder"):
            self._rank_cache = None
        if getattr(self._local, "busy", 0) or kind not in ("phrase", "folder") or id_ is None:
            return
        try:
            self.write_back(kind, id_)
        except Exception as e:                       # shown in the Libraries window
            log.warning("could not write to the phrase library: %s", e)
            known = self._uid_of_local(kind, id_)
            lib = self.get(known[0]) if known else None
            if lib is not None:
                self.store.set_setting(ERROR_KEY + lib.id, f"Could not save a change: {e}")

    def write_back(self, kind: str, local_id: int) -> None:
        store = self.store
        known = self._uid_of_local(kind, local_id)
        if kind == "phrase":
            row_exists = store.get_phrase(local_id) is not None
            lib = self.get(known[0]) if known else self.library_of_folder(self._phrase_folder(local_id))
        else:
            row_exists = store.get_folder(local_id) is not None
            lib = self.get(known[0]) if known else self.library_of_folder(local_id)
        if lib is None or not lib.writable:
            return
        root = self.root(lib)
        if kind == "folder" and local_id == root:
            return                                      # the root is this PC's, not part of the file
        from phraseforge.db import Store
        target = Store(lib.path)
        try:
            with target.policy_bypass():
                if not row_exists:
                    if known:
                        tid = self._target_id(target, kind, known[1])
                        if tid is not None:
                            (target.delete_phrase if kind == "phrase" else target.delete_folder)(tid)
                        with store.lock, store.conn:
                            store.conn.execute("DELETE FROM library_items WHERE kind=? AND local_id=?", (kind, local_id))
                elif kind == "phrase":
                    self._write_phrase(target, lib, local_id, known)
                else:
                    self._write_folder(target, lib, local_id, known)
        finally:
            target.close()
        store.set_setting(STAMP_KEY + lib.id, self.stamp(lib.path))

    @staticmethod
    def _target_id(target, kind: str, uid: str) -> int | None:
        table = "phrases" if kind == "phrase" else "folders"
        if uid.startswith("row:"):
            rid = int(uid[4:])
            r = target.conn.execute(f"SELECT id FROM {table} WHERE id=?", (rid,)).fetchone()
        else:
            r = target.conn.execute(f"SELECT id FROM {table} WHERE uid=?", (uid,)).fetchone()
        return r[0] if r else None

    def _target_folder(self, target, lib: Library, local_folder_id) -> int | None:
        """The library file's folder for a local folder inside the mirror (created if new)."""
        if local_folder_id is None or local_folder_id == self.root(lib):
            return None
        known = self._uid_of_local("folder", local_folder_id)
        if known:
            tid = self._target_id(target, "folder", known[1])
            if tid is not None:
                return tid
        return self._write_folder(target, lib, local_folder_id, None)

    def _write_folder(self, target, lib: Library, local_id: int, known) -> int:
        f = self.store.get_folder(local_id)
        parent = self._target_folder(target, lib, f.parent_id)
        tid = self._target_id(target, "folder", known[1]) if known else None
        data = {k: getattr(f, k) for k in FOLDER_FIELDS}
        if tid is None:
            nf = target.add_folder(Folder(parent_id=parent, **data))
            tid = nf.id
            uid = target.conn.execute("SELECT uid FROM folders WHERE id=?", (tid,)).fetchone()[0]
            self._map(lib.id, "folder", uid, local_id)
        else:
            tf = target.get_folder(tid)
            for k, v in data.items():
                setattr(tf, k, v)
            tf.parent_id = parent
            target.update_folder(tf)
        target.set_folder_triggers(tid, [Trigger.from_dict({k: v for k, v in t.to_dict().items()})
                                         for t in self.store.folder_triggers(local_id)])
        return tid

    def _write_phrase(self, target, lib: Library, local_id: int, known) -> None:
        p = self.store.get_phrase(local_id)
        folder = self._target_folder(target, lib, p.folder_id)
        tid = self._target_id(target, "phrase", known[1]) if known else None
        q = target.get_phrase(tid) if tid is not None else Phrase(description="")
        for k in PHRASE_FIELDS:
            setattr(q, k, getattr(p, k))
        q.folder_id = folder
        q.tags = list(p.tags)
        q.triggers = [Trigger.from_dict(t.to_dict()) for t in p.triggers]
        if tid is None:
            target.add_phrase(q)
            uid = target.conn.execute("SELECT uid FROM phrases WHERE id=?", (q.id,)).fetchone()[0]
            self._map(lib.id, "phrase", uid, local_id)
        else:
            target.update_phrase(q)
        want = self.store.phrase_versions(local_id)
        have = target.phrase_versions(q.id)
        for lang in have:
            if lang not in want:
                target.delete_phrase_version(q.id, lang)
        for lang, (c, cf) in want.items():
            if have.get(lang) != (c, cf):
                target.set_phrase_version(q.id, lang, c, cf)

    # ------------------------------------------------ read-only guard and precedence
    def _guard(self, method: str, args: tuple, kwargs: dict) -> None:
        if getattr(self._local, "busy", 0) or not root_ids(self.store):
            return
        folders: list = []
        a0 = args[0] if args else None
        if method in ("add_phrase",) and isinstance(a0, Phrase):
            folders = [a0.folder_id]
        elif method == "update_phrase" and isinstance(a0, Phrase):
            folders = [self._phrase_folder(a0.id), a0.folder_id]
        elif method in ("delete_phrase", "trash_phrase", "set_phrase_version", "delete_phrase_version",
                        "add_comment"):
            folders = [self._phrase_folder(a0)]
        elif method == "add_folder" and isinstance(a0, Folder):
            folders = [a0.parent_id]
        elif method == "update_folder" and isinstance(a0, Folder):
            folders = [a0.id, a0.parent_id]
        elif method in ("delete_folder", "trash_folder", "set_folder_triggers"):
            folders = [a0]
        elif method == "new_from_template":
            folders = [args[1] if len(args) > 1 else kwargs.get("folder_id")]
        for fid in folders:
            lib = self.library_of_folder(fid)
            if lib is not None and not lib.writable:
                raise ReadOnlyLibrary(f'"{lib.name}" is a read-only phrase library: its phrases can be used '
                                      "but not changed here. Copy a phrase into your own folders to change it.")

    def _rank(self, phrase_id: int) -> int:
        if self._rank_cache is None:
            cache: dict[int, int] = {}
            order = {lib.id: n + 1 for n, lib in enumerate(self.libraries())}
            with self.store.lock:
                for lib_id, root in root_ids(self.store).items():
                    for fid in _subtree(self.store.conn, [root]):
                        cache[fid] = order.get(lib_id, 99)
            self._rank_cache = cache
        return self._rank_cache.get(self._phrase_folder(phrase_id), 0)

    # ------------------------------------------------ a sync pull keeps the libraries
    def before_restore(self):
        kept = []
        for lib_id, root in root_ids(self.store).items():
            snap = self.store._folder_snapshot(root)
            with self.store.lock:
                rows = [(r[0], r[1], r[2], self.store._uid("phrases" if r[1] == "phrase" else "folders", r[3]))
                        for r in self.store.conn.execute(
                            "SELECT lib, kind, uid, local_id FROM library_items WHERE lib=?", (lib_id,))]
            kept.append((lib_id, snap, rows))
        return kept

    def after_restore(self, kept) -> None:
        store = self.store
        with store.lock:
            store.conn.executescript(TABLES)
        for lib_id, snap, rows in kept:
            if _root_of(store, lib_id) is not None:
                continue                                  # it came through (not a stripped copy)
            with self._mirroring():
                root = store._restore_folder(snap, None)
            _set_root(store, lib_id, root)
            with store.lock, store.conn:
                store.conn.execute("DELETE FROM library_items WHERE lib=?", (lib_id,))
                for lib, kind, uid, local_uid in rows:
                    table = "phrases" if kind == "phrase" else "folders"
                    r = store.conn.execute(f"SELECT id FROM {table} WHERE uid=?", (local_uid,)).fetchone()
                    if r:
                        store.conn.execute("INSERT OR REPLACE INTO library_items VALUES (?,?,?,?)",
                                           (lib, kind, uid, r[0]))
        self._rank_cache = None


def manager(store) -> LibraryManager:
    """The one LibraryManager of a store (created on first use)."""
    m = getattr(store, "_library_manager", None)
    if m is None:
        m = LibraryManager(store)
        store._library_manager = m
    return m
