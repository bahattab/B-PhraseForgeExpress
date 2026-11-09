"""Trash, phrase templates and phrase comments (PRD G-18: FR-DAT-02, -03, -04)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from phraseforge.ui.i18n import tr


def _when(iso: str | None) -> str:
    return (iso or "").replace("T", " ")[:16]


class TrashDialog(QDialog):
    """Deleted phrases and folders: put them back or delete them for good."""

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.restored: list[tuple[str, int]] = []
        self.setWindowTitle(tr("Trash"))
        self.resize(640, 420)
        lay = QVBoxLayout(self)
        days = store.setting("trash.days", str(store.TRASH_DAYS)) or str(store.TRASH_DAYS)
        note = QLabel(tr("Deleted phrases and folders stay here for {n} days. The trash belongs to this "
                         "PC and is not synced.").format(n=days))
        note.setWordWrap(True)
        lay.addWidget(note)
        self.list = QTreeWidget()
        self.list.setHeaderLabels([tr("Name"), tr("Type"), tr("Was in"), tr("Deleted")])
        self.list.setRootIsDecorated(False)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.itemDoubleClicked.connect(lambda *_: self.restore())
        lay.addWidget(self.list)
        row = QHBoxLayout()
        self.restore_button = QPushButton(tr("Restore"))
        self.restore_button.clicked.connect(self.restore)
        self.delete_button = QPushButton(tr("Delete for good"))
        self.delete_button.clicked.connect(self.delete)
        self.empty_button = QPushButton(tr("Empty trash"))
        self.empty_button.clicked.connect(self.empty)
        for b in (self.restore_button, self.delete_button, self.empty_button):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)
        self.load()

    def load(self) -> None:
        self.list.clear()
        for r in self.store.trash_items():
            kind = tr("Phrase") if r["kind"] == "phrase" else tr("Folder ({n} phrases)").format(n=r["count"])
            it = QTreeWidgetItem([r["name"] or "", kind, r["parent_name"] or tr("(top level)"), _when(r["deleted_at"])])
            it.setData(0, Qt.UserRole, r["id"])
            self.list.addTopLevelItem(it)
        for i in range(4):
            self.list.resizeColumnToContents(i)
        empty = self.list.topLevelItemCount() == 0
        for b in (self.restore_button, self.delete_button, self.empty_button):
            b.setEnabled(not empty)

    def _selected(self) -> list[int]:
        return [it.data(0, Qt.UserRole) for it in self.list.selectedItems()]

    def restore(self) -> None:
        for tid in self._selected():
            try:
                self.restored.append(self.store.restore_trash(tid))
            except Exception as e:
                QMessageBox.warning(self, self.windowTitle(), str(e))
        self.load()

    def delete(self) -> None:
        ids = self._selected()
        if ids and QMessageBox.question(self, self.windowTitle(),
                                        tr("Delete the selected items for good?")) == QMessageBox.Yes:
            for tid in ids:
                self.store.delete_trash(tid)
            self.load()

    def empty(self) -> None:
        if QMessageBox.question(self, self.windowTitle(), tr("Empty the trash? This cannot be undone.")) \
                == QMessageBox.Yes:
            self.store.delete_trash()
            self.load()


class TemplatePicker(QDialog):
    """Choose a phrase from the template folders."""

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.chosen: int | None = None
        self.setWindowTitle(tr("New phrase from template"))
        self.resize(520, 380)
        lay = QVBoxLayout(self)
        self.templates = store.template_phrases()
        if not self.templates:
            msg = QLabel(tr("There are no templates yet. Right-click a folder and choose \"Template folder\": "
                            "its phrases become templates (they are not expanded and not in the phrase menu)."))
            msg.setWordWrap(True)
            lay.addWidget(msg)
        self.list = QListWidget()
        for p in self.templates:
            it = QListWidgetItem(p.description)
            it.setData(Qt.UserRole, p.id)
            it.setToolTip(p.content[:300])
            self.list.addItem(it)
        self.list.itemDoubleClicked.connect(lambda *_: self.accept())
        self.list.currentItemChanged.connect(self._preview)
        lay.addWidget(self.list)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(110)
        lay.addWidget(self.preview)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.ok = bb.button(QDialogButtonBox.Ok)
        self.ok.setEnabled(bool(self.templates))
        lay.addWidget(bb)
        if self.templates:
            self.list.setCurrentRow(0)

    def _preview(self, it, _prev=None) -> None:
        p = self.store.get_phrase(it.data(Qt.UserRole)) if it else None
        self.preview.setPlainText(p.content if p else "")

    def accept(self) -> None:
        it = self.list.currentItem()
        if it is None:
            return
        self.chosen = it.data(Qt.UserRole)
        super().accept()


class CommentsDialog(QDialog):
    """Comments on one phrase: who wrote what and when; resolve or delete them."""

    def __init__(self, store, phrase_id: int, parent=None):
        super().__init__(parent)
        self.store, self.phrase_id = store, phrase_id
        p = store.get_phrase(phrase_id)
        self.setWindowTitle(tr("Comments") + (f" – {p.description}" if p else ""))
        self.resize(560, 440)
        lay = QVBoxLayout(self)
        self.show_resolved = QCheckBox(tr("Show resolved comments"))
        self.show_resolved.toggled.connect(self.load)
        lay.addWidget(self.show_resolved)
        self.list = QTreeWidget()
        self.list.setHeaderLabels([tr("Comment"), tr("By"), tr("When")])
        self.list.setRootIsDecorated(False)
        self.list.setWordWrap(True)
        lay.addWidget(self.list)
        row = QHBoxLayout()
        self.resolve_button = QPushButton(tr("Resolve"))
        self.resolve_button.clicked.connect(self.resolve)
        self.delete_button = QPushButton(tr("Delete"))
        self.delete_button.clicked.connect(self.delete)
        row.addWidget(self.resolve_button)
        row.addWidget(self.delete_button)
        row.addStretch(1)
        lay.addLayout(row)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText(tr("Write a comment..."))
        self.text.setMaximumHeight(90)
        lay.addWidget(self.text)
        add = QPushButton(tr("Add comment"))
        add.clicked.connect(self.add)
        lay.addWidget(add, alignment=Qt.AlignRight)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.load()

    def load(self) -> None:
        self.list.clear()
        for c in self.store.comments(self.phrase_id):
            if c["resolved"] and not self.show_resolved.isChecked():
                continue
            text = c["text"] + ("  ✓" if c["resolved"] else "")
            it = QTreeWidgetItem([text, c["author"] or "", _when(c["created"])])
            it.setData(0, Qt.UserRole, c["id"])
            it.setData(1, Qt.UserRole, c["resolved"])
            it.setToolTip(0, c["text"])
            self.list.addTopLevelItem(it)
        self.list.resizeColumnToContents(1)
        self.list.resizeColumnToContents(2)

    def _current(self):
        it = self.list.currentItem()
        return (it.data(0, Qt.UserRole), it.data(1, Qt.UserRole)) if it else (None, None)

    def add(self) -> None:
        text = self.text.toPlainText().strip()
        if not text:
            return
        try:
            self.store.add_comment(self.phrase_id, text)
        except Exception as e:
            QMessageBox.warning(self, self.windowTitle(), str(e))
            return
        self.text.clear()
        self.load()

    def resolve(self) -> None:
        cid, resolved = self._current()
        if cid is not None:
            self.store.resolve_comment(cid, not resolved)
            self.load()

    def delete(self) -> None:
        cid, _ = self._current()
        if cid is not None and QMessageBox.question(self, self.windowTitle(),
                                                    tr("Delete this comment?")) == QMessageBox.Yes:
            self.store.delete_comment(cid)
            self.load()
