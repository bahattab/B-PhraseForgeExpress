"""PhraseExpress-style hotkey picker: [Shift][Ctrl][Alt][Win] toggles + key list + clear (X).

value() / set_value() use PhraseForge's hotkey text, e.g. "ctrl+alt+c"; "" = none.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QToolButton, QWidget

from phraseforge.ui.iconset import icon

MODIFIERS = ("shift", "ctrl", "alt", "win")
KEYS = (["None"] + [chr(c) for c in range(ord("A"), ord("Z") + 1)] + [str(d) for d in range(10)]
        + [f"F{n}" for n in range(1, 25)]
        + ["Space", "Enter", "Tab", "Esc", "Backspace", "Insert", "Delete", "Home", "End",
           "PageUp", "PageDown", "Left", "Right", "Up", "Down", "Pause", "PrintScreen",
           "NumPad0", "NumPad1", "NumPad2", "NumPad3", "NumPad4", "NumPad5", "NumPad6", "NumPad7",
           "NumPad8", "NumPad9", "Multiply", "Add", "Subtract", "Decimal", "Divide",
           ";", "=", ",", "-", ".", "/", "`", "[", "\\", "]", "'"])


class HotkeyPicker(QWidget):
    changed = Signal(str)

    def __init__(self, value: str = "", clearable: bool = True, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.mod_buttons: dict[str, QPushButton] = {}
        for m in MODIFIERS:
            b = QPushButton(m.capitalize())
            b.setObjectName("ModifierButton")
            b.setCheckable(True)
            b.toggled.connect(self._emit)
            lay.addWidget(b)
            self.mod_buttons[m] = b
        self.key = QComboBox()
        self.key.setEditable(False)
        self.key.addItems(KEYS)
        self.key.setMinimumWidth(92)
        self.key.currentIndexChanged.connect(self._emit)
        lay.addWidget(self.key)
        self.clear_button = QToolButton()
        self.clear_button.setIcon(icon("remove"))
        self.clear_button.setAutoRaise(True)
        self.clear_button.setToolTip("Remove hotkey")
        self.clear_button.clicked.connect(lambda: self.set_value(""))
        self.clear_button.setVisible(clearable)
        lay.addWidget(self.clear_button)
        lay.addStretch(1)
        self._loading = False
        self.set_value(value)

    def value(self) -> str:
        key = self.key.currentText()
        if key == "None":
            return ""
        mods = [m for m in MODIFIERS if self.mod_buttons[m].isChecked()]
        return "+".join(mods + [key.lower()])

    def set_value(self, value: str) -> None:
        self._loading = True
        parts = [p for p in (value or "").lower().split("+") if p]
        key = parts[-1] if parts else ""
        for m in MODIFIERS:
            self.mod_buttons[m].setChecked(m in parts[:-1] or (m == "ctrl" and "control" in parts[:-1]))
        idx = 0
        for i, k in enumerate(KEYS):
            if k.lower() == key:
                idx = i
                break
        self.key.setCurrentIndex(idx)
        self._loading = False
        self._emit()

    def _emit(self, *_):
        if not self._loading:
            self.changed.emit(self.value())
