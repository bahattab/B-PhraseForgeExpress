"""Backup and two-way sync of the phrase database to a cloud location.

Remote layout (a Google Drive folder, or any local/synced folder):
    phraseforge-sync.db            the shared copy; its properties hold rev/hash/device
    backups/ (folder) or backup-*  dated backups, newest N kept

Sync rule per run, with `last_rev`/`last_hash` remembered from the previous sync:
    no remote copy                      -> push
    remote unchanged, local changed     -> push (rev + 1)
    remote changed, local unchanged     -> pull (replace local data)
    both changed                        -> MERGE (cloud/merge.py): a backup of this PC's copy is
                                           uploaded, the two sets of edits are merged against the
                                           copy both last agreed on ("base", kept next to the
                                           database), the result is uploaded and then applied here
                                           like a pull. Only when that is impossible (no base yet,
                                           a cloud copy from an older version, sync.merge = 0):
                                           CONFLICT, nothing is overwritten and the caller asks
                                           the user to keep "this PC" or "cloud" (resolve()).

End-to-end encryption (FR-SYN-03): with sync.encrypt = 1 every file uploaded (the sync copy
and the backups) is encrypted with the sync passphrase (vault.py: AES-256-GCM, key from
scrypt), which the user enters on each PC; Google Drive or the sync folder only ever holds
ciphertext. The passphrase is kept on each PC sealed by Windows (sync.passphrase). While
encryption is on, a cloud copy that is not encrypted is never taken (anyone with access to the
folder could have written it): an unchanged one is replaced by an encrypted upload, a changed
one stops the sync with a message. A PC without the passphrase never overwrites an encrypted
copy.

What syncs: folders, phrases, triggers, tags, variables, history, statistics and
shared settings. What never leaves this PC: clipboard history and device-only
settings (sign-in, sync state, paths, start-with-Windows).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import socket
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from phraseforge.db import DEVICE_SETTING_PREFIXES, SECRET_SETTINGS, Store, is_device_setting  # noqa: F401

log = logging.getLogger(__name__)

SYNC_NAME = "phraseforge-sync.db"
BACKUP_PREFIX = "backup-"

# settings that belong to this PC only; kept when pulling, removed when pushing (db.py)
LOCAL_SETTING_PREFIXES = DEVICE_SETTING_PREFIXES


@dataclass
class RemoteFile:
    name: str
    modified: str = ""
    size: int = 0
    props: dict = field(default_factory=dict)
    ref: str = ""            # provider id (Drive file id) or path


class Remote(Protocol):
    label: str
    def list(self) -> list[RemoteFile]: ...
    def put(self, local: Path, name: str, props: dict) -> None: ...
    def get(self, name: str, dest: Path) -> None: ...
    def delete(self, name: str) -> None: ...


# ---------------------------------------------------------------- remotes
class FolderRemote:
    """Any folder, e.g. one inside Google Drive for Desktop (G:\\My Drive\\PhraseForge)."""

    def __init__(self, folder: str | Path):
        self.root = Path(folder)
        self.label = str(self.root)

    def _ok(self) -> None:
        if not str(self.root).strip():
            raise RuntimeError("No sync folder chosen.")
        self.root.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[RemoteFile]:
        self._ok()
        out = []
        for p in self.root.iterdir():
            if p.suffix == ".db" and p.is_file():
                meta = p.with_suffix(".json")
                props = json.loads(meta.read_text(encoding="utf-8")) if meta.is_file() else {}
                st = p.stat()
                out.append(RemoteFile(p.name, datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                                      st.st_size, props, str(p)))
        return out

    def put(self, local: Path, name: str, props: dict) -> None:
        self._ok()
        dst = self.root / name
        tmp = dst.with_suffix(".db.part")
        shutil.copyfile(local, tmp)
        os.replace(tmp, dst)
        dst.with_suffix(".json").write_text(json.dumps(props, indent=1), encoding="utf-8")

    def get(self, name: str, dest: Path) -> None:
        shutil.copyfile(self.root / name, dest)

    def delete(self, name: str) -> None:
        (self.root / name).unlink(missing_ok=True)
        (self.root / name).with_suffix(".json").unlink(missing_ok=True)


class GDriveRemote:
    """A folder in the user's Google Drive, reached through the Drive API."""

    def __init__(self, drive, folder_name: str = "PhraseForge"):
        self.drive = drive
        self.folder_name = folder_name or "PhraseForge"
        self.label = f"Google Drive / {self.folder_name}"
        self._folder_id = None

    def _fid(self) -> str:
        if not self._folder_id:
            self._folder_id = self.drive.ensure_folder(self.folder_name)
        return self._folder_id

    def list(self) -> list[RemoteFile]:
        return [RemoteFile(f["name"], f.get("modifiedTime", ""), int(f.get("size", 0) or 0),
                           dict(f.get("appProperties") or {}), f["id"]) for f in self.drive.list(self._fid())]

    def _find(self, name: str) -> RemoteFile | None:
        return next((f for f in self.list() if f.name == name), None)

    def put(self, local: Path, name: str, props: dict) -> None:
        existing = self._find(name)
        self.drive.upload(local, name, self._fid(), props, existing.ref if existing else None)

    def get(self, name: str, dest: Path) -> None:
        f = self._find(name)
        if not f:
            raise FileNotFoundError(name)
        self.drive.download(f.ref, dest)

    def delete(self, name: str) -> None:
        f = self._find(name)
        if f:
            self.drive.delete(f.ref)


# ---------------------------------------------------------------- engine
class SyncError(RuntimeError):
    """Sync cannot go on until the user acts (passphrase missing or wrong, unencrypted copy)."""


@dataclass
class SyncResult:
    action: str                 # pushed | pulled | merged | unchanged | conflict
    message: str
    pulled_file: Path | None = None   # for "pulled"/"merged": apply with apply_pull() on the UI thread
    remote_rev: int = 0
    summary: dict = field(default_factory=dict)   # for "merged": added/removed/changed/conflicts


def content_hash(store: Store) -> str:
    """Hash of the user's data (not timestamps of the export itself)."""
    d = store.export_dict()
    d.pop("exported", None)
    from phraseforge.libraries import mirror_folder_ids
    lib_folders = mirror_folder_ids(store)                # mounted libraries are not synced
    if lib_folders:
        d["folders"] = [f for f in d.get("folders", []) if f.get("id") not in lib_folders]
        d["phrases"] = [p for p in d.get("phrases", []) if p.get("folder_id") not in lib_folders]
    for p in d.get("phrases", []):           # usage counters change on every expansion
        for k in ("use_count", "last_used"):
            p.pop(k, None)
    with store.lock:                         # comments are synced too, so a new one counts as a change
        d["comments"] = [list(r) for r in store.conn.execute(
            "SELECT phrase_id, author, created, text, resolved FROM phrase_comments ORDER BY id")]
    blob = json.dumps(d, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _is_local_key(key: str) -> bool:
    return is_device_setting(key)


class CloudSync:
    def __init__(self, store: Store, remote: Remote, device: str | None = None):
        self.store = store
        self.remote = remote
        self.device = device or store.setting("sync.device", "") or socket.gethostname()

    # ---------------------------------------------------- snapshots
    def _discard(self, path: Path | None) -> None:
        """Remove a plain temp copy and its -wal/-shm files. While the phrase file is encrypted,
        the copy is overwritten first, so the phrases are not left in %TEMP% (R66, R75)."""
        if path is None:
            return
        from phraseforge import vault
        for f in (Path(path), Path(str(path) + "-wal"), Path(str(path) + "-shm"), Path(str(path) + "-journal")):
            try:
                if self.store.vault_key is not None and not vault.is_encrypted(f):
                    vault.wipe(f)
                else:
                    f.unlink(missing_ok=True)
            except OSError as e:
                log.warning("could not remove %s: %s", f, e)

    def _snapshot(self) -> Path:
        """Copy of the database without clipboard history and device-only settings."""
        fd, name = tempfile.mkstemp(prefix="pf-snap-", suffix=".db")
        os.close(fd)
        self.store.backup_to(name)
        _strip(Path(name))
        return Path(name)

    # ---------------------------------------------------- base (the copy both sides agreed on)
    @property
    def base_path(self) -> Path | None:
        if self.store.path == ":memory:":
            return None
        p = Path(self.store.path)
        return p.with_name(p.stem + ".sync-base.db")

    def _save_base(self, path: Path, rev: int) -> None:
        bp = self.base_path
        if bp is None:
            return
        if self.store.vault_key is not None:      # the phrase file is encrypted: so is its base
            from phraseforge import vault
            vault.write(bp, Path(path).read_bytes(), self.store.vault_key)
        else:
            tmp = bp.with_suffix(".part")
            shutil.copyfile(path, tmp)
            os.replace(tmp, bp)
        self.store.set_setting("sync.base_rev", str(rev))

    def _base(self) -> Path | None:
        bp = self.base_path
        if bp is None or not bp.is_file():
            return None
        if self.store.setting("sync.base_rev", "") != self.store.setting("sync.last_rev", "0"):
            return None                       # saved for another revision: unsafe to merge against
        return bp

    def _remember(self, rev: int, h: str) -> None:
        self.store.set_setting("sync.last_rev", str(rev))
        self.store.set_setting("sync.last_hash", h)
        self.store.set_setting("sync.last_time", datetime.now().isoformat(timespec="seconds"))

    # ---------------------------------------------------- end-to-end encryption
    @property
    def passphrase(self) -> str | None:
        if self.store.setting("sync.encrypt", "0") != "1":
            return None
        pw = self.store.setting("sync.passphrase", "")
        if not pw:
            raise SyncError("Encryption is on but no sync passphrase is set on this PC "
                            "(Settings > Backup & Sync).")
        return pw

    HASH_KEY_SALT = b"PhraseForge.sync.prophash.v1"   # fixed: every PC must get the same key

    def _prop_hash(self, h: str) -> str:
        """The content hash shown in the cloud's file properties; keyed when encrypted, so the
        hash of a guessed phrase list cannot be checked against it. The key comes from the
        passphrase through scrypt (slow on purpose), never from a fast hash of it."""
        pw = self.passphrase
        if not pw:
            return h
        import hmac
        if getattr(self, "_hash_key_for", None) != pw:
            from phraseforge import vault
            # NFC like the vault, so PCs that typed the passphrase differently still agree (R90)
            self._hash_key = hashlib.scrypt(vault._nfc(pw).encode("utf-8"), salt=self.HASH_KEY_SALT, n=vault.SCRYPT_N,
                                            r=vault.SCRYPT_R, p=vault.SCRYPT_P, maxmem=256 * 1024 * 1024, dklen=32)
            self._hash_key_for = pw
        return hmac.new(self._hash_key, h.encode("utf-8"), hashlib.sha256).hexdigest()

    def _upload(self, local: Path, name: str, props: dict) -> None:
        pw = self.passphrase
        if not pw:
            self.remote.put(local, name, props)
            return
        from phraseforge import vault
        fd, enc = tempfile.mkstemp(prefix="pf-enc-", suffix=".db")
        os.close(fd)
        try:
            meta = {"name": name, "kind": props.get("kind", "sync"), "rev": int(props.get("rev", 0) or 0)}
            vault.write(enc, Path(local).read_bytes(), vault.Key.new(pw, use_dpapi=False), meta=meta)
            self.remote.put(Path(enc), name, {**props, "enc": "1"})
        finally:
            Path(enc).unlink(missing_ok=True)

    # ---------------------------------------------------- backup
    def backup_now(self, keep: int = 10) -> str:
        self._refuse_plain_over_encrypted()
        snap = self._snapshot()
        try:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            safe_dev = "".join(c for c in self.device if c.isalnum() or c in "-_") or "pc"
            name = f"{BACKUP_PREFIX}{stamp}-{safe_dev}.db"
            self._upload(snap, name, {"kind": "backup", "device": self.device, "created": stamp})
        finally:
            self._discard(snap)
        backups = sorted((f for f in self.remote.list() if f.name.startswith(BACKUP_PREFIX)),
                         key=lambda f: f.name, reverse=True)
        for old in backups[max(1, keep):]:
            self.remote.delete(old.name)
        try:
            self.prune_attachments()
        except Exception as e:                     # the backup is made; cleaning up can wait
            log.warning("unused attached files were not removed: %s", e)
        return name

    def restore_backup(self, name: str) -> Path:
        """Download a cloud backup (apply it with apply_pull) and fetch the attached files its
        phrases use, while they are still in the cloud folder."""
        path = self.download(name, allow_older=True)
        try:
            self.sync_attachments(path)
        except SyncError:
            raise
        except Exception as e:
            log.warning("attached files of %s were not fetched: %s", name, e)
        return path

    PRUNE_EVERY_DAYS = 7

    def prune_attachments(self, force: bool = False) -> int:
        """Remove attached files from the cloud that no phrase uses any more: not on this PC,
        not in the sync copy, not in any kept backup. At most once a week; when one of those
        copies cannot be read, nothing is removed. Returns the number removed."""
        last = self.store.setting("sync.att_pruned", "")
        if not force and last:
            try:
                if (datetime.now() - datetime.fromisoformat(last)).days < self.PRUNE_EVERY_DAYS:
                    return 0
            except ValueError:
                pass
        files = self.remote.list()
        there = [f.name for f in files if f.name.startswith(self.ATT_PREFIX) and f.name.endswith(".db")]
        if not there:
            self.store.set_setting("sync.att_pruned", datetime.now().isoformat(timespec="seconds"))
            return 0
        refs: dict[str, str] = {}
        self._attachment_refs(self.store.conn, refs)
        for f in files:
            if f.name != SYNC_NAME and not f.name.startswith(BACKUP_PREFIX):
                continue
            path = self.download(f.name, allow_older=True)     # any failure: remove nothing
            try:
                con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
                try:
                    self._attachment_refs(con, refs)
                finally:
                    con.close()
            finally:
                self._discard(path)
        removed = 0
        for name in there:
            h = name[len(self.ATT_PREFIX):-len(".db")]
            if h not in refs:
                self.remote.delete(name)
                removed += 1
        self.store.set_setting("sync.att_pruned", datetime.now().isoformat(timespec="seconds"))
        return removed

    def list_backups(self) -> list[RemoteFile]:
        return sorted((f for f in self.remote.list() if f.name.startswith(BACKUP_PREFIX)),
                      key=lambda f: f.name, reverse=True)

    def download(self, name: str, allow_older: bool = False) -> Path:
        """allow_older: the user asked for this copy (a cloud backup, "take the cloud copy"); a
        sync copy older than the one this PC synced last is refused otherwise (a replay, R84)."""
        fd, tmp = tempfile.mkstemp(prefix="pf-pull-", suffix=".db")
        os.close(fd)
        path = Path(tmp)
        try:
            self.remote.get(name, path)
            from phraseforge import vault
            pw = self.passphrase
            if vault.is_encrypted(path):
                if not pw:
                    raise SyncError("The cloud copy is encrypted. Turn on encryption and enter the sync "
                                    "passphrase in Settings > Backup & Sync.")
                try:
                    data, _key = vault.read(path, passphrase=pw)
                except vault.WrongPassphrase:
                    raise SyncError("The sync passphrase on this PC does not open the cloud copy.") from None
                meta = vault.header_of(path).get("meta") or {}     # authenticated: read() checked it
                if meta:
                    if meta.get("name") != name:
                        raise SyncError(f"{name} in the cloud holds another file ({meta.get('name')}): it was "
                                        "not used.")
                    last = int(self.store.setting("sync.last_rev", "0") or 0)
                    if name == SYNC_NAME and not allow_older and int(meta.get("rev", 0) or 0) < last:
                        raise SyncError("The cloud copy is older than the one this PC synced last (it may have "
                                        "been put back by someone with access to the sync folder): it was not "
                                        "used. To use it anyway, take the cloud copy in Settings > Backup & Sync.")
                path.write_bytes(vault.no_wal(data))
            elif pw:
                raise SyncError(f"{name} in the cloud is not encrypted, but encryption is on here: it was "
                                "not used. Upload this PC's phrases to replace it, or turn encryption off.")
            _check_db(path)
        except BaseException:
            self._discard(path)
            raise
        return path

    # ---------------------------------------------------- attached files (G-21)
    ATT_PREFIX = "pf-att-"          # pf-att-<hash16>.db in the cloud folder (".db": every remote lists those)

    @staticmethod
    def _attachment_refs(con, refs: dict[str, str]) -> None:
        """Add the attached files used by the phrases (and language versions) read through `con`."""
        from phraseforge.importers.files import attachment_refs
        for table in ("phrases", "phrase_versions"):
            try:
                rows = con.execute(f"SELECT content FROM {table} WHERE content LIKE '%attached/%'").fetchall()
            except sqlite3.Error:
                continue
            attachment_refs((c for (c,) in rows), refs)
        try:                                        # text a folder adds around its phrases (R168)
            rows = con.execute("SELECT text_before, text_after FROM folders "
                               "WHERE text_before LIKE '%attached/%' OR text_after LIKE '%attached/%'").fetchall()
        except sqlite3.Error:
            rows = []
        attachment_refs((t for pair in rows for t in pair), refs)
        try:                                        # phrases in the Trash keep their files too
            rows = con.execute("SELECT data FROM trash WHERE data LIKE '%attached/%'").fetchall()
        except sqlite3.Error:
            rows = []
        for (data,) in rows:
            try:
                snap = json.loads(data or "null")
            except ValueError:
                continue
            texts, todo = [], [snap]
            while todo:                             # every string anywhere in the snapshot
                v = todo.pop()
                if isinstance(v, str):
                    texts.append(v)
                elif isinstance(v, dict):
                    todo.extend(v.values())
                elif isinstance(v, list):
                    todo.extend(v)
            attachment_refs(texts, refs)

    def sync_attachments(self, pulled: Path | None = None) -> tuple[int, int]:
        """Carry the files attached to phrases: upload those the cloud lacks, download those
        this PC lacks (also for the phrases in `pulled`, a copy not applied yet). A download is
        kept only when its SHA-256 matches the hash in the phrase. Returns (uploaded, downloaded)."""
        from phraseforge.importers import files as fl
        refs: dict[str, str] = {}
        self._attachment_refs(self.store.conn, refs)
        if pulled:
            con = sqlite3.connect(f"file:{Path(pulled).as_posix()}?mode=ro", uri=True)
            try:
                self._attachment_refs(con, refs)
            finally:
                con.close()
        if not refs:
            return 0, 0
        there = {f.name for f in self.remote.list() if f.name.startswith(self.ATT_PREFIX)}
        up = down = 0
        for h, name in refs.items():
            local, remote_name = fl.attachment_path(h, name), f"{self.ATT_PREFIX}{h}.db"
            if local is None:
                continue
            try:
                if local.is_file() and remote_name not in there:
                    if local.stat().st_size <= fl.MAX_ATTACHMENT:
                        self._upload(local, remote_name, {"kind": "attachment", "rev": 0})
                        up += 1
                elif not local.is_file() and remote_name in there:
                    down += self._download_attachment(remote_name, h, local)
            except SyncError:
                raise
            except Exception as e:                 # one file must not stop the others
                log.warning("attached file %s was not synced: %s", name, e)
        return up, down

    def _download_attachment(self, remote_name: str, h: str, dest: Path) -> int:
        from phraseforge import vault
        from phraseforge.importers import files as fl
        fd, tmp = tempfile.mkstemp(prefix="pf-att-")
        os.close(fd)
        path = Path(tmp)
        try:
            self.remote.get(remote_name, path)
            if path.stat().st_size > fl.MAX_ATTACHMENT + 4096:
                return 0
            data = path.read_bytes()
            if vault.is_encrypted(path):
                pw = self.passphrase
                if not pw:
                    return 0
                try:
                    data, _key = vault.read(path, passphrase=pw)
                except vault.WrongPassphrase:
                    return 0
                if (vault.header_of(path).get("meta") or {}).get("name") != remote_name:
                    return 0
            elif self.passphrase:
                return 0                           # plain file in an encrypted sync: not ours
            if not fl.store_attachment(h, dest.name, data):
                log.warning("attached file %s in the cloud does not match its hash: not used", remote_name)
                return 0
            return 1
        finally:
            path.unlink(missing_ok=True)

    # ---------------------------------------------------- sync
    def sync(self) -> SyncResult:
        res = self._sync_db()
        if res.action != "conflict":
            try:
                up, down = self.sync_attachments(res.pulled_file)
                if up or down:
                    res.summary = {**res.summary, "attachments_up": up, "attachments_down": down}
            except SyncError:
                raise
            except Exception as e:                 # the phrases are synced; files try again next time
                log.warning("attached files were not synced: %s", e)
        return res

    def _sync_db(self) -> SyncResult:
        local_hash = content_hash(self.store)
        last_rev = int(self.store.setting("sync.last_rev", "0") or 0)
        last_hash = self.store.setting("sync.last_hash", "")
        remote = next((f for f in self.remote.list() if f.name == SYNC_NAME), None)
        remote_rev = int(remote.props.get("rev", 0)) if remote else 0
        local_changed = local_hash != last_hash
        remote_changed = remote is not None and remote_rev != last_rev
        pw = self.passphrase
        if remote is not None and remote.props.get("enc") == "1" and not pw:
            raise SyncError("The cloud copy is encrypted. Turn on encryption and enter the sync "
                            "passphrase in Settings > Backup & Sync.")
        if remote is not None and pw and remote.props.get("enc") != "1":
            if not remote_changed and last_hash:
                return self._push(remote_rev + 1, local_hash)      # encrypt what is already there
            raise SyncError("The cloud copy is not encrypted, but encryption is on here, so it was not "
                            "used. Upload this PC's phrases to replace it (Settings > Backup & Sync), "
                            "or turn encryption off.")
        local_cmp = self._prop_hash(local_hash)
        if remote is not None and not last_hash:
            # first sync on this PC: an empty PC just takes the cloud copy;
            # a PC that already has phrases must choose (handled as a conflict below)
            if not self.store.phrases() and not self.store.folders():
                local_changed = False
            elif remote.props.get("hash") == local_cmp:
                self._remember(remote_rev, local_hash)
                return SyncResult("unchanged", "Already in sync", remote_rev=remote_rev)

        if remote is None or (not remote_changed and local_changed):
            return self._push(remote_rev + 1, local_hash)
        if remote_changed and not local_changed:
            path = self.download(SYNC_NAME)
            return SyncResult("pulled", f"Updated from {remote.props.get('device', 'cloud')}", path, remote_rev)
        if remote_changed and local_changed:
            if remote.props.get("hash") == local_cmp:     # same data reached both sides
                self._remember(remote_rev, local_hash)
                return SyncResult("unchanged", "Already in sync", remote_rev=remote_rev)
            self.backup_now(int(self.store.setting("backup.cloud_keep", "10") or 10))
            merged = self._merge(remote, remote_rev)
            if merged is not None:
                return merged
            return SyncResult("conflict", f"Phrases changed on this PC and on {remote.props.get('device', 'another PC')}",
                              remote_rev=remote_rev)
        return SyncResult("unchanged", "Already in sync", remote_rev=remote_rev)

    def _merge(self, remote: RemoteFile, remote_rev: int) -> SyncResult | None:
        """Merge both sides' edits and upload the result; None = cannot merge, ask the user."""
        from phraseforge.cloud import merge as mg
        base = self._base()
        if base is None or self.store.setting("sync.merge", "1") == "0":
            return None
        theirs = self.download(SYNC_NAME)
        mine = self._snapshot()
        out = None
        try:
            try:
                b, loc, rem = mg.read_state(base, self.store.vault_key), mg.read_state(mine), mg.read_state(theirs)
            except Exception as e:     # an old copy without uids, a damaged or locked base
                log.info("cannot merge, asking instead: %s", e)
                return None
            try:
                m = mg.merge(b, loc, rem)
                ms = Store(mine)
                try:
                    mg.apply(ms, loc, rem, m)
                    h = content_hash(ms)
                finally:
                    ms.close()
            except Exception as e:     # bad values in the other copy must not block every sync (R52)
                log.warning("cannot merge, asking instead: %s", e)
                return None
            _strip(mine)
            rev = remote_rev + 1
            self._upload(mine, SYNC_NAME, {"rev": rev, "hash": self._prop_hash(h), "device": self.device,
                                              "modified": datetime.now().isoformat(timespec="seconds")})
            out, mine = mine, None
            who = remote.props.get("device", "another PC")
            return SyncResult("merged", f"Merged the changes from {who}", out, rev, m.summary)
        finally:
            self._discard(theirs)
            if mine is not None:
                self._discard(mine)

    def _push(self, rev: int, local_hash: str) -> SyncResult:
        snap = self._snapshot()
        try:
            self._upload(snap, SYNC_NAME, {"rev": rev, "hash": self._prop_hash(local_hash), "device": self.device,
                                              "modified": datetime.now().isoformat(timespec="seconds")})
            self._save_base(snap, rev)
        finally:
            self._discard(snap)
        self._remember(rev, local_hash)
        return SyncResult("pushed", f"Uploaded to {self.remote.label}", remote_rev=rev)

    def resolve(self, keep: str) -> SyncResult:
        """After a conflict: keep="local" uploads this PC's phrases, keep="remote" downloads the cloud copy."""
        remote = next((f for f in self.remote.list() if f.name == SYNC_NAME), None)
        rev = int(remote.props.get("rev", 0)) if remote else 0
        if keep == "local":
            self._refuse_plain_over_encrypted(remote)
            return self._push(rev + 1, content_hash(self.store))
        path = self.download(SYNC_NAME, allow_older=True)     # the user chose the cloud copy
        return SyncResult("pulled", "Replaced with the cloud copy", path, rev)

    def _refuse_plain_over_encrypted(self, remote=None) -> None:
        """A PC without the sync passphrase never replaces an encrypted cloud copy with a plain
        one, nor adds plain backups next to it (security R89)."""
        if self.passphrase:
            return
        if remote is None:
            remote = next((f for f in self.remote.list() if f.name == SYNC_NAME), None)
        if remote is not None and str(remote.props.get("enc", "")) == "1":
            raise SyncError("The cloud copy is encrypted, but encryption is off on this PC, so nothing was "
                            "uploaded. Turn on encryption and enter the sync passphrase in Settings > Backup & Sync.")

    def _local_backup(self) -> None:
        """A copy of this PC's phrases next to the phrase file, made before a pull replaces them:
        the cloud backups sit where the other copy came from, so a pull that deletes everything
        must have a way back that the cloud cannot touch (R56)."""
        if self.store.path == ":memory:":
            return
        p = Path(self.store.path)
        try:
            self.store.backup_to(p.with_name(p.stem + ".before-sync.db"), keep_encryption=True)
        except Exception as e:                    # never block the pull over this
            log.warning("local backup before the pull failed: %s", e)

    def apply_pull(self, path: Path, remote_rev: int | None = None) -> None:
        """Replace local data with a downloaded copy, keeping this PC's clipboard and device settings.
        Call on the UI thread (store change listeners update windows)."""
        _check_db(path)
        self._local_backup()
        if remote_rev is not None:
            self._save_base(path, remote_rev)
        with self.store.lock:                 # raw values: API keys stay encrypted
            keep_settings = {k: v for k, v in self.store.conn.execute("SELECT key, value FROM settings")
                             if _is_local_key(k)}
        keep_clip = [(e.text, e.created, e.source_app, int(e.pinned)) for e in self.store.clipboard_entries(10_000)]
        # phrases the pull adds or changes must be approved on this PC before their
        # privileged macros run (security.py)
        self.store.restore_from(path, untrusted="synced")
        with self.store.lock, self.store.conn:
            for k, v in keep_settings.items():
                self.store.conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (k, v))
            self.store.conn.execute("DELETE FROM clipboard")
            for row in reversed(keep_clip):
                self.store.conn.execute("INSERT INTO clipboard (text,created,source_app,pinned) VALUES (?,?,?,?)", row)
        if remote_rev is not None:
            self._remember(remote_rev, content_hash(self.store))
        self._discard(path)


def _strip(path: Path) -> None:
    """Remove what never leaves this PC: clipboard history, the trash, mounted phrase libraries
    and device-only settings."""
    con = sqlite3.connect(str(path))
    with con:
        con.execute("DELETE FROM clipboard")
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='trash'").fetchone():
            con.execute("DELETE FROM trash")              # the trash belongs to this PC
        from phraseforge.libraries import strip_copy
        strip_copy(con)                                   # so do the mounted phrase libraries
        for (k,) in con.execute("SELECT key FROM settings").fetchall():
            if _is_local_key(k):
                con.execute("DELETE FROM settings WHERE key=?", (k,))
    con.execute("VACUUM")
    con.close()


def _check_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    try:
        ok = con.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()
    if ok != "ok" or not {"phrases", "folders", "settings"} <= tables:
        raise RuntimeError("The downloaded file is not a valid PhraseForge database.")


def make_remote(store: Store, drive=None) -> Remote | None:
    """Remote for the current settings (sync.provider = off | gdrive | folder)."""
    provider = store.setting("sync.provider", "off")
    if provider == "folder":
        folder = store.setting("sync.folder_path", "")
        return FolderRemote(folder) if folder else None
    if provider == "gdrive":
        if drive is None:
            from phraseforge.cloud.gdrive import GoogleDrive
            drive = GoogleDrive()
        if not drive.signed_in():
            return None
        return GDriveRemote(drive, store.setting("sync.gdrive_folder", "PhraseForge"))
    return None
