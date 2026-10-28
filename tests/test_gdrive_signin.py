"""Google Drive sign-in: OAuth client sources and the Settings > Backup & Sync button.

Never contacts Google: sign_in is replaced by a fake.
"""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from phraseforge.cloud import gdrive
from phraseforge.db import Store

CID = "1234567890-abc.apps.googleusercontent.com"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _seal(b: bytes) -> bytes:              # stand-in for DPAPI off Windows: reversible, not plain text
    return b"SEALED" + bytes(x ^ 0x5A for x in b)


def _unseal(b: bytes) -> bytes:
    if not b.startswith(b"SEALED"):
        raise OSError("not sealed")
    return bytes(x ^ 0x5A for x in b[6:])


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("PHRASEFORGE_HOME", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(gdrive, "builtin_client_file", lambda: tmp_path / "builtin.json")
    monkeypatch.setattr(gdrive, "protect", _seal)
    monkeypatch.setattr(gdrive, "unprotect", _unseal)
    return tmp_path


def test_no_client(home):
    assert gdrive.client_config() is None and gdrive.client_source() == ""
    assert not gdrive.GoogleDrive().has_client()


def test_builtin_client_used_and_own_client_wins(home):
    (home / "builtin.json").write_text(json.dumps(gdrive.client_json("b" + CID, "s1")))
    assert gdrive.client_config()["installed"]["client_id"] == "b" + CID
    assert gdrive.client_source() == "builtin" and gdrive.GoogleDrive().has_client()
    gdrive.install_client_values(CID, "s2")
    assert gdrive.client_config()["installed"]["client_id"] == CID and gdrive.client_source() == "own"
    gdrive.remove_own_client()
    assert gdrive.client_source() == "builtin"


def test_invalid_builtin_ignored(home):
    (home / "builtin.json").write_text("{not json")
    assert gdrive.client_config() is None


def test_pasted_values_validated(home):
    with pytest.raises(gdrive.GDriveError):
        gdrive.install_client_values("not-an-id", "x")
    with pytest.raises(gdrive.GDriveError):
        gdrive.install_client_values(CID, " ")
    gdrive.install_client_values(f"  {CID} ", " GOCSPX-x ")
    inst = gdrive.client_config()["installed"]
    assert inst["client_id"] == CID and inst["client_secret"] == "GOCSPX-x"
    assert inst["token_uri"] == "https://oauth2.googleapis.com/token"


def test_client_file_validated(home):
    web = home / "web.json"
    web.write_text(json.dumps({"web": {"client_id": CID, "client_secret": "s"}}))
    with pytest.raises(gdrive.GDriveError):
        gdrive.install_client_file(web)
    bad = home / "bad.json"
    bad.write_text("nope")
    with pytest.raises(gdrive.GDriveError):
        gdrive.install_client_file(bad)
    ok = home / "ok.json"
    ok.write_text(json.dumps(gdrive.client_json(CID, "s")))
    gdrive.install_client_file(ok)
    assert gdrive.client_source() == "own"


def test_sign_in_uses_client_config(home, monkeypatch):
    (home / "builtin.json").write_text(json.dumps(gdrive.client_json(CID, "s")))
    seen = {}

    class FakeFlow:
        @classmethod
        def from_client_config(cls, cfg, scopes):
            seen["cfg"], seen["scopes"] = cfg, scopes
            return cls()

        def run_local_server(self, **kw):
            return None                                  # user closed the browser

    import google_auth_oauthlib.flow as f
    monkeypatch.setattr(f, "InstalledAppFlow", FakeFlow)
    with pytest.raises(gdrive.GDriveError):
        gdrive.GoogleDrive().sign_in()
    assert seen["cfg"]["installed"]["client_id"] == CID and gdrive.SCOPES == seen["scopes"]


class FakeDrive:
    def __init__(self):
        self.client, self.signed, self.calls = False, False, 0

    def has_client(self):
        return self.client or gdrive.client_config() is not None

    def signed_in(self):
        return self.signed

    def sign_in(self):
        self.calls += 1
        self.signed = True

    def sign_out(self):
        self.signed = False

    def email(self):
        return "me@example.com"


def _dialog(monkeypatch, store):
    from phraseforge.ui import settings_dialog as sd
    monkeypatch.setattr(sd, "_run_with_wait", lambda _p, _t, fn: (True, fn()))
    monkeypatch.setattr(sd.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(sd.QMessageBox, "warning", lambda *a, **k: None)
    d = sd.SettingsDialog(store, page="cloud")
    d._gdrive_obj = FakeDrive()
    d._update_cloud_ui()
    return sd, d


def test_button_enabled_without_client_and_with_sync_off(app, home, monkeypatch):
    """The reported bug: the button was greyed out (no client file / provider "off")."""
    s = Store(":memory:")
    s.set_setting("sync.provider", "off")
    sd, d = _dialog(monkeypatch, s)
    assert d.gdrive_box.isEnabled() and d.gdrive_signin_btn.isEnabled()
    assert d.gdrive_signin_btn.text() == "Sign in with Google"


def test_click_without_client_opens_setup_then_signs_in(app, home, monkeypatch):
    s = Store(":memory:")
    s.set_setting("sync.provider", "off")
    sd, d = _dialog(monkeypatch, s)
    shown = []

    def fake_exec(dlg):
        shown.append(dlg)
        dlg.client_id.setText(CID)
        dlg.client_secret.setText("GOCSPX-x")
        dlg.accept()
        return dlg.result()
    monkeypatch.setattr(sd.GoogleClientDialog, "exec", fake_exec)
    d.gdrive_signin_btn.click()
    assert len(shown) == 1 and gdrive.client_source() == "own"
    assert d._gdrive_obj.calls == 1 and d.cloud_radios["gdrive"].isChecked()
    assert d.gdrive_signin_btn.text() == "Sign out"


def test_cancelled_setup_does_not_sign_in(app, home, monkeypatch):
    sd, d = _dialog(monkeypatch, Store(":memory:"))
    monkeypatch.setattr(sd.GoogleClientDialog, "exec", lambda dlg: QDialog.Rejected)
    d.gdrive_signin_btn.click()
    assert d._gdrive_obj.calls == 0 and not d.cloud_radios["gdrive"].isChecked()


def test_with_builtin_client_signs_in_directly(app, home, monkeypatch):
    (home / "builtin.json").write_text(json.dumps(gdrive.client_json(CID, "s")))
    sd, d = _dialog(monkeypatch, Store(":memory:"))
    monkeypatch.setattr(sd.GoogleClientDialog, "exec", lambda dlg: pytest.fail("setup must not open"))
    d.gdrive_signin_btn.click()
    assert d._gdrive_obj.calls == 1 and d.cloud_radios["gdrive"].isChecked()


def test_setup_dialog_shows_errors(app, home):
    from phraseforge.ui.settings_dialog import GoogleClientDialog
    dlg = GoogleClientDialog()
    dlg.client_id.setText("wrong")
    dlg.client_secret.setText("x")
    dlg.accept()
    assert dlg.result() != QDialog.Accepted and "googleusercontent" in dlg.error.text()


def test_own_client_stored_encrypted(home):
    gdrive.install_client_values(CID, "GOCSPX-topsecret")
    raw = gdrive.client_file().read_bytes()
    assert b"GOCSPX-topsecret" not in raw and b"apps.googleusercontent" not in raw
    assert not gdrive.legacy_client_file().exists()


def test_legacy_plain_client_is_sealed_on_first_use(home):
    gdrive.legacy_client_file().write_text(json.dumps(gdrive.client_json(CID, "GOCSPX-old")))
    assert gdrive.client_source() == "own"
    assert gdrive.client_config()["installed"]["client_secret"] == "GOCSPX-old"
    assert not gdrive.legacy_client_file().exists()
    assert b"GOCSPX-old" not in gdrive.client_file().read_bytes()


def test_client_from_another_pc_is_ignored(home):
    gdrive.client_file().write_bytes(b"garbage that DPAPI cannot open")
    assert gdrive.client_config() is None and gdrive.client_source() == ""


def test_builtin_client_with_bom(home):
    (home / "builtin.json").write_bytes(b"\xef\xbb\xbf" + json.dumps(gdrive.client_json(CID, "s")).encode())
    assert gdrive.client_source() == "builtin"
