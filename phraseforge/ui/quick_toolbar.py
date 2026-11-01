"""Customizable quick toolbar (the small bar under the ribbon), like Office's Quick Access Toolbar.

The user chooses which commands it shows and their order: the ▾ menu at its end shows or hides
a command, right-clicking a button moves it left/right or removes it, right-clicking a button
in the Tools tab adds it, and "Customize toolbar..." opens QuickToolbarDialog. The keys are kept
in the setting "ui.quick_toolbar" as a JSON list.
"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QGridLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout,
)

from phraseforge.ui.i18n import tr
from phraseforge.ui.iconset import icon

SETTING = "ui.quick_toolbar"
DEFAULT = ["back", "forward", "sync", "new_folder", "new_phrase", "columns"]
# Commands of the window itself (key, label, icon); the Tools tab items are added after these.
BUILTIN = (("back", "Back", "back"), ("forward", "Forward", "forward"),
           ("sync", "Send/Receive updates (Ctrl+F5)", "sync"), ("new_folder", "New Folder (Ctrl+O)", "new_folder"),
           ("new_phrase", "New Phrase (Ctrl+N)", "new_phrase"),
           ("columns", "Toggle two/three columns", "column_toggle"))


def load(store, known: set[str]) -> list[str]:
    """The keys to show, in order (unknown or repeated keys dropped)."""
    raw = store.setting(SETTING, "")
    try:
        keys = json.loads(raw) if raw else list(DEFAULT)
        if not isinstance(keys, list):
            raise ValueError
    except ValueError:
        keys = list(DEFAULT)
    out: list[str] = []
    for k in keys:
        if isinstance(k, str) and k in known and k not in out:
            out.append(k)
    return out


def save(store, keys: list[str]) -> None:
    store.set_setting(SETTING, json.dumps(list(keys)))


def moved(keys: list[str], key: str, step: int) -> list[str]:
    """keys with key moved step places (−1 = earlier, +1 = later); unchanged at the ends."""
    keys = list(keys)
    if key not in keys:
        return keys
    i = keys.index(key)
    j = i + step
    if 0 <= j < len(keys):
        keys[i], keys[j] = keys[j], keys[i]
    return keys


def visual_step(direction: str, rtl: bool) -> int:
    """"left"/"right" on screen -> list step. In a right-to-left layout the first item is on the right."""
    step = -1 if direction == "left" else 1
    return -step if rtl else step


class QuickToolbarDialog(QDialog):
    """Two lists: available commands and the toolbar's commands, with Add / Remove / Move / Reset."""

    def __init__(self, catalog: list[tuple[str, str, str]], shown: list[str], parent=None, rtl: bool = False):
        super().__init__(parent)
        self.setWindowTitle(tr("Customize toolbar"))
        self.resize(560, 420)
        self.catalog = {k: (label, ic) for k, label, ic in catalog}
        self.order = [k for k, _, _ in catalog]
        self.rtl = rtl
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("Choose the buttons of the toolbar and their order "
                                "(the first one is shown at the start of the bar).")))
        grid = QGridLayout()
        grid.addWidget(QLabel(tr("Available commands:")), 0, 0)
        grid.addWidget(QLabel(tr("Shown on the toolbar:")), 0, 2)
        self.available = QListWidget()
        self.shown = QListWidget()
        for w in (self.available, self.shown):
            w.setSelectionMode(QListWidget.SingleSelection)
        self.available.itemDoubleClicked.connect(lambda _i: self.add())
        self.shown.itemDoubleClicked.connect(lambda _i: self.remove())
        grid.addWidget(self.available, 1, 0)
        grid.addWidget(self.shown, 1, 2)
        mid = QVBoxLayout()
        self.add_btn = QPushButton(tr("Add >>"))
        self.remove_btn = QPushButton(tr("<< Remove"))
        self.left_btn = QPushButton(tr("Move left"))
        self.right_btn = QPushButton(tr("Move right"))
        self.reset_btn = QPushButton(tr("Reset"))
        self.add_btn.clicked.connect(self.add)
        self.remove_btn.clicked.connect(self.remove)
        self.left_btn.clicked.connect(lambda: self.move("left"))
        self.right_btn.clicked.connect(lambda: self.move("right"))
        self.reset_btn.clicked.connect(lambda: self._fill(list(DEFAULT)))
        mid.addStretch(1)
        for b in (self.add_btn, self.remove_btn, self.left_btn, self.right_btn, self.reset_btn):
            mid.addWidget(b)
        mid.addStretch(1)
        grid.addLayout(mid, 1, 1)
        lay.addLayout(grid, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._fill([k for k in shown if k in self.catalog])

    def _item(self, key: str) -> QListWidgetItem:
        label, ic = self.catalog[key]
        it = QListWidgetItem(icon(ic), tr(label))
        it.setData(Qt.UserRole, key)
        return it

    def _fill(self, shown: list[str], select: str | None = None) -> None:
        self.available.clear()
        self.shown.clear()
        for k in self.order:
            if k not in shown:
                self.available.addItem(self._item(k))
        for k in shown:
            it = self._item(k)
            self.shown.addItem(it)
            if k == select:
                self.shown.setCurrentItem(it)

    def keys(self) -> list[str]:
        return [self.shown.item(i).data(Qt.UserRole) for i in range(self.shown.count())]

    def add(self) -> None:
        it = self.available.currentItem()
        if it is not None:
            key = it.data(Qt.UserRole)
            self._fill(self.keys() + [key], select=key)

    def remove(self) -> None:
        it = self.shown.currentItem()
        if it is not None:
            key = it.data(Qt.UserRole)
            self._fill([k for k in self.keys() if k != key])

    def move(self, direction: str) -> None:
        it = self.shown.currentItem()
        if it is not None:
            key = it.data(Qt.UserRole)
            self._fill(moved(self.keys(), key, visual_step(direction, self.rtl)), select=key)
