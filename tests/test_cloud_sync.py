"""Two simulated PCs syncing through a folder and through a fake Google Drive."""
import itertools
import shutil
import sys
from pathlib import Path

import pytest

from phraseforge.cloud.secure import protect, unprotect
from phraseforge.cloud.sync import SYNC_NAME, CloudSync, FolderRemote, GDriveRemote, content_hash
from phraseforge.db import SECRET_SETTINGS, Store
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
    b.set_setting("sync.merge", "0")          # merging off: ask (tests/test_change_sync.py merges)
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


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows only")
def test_dpapi_roundtrip():
    secret = b'{"refresh_token": "abc"}'
    enc = protect(secret)
    assert enc != secret
    assert unprotect(enc) == secret


def test_api_keys_are_encrypted_at_rest(tmp_path):
    s = Store(tmp_path / "k.db")
    s.set_setting("ai.openai_key", "sk-test-123")
    raw = s.conn.execute("SELECT value FROM settings WHERE key='ai.openai_key'").fetchone()[0]
    assert "sk-test-123" not in raw and raw.startswith("dpapi:")
    assert s.setting("ai.openai_key") == "sk-test-123"
    assert s.settings()["ai.openai_key"] == "sk-test-123"
    s.set_setting("ai.openai_key", "")
    assert s.setting("ai.openai_key") == ""


def test_plaintext_keys_from_older_versions_get_encrypted(tmp_path):
    db = tmp_path / "old.db"
    s = Store(db)
    s.conn.execute("UPDATE settings SET value='sk-old' WHERE key='ai.anthropic_key'")
    s.conn.commit()
    s.conn.close()
    s = Store(db)
    raw = s.conn.execute("SELECT value FROM settings WHERE key='ai.anthropic_key'").fetchone()[0]
    assert raw.startswith("dpapi:")
    assert s.setting("ai.anthropic_key") == "sk-old"


def test_api_keys_never_sync(tmp_path, remote_factory):
    a, sa = pc(tmp_path, "A", remote_factory)
    b, sb = pc(tmp_path, "B", remote_factory)
    for k in SECRET_SETTINGS:
        a.set_setting(k, "key-from-A")
    b.set_setting("ai.openai_key", "key-from-B")
    a.add_phrase(Phrase("P", "p"))
    sa.sync()
    apply(sb, sb.sync())
    assert b.setting("ai.openai_key") == "key-from-B"
    assert b.setting("ai.anthropic_key") == ""
    sealed = a.conn.execute("SELECT value FROM settings WHERE key='ai.openai_key'").fetchone()[0].encode()
    for f in tmp_path.rglob("*"):                 # nothing outside PC A's own database holds A's key
        if f.is_file() and not f.name.startswith("A.db"):
            data = f.read_bytes()
            assert b"key-from-A" not in data and sealed not in data, f


# ---------------------------------------------------------------- attached files (G-21)
def _pc(tmp_path, name, monkeypatch=None):
    data = tmp_path / name
    data.mkdir(exist_ok=True)
    return data, Store(data / "p.db")


def _use(monkeypatch, data):
    from phraseforge import paths
    monkeypatch.setattr(paths, "data_dir", lambda: data)


@pytest.mark.parametrize("encrypted", [False, True])
def test_attached_files_follow_the_phrases(tmp_path, monkeypatch, encrypted):
    from phraseforge.importers import files as fl
    cloud = FolderRemote(tmp_path / "cloud")
    d1, s1 = _pc(tmp_path, "pc1")
    d2, s2 = _pc(tmp_path, "pc2")
    for s in (s1, s2):
        if encrypted:
            s.set_setting("sync.encrypt", "1")
            s.set_setting("sync.passphrase", "correct horse")
    src = tmp_path / "Price list.pdf"
    src.write_bytes(b"%PDF demo " * 100)

    _use(monkeypatch, d1)
    macro = fl.attach_file(src)
    s1.add_phrase(Phrase("Prices", "See attached " + macro))
    r1 = CloudSync(s1, cloud, "pc1").sync()
    assert r1.action == "pushed" and r1.summary.get("attachments_up") == 1
    att = [p for p in (tmp_path / "cloud").iterdir() if p.name.startswith("pf-att-") and p.suffix == ".db"]
    assert len(att) == 1
    if encrypted:
        assert b"%PDF demo" not in att[0].read_bytes()

    _use(monkeypatch, d2)
    cs2 = CloudSync(s2, cloud, "pc2")
    r2 = cs2.sync()
    assert r2.action == "pulled" and r2.summary.get("attachments_down") == 1
    cs2.apply_pull(r2.pulled_file, r2.remote_rev)
    kept = fl.resolve_attachment(macro[len('{#pastefile "'):-2])
    assert kept is not None and kept.read_bytes() == src.read_bytes() and kept.name == "Price list.pdf"
    assert CloudSync(s2, cloud, "pc2").sync().summary.get("attachments_down") is None     # nothing left to do
    s1.close(); s2.close()


def test_a_swapped_attachment_in_the_cloud_is_not_used(tmp_path, monkeypatch):
    from phraseforge.importers import files as fl
    cloud = FolderRemote(tmp_path / "cloud")
    d1, s1 = _pc(tmp_path, "pc1")
    d2, s2 = _pc(tmp_path, "pc2")
    src = tmp_path / "a.txt"
    src.write_bytes(b"real")
    _use(monkeypatch, d1)
    macro = fl.attach_file(src)
    s1.add_phrase(Phrase("A", macro))
    CloudSync(s1, cloud, "pc1").sync()
    att = next(p for p in (tmp_path / "cloud").iterdir() if p.name.startswith("pf-att-") and p.suffix == ".db")
    att.write_bytes(b"evil")                                  # someone with access to the folder
    _use(monkeypatch, d2)
    r = CloudSync(s2, cloud, "pc2").sync()
    assert r.action == "pulled" and "attachments_down" not in r.summary
    assert fl.resolve_attachment(macro[len('{#pastefile "'):-2]) is None
    s1.close(); s2.close()


def _att_names(cloud_dir):
    return sorted(p.name for p in cloud_dir.iterdir() if p.name.startswith("pf-att-") and p.suffix == ".db")


def test_unused_attachments_are_pruned_but_backups_keep_theirs(tmp_path, monkeypatch):
    from phraseforge.importers import files as fl
    cloud_dir = tmp_path / "cloud"
    cloud = FolderRemote(cloud_dir)
    d1, s1 = _pc(tmp_path, "pc1")
    _use(monkeypatch, d1)
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_bytes(b"first file")
    b.write_bytes(b"second file")
    pa = s1.add_phrase(Phrase("A", fl.attach_file(a)))
    s1.add_phrase(Phrase("B", fl.attach_file(b)))
    cs = CloudSync(s1, cloud, "pc1")
    cs.sync()
    assert len(_att_names(cloud_dir)) == 2

    s1.delete_phrase(pa.id)                          # A is gone from the phrases ...
    cs.sync()
    assert cs.prune_attachments(force=True) == 1     # ... and from every copy: removed
    assert len(_att_names(cloud_dir)) == 1

    cs.backup_now()                                  # a backup still uses B
    s1.delete_phrase(next(p for p in s1.phrases() if p.description == "B").id)
    cs.sync()
    assert cs.prune_attachments(force=True) == 0     # the backup keeps B
    assert len(_att_names(cloud_dir)) == 1
    assert cs.prune_attachments() == 0               # once a week only
    s1.close()


def test_restoring_a_backup_fetches_its_attachments(tmp_path, monkeypatch):
    from phraseforge.importers import files as fl
    cloud = FolderRemote(tmp_path / "cloud")
    d1, s1 = _pc(tmp_path, "pc1")
    d2, s2 = _pc(tmp_path, "pc2")
    _use(monkeypatch, d1)
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF backup")
    macro = fl.attach_file(src)
    s1.add_phrase(Phrase("Doc", macro))
    cs1 = CloudSync(s1, cloud, "pc1")
    cs1.sync()
    name = cs1.backup_now()
    _use(monkeypatch, d2)
    cs2 = CloudSync(s2, cloud, "pc2")
    path = cs2.restore_backup(name)
    cs2.apply_pull(path)
    kept = fl.resolve_attachment(macro[len('{#pastefile "'):-2])
    assert kept is not None and kept.read_bytes() == b"%PDF backup"
    s1.close(); s2.close()
