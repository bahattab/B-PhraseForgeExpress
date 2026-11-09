"""End-to-end encryption of what sync uploads (FR-SYN-03)."""
import pytest

from phraseforge import vault
from phraseforge.cloud.sync import SYNC_NAME, CloudSync, FolderRemote, SyncError
from phraseforge.db import Store
from phraseforge.models import Phrase

SECRET = "Confidential phrase 0815"
PW = "correct horse battery"


def pc(tmp_path, name, pw=PW, encrypt=True):
    s = Store(tmp_path / f"{name}.db")
    if encrypt:
        s.set_setting("sync.encrypt", "1")
        s.set_setting("sync.passphrase", pw)
    return s, CloudSync(s, FolderRemote(tmp_path / "cloud"), device=name)


def run(cs):
    r = cs.sync()
    if r.action in ("pulled", "merged"):
        cs.apply_pull(r.pulled_file, r.remote_rev)
    return r


def cloud_files(tmp_path):
    return [f for f in (tmp_path / "cloud").iterdir() if f.suffix == ".db"]


def test_the_cloud_only_holds_ciphertext(tmp_path):
    a, sa = pc(tmp_path, "A")
    b, sb = pc(tmp_path, "B")
    a.add_phrase(Phrase("Secret", SECRET))
    assert run(sa).action == "pushed"
    sa.backup_now()
    files = cloud_files(tmp_path)
    assert len(files) == 2
    for f in files:
        data = f.read_bytes()
        assert vault.is_encrypted(f) and SECRET.encode() not in data and not data.startswith(b"SQLite")
        meta = f.with_suffix(".json").read_text()
        assert '"enc": "1"' in meta
    assert run(sb).action == "pulled"
    assert b.find_phrase("Secret").content == SECRET
    b.add_phrase(Phrase("From B", "b"))
    a.add_phrase(Phrase("From A", "a"))
    run(sb)
    assert run(sa).action == "merged"                   # merging works through the encryption too
    assert sorted(p.description for p in a.phrases()) == ["From A", "From B", "Secret"]
    assert all(vault.is_encrypted(f) for f in cloud_files(tmp_path))


def test_wrong_or_missing_passphrase(tmp_path):
    a, sa = pc(tmp_path, "A")
    a.add_phrase(Phrase("Secret", SECRET))
    run(sa)
    b, sb = pc(tmp_path, "B", pw="something else")
    with pytest.raises(SyncError, match="does not open"):
        sb.sync()
    c, sc = pc(tmp_path, "C", encrypt=False)
    c.add_phrase(Phrase("Mine", "m"))
    with pytest.raises(SyncError, match="encrypted"):
        sc.sync()                                        # never overwrites the encrypted copy with plain text
    assert vault.is_encrypted(tmp_path / "cloud" / SYNC_NAME)
    d, sd = pc(tmp_path, "D", pw="")
    with pytest.raises(SyncError, match="no sync passphrase"):
        sd.sync()


def test_turning_encryption_on_replaces_an_unchanged_plain_copy(tmp_path):
    a, sa = pc(tmp_path, "A", encrypt=False)
    a.add_phrase(Phrase("Secret", SECRET))
    run(sa)
    assert not vault.is_encrypted(tmp_path / "cloud" / SYNC_NAME)
    a.set_setting("sync.encrypt", "1")
    a.set_setting("sync.passphrase", PW)
    assert run(sa).action == "pushed"
    assert vault.is_encrypted(tmp_path / "cloud" / SYNC_NAME)


def test_a_changed_plain_copy_is_not_taken(tmp_path):
    a, sa = pc(tmp_path, "A")
    a.add_phrase(Phrase("P", "p"))
    run(sa)
    # someone with access to the folder (or a PC with encryption off) writes a plain copy
    evil, se = pc(tmp_path, "E", encrypt=False)
    evil.add_phrase(Phrase("Injected", "{#run cmd.exe}"))
    se.store.set_setting("sync.last_rev", "1")
    se._push(5, "x")
    with pytest.raises(SyncError, match="not encrypted"):
        sa.sync()
    assert a.find_phrase("Injected") is None
    assert sa.resolve("local").action == "pushed"        # "Upload this PC's phrases"
    assert vault.is_encrypted(tmp_path / "cloud" / SYNC_NAME)


def test_the_hash_in_the_file_properties_is_keyed(tmp_path):
    import json
    from phraseforge.cloud.sync import content_hash
    a, sa = pc(tmp_path, "A")
    a.add_phrase(Phrase("P", "p"))
    run(sa)
    props = json.loads((tmp_path / "cloud" / "phraseforge-sync.json").read_text())
    assert props["hash"] != content_hash(a)


def test_cloud_backups_can_be_restored(tmp_path):
    a, sa = pc(tmp_path, "A")
    a.add_phrase(Phrase("Secret", SECRET))
    name = sa.backup_now()
    path = sa.download(name)
    a.delete_phrase(a.find_phrase("Secret").id)
    sa.apply_pull(path)
    assert a.find_phrase("Secret").content == SECRET
