"""Backup and two-way sync of the phrase database to a cloud location.

Remote layout (a Google Drive folder, or any local/synced folder):
    phraseforge-sync.db            the shared copy; its properties hold rev/hash/device
    backups/ (folder) or backup-*  dated backups, newest N kept

Sync rule per run, with `last_rev`/`last_hash` remembered from the previous sync:
    no remote copy                      -> push
    remote unchanged, local changed     -> push (rev + 1)
    remote changed, local unchanged     -> pull (replace local data)
    both changed                        -> CONFLICT: nothing is overwritten; the local copy is
                                           uploaded as a backup and the caller asks the user
                                           to keep "this PC" or "cloud" (resolve()).

What syncs: folders, phrases, triggers, tags, variables, history, statistics and
shared settings. What never leaves this PC: clipboard history and device-only
settings (sign-in, sync state, paths, start-with-Windows).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from phraseforge.db import SECRET_SETTINGS, Store

SYNC_NAME = "phraseforge-sync.db"
BACKUP_PREFIX = "backup-"

# settings that belong to this PC only; kept when pulling, removed when pushing
LOCAL_SETTING_PREFIXES = ("sync.", "gdrive.", "backup.cloud_", "ocr.cli_path", "app.start_with_windows",
                          "app.first_run_done", "ui.item_colors", "updates.last_check",
                          "updates.notified_version",
                          # API keys: encrypted for this Windows account, never uploaded. Taken
                          # from db.SECRET_SETTINGS so a newly added key can never leak.
                          *sorted(SECRET_SETTINGS))


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
@dataclass
class SyncResult:
    action: str                 # pushed | pulled | unchanged | conflict
    message: str
    pulled_file: Path | None = None   # for "pulled": apply with apply_pull() on the UI thread
    remote_rev: int = 0


def content_hash(store: Store) -> str:
    """Hash of the user's data (not timestamps of the export itself)."""
    d = store.export_dict()
    d.pop("exported", None)
    for p in d.get("phrases", []):           # usage counters change on every expansion
        for k in ("use_count", "last_used"):
            p.pop(k, None)
    blob = json.dumps(d, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _is_local_key(key: str) -> bool:
    return key.startswith(LOCAL_SETTING_PREFIXES)


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
        con = sqlite3.connect(name)
        with con:
            con.execute("DELETE FROM clipboard")
            for (k,) in con.execute("SELECT key FROM settings").fetchall():
                if _is_local_key(k):
                    con.execute("DELETE FROM settings WHERE key=?", (k,))
        con.execute("VACUUM")
        con.close()
        return Path(name)

    def _remember(self, rev: int, h: str) -> None:
        self.store.set_setting("sync.last_rev", str(rev))
        self.store.set_setting("sync.last_hash", h)
        self.store.set_setting("sync.last_time", datetime.now().isoformat(timespec="seconds"))

    # ---------------------------------------------------- backup
    def backup_now(self, keep: int = 10) -> str:
        snap = self._snapshot()
        try:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            safe_dev = "".join(c for c in self.device if c.isalnum() or c in "-_") or "pc"
            name = f"{BACKUP_PREFIX}{stamp}-{safe_dev}.db"
            self.remote.put(snap, name, {"kind": "backup", "device": self.device, "created": stamp})
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
        self.remote.get(name, Path(tmp))
        _check_db(Path(tmp))
        return Path(tmp)

    # ---------------------------------------------------- sync
    def sync(self) -> SyncResult:
        local_hash = content_hash(self.store)
        last_rev = int(self.store.setting("sync.last_rev", "0") or 0)
        last_hash = self.store.setting("sync.last_hash", "")
        remote = next((f for f in self.remote.list() if f.name == SYNC_NAME), None)
        remote_rev = int(remote.props.get("rev", 0)) if remote else 0
        local_changed = local_hash != last_hash
        remote_changed = remote is not None and remote_rev != last_rev
        if remote is not None and not last_hash:
            # first sync on this PC: an empty PC just takes the cloud copy;
            # a PC that already has phrases must choose (handled as a conflict below)
            if not self.store.phrases() and not self.store.folders():
                local_changed = False
            elif remote.props.get("hash") == local_hash:
                self._remember(remote_rev, local_hash)
                return SyncResult("unchanged", "Already in sync", remote_rev=remote_rev)

        if remote is None or (not remote_changed and local_changed):
            return self._push(remote_rev + 1, local_hash)
        if remote_changed and not local_changed:
            path = self.download(SYNC_NAME)
            return SyncResult("pulled", f"Updated from {remote.props.get('device', 'cloud')}", path, remote_rev)
        if remote_changed and local_changed:
            if remote.props.get("hash") == local_hash:     # same data reached both sides
                self._remember(remote_rev, local_hash)
                return SyncResult("unchanged", "Already in sync", remote_rev=remote_rev)
            self.backup_now(int(self.store.setting("backup.cloud_keep", "10") or 10))
            return SyncResult("conflict", f"Phrases changed on this PC and on {remote.props.get('device', 'another PC')}",
                              remote_rev=remote_rev)
        return SyncResult("unchanged", "Already in sync", remote_rev=remote_rev)

    def _push(self, rev: int, local_hash: str) -> SyncResult:
        snap = self._snapshot()
        try:
            self.remote.put(snap, SYNC_NAME, {"rev": rev, "hash": local_hash, "device": self.device,
                                              "modified": datetime.now().isoformat(timespec="seconds")})
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

    def apply_pull(self, path: Path, remote_rev: int | None = None) -> None:
        """Replace local data with a downloaded copy, keeping this PC's clipboard and device settings.
        Call on the UI thread (store change listeners update windows)."""
        _check_db(path)
        with self.store.lock:                 # raw values: API keys stay encrypted
            keep_settings = {k: v for k, v in self.store.conn.execute("SELECT key, value FROM settings")
                             if _is_local_key(k)}
        keep_clip = [(e.text, e.created, e.source_app, int(e.pinned)) for e in self.store.clipboard_entries(10_000)]
        self.store.restore_from(path)
        with self.store.lock, self.store.conn:
            for k, v in keep_settings.items():
                self.store.conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (k, v))
            self.store.conn.execute("DELETE FROM clipboard")
            for row in reversed(keep_clip):
                self.store.conn.execute("INSERT INTO clipboard (text,created,source_app,pinned) VALUES (?,?,?,?)", row)
        if remote_rev is not None:
            self._remember(remote_rev, content_hash(self.store))
        path.unlink(missing_ok=True)


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
