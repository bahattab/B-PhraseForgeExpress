"""Sticky notes built into PhraseForge (no external program).

Each note is a small frameless desktop window with a coloured header, rich text
(bold, italic, underline, strikethrough, bullets), seven colours, "always on top",
copy, save-as-phrase and delete. Notes are saved to PhraseForge's database as you
type, and open notes come back at their place the next time PhraseForge starts.
The notes list (Sticky Notes button / tray) searches, opens, creates and deletes
notes, and can import notes from Microsoft Sticky Notes' file (read-only).
"""
from __future__ import annotations

import sqlite3

from PySide6.QtCore import QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QGuiApplication, QKeySequence, QPixmap, QIcon, \
    QShortcut, QTextCharFormat, QTextListFormat
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox,
    QSizeGrip, QTextEdit, QToolButton, QVBoxLayout, QWidget,
)

from phraseforge.stickynotes import COLORS, StickyNote
from phraseforge.ui.i18n import tr
from phraseforge.ui.icons import app_icon

COLOR_LABELS = {"yellow": "Yellow", "green": "Green", "pink": "Pink", "purple": "Purple",
                "blue": "Blue", "gray": "Gray", "charcoal": "Charcoal"}


def _paper(color: str) -> tuple[str, str, str]:
    paper, header = COLORS.get(color, COLORS["yellow"])
    ink = "#ffffff" if color == "charcoal" else "#1f1f1f"
    return paper, header, ink


def _swatch(color: str) -> QIcon:
    pm = QPixmap(14, 14)
    pm.fill(QColor(_paper(color)[1]))
    return QIcon(pm)


def _tool(text: str, tip: str, parent=None) -> QToolButton:
    b = QToolButton(parent)
    b.setText(text)
    b.setToolTip(tr(tip))
    b.setAutoRaise(True)
    b.setCursor(Qt.PointingHandCursor)
    return b


class _Header(QWidget):
    """Coloured title bar: drag it to move the note."""

    def __init__(self, note_window: "StickyNoteWindow"):
        super().__init__(note_window)
        self._win = note_window
        self._drag: QPoint | None = None
        self.setFixedHeight(30)

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self._win.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self._win.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _e):  # noqa: N802
        self._drag = None

    def mouseDoubleClickEvent(self, _e):  # noqa: N802
        self._win.manager.show_list()


class StickyNoteWindow(QWidget):
    def __init__(self, manager: "StickyNotesManager", note: StickyNote):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint)
        self.manager, self.store, self.note_id = manager, manager.store, note.id
        self.color = note.theme or "yellow"
        self.on_top = note.on_top
        self.setWindowTitle(tr("Sticky note"))
        self.setWindowIcon(app_icon())
        self.setMinimumSize(180, 140)
        self.setAttribute(Qt.WA_DeleteOnClose, False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.header = _Header(self)
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(4, 0, 4, 0)
        self.new_btn = _tool("+", "New note")
        self.new_btn.clicked.connect(lambda: self.manager.new_note(near=self))
        hl.addWidget(self.new_btn)
        hl.addStretch(1)
        self.menu_btn = _tool("…", "Menu")
        self.menu_btn.setPopupMode(QToolButton.InstantPopup)
        self.menu_btn.setMenu(self._build_menu())
        hl.addWidget(self.menu_btn)
        self.close_btn = _tool("✕", "Close note")
        self.close_btn.clicked.connect(self.close)
        hl.addWidget(self.close_btn)
        lay.addWidget(self.header)

        self.edit = QTextEdit()
        self.edit.setAcceptRichText(True)
        self.edit.setFrameShape(QTextEdit.NoFrame)
        self.edit.setFont(QFont("Segoe UI", 11))
        self.edit.setPlaceholderText(tr("Take a note…"))
        if note.html:
            self.edit.setHtml(note.html)
        else:
            self.edit.setPlainText(note.text)
        lay.addWidget(self.edit, 1)

        self.footer = QWidget()
        fl = QHBoxLayout(self.footer)
        fl.setContentsMargins(4, 0, 0, 0)
        fl.setSpacing(0)
        for text, tip, fn in (("B", "Bold (Ctrl+B)", self.toggle_bold), ("I", "Italic (Ctrl+I)", self.toggle_italic),
                              ("U", "Underline (Ctrl+U)", self.toggle_underline),
                              ("S", "Strikethrough (Ctrl+T)", self.toggle_strike),
                              ("•", "Bullets (Ctrl+Shift+L)", self.toggle_bullets)):
            b = _tool(text, tip)
            f = b.font()
            f.setBold(text == "B")
            f.setItalic(text == "I")
            f.setUnderline(text == "U")
            f.setStrikeOut(text == "S")
            b.setFont(f)
            b.clicked.connect(fn)
            fl.addWidget(b)
        fl.addStretch(1)
        fl.addWidget(QSizeGrip(self), 0, Qt.AlignBottom | Qt.AlignRight)
        lay.addWidget(self.footer)

        for keys, fn in (("Ctrl+B", self.toggle_bold), ("Ctrl+I", self.toggle_italic),
                         ("Ctrl+U", self.toggle_underline), ("Ctrl+T", self.toggle_strike),
                         ("Ctrl+Shift+L", self.toggle_bullets), ("Ctrl+N", lambda: self.manager.new_note(near=self)),
                         ("Ctrl+D", self.delete), ("Ctrl+W", self.close)):
            QShortcut(QKeySequence(keys), self, activated=fn)

        self._save_text_timer = QTimer(self, singleShot=True, interval=500, timeout=self.save_text)
        self._save_geo_timer = QTimer(self, singleShot=True, interval=400, timeout=self.save_geometry)
        self.edit.textChanged.connect(self._save_text_timer.start)
        self._apply_style()
        self._apply_on_top(show=False)
        self.resize(note.w or 300, note.h or 300)
        if note.x is not None and note.y is not None:
            self.move(note.x, note.y)
        self._ready = True

    # ---- menu
    def _build_menu(self) -> QMenu:
        m = QMenu(self)
        group = QActionGroup(m)
        self.color_actions = {}
        for key, label in COLOR_LABELS.items():
            a = QAction(_swatch(key), tr(label), m, checkable=True)
            a.setChecked(key == self.color)
            a.triggered.connect(lambda _=False, k=key: self.set_color(k))
            group.addAction(a)
            m.addAction(a)
            self.color_actions[key] = a
        m.addSeparator()
        self.top_action = m.addAction(tr("Always on top"))
        self.top_action.setCheckable(True)
        self.top_action.setChecked(self.on_top)
        self.top_action.toggled.connect(self.set_on_top)
        m.addSeparator()
        m.addAction(tr("Copy text"), self.copy_text)
        m.addAction(tr("Save as phrase"), lambda: self.manager.save_as_phrase.emit(self.title(), self.text()))
        m.addAction(tr("Notes list"), self.manager.show_list)
        m.addSeparator()
        m.addAction(tr("Delete note"), self.delete)
        return m

    # ---- content
    def text(self) -> str:
        return self.edit.toPlainText()

    def title(self) -> str:
        return StickyNote(self.note_id, self.text()).title

    def _save(self, **fields) -> None:
        try:
            self.store.update_sticky_note(self.note_id, **fields)
        except sqlite3.ProgrammingError:   # database already closed (PhraseForge is exiting)
            pass

    def save_text(self) -> None:
        self._save(text=self.text(), html=self.edit.toHtml())

    def save_geometry(self) -> None:
        g = self.geometry()
        self._save(touch=False, x=g.x(), y=g.y(), w=g.width(), h=g.height())

    def flush(self) -> None:
        if self._save_text_timer.isActive():
            self._save_text_timer.stop()
            self.save_text()
        if self._save_geo_timer.isActive():
            self._save_geo_timer.stop()
            self.save_geometry()

    def copy_text(self) -> None:
        QApplication.clipboard().setText(self.text())

    # ---- formatting
    def _merge(self, fmt: QTextCharFormat) -> None:
        cur = self.edit.textCursor()
        if not cur.hasSelection():
            self.edit.mergeCurrentCharFormat(fmt)
        else:
            cur.mergeCharFormat(fmt)
        self.edit.setFocus()

    def toggle_bold(self) -> None:
        f = QTextCharFormat()
        f.setFontWeight(QFont.Normal if self.edit.fontWeight() > QFont.Normal else QFont.Bold)
        self._merge(f)

    def toggle_italic(self) -> None:
        f = QTextCharFormat()
        f.setFontItalic(not self.edit.fontItalic())
        self._merge(f)

    def toggle_underline(self) -> None:
        f = QTextCharFormat()
        f.setFontUnderline(not self.edit.fontUnderline())
        self._merge(f)

    def toggle_strike(self) -> None:
        f = QTextCharFormat()
        f.setFontStrikeOut(not self.edit.currentCharFormat().fontStrikeOut())
        self._merge(f)

    def toggle_bullets(self) -> None:
        cur = self.edit.textCursor()
        lst = cur.currentList()
        if lst is not None:
            block_fmt = cur.blockFormat()
            lst.remove(cur.block())
            block_fmt.setIndent(0)
            cur.setBlockFormat(block_fmt)
        else:
            fmt = QTextListFormat()
            fmt.setStyle(QTextListFormat.ListDisc)
            cur.createList(fmt)
        self.edit.setFocus()

    # ---- colour / on top
    def _apply_style(self) -> None:
        paper, header, ink = _paper(self.color)
        self.setStyleSheet(
            f"StickyNoteWindow{{background:{paper};border:1px solid {header}}}"
            f"QTextEdit{{background:{paper};color:{ink};padding:6px 10px;"
            f"selection-background-color:{header}}}"
            f"QToolButton{{color:{ink};font-size:14px;padding:2px 6px;border:none}}"
            f"QToolButton:hover{{background:rgba(0,0,0,0.08)}}")
        self.header.setStyleSheet(f"background:{header}")
        self.footer.setStyleSheet(f"background:{paper}")
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor(paper))
        self.setPalette(pal)

    def set_color(self, color: str) -> None:
        if color not in COLORS:
            return
        self.color = color
        if color in getattr(self, "color_actions", {}):
            self.color_actions[color].setChecked(True)
        self._apply_style()
        self._save(touch=False, color=color)

    def _apply_on_top(self, show: bool = True) -> None:
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, self.on_top)
        if show and visible:
            self.show()

    def set_on_top(self, on: bool) -> None:
        self.on_top = bool(on)
        self._apply_on_top()
        self._save(touch=False, on_top=self.on_top)

    # ---- window events
    def moveEvent(self, e):  # noqa: N802
        super().moveEvent(e)
        if getattr(self, "_ready", False) and self.isVisible():
            self._save_geo_timer.start()

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        if getattr(self, "_ready", False) and self.isVisible():
            self._save_geo_timer.start()

    def closeEvent(self, e):  # noqa: N802
        """Closing hides the note; it stays in the notes list."""
        self.flush()
        self._save(touch=False, visible=False)
        e.accept()

    def delete(self) -> None:
        if self.text().strip():
            ans = QMessageBox.question(self, tr("Delete note"), tr("Delete this note?"))
            if ans != QMessageBox.Yes:
                return
        self.manager.delete_note(self.note_id)

    def show_note(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.edit.setFocus()
        self._save(touch=False, visible=True)


class NotesListWindow(QWidget):
    """All notes: search, open, create, delete, import from Microsoft Sticky Notes."""

    def __init__(self, manager: "StickyNotesManager"):
        super().__init__(None, Qt.Window)
        self.manager, self.store = manager, manager.store
        self.setWindowTitle(tr("Sticky Notes"))
        self.setWindowIcon(app_icon())
        self.resize(340, 520)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        title = QLabel(tr("Sticky Notes"))
        f = title.font()
        f.setPointSize(f.pointSize() + 4)
        f.setBold(True)
        title.setFont(f)
        top.addWidget(title, 1)
        self.new_btn = _tool("+", "New note")
        self.new_btn.setFont(QFont("Segoe UI", 14))
        self.new_btn.clicked.connect(lambda: self.manager.new_note())
        top.addWidget(self.new_btn)
        lay.addLayout(top)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        lay.addWidget(self.search)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.setSpacing(3)
        self.list.itemActivated.connect(lambda it: self.manager.open_note(it.data(Qt.UserRole)))
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        lay.addWidget(self.list, 1)
        self.empty = QLabel(tr("No notes yet. Click + to add one."))
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet("color:#777777")
        lay.addWidget(self.empty)
        bottom = QHBoxLayout()
        self.import_btn = _tool(tr("Import from Microsoft Sticky Notes"), "Copy your Microsoft Sticky Notes into PhraseForge")
        self.import_btn.clicked.connect(self._import)
        bottom.addWidget(self.import_btn)
        bottom.addStretch(1)
        lay.addLayout(bottom)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=lambda: self.manager.new_note())
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.search.setFocus)
        self.refresh()

    def refresh(self) -> None:
        q = self.search.text().strip().lower()
        self.list.clear()
        notes = [n for n in self.store.sticky_notes() if not q or q in n.text.lower()]
        for n in notes:
            when = n.updated.strftime("%Y-%m-%d %H:%M") if n.updated else ""
            preview = " ".join(n.text.split())[:140] or tr("(empty note)")
            it = QListWidgetItem(f"{preview}\n{when}")
            it.setData(Qt.UserRole, n.id)
            paper, header, ink = _paper(n.theme)
            it.setBackground(QColor(paper))
            it.setForeground(QColor(ink))
            it.setToolTip(n.text[:500])
            self.list.addItem(it)
        self.empty.setVisible(not notes)
        from phraseforge import stickynotes
        self.import_btn.setVisible(stickynotes.installed())

    def _context_menu(self, pos) -> None:
        it = self.list.itemAt(pos)
        if it is None:
            return
        nid = it.data(Qt.UserRole)
        m = QMenu(self)
        m.addAction(tr("Open note"), lambda: self.manager.open_note(nid))
        m.addAction(tr("Delete note"), lambda: self._delete(nid))
        m.exec(self.list.viewport().mapToGlobal(pos))

    def _delete(self, nid) -> None:
        if QMessageBox.question(self, tr("Delete note"), tr("Delete this note?")) == QMessageBox.Yes:
            self.manager.delete_note(nid)

    def _import(self) -> None:
        try:
            n = self.manager.import_microsoft()
        except Exception as e:  # unreadable file
            QMessageBox.warning(self, tr("Sticky Notes"), str(e))
            return
        QMessageBox.information(self, tr("Sticky Notes"), tr("Imported notes: ") + str(n))


class StickyNotesManager(QObject):
    """Owns the note windows and the notes list."""

    save_as_phrase = Signal(str, str)   # title, text
    _changed = Signal()

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.windows: dict[int, StickyNoteWindow] = {}
        self.list_window: NotesListWindow | None = None
        self._changed.connect(self._refresh_list, Qt.QueuedConnection)
        store.on_change(lambda kind, _id: self._changed.emit() if kind == "sticky" else None)

    def _refresh_list(self) -> None:
        if self.list_window is not None and self.list_window.isVisible():
            self.list_window.refresh()

    def _default_pos(self, near: QWidget | None) -> QPoint:
        if near is not None:
            g = near.frameGeometry()
            return QPoint(g.x() + 30, g.y() + 30)
        geo = QGuiApplication.primaryScreen().availableGeometry()
        k = len([w for w in self.windows.values() if w.isVisible()]) % 8
        return QPoint(geo.right() - 340 - 30 * k, geo.top() + 60 + 30 * k)

    def new_note(self, text: str = "", near: QWidget | None = None) -> StickyNoteWindow:
        pos = self._default_pos(near)
        color = near.color if isinstance(near, StickyNoteWindow) else "yellow"
        note = self.store.add_sticky_note(text=text, color=color, x=pos.x(), y=pos.y())
        return self.open_note(note.id)

    def open_note(self, note_id) -> StickyNoteWindow | None:
        w = self.windows.get(note_id)
        if w is None:
            note = self.store.sticky_note(note_id)
            if note is None:
                return None
            w = StickyNoteWindow(self, note)
            self.windows[note_id] = w
        w.show_note()
        return w

    def delete_note(self, note_id) -> None:
        w = self.windows.pop(note_id, None)
        if w is not None:
            w._save_text_timer.stop()
            w._save_geo_timer.stop()
            w.hide()
            w.deleteLater()
        self.store.delete_sticky_note(note_id)

    def show_list(self) -> NotesListWindow:
        if self.list_window is None:
            self.list_window = NotesListWindow(self)
        self.list_window.refresh()
        self.list_window.show()
        self.list_window.raise_()
        self.list_window.activateWindow()
        return self.list_window

    def restore(self) -> int:
        """Open the notes that were open when PhraseForge last closed."""
        n = 0
        for note in self.store.sticky_notes():
            if note.visible:
                w = self.windows.get(note.id) or StickyNoteWindow(self, note)
                self.windows[note.id] = w
                w.show()
                n += 1
        return n

    def flush(self) -> None:
        for w in self.windows.values():
            w.flush()

    def import_microsoft(self, path=None) -> int:
        """Copy notes from Microsoft Sticky Notes' file (read only) into PhraseForge notes,
        skipping notes whose text is already present."""
        from phraseforge import stickynotes
        existing = {" ".join(n.text.split()) for n in self.store.sticky_notes()}
        added = 0
        for n in reversed(stickynotes.read_notes(path, use_cache=False)):   # oldest first
            key = " ".join(n.text.split())
            if not key or key in existing:
                continue
            self.store.add_sticky_note(text=n.text, color=stickynotes.color_of(n.theme), visible=False)
            existing.add(key)
            added += 1
        return added
