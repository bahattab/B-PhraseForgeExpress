"""Search files window, settings page, hotkey/tray wiring (no real files are opened)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from phraseforge import filesearch
from phraseforge.db import Store


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def index(tmp_path):
    for n in ("Quarterly report.xlsx", "report notes.txt", "Calculator.lnk"):
        (tmp_path / n).write_text("x")
    ix = filesearch.FileIndex([str(tmp_path)], history_file=tmp_path / "h.json")
    ix.build()
    return ix


def _key(w, key, mods=Qt.NoModifier):
    w._handle_key(QKeyEvent(QEvent.KeyPress, key, mods))


def test_window_lists_results_and_opens(app, index, monkeypatch):
    from phraseforge.ui.file_search import FileSearchWindow
    opened, folders = [], []
    monkeypatch.setattr(filesearch, "open_path", opened.append)
    monkeypatch.setattr(filesearch, "open_folder", folders.append)
    w = FileSearchWindow(index)
    w.show_centered()
    w.search.setText("rep")
    w.refresh()
    assert w.list.count() == 2
    assert w.list.item(0).text().startswith("report notes.txt")
    _key(w, Qt.Key_Return)
    assert opened and opened[0].endswith("report notes.txt") and not w.isVisible()
    assert index.search("rep")[0].name == "report notes.txt"
    w.show_centered()
    w.search.setText("quarterly")
    w.refresh()
    _key(w, Qt.Key_Return, Qt.ControlModifier)
    assert folders and folders[0].endswith("Quarterly report.xlsx")


def test_shift_enter_inserts_path_and_ctrl_c_copies(app, index):
    from phraseforge.ui.file_search import FileSearchWindow
    w = FileSearchWindow(index)
    got = []
    w.insert_path.connect(got.append)
    w.show_centered()
    w.search.setText("calc")
    w.refresh()
    _key(w, Qt.Key_Return, Qt.ShiftModifier)
    assert got and got[0].endswith("Calculator.lnk")
    w.show_centered()
    w.search.setText("calc")
    w.refresh()
    _key(w, Qt.Key_C, Qt.ControlModifier)
    assert QApplication.clipboard().text().endswith("Calculator.lnk")


def test_status_shows_count_when_empty(app, index):
    from phraseforge.ui.file_search import FileSearchWindow
    w = FileSearchWindow(index)
    w.show_centered()
    assert "3 items indexed" in w.status.text()


def test_settings_page_round_trip(app):
    from phraseforge.ui.settings_dialog import SettingsDialog, pages
    from phraseforge.ui.settings_schema import SCHEMA
    assert "file_search" in pages()
    assert SCHEMA["filesearch.hotkey"] == "ctrl+alt+f"
    s = Store(":memory:")
    d = SettingsDialog(s, page="file_search")
    d.filesearch_roots.setPlainText("C:\\Work\nD:\\Projects")
    d.filesearch_refresh.setValue(60)
    d.save()
    assert filesearch.parse_roots(s.setting("filesearch.roots")) == ["C:\\Work", "D:\\Projects"]
    assert s.setting("filesearch.refresh_minutes") == "60"


def test_hotkey_and_tray_are_wired():
    from phraseforge.triggers.manager import COMMAND_HOTKEY_SETTINGS
    from phraseforge.ui.tray import Tray
    assert COMMAND_HOTKEY_SETTINGS["filesearch.hotkey"] == "file_search"
    assert hasattr(Tray, "file_search")


def test_web_keyword_row_opens_url(app, index, monkeypatch):
    from phraseforge.ui.file_search import FileSearchWindow
    opened = []
    monkeypatch.setattr(filesearch, "open_path", opened.append)
    w = FileSearchWindow(index)
    w.show_centered()
    w.search.setText("g quarterly report")
    w.refresh()
    assert "Search the web" in w.list.item(0).text()
    _key(w, Qt.Key_Return)
    assert opened == ["https://www.google.com/search?q=quarterly+report"]


def test_settings_page_has_double_ctrl_and_keywords(app):
    from phraseforge.ui.settings_dialog import SettingsDialog
    s = Store(":memory:")
    d = SettingsDialog(s, page="file_search")
    d.filesearch_web.setPlainText("gh=https://github.com/search?q={q}")
    d.save()
    assert filesearch.parse_web_keywords(s.setting("filesearch.web_keywords")) == {
        "gh": "https://github.com/search?q={q}"}
    assert s.setting("filesearch.double_ctrl") == "1"
