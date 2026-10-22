"""Two simulated PCs syncing through a folder and through a fake Google Drive."""
import itertools
import shutil
from pathlib import Path

import pytest

from phraseforge.cloud.secure import protect, unprotect
from phraseforge.cloud.sync import SYNC_NAME, CloudSync, FolderRemote, GDriveRemote, content_hash
from phraseforge.db import Store
from phraseforge.models import Phrase


class FakeDrive:
    """In-memory stand-in for phraseforge.cloud.gdrive.GoogleDrive."""
    def __init__(self, root: Path):
        self.root, self.files, self.ids = root, {}, itertools.count(1)
        self.folders = {}

    def ensure_folder(self, name):
        return self.folders.setdefault(name, f"folder{next(self.ids)}")

    def list(self, folder_id):
        return [{"id": fid, "name": f["name"], "modifiedTime": "", "size": f["path"].stat().st_size,
                 "appProperties": f["props"]} for fid, f in self.files.items() if f["parent"] == folder_id]

    def upload(self, local, name, folder_id, props=None, file_id=None):
        fid = file_id or f"file{next(self.ids)}"
        path = self.root / fid
        shutil.copyfile(local, path)
        parent = self.files[fid]["parent"] if file_id else folder_id
        self.files[fid] = {"name": name, "parent": parent, "path": path,
                           "props": {k: str(v) for k, v in (props or {}).items()}}
        return fid

    def download(self, file_id, dest):
        shutil.copyfile(self.files[file_id]["path"], dest)

    def delete(self, file_id):
        self.files.pop(file_id)


@pytest.fixture(params=["folder", "gdrive"])
def remote_factory(request, tmp_path):
    if request.param == "folder":
        folder = tmp_path / "cloud"
        return lambda: FolderRemote(folder)
    drive = FakeDrive(tmp_path)
    return lambda: GDriveRemote(drive, "PhraseForge")


def pc(tmp_path, name, remote):
    store = Store(tmp_path / f"{name}.db")
    return store, CloudSync(store, remote(), device=name)


def apply(sync, result):
    if result.action == "pulled":
        sync.apply_pull(result.pulled_file, result.remote_rev)


def descriptions(store):
    return sorted(p.description for p in store.phrases())


def test_push_then_pull_to_second_pc(tmp_path, remote_factory):
    a, sa = pc(tmp_path, "A", remote_factory)
    b, sb = pc(tmp_path, "B", remote_factory)
    a.add_phrase(Phrase("Hello", "hi"))
    assert sa.sync().action == "pushed"
    r = sb.sync()
    assert r.action == "pulled"
    apply(sb, r)
    assert descriptions(b) == ["Hello"]
    assert sb.sync().action == "unchanged"
    assert sa.sync().action == "unchanged"


def test_changes_flow_both_ways(tmp_path, remote_factory):
    a, sa = pc(tmp_path, "A", remote_factory)
    b, sb = pc(tmp_path, "B", remote_factory)
    a.add_phrase(Phrase("One", "1"))
    sa.sync()
    apply(sb, sb.sync())
    b.add_phrase(Phrase("Two", "2"))
    assert sb.sync().action == "pushed"
    apply(sa, sa.sync())
    assert descriptions(a) == ["One", "Two"]


def test_first_sync_with_existing_phrases_asks(tmp_path, remote_factory):
    a, sa = pc(tmp_path, "A", remote_factory)
    b, sb = pc(tmp_path, "B", remote_factory)
    a.add_phrase(Phrase("From A", "a"))
    sa.sync()
    b.add_phrase(Phrase("B's own", "b"))
    assert sb.sync().action == "conflict"
    assert sb.resolve("local").action == "pushed"
    apply(sa, sa.sync())
    assert descriptions(a) == ["B's own"]


def test_conflict_keeps_both_and_resolves(tmp_path, remote_factory):
    a, sa = pc(tmp_path, "A", remote_factory)
    b, sb = pc(tmp_path, "B", remote_factory)
    a.add_phrase(Phrase("Base", "x"))
    sa.sync()
    apply(sb, sb.sync())
    a.add_phrase(Phrase("From A", "a"))
    b.add_phrase(Phrase("From B", "b"))
    assert sa.sync().action == "pushed"
    r = sb.sync()
    assert r.action == "conflict"
    assert descriptions(b) == ["Base", "From B"]          # nothing overwritten
    assert sb.list_backups(), "local copy saved as a backup before asking"
    apply(sb, sb.resolve("remote"))
    assert descriptions(b) == ["Base", "From A"]


def test_clipboard_and_device_settings_never_sync(tmp_path, remote_factory):
    a, sa = pc(tmp_path, "A", remote_factory)
    b, sb = pc(tmp_path, "B", remote_factory)
    a.add_clipboard("secret from A")
    a.set_setting("ocr.cli_path", r"C:\A\Capture2Text_CLI.exe")
    a.set_setting("autotext.delimiters", " .")            # shared setting
    b.add_clipboard("B's own clipboard")
    b.set_setting("ocr.cli_path", r"D:\B\cli.exe")
    a.add_phrase(Phrase("P", "p"))
    sa.sync()
    apply(sb, sb.sync())
    assert [e.text for e in b.clipboard_entries()] == ["B's own clipboard"]
    assert b.setting("ocr.cli_path") == r"D:\B\cli.exe"
    assert b.setting("autotext.delimiters") == " ."


def test_backups_are_pruned(tmp_path, remote_factory, monkeypatch):
    a, sa = pc(tmp_path, "A", remote_factory)
    stamps = iter(f"2026010{i}-000000" for i in range(1, 9))
    import phraseforge.cloud.sync as mod

    real = mod.datetime

    class FakeNow(real):
        @classmethod
        def now(cls, tz=None):
            class D:
                def strftime(self, _): return next(stamps)
                def isoformat(self, **_): return "2026-01-01T00:00:00"
            return D()
    monkeypatch.setattr(mod, "datetime", FakeNow)
    for _ in range(5):
        sa.backup_now(keep=3)
    names = [f.name for f in sa.list_backups()]
    assert len(names) == 3 and names[0].startswith("backup-20260105")


def test_snapshot_is_valid_and_hash_ignores_usage(tmp_path, remote_factory):
    a, sa = pc(tmp_path, "A", remote_factory)
    p = a.add_phrase(Phrase("P", "p"))
    h = content_hash(a)
    a.record_use(p.id, chars=3)
    assert content_hash(a) == h
    sa.sync()
    assert any(f.name == SYNC_NAME for f in sa.remote.list())


def test_dpapi_roundtrip():
    secret = b'{"refresh_token": "abc"}'
    enc = protect(secret)
    assert enc != secret
    assert unprotect(enc) == secret
