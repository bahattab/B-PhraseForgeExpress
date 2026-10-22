"""Clipboard history ("Clipboard Cache") window, styled like the phrase popup."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QToolButton, QVBoxLayout,
)

from phraseforge.db import Store
from phraseforge.ui.i18n import tr
from phraseforge.ui.iconset import icon
from phraseforge.ui.icons import app_icon
from phraseforge.ui.popup import HEADER_H, ROW_H, SELECT, _Band, _Footer

ROLE_ID, ROLE_TEXT, ROLE_PINNED = Qt.UserRole, Qt.UserRole + 1, Qt.UserRole + 2


class ClipboardWindow(QFrame):
    entry_chosen = Signal(str)

    def __init__(self, store: Store, parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.store = store
        self.setWindowTitle(tr("Clipboard history"))
        self.setWindowIcon(app_icon())
        self.setObjectName("PopupPanel")
        self.setStyleSheet("#PopupPanel{background:white;border:1px solid #8c8c8c}")
        self.setFont(QFont("Segoe UI", 9))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(0)
        self.band = _Band(tr("Clipboard Cache"), parent=self)
        self.pin_button = self.band.add_button("pin", "Pin the selected entry")
        self.pin_button.clicked.connect(self._pin)
        self.delete_button = self.band.add_button("delete", "Delete the selected entry")
        self.delete_button.clicked.connect(self._delete)
        close = self.band.add_button("remove", "Close (Esc)")
        close.clicked.connect(self.hide)
        lay.addWidget(self.band)
        row = QHBoxLayout()
        row.setContentsMargins(6, 4, 6, 4)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search") + "…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.search.installEventFilter(self)
        row.addWidget(self.search)
        lay.addLayout(row)
        self.list = QListWidget()
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setMouseTracking(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setStyleSheet(
            "QListWidget{background:white;border:none;outline:0}"
            f"QListWidget::item{{padding:0 8px;border:none}}QListWidget::item:selected{{background:{SELECT.name()};color:#1f1f1f}}")
        self.list.itemEntered.connect(self.list.setCurrentItem)
        self.list.itemActivated.connect(self._choose)
        self.list.itemClicked.connect(self._choose)
        lay.addWidget(self.list, 1)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color:#d6d6d6")
        lay.addWidget(line)
        self.footer = _Footer(tr("Clear clipboard cache"))
        self.footer.clicked.connect(self._clear)
        lay.addWidget(self.footer)
        self.resize(380, 26 * ROW_H // 2 + HEADER_H)
        store.on_change(lambda kind, _id: kind == "clipboard" and self.isVisible() and self.refresh())

    def refresh(self) -> None:
        q = self.search.text().lower()
        self.list.clear()
        for e in self.store.clipboard_entries():
            if q and q not in e.text.lower():
                continue
            one = " ".join(e.text.split())
            it = QListWidgetItem(("📌 " if e.pinned else "") + (one[:120] + ("…" if len(one) > 120 else "")))
            it.setSizeHint(QSize(10, ROW_H))
            it.setData(ROLE_ID, e.id)
            it.setData(ROLE_TEXT, e.text)
            it.setData(ROLE_PINNED, e.pinned)
            it.setToolTip(e.text[:1000] + (f"\n— {e.source_app}" if e.source_app else ""))
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _choose(self, it: QListWidgetItem) -> None:
        if it is None:
            return
        self.hide()
        self.entry_chosen.emit(it.data(ROLE_TEXT))

    def _pin(self) -> None:
        it = self.list.currentItem()
        if it:
            self.store.pin_clipboard(it.data(ROLE_ID), not it.data(ROLE_PINNED))
            self.refresh()

    def _delete(self) -> None:
        it = self.list.currentItem()
        if it:
            self.store.delete_clipboard(it.data(ROLE_ID))
            self.refresh()

    def _clear(self) -> None:
        self.store.clear_clipboard(keep_pinned=True)
        self.refresh()

    def eventFilter(self, obj, e):  # noqa: N802
        if obj is self.search and e.type() == QEvent.KeyPress:
            k = e.key()
            if k in (Qt.Key_Down, Qt.Key_Up, Qt.Key_PageDown, Qt.Key_PageUp):
                self.list.keyPressEvent(e)
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                self._choose(self.list.currentItem())
                return True
            if k == Qt.Key_Escape:
                self.hide()
                return True
        return super().eventFilter(obj, e)

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() == Qt.Key_Escape:
            self.hide()
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter) and self.list.currentItem():
            self._choose(self.list.currentItem())
        else:
            super().keyPressEvent(e)

    def changeEvent(self, e):  # noqa: N802
        if e.type() == QEvent.ActivationChange and self.isVisible() and not self.isActiveWindow():
            self.hide()
        super().changeEvent(e)

    def show_at(self, x: int, y: int) -> None:
        self.search.clear()
        self.refresh()
        scr = QGuiApplication.screenAt(QPoint(x, y)) or QGuiApplication.primaryScreen()
        g = scr.availableGeometry()
        self.move(min(max(g.left(), x), g.right() - self.width()),
                  min(max(g.top(), y), g.bottom() - self.height()))
        self.show()
        self.raise_()
        self.activateWindow()
        self.search.setFocus()
