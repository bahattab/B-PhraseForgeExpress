"""Portable mode: everything next to the program, nothing in %APPDATA% or the registry (G-09)."""
import os
import sys
from pathlib import Path

import pytest

from phraseforge import autostart, io_formats, paths, signatures


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    monkeypatch.delenv("PHRASEFORGE_HOME", raising=False)
    monkeypatch.delenv("PHRASEFORGE_PORTABLE", raising=False)
    appdata = tmp_path / "appdata"
    appdata.mkdir()
    monkeypatch.setenv("APPDATA", str(appdata))
    app = tmp_path / "stick" / "PhraseForge"
    app.mkdir(parents=True)
    monkeypatch.setattr(paths, "app_dir", lambda: app)
    return appdata, app


def test_where_the_data_goes(clean_env, monkeypatch, tmp_path):
    appdata, app = clean_env
    assert paths.data_dir() == appdata / "PhraseForge" and not paths.is_portable()
    (app / "portable.ini").write_text("")
    assert paths.is_portable() and paths.data_dir() == app / "PhraseForgeData"
    monkeypatch.setenv("PHRASEFORGE_PORTABLE", "0")
    assert not paths.is_portable()
    monkeypatch.setenv("PHRASEFORGE_HOME", str(tmp_path / "custom"))
    monkeypatch.delenv("PHRASEFORGE_PORTABLE")
    assert paths.data_dir() == tmp_path / "custom" and not paths.is_portable()


def test_the_portable_exe_is_portable_by_its_name(clean_env, monkeypatch):
    _appdata, app = clean_env
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app / "B-PhraseForgeExpress-portable.exe"))
    assert paths.is_portable()
    monkeypatch.setattr(sys, "executable", str(app / "B-PhraseForgeExpress.exe"))
    assert not paths.is_portable()


def test_command_line_switches(clean_env, tmp_path):
    rest = paths.apply_command_line(["pf", "--portable", "--minimized"])
    assert rest == ["pf", "--minimized"] and paths.is_portable()
    rest = paths.apply_command_line(["pf", "--home", str(tmp_path / "h")])
    assert rest == ["pf"] and paths.data_dir() == tmp_path / "h" and not paths.is_portable()
    paths.apply_command_line(["pf", f"--home={tmp_path / 'h2'}"])
    assert paths.data_dir() == tmp_path / "h2"


def test_registry_and_profile_features_are_refused(clean_env, monkeypatch):
    monkeypatch.setenv("PHRASEFORGE_PORTABLE", "1")
    with pytest.raises(paths.PortableRefused, match="portable"):
        autostart.set_enabled(True)
    assert autostart.is_enabled() is False
    from phraseforge.db import Store
    from phraseforge.models import Phrase
    s = Store(paths.db_path())
    with pytest.raises(paths.PortableRefused):
        signatures.export_outlook(s, lambda c, f: c)                  # into Outlook's folder in %APPDATA%
    with pytest.raises(paths.PortableRefused):
        signatures.set_outlook_default("Main")
    s.close()


def test_nothing_is_written_to_appdata(clean_env, monkeypatch):
    appdata, app = clean_env
    monkeypatch.setenv("PHRASEFORGE_PORTABLE", "1")
    from phraseforge import spell
    from phraseforge.db import Store
    from phraseforge.models import Folder, Phrase
    s = Store(paths.db_path())
    f = s.add_folder(Folder("F"))
    s.add_phrase(Phrase("P", "p", folder_id=f.id))
    s.set_setting("ui.theme", "dark")
    io_formats.backup(s)
    spell.dictionaries_dir()
    s.close()
    assert list(appdata.iterdir()) == []                         # %APPDATA% untouched
    assert (app / "PhraseForgeData" / "phrases.db").is_file()
    assert any((app / "PhraseForgeData" / "backups").iterdir())


def test_the_settings_window_switches_off_start_with_windows(clean_env, monkeypatch):
    monkeypatch.setenv("PHRASEFORGE_PORTABLE", "1")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from phraseforge.db import Store
    from phraseforge.ui.settings_dialog import SettingsDialog
    s = Store(":memory:")
    d = SettingsDialog(s)
    assert not d.start_with_windows.isEnabled()
    d.deleteLater()
