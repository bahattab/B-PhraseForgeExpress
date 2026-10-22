"""Reusable widgets: hotkey recorder, tag editor."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QLineEdit

_NAMED = {
    Qt.Key_Space: "space", Qt.Key_Return: "enter", Qt.Key_Enter: "enter", Qt.Key_Tab: "tab",
    Qt.Key_Escape: "esc", Qt.Key_Backspace: "backspace", Qt.Key_Delete: "delete", Qt.Key_Insert: "insert",
    Qt.Key_Home: "home", Qt.Key_End: "end", Qt.Key_PageUp: "pageup", Qt.Key_PageDown: "pagedown",
    Qt.Key_Left: "left", Qt.Key_Right: "right", Qt.Key_Up: "up", Qt.Key_Down: "down",
    Qt.Key_Print: "printscreen", Qt.Key_Pause: "pause",
}
_MODIFIER_KEYS = {Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr}


def chord_from_event(e: QKeyEvent) -> str | None:
    """Return 'ctrl+alt+k' style chord, or None if only modifiers pressed."""
    key = e.key()
    if key in _MODIFIER_KEYS or key == Qt.Key_unknown:
        return None
    mods = e.modifiers()
    parts = []
    if mods & Qt.ControlModifier:
        parts.append("ctrl")
    if mods & Qt.AltModifier:
        parts.append("alt")
    if mods & Qt.ShiftModifier:
        parts.append("shift")
    if mods & Qt.MetaModifier:
        parts.append("win")
    if key in _NAMED:
        name = _NAMED[key]
    elif Qt.Key_F1 <= key <= Qt.Key_F24:
        name = f"f{key - Qt.Key_F1 + 1}"
    elif Qt.Key_A <= key <= Qt.Key_Z or Qt.Key_0 <= key <= Qt.Key_9:
        name = chr(key).lower()
    else:
        t = e.text()
        if not t or not t.isprintable():
            return None
        name = t.lower()
    parts.append(name)
    return "+".join(parts)


class HotkeyEdit(QLineEdit):
    """Click, then press a key combination. Backspace/Delete alone clears."""
    chord_changed = Signal(str)

    def __init__(self, value: str = "", parent=None):
        super().__init__(value, parent)
        self.setPlaceholderText("Press a key combination…")
        self.setReadOnly(True)

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        if e.key() in (Qt.Key_Backspace, Qt.Key_Delete) and not e.modifiers():
            self.setText("")
            self.chord_changed.emit("")
            return
        chord = chord_from_event(e)
        if chord:
            self.setText(chord)
            self.chord_changed.emit(chord)

    def chord(self) -> str:
        return self.text().strip()


class TagEdit(QLineEdit):
    """Comma separated tags."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("tag1, tag2")

    def tags(self) -> list[str]:
        return [t.strip() for t in self.text().split(",") if t.strip()]

    def set_tags(self, tags: list[str]) -> None:
        self.setText(", ".join(tags))
