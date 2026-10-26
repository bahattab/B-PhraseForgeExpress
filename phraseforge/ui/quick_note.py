"""Quick note window (like OneNote's "New Quick Note" from the tray tool ONENOTEM.EXE).

A small always-on-top note. Ctrl+Enter sends it to OneNote (the default page or
section from Settings > OneNote, or a new page in Quick Notes); Ctrl+S saves it
as a PhraseForge phrase instead. Esc hides the window and keeps the draft.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from phraseforge.ui.i18n import tr
from phraseforge.ui.icons import app_icon


class QuickNoteWindow(QDialog):
    send_to_onenote = Signal(str)   # note text
    save_as_phrase = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Tool | Qt.WindowStaysOnTopHint | Qt.WindowCloseButtonHint)
        self.setWindowTitle(tr("Quick note"))
        self.setWindowIcon(app_icon())
        self.setStyleSheet("QDialog{background:#fff8c5}QPlainTextEdit{background:#fffbe0;border:1px solid #e3d78a}")
        lay = QVBoxLayout(self)
        self.edit = QPlainTextEdit()
        self.edit.setFont(QFont("Segoe UI", 10))
        self.edit.setPlaceholderText(tr("Type a note…"))
        lay.addWidget(self.edit, 1)
        row = QHBoxLayout()
        self.hint = QLabel("Ctrl+Enter OneNote · Ctrl+S phrase · Esc hide")
        self.hint.setStyleSheet("color:#7a6f2b")
        row.addWidget(self.hint, 1)
        self.phrase_button = QPushButton(tr("Save as phrase"))
        self.phrase_button.clicked.connect(lambda: self._emit(self.save_as_phrase))
        self.onenote_button = QPushButton(tr("Send to OneNote"))
        self.onenote_button.setDefault(True)
        self.onenote_button.clicked.connect(lambda: self._emit(self.send_to_onenote))
        row.addWidget(self.phrase_button)
        row.addWidget(self.onenote_button)
        lay.addLayout(row)
        for keys in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(keys), self, activated=lambda: self._emit(self.send_to_onenote))
        QShortcut(QKeySequence("Ctrl+S"), self, activated=lambda: self._emit(self.save_as_phrase))
        self.resize(360, 260)

    def _emit(self, signal) -> None:
        text = self.edit.toPlainText()
        if not text.strip():
            return
        signal.emit(text)
        self.edit.clear()
        self.hide()

    def show_note(self) -> None:
        if not self.isVisible():
            g = QGuiApplication.primaryScreen().availableGeometry()
            self.move(g.right() - self.width() - 24, g.bottom() - self.height() - 24)
        self.show()
        self.raise_()
        self.activateWindow()
        self.edit.setFocus()
