"""Quick note window (ONENOTEM-style 'New Quick Note')."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_send_and_save_emit_text_then_clear(app):
    from phraseforge.ui.quick_note import QuickNoteWindow
    w = QuickNoteWindow()
    sent, saved = [], []
    w.send_to_onenote.connect(sent.append)
    w.save_as_phrase.connect(saved.append)
    w.show_note()
    w.edit.setPlainText("Call Ahmed\nabout the report")
    w.onenote_button.click()
    assert sent == ["Call Ahmed\nabout the report"] and w.edit.toPlainText() == "" and not w.isVisible()
    w.show_note()
    w.edit.setPlainText("   ")
    w.phrase_button.click()
    assert saved == []                       # empty notes are ignored
    w.edit.setPlainText("Address: Riyadh")
    w.phrase_button.click()
    assert saved == ["Address: Riyadh"]


def test_wiring():
    from phraseforge.triggers.manager import COMMAND_HOTKEY_SETTINGS
    from phraseforge.ui.settings_schema import SCHEMA
    from phraseforge.ui.tray import Tray
    assert COMMAND_HOTKEY_SETTINGS["onenote.quick_note_hotkey"] == "quick_note"
    assert "onenote.quick_note_hotkey" in SCHEMA and hasattr(Tray, "quick_note")
