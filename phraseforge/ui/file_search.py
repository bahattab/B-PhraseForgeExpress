"""Search files window (Listary-style launcher), opened with Ctrl+Alt+F or from the tray.

Keys: type fragments of a name, Up/Down to choose,
  Enter        open the file / start the program
  Ctrl+Enter   open the containing folder with the item selected
  Shift+Enter  type the full path into the program you were in
  Ctrl+C       copy the full path
  Esc          close
"""
from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QFileInfo, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QFileIconProvider, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QVBoxLayout,
)

from phraseforge import filesearch
from phraseforge.ui.i18n import tr
from phraseforge.ui.icons import app_icon
from phraseforge.ui.popup import HEADER_H, ROW_H, SELECT, _Band

ROLE_PATH = Qt.UserRole


class FileSearchWindow(QFrame):
    insert_path = Signal(str)      # Shift+Enter: type this path into the previous program

    def __init__(self, index: filesearch.FileIndex, parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.index = index
        self._icons = QFileIconProvider()
        self.setWindowTitle(tr("Search files"))
        self.setWindowIcon(app_icon())
        self.setObjectName("PopupPanel")
        self.setStyleSheet("#PopupPanel{background:white;border:1px solid #8c8c8c}")
        self.setFont(QFont("Segoe UI", 9))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(0)
        self.band = _Band(tr("Search files"), parent=self)
        self.folder_button = self.band.add_button("folder", "Open containing folder (Ctrl+Enter)")
        self.folder_button.clicked.connect(lambda: self._open(self.list.currentItem(), folder=True))
        self.refresh_button = self.band.add_button("refresh", "Rebuild the file index")
        self.refresh_button.clicked.connect(self.rebuild)
        close = self.band.add_button("remove", "Close (Esc)")
        close.clicked.connect(self.hide)
        lay.addWidget(self.band)
        row = QHBoxLayout()
        row.setContentsMargins(6, 4, 6, 4)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Type part of a file or program name") + "…")
        self.search.setClearButtonEnabled(True)
        self.search.installEventFilter(self)
        row.addWidget(self.search)
        lay.addLayout(row)
        self.list = QListWidget()
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setMouseTracking(True)
        self.list.setIconSize(QSize(16, 16))
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setStyleSheet(
            "QListWidget{background:white;border:none;outline:0}"
            f"QListWidget::item{{padding:0 6px;border:none}}QListWidget::item:selected{{background:{SELECT.name()};color:#1f1f1f}}")
        self.list.itemEntered.connect(self.list.setCurrentItem)
        self.list.itemActivated.connect(lambda it: self._open(it))
        lay.addWidget(self.list, 1)
        self.status = QLabel()
        self.status.setStyleSheet("color:#6b6b6b;padding:2px 8px")
        lay.addWidget(self.status)
        self._timer = QTimer(self, singleShot=True, interval=60)
        self._timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda _t: self._timer.start())
        self.resize(560, 14 * ROW_H + HEADER_H + 40)

    # ------------------------------------------------------------ results
    def refresh(self) -> None:
        q = self.search.text().strip()
        self.list.clear()
        if not q:
            self._show_status()
            return
        hits = self.index.search(q, limit=60)
        for h in hits:
            folder = os.path.dirname(h.path)
            it = QListWidgetItem(f"{h.name}    —  {folder}")
            it.setSizeHint(QSize(10, ROW_H))
            it.setData(ROLE_PATH, h.path)
            it.setToolTip(h.path)
            it.setIcon(self._icons.icon(QFileInfo(h.path)))
            self.list.addItem(it)
        if hits:
            self.list.setCurrentRow(0)
        self._show_status(len(hits))

    def _show_status(self, n: int | None = None) -> None:
        if self.index.building:
            self.status.setText(tr("Indexing files…"))
        elif n is None:
            self.status.setText(tr("{n} items indexed").replace("{n}", f"{len(self.index):,}"))
        else:
            self.status.setText(tr("{n} results").replace("{n}", str(n)) +
                                "   ·   Enter open · Ctrl+Enter folder · Shift+Enter type path · Ctrl+C copy")

    def rebuild(self) -> None:
        self.status.setText(tr("Indexing files…"))
        self.index.build_async()

    # ------------------------------------------------------------ actions
    def _open(self, it: QListWidgetItem | None, folder: bool = False) -> None:
        if it is None:
            return
        path = it.data(ROLE_PATH)
        self.hide()
        self.index.record_open(path)
        (filesearch.open_folder if folder else filesearch.open_path)(path)

    def _copy(self) -> None:
        it = self.list.currentItem()
        if it:
            QGuiApplication.clipboard().setText(it.data(ROLE_PATH))
            self.hide()

    def _insert(self) -> None:
        it = self.list.currentItem()
        if it:
            self.hide()
            self.insert_path.emit(it.data(ROLE_PATH))

    def _handle_key(self, e) -> bool:
        k, mods = e.key(), e.modifiers()
        if k in (Qt.Key_Down, Qt.Key_Up, Qt.Key_PageDown, Qt.Key_PageUp):
            self.list.keyPressEvent(e)
            return True
        if k in (Qt.Key_Return, Qt.Key_Enter):
            if mods & Qt.ShiftModifier:
                self._insert()
            else:
                self._open(self.list.currentItem(), folder=bool(mods & Qt.ControlModifier))
            return True
        if k == Qt.Key_C and mods & Qt.ControlModifier and not self.search.hasSelectedText():
            self._copy()
            return True
        if k == Qt.Key_Escape:
            self.hide()
            return True
        return False

    def eventFilter(self, obj, e):  # noqa: N802
        if obj is self.search and e.type() == QEvent.KeyPress and self._handle_key(e):
            return True
        return super().eventFilter(obj, e)

    def keyPressEvent(self, e):  # noqa: N802
        if not self._handle_key(e):
            super().keyPressEvent(e)

    def changeEvent(self, e):  # noqa: N802
        if e.type() == QEvent.ActivationChange and self.isVisible() and not self.isActiveWindow():
            self.hide()
        super().changeEvent(e)

    def show_centered(self) -> None:
        self.search.clear()
        self.refresh()
        scr = QGuiApplication.screenAt(QPoint(*_cursor())) or QGuiApplication.primaryScreen()
        g = scr.availableGeometry()
        self.move(g.center().x() - self.width() // 2, g.top() + g.height() // 4)
        self.show()
        self.raise_()
        self.activateWindow()
        self.search.setFocus()


def _cursor() -> tuple[int, int]:
    from PySide6.QtGui import QCursor
    c = QCursor.pos()
    return c.x(), c.y()
