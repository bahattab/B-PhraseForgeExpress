"""Keep a local folder in step with the shared database (shared/server.py).

The shared folders and phrases appear under one top-level local folder ("Shared"
by default), so everything PhraseForge does with phrases (autotext, hotkeys, the
phrase menu, the editor) works on them unchanged. sync() first pulls what others
changed since the last sync, then pushes what was changed here.

Local bookkeeping lives in two tables of the local database:
  shared_map    kind ('folder'/'phrase'), local_id, remote_id, rev (the server
                revision this copy matches), fp (fingerprint of the local copy
                at that time, to tell whether it was edited here since)
  shared_state  last_rev (the newest server revision seen), root (local folder id)

Conflicts never lose text: when a phrase was edited here and on the server, the
server's version wins and the local one is kept next to it as "(conflict copy)",
which the next push uploads as a new phrase. A phrase someone else deleted while
it was edited here is kept the same way.

Safety: if the local Shared folder is gone (deleted by the user, a restored
backup ...), nothing is deleted on the server: the mirror starts over and pulls
everything again. Phrases changed by another user are quarantined like a cloud
sync pull (security.py), so their {#run} and similar macros wait for approval.
Pulls go through Store.policy_bypass(): an administrator's "editing disabled"
policy still lets shared phrases arrive.

Permissions (stage 2): the server sends only what this login may read. When the
permissions change, the next sync reads everything again and removes copies that
may no longer be read. A change the permissions refuse is undone here (the
server's version comes back) and the local text is kept as a phrase in the local
folder "Not saved to the shared database", outside the Shared folder.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field

from phraseforge.models import Folder, Phrase, Trigger
from phraseforge.shared.server import Conflict, PermissionDenied, RemoteFolder, RemotePhrase, SharedServer

log = logging.getLogger(__name__)

TABLES = """
CREATE TABLE IF NOT EXISTS shared_map (
  kind TEXT NOT NULL, local_id INTEGER NOT NULL, remote_id INTEGER NOT NULL, rev INTEGER NOT NULL,
  fp TEXT NOT NULL, PRIMARY KEY (kind, remote_id));
CREATE UNIQUE INDEX IF NOT EXISTS shared_map_local ON shared_map (kind, local_id);
CREATE TABLE IF NOT EXISTS shared_state (k TEXT PRIMARY KEY, v TEXT);
"""
CONFLICT_SUFFIX = " (conflict copy)"
NOT_SAVED = "Not saved to the shared database"    # local folder for edits the permissions refused


@dataclass
class SyncResult:
    pulled: int = 0
    pushed: int = 0
    deleted: int = 0
    conflicts: list[str] = field(default_factory=list)
    denied: list[str] = field(default_factory=list)
    user: str = ""

    def summary(self) -> str:
        parts = [f"{self.pulled} received", f"{self.pushed} sent"]
        if self.deleted:
            parts.append(f"{self.deleted} deleted")
        if self.conflicts:
            parts.append(f"{len(self.conflicts)} conflicts kept as copies")
        if self.denied:
            parts.append(f"{len(self.denied)} changes not allowed (kept in \"{NOT_SAVED}\")")
        return ", ".join(parts)


def _triggers_out(p: Phrase) -> list[dict]:
    out = []
    for t in p.triggers:
        d = t.to_dict()
        for k in ("id", "phrase_id", "folder_id"):
            d.pop(k, None)
        out.append(d)
    return out


class Mirror:
    def __init__(self, store, server: SharedServer, root_name: str = "Shared"):
        self.store = store
        self.server = server
        self.root_name = root_name
        with store.lock:
            store.conn.executescript(TABLES)

    # ---------------------------------------------------------------- local bookkeeping
    def _state(self, k: str, default: str = "") -> str:
        with self.store.lock:
            r = self.store.conn.execute("SELECT v FROM shared_state WHERE k=?", (k,)).fetchone()
        return r[0] if r else default

    def _set_state(self, k: str, v) -> None:
        with self.store.lock, self.store.conn:
            self.store.conn.execute("INSERT OR REPLACE INTO shared_state VALUES (?,?)", (k, str(v)))

    def _map(self, kind: str, *, remote: int | None = None, local: int | None = None):
        col, val = ("remote_id", remote) if remote is not None else ("local_id", local)
        with self.store.lock:
            r = self.store.conn.execute(f"SELECT local_id, remote_id, rev, fp FROM shared_map WHERE kind=? AND {col}=?",
                                        (kind, val)).fetchone()
        return tuple(r) if r else None

    def _all_maps(self, kind: str) -> list[tuple[int, int, int, str]]:
        with self.store.lock:
            return [tuple(r) for r in self.store.conn.execute(
                "SELECT local_id, remote_id, rev, fp FROM shared_map WHERE kind=?", (kind,))]

    def _set_map(self, kind: str, local_id: int, remote_id: int, rev: int, fp: str) -> None:
        with self.store.lock, self.store.conn:
            self.store.conn.execute("DELETE FROM shared_map WHERE kind=? AND (local_id=? OR remote_id=?)",
                                    (kind, local_id, remote_id))
            self.store.conn.execute("INSERT INTO shared_map VALUES (?,?,?,?,?)", (kind, local_id, remote_id, rev, fp))

    def _drop_map(self, kind: str, remote_id: int) -> None:
        with self.store.lock, self.store.conn:
            self.store.conn.execute("DELETE FROM shared_map WHERE kind=? AND remote_id=?", (kind, remote_id))

    def _reset(self) -> None:
        with self.store.lock, self.store.conn:
            self.store.conn.execute("DELETE FROM shared_map")
            self.store.conn.execute("DELETE FROM shared_state WHERE k='last_rev'")

    # ---------------------------------------------------------------- the local tree
    def root_id(self) -> int:
        """Local folder that holds the shared tree; created (and the mirror reset) if missing."""
        rid = self._state("root")
        if rid and self.store.get_folder(int(rid)) is not None:
            return int(rid)
        if rid:
            log.warning("the local Shared folder is gone; pulling everything again, deleting nothing on the server")
        self._reset()
        with self.store.policy_bypass():
            f = self.store.add_folder(Folder(self.root_name))
        self._set_state("root", f.id)
        return f.id

    def _local_folders(self, root: int) -> list[Folder]:
        """Folders below root, parents before children."""
        out, todo = [], [root]
        while todo:
            fid = todo.pop(0)
            for f in self.store.folders(fid):
                out.append(f)
                todo.append(f.id)
        return out

    def _remote_of_folder(self, local_id: int | None, root: int) -> int | None:
        if local_id is None or local_id == root:
            return None
        m = self._map("folder", local=local_id)
        return m[1] if m else None

    def _local_of_folder(self, remote_id: int | None, root: int) -> int:
        if remote_id is None:
            return root
        m = self._map("folder", remote=remote_id)
        if m and self.store.get_folder(m[0]) is not None:
            return m[0]
        return root

    def _folder_fp(self, f: Folder, root: int) -> str:
        return hashlib.sha256(json.dumps([f.name, self._remote_of_folder(f.parent_id, root), f.sort],
                                         ensure_ascii=False).encode()).hexdigest()

    def _phrase_fp(self, p: Phrase, root: int) -> str:
        data = [p.description, p.content, p.content_format, _triggers_out(p),
                self._remote_of_folder(p.folder_id, root)]
        return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()

    def _to_remote(self, p: Phrase, root: int, remote_id: int = 0) -> RemotePhrase:
        return RemotePhrase(remote_id, self._remote_of_folder(p.folder_id, root), p.description, p.content,
                            p.content_format, _triggers_out(p))

    # ---------------------------------------------------------------- sync
    def sync(self) -> SyncResult:
        res = SyncResult(user=self.server.user())
        root = self.root_id()
        self.pull(root, res)
        self.push(root, res)
        return res

    def pull(self, root: int, res: SyncResult) -> None:
        last = int(self._state("last_rev", "0") or 0)
        acl_rev = str(self.server.acl_rev()) if hasattr(self.server, "acl_rev") else ""
        full = acl_rev != self._state("acl_rev", "")
        if full:
            last = 0                                   # permissions changed: read everything again
        folders, phrases, top = self.server.changes_since(last)
        me = (res.user or self.server.user()).casefold()
        with self.store.policy_bypass():
            self._pull_folders(folders, root, res)
            for rp in phrases:
                self._pull_phrase(rp, root, res, me)
            if full:
                self._drop_unreadable(root, {f.id for f in folders if not f.deleted},
                                      {p.id for p in phrases if not p.deleted}, res)
        self._set_state("last_rev", top)
        self._set_state("acl_rev", acl_rev)

    def _not_saved_folder(self) -> int:
        f = next((f for f in self.store.folders(None) if f.name == NOT_SAVED), None)
        return (f or self.store.add_folder(Folder(NOT_SAVED))).id

    def _keep_outside(self, p: Phrase) -> None:
        """Copy a phrase the server would not take into the local Not saved folder."""
        self.store.add_phrase(Phrase(p.description, p.content, folder_id=self._not_saved_folder(),
                                     content_format=p.content_format,
                                     triggers=[Trigger.from_dict(t) for t in _triggers_out(p)]))

    def _drop_unreadable(self, root: int, folder_ids: set[int], phrase_ids: set[int], res: SyncResult) -> None:
        """After a full read: remove local copies of what this login may no longer read."""
        for local_id, remote_id, _rev, fp in self._all_maps("phrase"):
            if remote_id not in phrase_ids:
                p = self.store.get_phrase(local_id)
                if p is not None:
                    if fp != self._phrase_fp(p, root):
                        self._keep_outside(p)           # edited here and not sent: keep the text
                    self.store.delete_phrase(local_id)
                    res.pulled += 1
                self._drop_map("phrase", remote_id)
        for local_id, remote_id, _rev, _fp in self._all_maps("folder"):
            if remote_id not in folder_ids:
                if self.store.get_folder(local_id) is not None:
                    for p in self.store.phrases(local_id):
                        if self._map("phrase", local=p.id) is None:
                            self._keep_outside(p)       # never sent: keep it
                    self.store.delete_folder(local_id)
                    res.pulled += 1
                self._drop_map("folder", remote_id)

    def _pull_folders(self, folders: list[RemoteFolder], root: int, res: SyncResult) -> None:
        live = []
        for rf in folders:
            m = self._map("folder", remote=rf.id)
            if rf.deleted:
                if m and self.store.get_folder(m[0]) is not None:
                    self._rescue_unshared(m[0], root)
                    self.store.delete_folder(m[0])
                    res.pulled += 1
                if m:
                    self._drop_map("folder", rf.id)
                continue
            if m and m[2] == rf.rev:
                continue                                # unchanged there (deleted here: push deletes it)
            local = self.store.get_folder(m[0]) if m else None
            if local is None:
                local = self.store.add_folder(Folder(rf.name, parent_id=root, sort=rf.sort_order))
            else:
                local.name, local.sort = rf.name, rf.sort_order
                self.store.update_folder(local)
            self._set_map("folder", local.id, rf.id, rf.rev, "")
            live.append(rf)
            res.pulled += 1
        for rf in live:                                 # parents may arrive after their children
            m = self._map("folder", remote=rf.id)
            local = self.store.get_folder(m[0])
            parent = self._local_of_folder(rf.parent_id, root)
            if parent != local.id and local.parent_id != parent:
                local.parent_id = parent
                self.store.update_folder(local)
        for rf in live:
            m = self._map("folder", remote=rf.id)
            self._set_map("folder", m[0], rf.id, rf.rev, self._folder_fp(self.store.get_folder(m[0]), root))

    def _rescue_unshared(self, folder_id: int, root: int) -> None:
        """Before a folder deleted on the server is deleted here: move phrases that were
        never uploaded (or edited here since) to the Shared folder, so they are not lost."""
        todo = [folder_id]
        while todo:
            fid = todo.pop()
            for p in self.store.phrases(fid):
                m = self._map("phrase", local=p.id)
                if m is None or m[3] != self._phrase_fp(p, root):
                    if m is not None:
                        self._drop_map("phrase", m[1])
                    p.folder_id = root
                    self.store.update_phrase(p, record_history=False)
            todo += [f.id for f in self.store.folders(fid)]

    def _pull_phrase(self, rp: RemotePhrase, root: int, res: SyncResult, me: str) -> None:
        m = self._map("phrase", remote=rp.id)
        local = self.store.get_phrase(m[0]) if m else None
        edited_here = local is not None and m is not None and m[3] != self._phrase_fp(local, root)
        if rp.deleted:
            if local is not None:
                if edited_here:                         # keep the local edit as a new phrase
                    res.conflicts.append(local.description)
                else:
                    self.store.delete_phrase(local.id)
                    res.pulled += 1
            if m:
                self._drop_map("phrase", rp.id)
            return
        if m and m[2] == rp.rev:
            return            # already have this revision (often our own push); deleted here: push deletes it
        if edited_here:
            copy = Phrase(local.description + CONFLICT_SUFFIX, local.content, folder_id=local.folder_id,
                          content_format=local.content_format,
                          triggers=[Trigger.from_dict(t) for t in _triggers_out(local)])
            self.store.add_phrase(copy)
            res.conflicts.append(local.description)
        folder = self._local_of_folder(rp.folder_id, root)
        triggers = []
        for d in rp.triggers:
            try:
                triggers.append(Trigger.from_dict(d))
            except Exception:
                log.warning("shared phrase %s: unreadable trigger %r skipped", rp.id, d)
        if local is None:
            local = self.store.add_phrase(Phrase(rp.description, rp.content, folder_id=folder,
                                                 content_format=rp.content_format, triggers=triggers))
        else:
            local.description, local.content, local.content_format = rp.description, rp.content, rp.content_format
            local.folder_id, local.triggers = folder, triggers
            self.store.update_phrase(local)
        if rp.modified_by.casefold() != me and hasattr(self.store, "quarantine"):
            self.store.quarantine(local.id, "synced")
        local = self.store.get_phrase(local.id)
        self._set_map("phrase", local.id, rp.id, rp.rev, self._phrase_fp(local, root))
        res.pulled += 1

    def push(self, root: int, res: SyncResult) -> None:
        folders = self._local_folders(root)
        folder_ids = {f.id for f in folders} | {root}
        for f in folders:                               # parents first, so children get a parent id
            m = self._map("folder", local=f.id)
            parent = self._remote_of_folder(f.parent_id, root)
            try:
                if m is None:
                    rid, rev = self.server.create_folder(f.name, parent, f.sort)
                    self._set_map("folder", f.id, rid, rev, self._folder_fp(f, root))
                    res.pushed += 1
                elif m[3] != self._folder_fp(f, root):
                    rev = self.server.update_folder(m[1], m[2], f.name, parent, f.sort)
                    self._set_map("folder", f.id, m[1], rev, self._folder_fp(f, root))
                    res.pushed += 1
            except Conflict:
                res.conflicts.append(f.name)            # the next pull brings the server's version
            except PermissionDenied:
                res.denied.append(f.name)
                self._set_state("acl_rev", "")          # read everything again: the server's tree comes back
                if m is None:
                    with self.store.policy_bypass():
                        for p in self.store.phrases(f.id):
                            if self._map("phrase", local=p.id) is None:
                                self._keep_outside(p)
                        self.store.delete_folder(f.id)
                else:
                    self._set_map("folder", f.id, m[1], -1, self._folder_fp(f, root))
        phrases = [p for p in self.store.phrases() if p.folder_id in folder_ids]
        for p in phrases:
            m = self._map("phrase", local=p.id)
            fp = self._phrase_fp(p, root)
            try:
                if m is None:
                    rid, rev = self.server.create_phrase(self._to_remote(p, root))
                    self._set_map("phrase", p.id, rid, rev, fp)
                    res.pushed += 1
                elif m[3] != fp:
                    rev = self.server.update_phrase(self._to_remote(p, root, m[1]), m[2])
                    self._set_map("phrase", p.id, m[1], rev, fp)
                    res.pushed += 1
            except Conflict:
                res.conflicts.append(p.description)
            except PermissionDenied:
                res.denied.append(p.description)
                with self.store.policy_bypass():
                    self._keep_outside(p)
                    if m is None:
                        self.store.delete_phrase(p.id)
                    else:
                        self._restore_from_server(m[1], p, root)
        # deleted (or moved out of the Shared folder) here: delete on the server
        live_phrases = {p.id for p in phrases}
        for local_id, remote_id, rev, _fp in self._all_maps("phrase"):
            if local_id not in live_phrases:
                try:
                    self.server.delete_phrase(remote_id, rev)
                    res.deleted += 1
                except Conflict:
                    pass                                # changed or deleted there: the next pull decides
                except PermissionDenied:
                    res.denied.append(str(remote_id))
                    self._set_state("acl_rev", "")      # the next sync brings it back
                self._drop_map("phrase", remote_id)
        for local_id, remote_id, rev, _fp in self._all_maps("folder"):
            if local_id not in folder_ids:
                try:
                    self.server.delete_folder(remote_id, rev)
                    res.deleted += 1
                except Conflict:
                    pass
                except PermissionDenied:
                    res.denied.append(str(remote_id))
                    self._set_state("acl_rev", "")
                self._drop_map("folder", remote_id)

    def _restore_from_server(self, remote_id: int, local: Phrase, root: int) -> None:
        """Put the server's current version back into the local copy."""
        rp = self.server.get_phrase(remote_id)
        if rp is None or rp.deleted:
            self.store.delete_phrase(local.id)
            self._drop_map("phrase", remote_id)
            return
        local.description, local.content, local.content_format = rp.description, rp.content, rp.content_format
        local.folder_id = self._local_of_folder(rp.folder_id, root)
        local.triggers = [Trigger.from_dict(d) for d in rp.triggers]
        self.store.update_phrase(local, record_history=False)
        local = self.store.get_phrase(local.id)
        self._set_map("phrase", local.id, remote_id, rp.rev, self._phrase_fp(local, root))

    def remote_id(self, local_phrase_id: int) -> int | None:
        """The server id of a local shared phrase (for its history)."""
        m = self._map("phrase", local=local_phrase_id)
        return m[1] if m else None
