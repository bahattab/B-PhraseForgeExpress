"""Google Drive for desktop folder detection and the Settings > Backup & Sync folder box."""
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from phraseforge.cloud.drive_folder import find_google_drive_folders, sync_folder_in
from phraseforge.db import Store

NO_LABEL = lambda root: ""  # noqa: E731


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_streaming_drive_with_my_drive(tmp_path):
    g = tmp_path / "G"
    (g / "My Drive").mkdir(parents=True)
    (tmp_path / "C").mkdir()
    found = find_google_drive_folders([tmp_path / "C", g], home=tmp_path / "home", label=NO_LABEL)
    assert found == [g / "My Drive"]
    assert sync_folder_in(found[0]) == g / "My Drive" / "PhraseForge"


def test_translated_my_drive_found_by_volume_label(tmp_path):
    g = tmp_path / "G"
    for name in ("ملفاتي", "Shared drives", ".shortcut-targets-by-id"):
        (g / name).mkdir(parents=True)
    found = find_google_drive_folders([g], home=tmp_path / "home",
                                      label=lambda r: "Google Drive" if r == str(g) else "")
    assert found == [g / "ملفاتي"]


def test_other_drive_without_label_is_ignored(tmp_path):
    d = tmp_path / "D"
    (d / "Projects").mkdir(parents=True)
    assert find_google_drive_folders([d], home=tmp_path / "home", label=NO_LABEL) == []


def test_mirrored_folder_in_profile(tmp_path):
    home = tmp_path / "home"
    (home / "My Drive").mkdir(parents=True)
    assert find_google_drive_folders([], home=home, label=NO_LABEL) == [home / "My Drive"]


def test_unreadable_drive_is_skipped(tmp_path):
    missing = tmp_path / "Z"                      # like an empty card reader
    assert find_google_drive_folders([missing], home=tmp_path / "home", label=NO_LABEL) == []


def _dialog(monkeypatch, store):
    from phraseforge.ui import settings_dialog as sd
    monkeypatch.setattr(sd.QMessageBox, "information", lambda *a, **k: None)
    d = sd.SettingsDialog(store, page="cloud")
    return sd, d


def test_folder_box_usable_while_sync_is_off(app, monkeypatch):
    """The reported bug: the folder box was greyed out unless "A folder" was chosen first."""
    s = Store(":memory:")
    s.set_setting("sync.provider", "off")
    sd, d = _dialog(monkeypatch, s)
    assert d.folder_box.isEnabled() and d.sync_folder.isEnabled()


def test_typing_a_folder_selects_folder_sync(app, monkeypatch):
    s = Store(":memory:")
    s.set_setting("sync.provider", "off")
    sd, d = _dialog(monkeypatch, s)
    d.sync_folder.textEdited.emit(r"G:\My Drive\PhraseForge")
    assert d.cloud_radios["folder"].isChecked()


def test_find_google_drive_fills_folder(app, monkeypatch, tmp_path):
    from phraseforge.cloud import drive_folder
    s = Store(":memory:")
    s.set_setting("sync.provider", "off")
    sd, d = _dialog(monkeypatch, s)
    monkeypatch.setattr(drive_folder, "find_google_drive_folders", lambda: [tmp_path / "My Drive"])
    d._find_gdrive_folder()
    assert d.sync_folder.text() == str(tmp_path / "My Drive" / "PhraseForge")
    assert d.cloud_radios["folder"].isChecked()
    d.save()
    assert s.setting("sync.provider") == "folder"
    assert s.setting("sync.folder_path") == str(tmp_path / "My Drive" / "PhraseForge")


def test_find_google_drive_asks_when_several(app, monkeypatch, tmp_path):
    from phraseforge.cloud import drive_folder
    sd, d = _dialog(monkeypatch, Store(":memory:"))
    a, b = tmp_path / "G" / "My Drive", tmp_path / "home" / "My Drive"
    monkeypatch.setattr(drive_folder, "find_google_drive_folders", lambda: [a, b])
    monkeypatch.setattr(sd.QInputDialog, "getItem", lambda *args, **k: (str(b), True))
    d._find_gdrive_folder()
    assert d.sync_folder.text() == str(b / "PhraseForge")


def test_find_google_drive_not_installed_changes_nothing(app, monkeypatch):
    from phraseforge.cloud import drive_folder
    s = Store(":memory:")
    s.set_setting("sync.provider", "off")
    sd, d = _dialog(monkeypatch, s)
    shown = []
    monkeypatch.setattr(sd.QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    monkeypatch.setattr(drive_folder, "find_google_drive_folders", lambda: [])
    d._find_gdrive_folder()
    assert shown and "not found" in shown[0]
    assert d.sync_folder.text() == "" and d.cloud_radios["off"].isChecked()
