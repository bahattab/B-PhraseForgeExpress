"""Learned suggestions: text typed often -> offer to make it a phrase."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
)

from phraseforge.db import Store
from phraseforge.models import Folder, Phrase, Trigger, TriggerKind
from phraseforge.ui.i18n import tr
from phraseforge.ui.icons import app_icon


class SuggestionsDialog(QDialog):
    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle(tr("Suggestions"))
        self.setWindowIcon(app_icon())
        self.resize(520, 420)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("You typed these often. Turn them into phrases?"))
        self.list = QListWidget()
        lay.addWidget(self.list)
        row = QHBoxLayout()
        b1 = QPushButton(tr("Create phrase"))
        b1.setObjectName("primary")
        b1.clicked.connect(self._create)
        b2 = QPushButton(tr("Dismiss"))
        b2.clicked.connect(self._dismiss)
        row.addWidget(b1)
        row.addWidget(b2)
        row.addStretch()
        lay.addLayout(row)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        mc = int(self.store.setting("learning.min_count", "3") or 3)
        for s in self.store.suggestions(mc):
            it = QListWidgetItem(f"{s['count']}×  {s['text']}")
            it.setData(Qt.UserRole, s["text"])
            self.list.addItem(it)

    def _target_folder(self) -> int:
        for f in self.store.folders(None):
            if f.name == "Learned":
                return f.id
        return self.store.add_folder(Folder("Learned")).id

    def create_phrase(self, text: str, abbreviation: str) -> Phrase:
        trig = [Trigger(TriggerKind.AUTOTEXT, abbreviation)] if abbreviation else []
        p = self.store.add_phrase(Phrase(text[:60], text, folder_id=self._target_folder(), triggers=trig))
        self.store.dismiss_suggestion(text)
        return p

    def _create(self) -> None:
        it = self.list.currentItem()
        if not it:
            return
        abbr, ok = QInputDialog.getText(self, tr("Create phrase"), "Abbreviation (optional):")
        if not ok:
            return
        self.create_phrase(it.data(Qt.UserRole), abbr.strip())
        self.refresh()

    def _dismiss(self) -> None:
        it = self.list.currentItem()
        if it:
            self.store.dismiss_suggestion(it.data(Qt.UserRole))
            self.refresh()
