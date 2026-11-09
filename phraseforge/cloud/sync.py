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

    def _prop_hash(self, h: str) -> str:
        """The content hash shown in the cloud's file properties; keyed when encrypted, so the
        hash of a guessed phrase list cannot be checked against it."""
        pw = self.passphrase
        return hashlib.sha256(f"{pw}|{h}".encode("utf-8")).hexdigest() if pw else h

    def _upload(self, local: Path, name: str, props: dict) -> None:
        pw = self.passphrase
        if not pw:
            self.remote.put(local, name, props)
            return
        from phraseforge import vault
        fd, enc = tempfile.mkstemp(prefix="pf-enc-", suffix=".db")
        os.close(fd)
        try:
            vault.write(enc, Path(local).read_bytes(), vault.Key.new(pw, use_dpapi=False))
            self.remote.put(Path(enc), name, {**props, "enc": "1"})
        finally:
            Path(enc).unlink(missing_ok=True)

    # ---------------------------------------------------- backup
    def backup_now(self, keep: int = 10) -> str:
        snap = self._snapshot()
        try:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            safe_dev = "".join(c for c in self.device if c.isalnum() or c in "-_") or "pc"
            name = f"{BACKUP_PREFIX}{stamp}-{safe_dev}.db"
            self._upload(snap, name, {"kind": "backup", "device": self.device, "created": stamp})
        finally:
            snap.unlink(missing_ok=True)
        backups = sorted((f for f in self.remote.list() if f.name.startswith(BACKUP_PREFIX)),
                         key=lambda f: f.name, reverse=True)
        for old in backups[max(1, keep):]:
            self.remote.delete(old.name)
        return name

    def list_backups(self) -> list[RemoteFile]:
        return sorted((f for f in self.remote.list() if f.name.startswith(BACKUP_PREFIX)),
                      key=lambda f: f.name, reverse=True)

    def download(self, name: str) -> Path:
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
                path.write_bytes(vault.no_wal(data))
            elif pw:
                raise SyncError(f"{name} in the cloud is not encrypted, but encryption is on here: it was "
                                "not used. Upload this PC's phrases to replace it, or turn encryption off.")
            _check_db(path)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return path

    # ---------------------------------------------------- sync
    def sync(self) -> SyncResult:
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
            theirs.unlink(missing_ok=True)
            if mine is not None:
                mine.unlink(missing_ok=True)

    def _push(self, rev: int, local_hash: str) -> SyncResult:
        snap = self._snapshot()
        try:
            self._upload(snap, SYNC_NAME, {"rev": rev, "hash": self._prop_hash(local_hash), "device": self.device,
                                              "modified": datetime.now().isoformat(timespec="seconds")})
            self._save_base(snap, rev)
        finally:
            snap.unlink(missing_ok=True)
        self._remember(rev, local_hash)
        return SyncResult("pushed", f"Uploaded to {self.remote.label}", remote_rev=rev)

    def resolve(self, keep: str) -> SyncResult:
        """After a conflict: keep="local" uploads this PC's phrases, keep="remote" downloads the cloud copy."""
        remote = next((f for f in self.remote.list() if f.name == SYNC_NAME), None)
        rev = int(remote.props.get("rev", 0)) if remote else 0
        if keep == "local":
            return self._push(rev + 1, content_hash(self.store))
        path = self.download(SYNC_NAME)
        return SyncResult("pulled", "Replaced with the cloud copy", path, rev)

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
        path.unlink(missing_ok=True)


def _strip(path: Path) -> None:
    """Remove what never leaves this PC: clipboard history, the trash and device-only settings."""
    con = sqlite3.connect(str(path))
    with con:
        con.execute("DELETE FROM clipboard")
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='trash'").fetchone():
            con.execute("DELETE FROM trash")              # the trash belongs to this PC
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
