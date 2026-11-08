"""Encryption of the phrase file at rest (G-04, FR-SEC-09)."""
import sqlite3
import time

import pytest

from phraseforge import io_formats, vault
from phraseforge.cloud.sync import CloudSync, FolderRemote
from phraseforge.db import Store
from phraseforge.models import Phrase

SECRET = "Top secret phrase text 4711"


@pytest.fixture(autouse=True)
def fake_dpapi(monkeypatch):
    monkeypatch.setattr(vault, "FAKE_DPAPI_FOR_TESTS", True)
    monkeypatch.setattr(Store, "FLUSH_SECONDS", 0.05)


def plain_on_disk(path):
    data = path.read_bytes()
    return data.startswith(b"SQLite format 3") or SECRET.encode() in data


def test_encrypted_file_has_no_sqlite_header_and_no_plain_text(tmp_path):
    db = tmp_path / "phrases.db"
    s = Store(db)
    s.add_phrase(Phrase("Secret", SECRET))
    s.enable_encryption()
    assert s.encrypted and vault.is_encrypted(db) and not plain_on_disk(db)
    for side in ("-wal", "-shm"):
        assert not (tmp_path / f"phrases.db{side}").exists()
    s.add_phrase(Phrase("Later", "added after encrypting"))
    s.close()
    assert not plain_on_disk(db)
    s2 = Store(db)
    assert sorted(p.description for p in s2.phrases()) == ["Later", "Secret"]
    assert s2.encrypted
    s2.close()


def test_changes_reach_the_file_while_open(tmp_path):
    db = tmp_path / "phrases.db"
    s = Store(db)
    s.enable_encryption()
    s.add_phrase(Phrase("New", "n"))
    deadline = time.time() + 5
    while time.time() < deadline:
        data, _ = vault.read(db, s.vault_key)
        con = vault.memory_db(data)
        if con.execute("SELECT count(*) FROM phrases").fetchone()[0] == 1:
            break
        time.sleep(0.05)
    else:
        pytest.fail("the change was not written")
    s.close()


def test_passphrase_only(tmp_path):
    db = tmp_path / "phrases.db"
    s = Store(db)
    s.add_phrase(Phrase("Secret", SECRET))
    s.enable_encryption("correct horse", use_dpapi=False)
    s.close()
    with pytest.raises(vault.NeedPassphrase):
        Store(db)
    with pytest.raises(vault.WrongPassphrase):
        Store(db, passphrase="wrong one")
    s = Store(db, passphrase="correct horse")
    assert s.find_phrase("Secret").content == SECRET
    s.close()


def test_passphrase_opens_it_where_windows_cannot(tmp_path, monkeypatch):
    db = tmp_path / "phrases.db"
    s = Store(db)
    s.add_phrase(Phrase("Secret", SECRET))
    s.enable_encryption("recovery phrase")
    s.close()
    monkeypatch.setattr(vault, "_unprotect", lambda b: (_ for _ in ()).throw(OSError("other user")))
    with pytest.raises(vault.NeedPassphrase):
        Store(db)
    s = Store(db, passphrase="recovery phrase")
    assert s.find_phrase("Secret").content == SECRET
    s.close()


def test_without_dpapi_a_passphrase_is_required(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "FAKE_DPAPI_FOR_TESTS", False)
    if vault.dpapi_available():
        pytest.skip("Windows has DPAPI")
    s = Store(tmp_path / "phrases.db")
    with pytest.raises(vault.VaultError):
        s.enable_encryption()
    assert not s.encrypted
    s.enable_encryption("long enough")
    assert s.encrypted
    s.close()


def test_a_changed_file_is_refused(tmp_path):
    db = tmp_path / "phrases.db"
    s = Store(db)
    s.enable_encryption()
    s.close()
    data = bytearray(db.read_bytes())
    data[-5] ^= 1
    db.write_bytes(bytes(data))
    with pytest.raises(vault.VaultError):
        Store(db)


def test_change_passphrase_and_turn_off(tmp_path):
    db = tmp_path / "phrases.db"
    s = Store(db)
    s.add_phrase(Phrase("Secret", SECRET))
    s.enable_encryption("first pass")
    s.change_passphrase("second pass", use_dpapi=False)
    s.close()
    with pytest.raises(vault.WrongPassphrase):
        Store(db, passphrase="first pass")
    s = Store(db, passphrase="second pass")
    s.disable_encryption()
    assert not s.encrypted
    s.add_phrase(Phrase("After", "a"))
    s.close()
    assert db.read_bytes().startswith(b"SQLite format 3")
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM phrases").fetchone()[0] == 2
    con.close()


def test_backups_stay_encrypted_and_restore(tmp_path):
    db = tmp_path / "phrases.db"
    s = Store(db)
    s.add_phrase(Phrase("Secret", SECRET))
    s.enable_encryption()
    b = io_formats.backup(s, tmp_path / "backups")
    assert vault.is_encrypted(b) and not plain_on_disk(b)
    s.delete_phrase(s.find_phrase("Secret").id)
    s.restore_from(b)
    assert s.find_phrase("Secret").content == SECRET
    s.close()
    assert Store(db).find_phrase("Secret") is not None


def test_sync_with_an_encrypted_phrase_file(tmp_path):
    a = Store(tmp_path / "A.db")
    a.enable_encryption()
    b = Store(tmp_path / "B.db")
    sa = CloudSync(a, FolderRemote(tmp_path / "cloud"), device="A")
    sb = CloudSync(b, FolderRemote(tmp_path / "cloud"), device="B")
    a.add_phrase(Phrase("Base", SECRET))

    def run(cs):
        r = cs.sync()
        if r.action in ("pulled", "merged"):
            cs.apply_pull(r.pulled_file, r.remote_rev)
        return r
    run(sa)
    run(sb)
    assert vault.is_encrypted(sa.base_path) and not plain_on_disk(sa.base_path)
    a.add_phrase(Phrase("From A", "a"))
    b.add_phrase(Phrase("From B", "b"))
    run(sb)
    assert run(sa).action == "merged"
    assert sorted(p.description for p in a.phrases()) == ["Base", "From A", "From B"]
    a.close()
    b.close()
    assert not plain_on_disk(tmp_path / "A.db")


def test_settings_dialog_checks_the_passphrase(tmp_path, qapp=None):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from phraseforge.ui.encryption_dialog import EncryptionDialog, status_text
    s = Store(tmp_path / "phrases.db")
    d = EncryptionDialog(s)
    d.ask.setChecked(True)
    d.pass1.setText("short")
    d.pass2.setText("short")
    assert "at least" in d.problem()
    d.pass1.setText("long enough pass")
    assert "not the same" in d.problem()
    d.pass2.setText("long enough pass")
    assert d.problem() == ""
    assert d.apply() and s.encrypted and not s.vault_key.opens_without_passphrase
    assert "every time" in status_text(s)
    s.close()
