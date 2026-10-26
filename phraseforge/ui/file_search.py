"""Search files window (Listary-style launcher), opened with Ctrl+Alt+F or from the tray.

Keys: type fragments of a name, Up/Down to choose,
  Enter        open the file / start the program
  Ctrl+Enter   open the containing folder with the item selected
  Shift+Enter  type the full path into the program you were in
  Ctrl+C       copy the full path
  Ctrl+O       actions menu (open folder, copy/cut the file, copy path or name, custom actions)
  Ctrl+N/P     next / previous result
  Esc          close
Type "doc: report" to search with a filter (folder, file, doc, pic, video, audio and your own),
or a command keyword such as "cmd", "psh", "hosts", "rebuild", "opt".
Keys, filters, actions and commands follow Listary's Options window (docs/menus/listary.md).
"""
from __future__ import annotations

import os

from PySide6.QtCore import QByteArray, QEvent, QFileInfo, QMimeData, QPoint, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QFileIconProvider, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QVBoxLayout,
)

from phraseforge import filesearch
from phraseforge.ui.i18n import tr
from phraseforge.ui.icons import app_icon
from phraseforge.ui.popup import HEADER_H, ROW_H, SELECT, _Band

ROLE_PATH = Qt.UserRole
ROLE_URL = Qt.UserRole + 1
ROLE_CMD = Qt.UserRole + 2
ROLE_CUSTOM = Qt.UserRole + 3      # (custom command index, query)


class FileSearchWindow(QFrame):
    insert_path = Signal(str)      # Shift+Enter: type this path into the previous program
    open_settings = Signal()       # "opt" command

    def __init__(self, index: filesearch.FileIndex, parent=None, web_keywords: dict[str, str] | None = None,
                 filters: dict | None = None, custom_actions: list | None = None,
                 custom_commands: list | None = None, favorites: list[str] | None = None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.index = index
        self.filters = filters if filters is not None else dict(filesearch.DEFAULT_FILTERS)
        self.custom_actions = custom_actions or []
        self.custom_commands = custom_commands or []
        self.favorites = favorites or []        # Listary "Menu": folders shown while the box is empty
        self.actions_menu: QMenu | None = None
        self.web_keywords = (web_keywords if web_keywords is not None
                             else filesearch.parse_web_keywords(filesearch.DEFAULT_WEB_KEYWORDS))
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
            for path in self.favorites:
                it = QListWidgetItem(f"★  {os.path.basename(path.rstrip(chr(92) + '/')) or path}    —  {path}")
                it.setSizeHint(QSize(10, ROW_H))
                it.setData(ROLE_PATH, path)
                it.setToolTip(path)
                self.list.addItem(it)
            if self.list.count():
                self.list.setCurrentRow(0)
            self._show_status()
            return
        for i, (c, arg) in enumerate(filesearch.match_custom_commands(q, self.custom_commands)):
            it = QListWidgetItem(f"{c.keyword}    —  {c.title}" + (f":  {arg}" if arg else ""))
            it.setSizeHint(QSize(10, ROW_H))
            it.setData(ROLE_CUSTOM, (self.custom_commands.index(c), arg))
            self.list.addItem(it)
        for key in filesearch.match_commands(q):
            it = QListWidgetItem(f"{key}    —  {tr(filesearch.COMMANDS[key])}")
            it.setSizeHint(QSize(10, ROW_H))
            it.setData(ROLE_CMD, key)
            self.list.addItem(it)
        web = filesearch.web_search(q, self.web_keywords)
        if web:
            key, url = web
            it = QListWidgetItem(f"{tr('Search the web')} ({key}):  {q.partition(' ')[2].strip()}")
            it.setSizeHint(QSize(10, ROW_H))
            it.setData(ROLE_URL, url)
            it.setToolTip(url)
            self.list.addItem(it)
        filt, words = filesearch.split_filter(q, self.filters)
        self._filter = filt
        hits = self.index.search(words, limit=60, filt=filt) if words else []
        for h in hits:
            folder = os.path.dirname(h.path)
            it = QListWidgetItem(f"{h.name}    —  {folder}")
            it.setSizeHint(QSize(10, ROW_H))
            it.setData(ROLE_PATH, h.path)
            it.setToolTip(h.path)
            it.setIcon(self._icons.icon(QFileInfo(h.path)))
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)
        self._show_status(len(hits))

    def _show_status(self, n: int | None = None) -> None:
        if self.index.building:
            self.status.setText(tr("Indexing files…"))
        elif n is None:
            self.status.setText(tr("{n} items indexed").replace("{n}", f"{len(self.index):,}"))
        else:
            filt = getattr(self, "_filter", None)
            prefix = f"{tr(filt.name)}: " if filt else ""
            self.status.setText(prefix + tr("{n} results").replace("{n}", str(n)) +
                                "   ·   Enter open · Ctrl+Enter folder · Shift+Enter type path · Ctrl+O actions")

    def rebuild(self) -> None:
        self.status.setText(tr("Indexing files…"))
        self.index.build_async()

    # ------------------------------------------------------------ actions
    def _open(self, it: QListWidgetItem | None, folder: bool = False) -> None:
        if it is None:
            return
        custom = it.data(ROLE_CUSTOM)
        if custom:
            self.hide()
            i, arg = custom
            filesearch.run_custom_command(self.custom_commands[i], arg)
            return
        cmd = it.data(ROLE_CMD)
        if cmd:
            self.hide()
            if cmd == "opt":
                self.open_settings.emit()
            elif cmd == "rebuild":
                self.index.build_async()
            else:
                filesearch.run_command(cmd)
            return
        url = it.data(ROLE_URL)
        if url:
            self.hide()
            filesearch.open_path(url)
            return
        path = it.data(ROLE_PATH)
        self.hide()
        self.index.record_open(path)
        (filesearch.open_folder if folder else filesearch.open_path)(path)

    def _copy(self) -> None:
        it = self.list.currentItem()
        if it:
            QGuiApplication.clipboard().setText(it.data(ROLE_PATH) or it.data(ROLE_URL))
            self.hide()

    def _file_clip(self, cut: bool) -> None:
        """Put the file itself on the clipboard so it can be pasted in Explorer."""
        path = self._current_path()
        if not path:
            return
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(path)])
        md.setText(path)
        # Explorer reads "Preferred DropEffect": 2 = move (cut), 5 = copy|link
        md.setData("Preferred DropEffect", QByteArray(bytes([2 if cut else 5, 0, 0, 0])))
        QGuiApplication.clipboard().setMimeData(md)
        self.hide()

    def _current_path(self) -> str:
        it = self.list.currentItem()
        return (it.data(ROLE_PATH) or "") if it else ""

    def run_action(self, key: str) -> None:
        """Built-in action key (filesearch.BUILTIN_ACTIONS) or 'custom:<n>'."""
        path = self._current_path()
        if not path:
            return
        if key == "open":
            self._open(self.list.currentItem())
        elif key == "folder":
            self._open(self.list.currentItem(), folder=True)
        elif key in ("copy", "cut"):
            self._file_clip(cut=key == "cut")
        elif key == "copy_path":
            QGuiApplication.clipboard().setText(path)
            self.hide()
        elif key == "copy_name":
            QGuiApplication.clipboard().setText(os.path.basename(path))
            self.hide()
        elif key.startswith("custom:"):
            i = int(key[7:])
            if 0 <= i < len(self.custom_actions):
                self.hide()
                self.index.record_open(path)
                filesearch.run_custom_action(self.custom_actions[i], path)

    def build_actions_menu(self) -> QMenu:
        m = QMenu(self)
        for key in filesearch.BUILTIN_ACTIONS:
            m.addAction(tr(filesearch.ACTION_TITLES[key]), lambda k=key: self.run_action(k))
        if self.custom_actions:
            m.addSeparator()
            for i, a in enumerate(self.custom_actions):
                m.addAction(a.title, lambda k=f"custom:{i}": self.run_action(k))
        return m

    def show_actions(self) -> None:
        it = self.list.currentItem()
        if it is None or not it.data(ROLE_PATH):
            return
        self.actions_menu = self.build_actions_menu()
        r = self.list.visualItemRect(it)
        self.actions_menu.popup(self.list.viewport().mapToGlobal(r.bottomLeft()))

    def _insert(self) -> None:
        it = self.list.currentItem()
        if it:
            self.hide()
            self.insert_path.emit(it.data(ROLE_PATH) or it.data(ROLE_URL))

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
        if mods & Qt.ControlModifier and k in (Qt.Key_N, Qt.Key_P):
            row = self.list.currentRow() + (1 if k == Qt.Key_N else -1)
            if 0 <= row < self.list.count():
                self.list.setCurrentRow(row)
            return True
        if k == Qt.Key_O and mods & Qt.ControlModifier:
            self.show_actions()
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
        if (e.type() == QEvent.ActivationChange and self.isVisible() and not self.isActiveWindow()
                and not (self.actions_menu and self.actions_menu.isVisible())):
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
