"""PhraseForge main window, laid out like the PhraseExpress reference
(reference/phraseexpress/01_main_phrase_selected.png):

  ribbon (File | Phrases | View | Tools | Help | [Phrase content]) + search box + user
  quick toolbar
  tree panel | (phrase list in three-column mode) | editor
  status bar: breadcrumb links ................................ editor info
"""
from __future__ import annotations

import logging

import getpass
import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QFont, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow,
    QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QStackedWidget, QStatusBar, QToolBar, QToolButton,
    QVBoxLayout, QWidget,
)

from phraseforge.db import Store, hash_password
from phraseforge.host import Cancelled, ExpansionContext, FormField
from phraseforge.models import Folder, Phrase, Trigger
from phraseforge.ui import pe_style
from phraseforge.ui.i18n import tr
from phraseforge.ui.iconset import icon
from phraseforge.ui.main_dialogs import (
    FileMenu, FindReplaceDialog, FolderDialog, HistoryDialog, MoveToDialog, PhrasePropertiesDialog,
    PrintPreviewDialog, ProgramRestrictionsDialog, RestoreBackupDialog, big_submenu, color_menu, print_html,
)
from phraseforge.ui.ribbon import Ribbon, menu_with
from phraseforge.ui.tree_panel import (
    ROLE_ID, ROLE_KIND, PhraseList, TreePanel, set_item_color, sorted_folders, sorted_phrases,
)

__all__ = ["MainWindow", "FolderDialog", "preview_text", "PreviewHost", "macro_catalog", "ROLE_KIND", "ROLE_ID"]


# ======================================================================= preview host

# Layout when the user has not chosen one: three columns (folders | phrases | editor).
DEFAULT_LAYOUT = "three"
# Context menu > Translate
TRANSLATE_LANGUAGES = ("Arabic", "English", "French", "German", "Spanish", "Turkish", "Urdu", "Persian",
                       "Hindi", "Indonesian", "Malay", "Russian", "Chinese", "Japanese", "Korean",
                       "Italian", "Portuguese")

class PreviewHost:
    """HostServices stand-in for previews: never blocks, returns placeholders."""

    def __init__(self, store: Store):
        self.store = store

    def ask_input(self, prompt, default="", multiline=False):
        return default or f"[{prompt}]"

    def show_form(self, title, fields: list[FormField]):
        return {f.name: (f.default if f.default not in ("", None) else f"[{f.label or f.name}]") for f in fields}

    def choose(self, prompt, options, multi=False):
        return options[:1] if options else [f"[{prompt}]"]

    def pick_date(self, prompt, default_iso):
        return default_iso or date.today().isoformat()

    def message(self, text, title=""):
        pass

    def select_screen_region(self):
        return None

    def get_clipboard(self):
        return "[clipboard]"

    def set_clipboard(self, text):
        pass

    def clipboard_history(self, index):
        return self.store.clipboard_at(index) or f"[clipboard #{index}]"

    def phrase_content(self, description_or_id):
        p = None
        if str(description_or_id).isdigit():
            p = self.store.get_phrase(int(description_or_id))
        p = p or self.store.find_phrase(str(description_or_id))
        return (p.content, p.content_format) if p else None

    def get_var(self, name, scope="global"):
        return self.store.get_var(name, scope)

    def set_var(self, name, value, scope="global"):
        pass

    def run_program(self, cmd, args="", wait=False, workdir=""):
        return 0

    def open_target(self, target):
        pass

    def wait_for_window(self, title_substring, timeout_s):
        return True

    def focused_app(self):
        return ("preview.exe", "Preview")

    def http_request(self, method, url, headers=None, body=None, timeout_s=30):
        return f"[{method} {url}]"

    def ai_complete(self, prompt, provider="", model="", system=""):
        return "[AI response]"

    def ocr_region(self, language="English", keep_line_breaks=True):
        return f"[OCR text, {language}]"

    def ocr_image(self, path, language="English"):
        return f"[OCR of {path}]"

    def setting(self, key, default=""):
        return self.store.setting(key, default)


def preview_text(store: Store, content: str) -> str:
    """Expand content with PreviewHost; falls back to raw content if macros are unavailable."""
    try:
        from phraseforge.macros import MacroEngine
    except Exception:
        return content
    try:
        return MacroEngine(PreviewHost(store), store).expand_to_text(
            content, ExpansionContext(phrase_description="preview"))
    except Cancelled:
        return "(cancelled)"
    except Exception as e:
        return f"⚠ {e}"


def macro_catalog() -> list:
    try:
        from phraseforge.macros import catalog
        return list(catalog())
    except Exception:
        return []


# ======================================================================= fallback editors
class FallbackPhraseEditor(QWidget):
    """Minimal editor used only if ui.phrase_editor (owned by another module) is missing."""
    content_focus_changed = Signal(bool)
    saved = Signal(int)

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self.phrase_id: int | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.addWidget(pe_style.caption("Description"))
        self.description = QLineEdit()
        lay.addWidget(self.description)
        lay.addWidget(pe_style.caption("Phrase content"))
        self.content = QPlainTextEdit()
        self.content.setObjectName("ContentEditor")
        lay.addWidget(self.content, 1)
        self._dirty = False
        self.description.textEdited.connect(self._mark)
        self.content.textChanged.connect(self._mark)

    def _mark(self, *_):
        self._dirty = True

    def load(self, phrase_id: int) -> None:
        p = self.store.get_phrase(phrase_id)
        self.phrase_id = phrase_id
        self.description.setText(p.description if p else "")
        self.content.blockSignals(True)
        self.content.setPlainText(p.content if p else "")
        self.content.blockSignals(False)
        self._dirty = False

    def is_dirty(self) -> bool:
        return self._dirty

    def save(self) -> bool:
        if self.phrase_id is None or not self._dirty:
            return True
        p = self.store.get_phrase(self.phrase_id)
        if not p:
            return False
        p.description = self.description.text().strip() or p.description
        p.content = self.content.toPlainText()
        self.store.update_phrase(p)
        self._dirty = False
        self.saved.emit(p.id)
        return True

    def focus_description(self) -> None:
        self.description.setFocus()
        self.description.selectAll()


class FallbackFolderEditor(QWidget):
    saved = Signal(int)

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self.folder_id: int | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.addWidget(pe_style.caption("Description"))
        self.description = QLineEdit()
        self.description.editingFinished.connect(self.save)
        lay.addWidget(self.description)
        lay.addStretch(1)

    def load(self, folder_id: int) -> None:
        f = self.store.get_folder(folder_id)
        self.folder_id = folder_id
        self.description.setText(f.name if f else "")

    def save(self) -> bool:
        f = self.store.get_folder(self.folder_id) if self.folder_id else None
        if f and self.description.text().strip() and self.description.text().strip() != f.name:
            f.name = self.description.text().strip()
            self.store.update_folder(f)
            self.saved.emit(f.id)
        return True

    def focus_description(self) -> None:
        self.description.setFocus()
        self.description.selectAll()


class ClipEntryView(QWidget):
    """Read-only view of one Clipboard Cache entry."""

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.addWidget(pe_style.caption("Clipboard content"))
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        lay.addWidget(self.text, 1)

    def load(self, entry_id: int) -> None:
        e = next((e for e in self.store.clipboard_entries(500) if e.id == entry_id), None)
        self.text.setPlainText(e.text if e else "")


class StickyNoteView(QWidget):
    """One PhraseForge sticky note in the main window (or, for the folder node, a summary)."""

    def __init__(self, store: Store, window: "MainWindow", parent=None):
        super().__init__(parent)
        self.store = store
        self.window = window
        self.note = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        self.caption = pe_style.caption("Sticky note")
        lay.addWidget(self.caption)
        self.info = QLabel()
        self.info.setStyleSheet("color:#666666")
        lay.addWidget(self.info)
        self.text = QPlainTextEdit()          # editable: changes are saved after a short pause
        self.text.setPlaceholderText("Type your note…")
        self._loading = False
        self._save_timer = QTimer(self, singleShot=True, interval=700)
        self._save_timer.timeout.connect(self.save)
        self.text.textChanged.connect(self._edited)
        lay.addWidget(self.text, 1)
        row = QHBoxLayout()
        self.delete_btn = QPushButton(icon("delete"), "Delete")
        self.delete_btn.clicked.connect(self.delete_note)
        self.open_note_btn = QPushButton(icon("sticky_notes"), "Open note")
        self.open_note_btn.clicked.connect(self.open_note)
        self.copy_btn = QPushButton(icon("copy"), "Copy")
        self.copy_btn.clicked.connect(self.copy)
        self.create_btn = QPushButton(icon("new_phrase"), "Create phrase from this note")
        self.create_btn.clicked.connect(self.create_phrase)
        self.new_btn = QPushButton(icon("sticky_notes"), "New sticky note")
        self.new_btn.clicked.connect(lambda: self._command("new_sticky_note"))
        self.open_btn = QPushButton(icon("sticky_notes"), "Open Sticky Notes")
        self.open_btn.clicked.connect(lambda: self._command("open_sticky_notes"))
        for b in (self.open_note_btn, self.copy_btn, self.create_btn, self.delete_btn):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        row2 = QHBoxLayout()            # second row, so the pane can stay narrow without cutting labels
        for b in (self.new_btn, self.open_btn):
            row2.addWidget(b)
        row2.addStretch(1)
        lay.addLayout(row2)

    def _command(self, cmd: str) -> None:
        if getattr(self.window, "on_command", None) is not None:
            self.window.on_command(cmd)

    # ---- editing in the main window
    def _edited(self) -> None:
        if not self._loading and self.note is not None:
            self._save_timer.start()

    def is_dirty(self) -> bool:
        return self._save_timer.isActive()

    def save(self) -> bool:
        """Store the edited text. The rich-text copy is cleared so the desktop note shows
        the same text (formatting made on the desktop note is replaced by plain text)."""
        self._save_timer.stop()
        if self.note is None:
            return False
        text = self.text.toPlainText()
        if text == self.note.text:
            return False
        self.store.update_sticky_note(self.note.id, text=text, html="")
        self.note = self.store.sticky_note(self.note.id) or self.note
        self.caption.setText(self.note.title)
        return True

    def delete_note(self) -> bool:
        if self.note is None:
            return False
        if not getattr(self.window, "_quiet_updates", False):
            ok = QMessageBox.question(self, "Delete note", f'Delete the sticky note "{self.note.title}"?',
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ok != QMessageBox.Yes:
                return False
        self._save_timer.stop()
        nid, self.note = self.note.id, None
        if getattr(self.window, "on_command", None) is not None:
            self.window.on_command(f"delete_sticky_note:{nid}")   # also closes its desktop window
        else:
            self.store.delete_sticky_note(nid)
        self.window.panel.notes_by_id.pop(nid, None)
        self.window.refresh_tree()
        self.load(None)
        return True

    def load(self, note_id=None) -> None:
        """note_id: a note id from the tree, or None for the "Sticky Notes" folder node."""
        from phraseforge.ui import tree_panel as tp
        if self._save_timer.isActive():
            self.save()                    # keep what was typed before switching notes
        self._loading = True
        try:
            self._load(note_id, tp)
        finally:
            self._loading = False

    def _load(self, note_id, tp) -> None:
        if note_id is None:
            notes = tp.sticky_notes(self.store)
            self.note = None
            self.caption.setText("Sticky Notes")
            self.info.setText(f"{len(notes)} note(s). Choose a note to view it, or open the notes "
                              "to write and edit them on your desktop.")
            self.text.setPlainText("")
            self.text.setVisible(False)
            for b in (self.open_note_btn, self.copy_btn, self.create_btn, self.delete_btn):
                b.setVisible(False)
            return
        n = self.window.panel.notes_by_id.get(note_id) or self.store.sticky_note(note_id)
        self.note = n
        self.caption.setText(n.title if n else "Sticky note")
        when = n.updated.strftime("%Y-%m-%d %H:%M") if n and n.updated else ""
        self.info.setText(f"Updated {when}" if when else "")
        self.text.setPlainText(n.text if n else "")
        self.text.setVisible(True)
        for b in (self.open_note_btn, self.copy_btn, self.create_btn, self.delete_btn):
            b.setVisible(True)

    def open_note(self) -> None:
        if self.note is not None:
            self._command(f"open_sticky_notes:{self.note.id}")

    def copy(self) -> None:
        if self.note is not None:
            QApplication.clipboard().setText(self.text.toPlainText())

    def create_phrase(self):
        """New phrase (root folder) with description = note title and content = note text."""
        if self.note is None:
            return None
        p = self.store.add_phrase(Phrase(self.note.title, self.note.text, tags=["stickynotes"]))
        self.window.refresh_tree()
        self.window.select_phrase(p.id)
        return p


def initials_avatar(name: str) -> QPixmap:
    parts = [p for p in name.replace(".", " ").split() if p] or ["?"]
    ini = (parts[0][0] + (parts[1][0] if len(parts) > 1 else "")).upper()
    pm = QPixmap(22, 22)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#e8a85c"))
    p.setPen(Qt.NoPen)
    p.drawEllipse(0, 0, 22, 22)
    p.setPen(QColor("white"))
    f = QFont("Segoe UI", 7)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, ini)
    p.end()
    return pm


# ======================================================================= main window
class MainWindow(QMainWindow):
    usage_changed = Signal()          # a phrase was used (any thread) -> refresh Last Used
    SEARCH_SCOPES = (("all", "Search everywhere"), ("description", "Search in Description"),
                     ("content", "Search in Phrase content"), ("autotext", "Search in Autotext"))

    def __init__(self, store: Store, on_test_phrase: Callable[[int], None] | None = None,
                 on_command: Callable[[str], None] | None = None, tray=None):
        super().__init__()
        self.store = store
        self.tray = tray                    # the tray icon: the Tools tab runs its menu items
        self.on_test_phrase = on_test_phrase
        self.on_command = on_command        # app-level commands (OneNote, OCR, Search files)
        from phraseforge import __version__
        self.setWindowTitle(f"PhraseForge v{__version__}")
        try:
            from phraseforge.ui.icons import app_icon
            self.setWindowIcon(app_icon())
        except Exception:
            pass
        self.resize(1280, 820)
        app = QApplication.instance()
        if app is not None and "#Ribbon" not in (app.styleSheet() or ""):
            pe_style.apply(app)

        self.current: Phrase | None = None
        self.sel_kind: str | None = None
        self.sel_id: Any = None
        self.last_import_summary = ""
        self._clip: list[tuple[str, int, str]] = []        # (kind, id, "cut"|"copy")
        self._nav: list[tuple[str, Any]] = []
        self._nav_pos = -1
        self._navigating = False
        self.three_columns = self.store.setting("view.layout", DEFAULT_LAYOUT) == "three"

        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self.ribbon = Ribbon()
        cl.addWidget(self.ribbon)
        self.quickbar = self._build_quick_toolbar()
        cl.addWidget(self.quickbar)

        self.splitter = QSplitter(Qt.Horizontal)
        self.panel = TreePanel(store)
        self.tree = self.panel.tree
        self.phrase_list = PhraseList(store, self.panel)
        self.editor_stack = QStackedWidget()
        self.editor_stack.setObjectName("EditorStack")
        self.blank = QWidget()
        self.editor_stack.addWidget(self.blank)
        self._editors: dict[str, QWidget] = {}
        self.splitter.addWidget(self.panel)
        self.splitter.addWidget(self.phrase_list)
        self.splitter.addWidget(self.editor_stack)
        self.splitter.setStretchFactor(2, 1)
        self.splitter.setSizes([390, 290, 900])
        cl.addWidget(self.splitter, 1)
        self.setCentralWidget(central)

        sb = QStatusBar()
        self.breadcrumb = QLabel()
        self.breadcrumb.setTextFormat(Qt.RichText)
        self.breadcrumb.linkActivated.connect(self._breadcrumb_clicked)
        self.info = QLabel()
        sb.addWidget(self.breadcrumb, 1)
        sb.addPermanentWidget(self.info)
        self.setStatusBar(sb)

        self._build_search()
        self._build_user_label()
        self._build_file_menu()
        self._build_phrases_tab()
        self._build_view_tab()
        self._build_tools_tab()
        self._build_help_tab()
        self._build_content_tab()
        self._build_shortcuts()

        self.panel.selected.connect(self._on_selected)
        self.panel.tree.dropped.connect(self.move_item)
        self.panel.tree.customContextMenuRequested.connect(self._tree_menu)
        self.panel.tree.itemChanged.connect(self._item_renamed)
        self.phrase_list.selected.connect(self._on_list_selected)
        self.phrase_list.open_folder.connect(self._open_folder_from_list)
        self.phrase_list.open_note.connect(self._open_sticky_note)
        self.phrase_list.list.customContextMenuRequested.connect(self._list_menu)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(150)
        self._refresh_timer.timeout.connect(self.refresh_tree)
        self.usage_changed.connect(self._on_usage_changed)     # queued to the UI thread
        self._last_tree_settings = self._tree_settings()
        self.store.on_change(self._on_store_change)

        self.set_columns(3 if self.three_columns else 2, save=False)
        self.refresh_tree()
        self._update_status()
        self._update_actions()

    # ================================================================= building
    @property
    def unlocked(self) -> set[int]:
        return self.panel.unlocked

    def _build_quick_toolbar(self) -> QToolBar:
        tb = QToolBar()
        tb.setObjectName("QuickToolbar")
        tb.setIconSize(QSize(16, 16))
        tb.setMovable(False)
        self.act_back = tb.addAction(icon("back"), "Back", self.nav_back)
        self.act_forward = tb.addAction(icon("forward"), "Forward", self.nav_forward)
        tb.addAction(icon("sync"), "Send/Receive updates (Ctrl+F5)", self.sync_now)
        tb.addAction(icon("new_folder"), "New Folder (Ctrl+O)", lambda: self.new_folder())
        tb.addAction(icon("new_phrase"), "New Phrase (Ctrl+N)", lambda: self.new_phrase())
        tb.addAction(icon("column_toggle"), "Toggle two/three columns",
                     lambda: self.set_columns(2 if self.three_columns else 3))
        return tb

    def _build_search(self) -> None:
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search in Description [F3]")
        self.search.setFixedWidth(300)
        self.search.setClearButtonEnabled(True)
        scope_menu = QMenu(self)
        grp = QActionGroup(scope_menu)
        for key, text in self.SEARCH_SCOPES:
            a = scope_menu.addAction(text)
            a.setCheckable(True)
            a.setChecked(key == "description")
            a.triggered.connect(lambda _=False, k=key, t=text: self.set_search_scope(k, t))
            grp.addAction(a)
        self.panel_search_scope = "description"
        self.panel.search_scope = "description"
        act = self.search.addAction(icon("search"), QLineEdit.TrailingPosition)
        act.setToolTip("Search options")
        act.triggered.connect(lambda: scope_menu.exec(self.search.mapToGlobal(self.search.rect().bottomRight())))
        self.search_scope_menu = scope_menu
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._apply_search)
        self.search.textChanged.connect(lambda *_: self._search_timer.start())
        self.ribbon.set_center_widget(self.search)

    def set_search_scope(self, key: str, text: str) -> None:
        self.panel.search_scope = key
        self.search.setPlaceholderText(f"{text} [F3]")
        self._apply_search()

    def _apply_search(self) -> None:
        self.panel.search_text = self.search.text()
        self.refresh_tree()

    @staticmethod
    def windows_user_name() -> str:
        """Display name (e.g. 'Jane Doe') of the signed-in Windows user, else the login name."""
        if os.name == "nt":
            try:
                import ctypes
                size = ctypes.c_ulong(0)
                fn = ctypes.windll.secur32.GetUserNameExW
                fn(3, None, ctypes.byref(size))              # 3 = NameDisplay
                if size.value:
                    buf = ctypes.create_unicode_buffer(size.value)
                    if fn(3, buf, ctypes.byref(size)) and buf.value.strip():
                        return buf.value.strip()
            except Exception:
                pass
        return os.environ.get("USERNAME") or getpass.getuser() or "User"

    def _build_user_label(self) -> None:
        user = self.windows_user_name()
        b = QToolButton()
        b.setIcon(initials_avatar(user))
        b.setText(user)
        b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        b.setAutoRaise(True)
        b.setToolTip("Signed in as Windows user " + user)
        b.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(b)
        head = m.addAction(initials_avatar(user), tr("Windows user:") + " " + user)
        head.setEnabled(False)
        m.addSeparator()
        m.addAction(icon("settings"), "Settings...", self.show_settings)
        m.addAction(icon("open"), "Open data folder", self.open_data_folder)
        m.addSeparator()
        m.addAction(icon("help"), "User guide", self.open_help)
        m.addAction(icon("support"), "Get support...", self.get_support)
        b.setMenu(m)
        self.user_button = b
        self.ribbon.set_right_widget(b)

    def _build_file_menu(self) -> None:
        m = FileMenu(self)
        open_menu = big_submenu(m, [("Local phrase file", "local_file", self.open_phrase_file, True),
                                    ("Connect to SQL database [Demo]", "database", None, False)])
        m.add("Open", "open", open_menu)
        m.add("Save As...", "save_as", self.save_as)
        m.addSeparator()
        m.add("Restore from backup", "restore", self.restore_backup)
        m.add("Send/Receive updates", "sync", self.sync_now, "Ctrl+F5")
        m.add("User Manager", "users", None, enabled=False)
        m.add("Settings", "settings", self.show_settings)
        mig = big_submenu(m, [("Save settings and phrases into migration file", "save_as", self.migration_save, True),
                              ("Restore settings and phrases from migration file", "restore", self.migration_restore, True)])
        m.add("Migration Assistant", "migration", mig)
        m.addSeparator()
        m.add("Exit", "exit", self.close)
        self.file_menu = m
        self.ribbon.set_file_menu(m)

    def _build_phrases_tab(self) -> None:
        t = self.ribbon.add_tab("phrases", "Phrases")
        g = t.add_group("Insert")
        new_menu = menu_with(self, [("Phrase", "new_phrase", lambda: self.new_phrase()),
                                    ("Rich text phrase", "phrase_rich", lambda: self.new_phrase(rich=True)),
                                    ("Folder", "new_folder", lambda: self.new_folder())])
        self.btn_new_folder = g.add_large("New\nFolder", "new_folder", lambda: self.new_folder(), key="New Folder")
        self.btn_new_phrase = g.add_large("New\nPhrase", "new_phrase", lambda: self.new_phrase(), menu=new_menu,
                                          key="New Phrase")
        self.btn_new_folder.setToolTip("New Folder (Ctrl+O)")
        self.btn_new_phrase.setToolTip("New Phrase (Ctrl+N)")
        g = t.add_group("Sync")
        b = g.add_large("Send/Receive\nupdates", "sync", self.sync_now)
        b.setToolTip("Synchronize your phrases with the cloud now (Ctrl+F5). "
                     "Set up the cloud service in Settings > Backup & Sync.")
        g = t.add_group("Edit")
        self.color_menu = color_menu(self, self.set_color)
        self.btn_color = g.add_large("Color", "color", menu=self.color_menu, split=False)
        b = g.add_large("Access\nrights", "access_rights")
        b.setEnabled(False)
        self.btn_restrict = g.add_large("Program\nrestrictions", "program_restrictions", self.program_restrictions)
        c = g.add_column()
        self.btn_up = c.add_small("Up", "up", lambda: self.move_up_down(-1))
        self.btn_down = c.add_small("Down", "down", lambda: self.move_up_down(1))
        self.btn_move = c.add_small("Move to...", "move_to", self.move_to_dialog)
        c = g.add_column()
        self.btn_dup = c.add_small("Duplicate", "duplicate", self.duplicate_selected)
        self.btn_find = c.add_small("Find and Replace", "find_replace", self.find_replace)
        self.history_menu = QMenu(self)
        self.history_menu.aboutToShow.connect(self._fill_history_menu)
        self.btn_history = c.add_small("Edit history", "edit_history", menu=self.history_menu, split=False)
        g = t.add_group("Clipboard")
        self.btn_paste = g.add_large("Paste", "paste", self.paste_items)
        c = g.add_column()
        self.btn_cut = c.add_small("Cut", "cut", lambda: self.clip_items("cut"))
        self.btn_copy = c.add_small("Copy", "copy", lambda: self.clip_items("copy"))
        g = t.add_group("Languages")
        lang_menu = QMenu(self)
        lang_menu.aboutToShow.connect(lambda: self._fill_language_menu(lang_menu))
        g.add_large("Manage languages", "languages", menu=lang_menu, split=False)
        g = t.add_group("Import / Export")
        imp = menu_with(self, [("File import (JSON, CSV, TXT)...", "import", self.import_file),
                               ("Files including directory structure...", "folder_tree", self.import_folder),
                               None,
                               ("From PhraseExpress (CSV export)...", "import", self.import_phraseexpress),
                               ("TextExpander / macOS (.csv / .textexpander / .plist)...", "textexpander", self.import_textexpander),
                               ("From OneNote...", "on_notebook", self.import_onenote)])
        exp = menu_with(self, [("Export to file (JSON, CSV)...", "export", self.export_file),
                               ("Text files (one file per phrase)...", "text_file", self.export_text_folder),
                               None,
                               ("Word document (.docx)...", "export", lambda: self.export_document("docx")),
                               ("PDF document (.pdf)...", "print", lambda: self.export_document("pdf")),
                               None,
                               ("For PhraseExpress (CSV)...", "export", lambda: self.export_for("phraseexpress")),
                               ("For TextExpander (CSV)...", "textexpander", lambda: self.export_for("textexpander")),
                               ("For macOS Text Replacements (.plist)...", "export", lambda: self.export_for("macos"))])
        self.btn_import = g.add_large("Import", "import", menu=imp, split=False)
        self.btn_export = g.add_large("Export", "export", menu=exp, split=False)
        g.add_large("Print\nphrases", "print", self.print_phrases)

    def _build_view_tab(self) -> None:
        t = self.ribbon.add_tab("view", "View")
        g = t.add_group("Layout")
        self.btn_two = g.add_large("Two\ncolumns", "two_columns", lambda: self.set_columns(2))
        self.btn_three = g.add_large("Three\ncolumns", "three_columns", lambda: self.set_columns(3))
        self.btn_flat = g.add_large("Flat\nlist", "flat_list", self.toggle_flat)
        self.btn_fit = g.add_large("Resize column\nto fit contents", "fit_columns", self.fit_columns)
        for b in (self.btn_two, self.btn_three, self.btn_flat):
            b.setCheckable(True)
        self.btn_two.setToolTip("Two columns (Ctrl+2)")
        self.btn_three.setToolTip("Three columns (Ctrl+3)")
        g = t.add_group("Editor")
        box = QWidget()
        grid = QHBoxLayout(box)
        grid.setContentsMargins(4, 0, 4, 0)
        left, right = QVBoxLayout(), QVBoxLayout()
        self.view_options: dict[str, QCheckBox] = {}
        for key, text, default, col in (("show_rulers", "Show rulers", "0", left),
                                        ("show_special_chars", "Show special characters", "0", left),
                                        ("word_wrap", "Word Wrap", "1", left),
                                        ("show_macro_params", "Show macro parameters", "0", right)):
            cb = QCheckBox(text)
            cb.setChecked(self.store.setting(f"view.{key}", default) == "1")
            cb.toggled.connect(lambda on, k=key: self.set_view_option(k, on))
            col.addWidget(cb)
            self.view_options[key] = cb
        right.addStretch(1)
        left.addStretch(1)
        grid.addLayout(left)
        grid.addLayout(right)
        g.add_widget(box)
        g.caption.setText("")

    # The Tools tab holds the tray menu's items, grouped like the tray's sections:
    # (group, columns of (key, label, icon)). A key is a Tray.items key; COMMANDS
    # says how to run it when the window has no tray (opened alone, tests).
    TOOLS_TAB = (
        ("PhraseForge", ((("open_main", "Open PhraseForge", "phrase"),
                          ("new_phrase_from_clipboard", "New phrase from clipboard", "new_phrase"),
                          ("edit_last_phrase", "Edit last used phrase", "pencil")),)),
        ("Tools", ((("popup", "Phrase menu", "search"),
                    ("clipboard_history", "Clipboard history", "clipboard_cache"),
                    ("ocr", "OCR to clipboard", "m_ocr")),
                   (("ocr_language", "OCR language", "languages"),
                    ("file_search", "Search files", "file_search"),
                    ("prompt_tower", "Prompt Tower", "m_ai")),
                   (("prompt_optimizer", "Prompt Optimizer", "m_ai"),
                    ("ocr_file", "OCR PDF / image", "m_ocr")))),
        ("OneNote and notes", ((("onenote_send_clipboard", "Send clipboard to OneNote", "on_send"),
                                ("onenote_clip", "Screen clip to OneNote", "on_clip"),
                                ("quick_note", "New quick note", "sticky_notes")),
                               (("new_sticky_note", "New sticky note", "sticky_notes"),
                                ("open_sticky_notes", "Sticky notes", "sticky_notes")))),
        ("Program", ((("statistics", "Statistics", "statistics"),
                      ("settings", "Settings", "settings"),
                      ("about", "About PhraseForge", "about")),)),
        ("Options", ((("language", "Language selection", "languages"),
                      ("app_enabled", "Enabled in program", "app_toggle"),
                      ("pause", "Pause", "pause")),
                     (("quit", "Quit", "exit"),))),
    )
    # app command for each key (used without a tray); "" = handled by the window itself
    TOOL_COMMANDS = {
        "open_main": "open_main", "new_phrase_from_clipboard": "new_phrase_from_clipboard",
        "edit_last_phrase": "edit_last_phrase", "popup": "popup", "clipboard_history": "clipboard_history",
        "ocr": "ocr", "file_search": "file_search", "prompt_tower": "prompt_tower",
        "prompt_optimizer": "prompt_optimizer", "ocr_file": "ocr_file",
        "onenote_send_clipboard": "onenote_send_clipboard", "onenote_clip": "onenote_clip",
        "quick_note": "quick_note", "new_sticky_note": "new_sticky_note", "open_sticky_notes": "open_sticky_notes",
        "settings": "open_settings", "statistics": "", "about": "",
    }
    TOOL_MENUS = ("ocr_language", "language")          # open the tray's sub-menu
    TOOL_TOGGLES = ("app_enabled", "pause")            # checkable, mirror the tray item

    def _build_tools_tab(self) -> None:
        t = self.ribbon.add_tab("tools", "Tools")
        self.tool_buttons: dict[str, QToolButton] = {}
        tray_items = getattr(self.tray, "items", {}) if self.tray is not None else {}
        for group, columns in self.TOOLS_TAB:
            g = t.add_group(group)
            for column in columns:
                col = g.add_column()
                for key, label, icon_name in column:
                    act = tray_items.get(key)
                    if key in self.TOOL_MENUS:
                        menu = act.menu() if act is not None else None
                        b = col.add_small(label, icon_name, menu=menu, split=False)
                        b.setEnabled(menu is not None)
                    else:
                        b = col.add_small(label, icon_name, lambda k=key: self.run_tool(k))
                        if key in self.TOOL_TOGGLES:
                            b.setCheckable(True)
                            if act is not None:
                                b.setChecked(act.isChecked())
                                act.toggled.connect(b.setChecked)
                        b.setEnabled(self._tool_available(key))
                    self.tool_buttons[key] = b
        self.ribbon.tab_changed.connect(lambda k: k == "tools" and self.refresh_tools())
        self.refresh_tools()

    def _tool_available(self, key: str) -> bool:
        if self.tray is not None and key in getattr(self.tray, "items", {}):
            return True
        cmd = self.TOOL_COMMANDS.get(key)
        if cmd == "":
            return True                                     # Statistics / About: the window's own
        return bool(cmd) and self.on_command is not None

    def run_tool(self, key: str) -> None:
        """Run a Tools tab item exactly like the same item in the tray menu."""
        act = getattr(self.tray, "items", {}).get(key) if self.tray is not None else None
        if act is not None:
            if key in self.TOOL_TOGGLES and not act.isEnabled():
                return
            act.trigger()
            if key in self.TOOL_TOGGLES:       # keep the button in step even if nothing changed
                self.tool_buttons[key].setChecked(act.isChecked())
            return
        cmd = self.TOOL_COMMANDS.get(key)
        if cmd == "" and key == "statistics":
            self.show_stats()
        elif cmd == "" and key == "about":
            self.about()
        elif cmd and self.on_command is not None:
            self.on_command(cmd)

    def refresh_tools(self) -> None:
        """Update the items that change: "Enabled in <program>", OCR languages, Statistics."""
        tray = self.tray
        if tray is None or not hasattr(self, "tool_buttons"):
            return
        try:
            tray.refresh()
        except Exception:
            return
        items = tray.items
        b = self.tool_buttons.get("app_enabled")
        act = items.get("app_enabled")
        if b is not None and act is not None:
            label = act.text() if act.isVisible() and act.text() else tr("Enabled in program")
            b.setText(label)
            b.setEnabled(act.isVisible())
            b.setChecked(act.isChecked())
        for key in ("ocr_language", "statistics", "onenote_send_clipboard", "onenote_clip"):
            if key in items and key in self.tool_buttons:
                self.tool_buttons[key].setEnabled(items[key].isVisible())
        if "pause" in items and "pause" in self.tool_buttons:
            self.tool_buttons["pause"].setChecked(items["pause"].isChecked())

    def _build_help_tab(self) -> None:
        t = self.ribbon.add_tab("help", "Help")
        g = t.add_group("Statistics")
        g.add_large("Statistics", "statistics", self.show_stats)
        g = t.add_group("Program")
        g.add_large("Check for\nupdates", "updates", self.check_updates)
        g.add_large("About\nPhraseForge", "about", self.about)
        g = t.add_group("Support")
        g.add_large("Get\nsupport", "support", self.get_support)
        g.add_large("Help", "help", self.open_help)
        for grp in t.groups.values():
            grp.caption.setText("")

    def _build_content_tab(self) -> None:
        """'Phrase content' contextual tab, filled by ui.content_tab when available."""
        self.content_tab_ready = False
        try:
            from phraseforge.ui.content_tab import build_content_tab
        except Exception:
            return
        try:
            ed = self._editor("phrase")
            build_content_tab(self.ribbon, ed)
            self.content_tab_ready = "content" in self.ribbon.tabs
        except Exception:
            self.content_tab_ready = False

    def _build_shortcuts(self) -> None:
        def sc(seq, fn):
            s = QShortcut(QKeySequence(seq), self)
            s.activated.connect(fn)
            return s
        sc("F3", lambda: (self.search.setFocus(), self.search.selectAll()))
        sc("Ctrl+N", lambda: self.new_phrase())
        sc("Ctrl+O", lambda: self.new_folder())
        sc("Ctrl+2", lambda: self.set_columns(2))
        sc("Ctrl+3", lambda: self.set_columns(3))
        sc("Alt+Return", self.properties_selected)
        sc("Alt+Left", self.nav_back)
        sc("Alt+Right", self.nav_forward)
        s = QShortcut(QKeySequence(Qt.Key_Delete), self.tree)
        s.setContext(Qt.WidgetShortcut)
        s.activated.connect(self.delete_selected)
        s = QShortcut(QKeySequence("F2"), self.tree)
        s.setContext(Qt.WidgetShortcut)
        s.activated.connect(self.rename_selected)

    # ================================================================= editors
    def _editor(self, kind: str) -> QWidget:
        """Editor page for kind in phrase/folder/last_used/clipboard_cache/clip (created lazily)."""
        if kind in self._editors:
            return self._editors[kind]
        ed: QWidget | None = None
        try:
            from phraseforge.ui import phrase_editor as pe
            if kind == "phrase":
                ed = pe.PhraseEditor(self.store)
            elif kind == "folder":
                ed = pe.FolderEditor(self.store)
            elif kind in ("last_used", "clipboard_cache"):
                ed = pe.SpecialFolderEditor(self.store, kind)
        except Exception:
            # keep the window usable, but leave a trace: the simple fallback editor has
            # no view options (rulers, word wrap...), so a silent failure looks like broken buttons
            logging.getLogger(__name__).exception("creating the %s editor", kind)
            ed = None
        if ed is None:
            if kind == "phrase":
                ed = FallbackPhraseEditor(self.store)
            elif kind == "folder":
                ed = FallbackFolderEditor(self.store)
            elif kind == "clip":
                ed = ClipEntryView(self.store)
            elif kind == "note":
                ed = StickyNoteView(self.store, self)
            else:
                ed = QWidget()
        for sig, slot in (("content_focus_changed", self._content_focus), ("saved", self._editor_saved),
                          ("info_changed", self.info.setText), ("status_changed", self._editor_status)):
            s = getattr(ed, sig, None)
            if s is not None:
                try:
                    s.connect(slot)
                except Exception:
                    pass
        if kind == "phrase":
            self._push_view_options(ed)
        self._editors[kind] = ed
        self.editor_stack.addWidget(ed)
        return ed

    @property
    def editor(self) -> QWidget:
        return self.editor_stack.currentWidget()

    def save_current(self) -> bool:
        """Save the visible editor if it has changes. Returns False only when saving failed."""
        ed = self.editor_stack.currentWidget()
        if ed is self.blank or not hasattr(ed, "save"):
            return True
        dirty = getattr(ed, "is_dirty", None)
        dirty = dirty() if callable(dirty) else getattr(ed, "dirty", True)
        if not dirty:
            return True
        try:
            ed.save()      # editors return False for "nothing to save"; only exceptions are failures
            return True
        except Exception as e:
            QMessageBox.warning(self, "Save", str(e))
            return False

    save = save_current

    def _content_focus(self, on: bool) -> None:
        if not self.content_tab_ready:
            return
        if on:
            self.ribbon.set_contextual("content", True, activate=True)
        else:
            # Like PhraseExpress: keep "Phrase content" while the user works in the ribbon,
            # its menus or a macro dialog; hide it once focus lands elsewhere (tree, search...).
            QTimer.singleShot(200, self._maybe_hide_content_tab)

    def _maybe_hide_content_tab(self) -> None:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app.activePopupWidget() is not None or app.activeModalWidget() is not None:
            QTimer.singleShot(300, self._maybe_hide_content_tab)   # menu/dialog still open
            return
        fw = app.focusWidget()
        w = fw
        while w is not None:
            if w is self.ribbon:
                return                      # focus is on a ribbon control: keep the tab
            w = w.parentWidget()
        ce = getattr(self.editor, "content_edit", None)
        if fw is not None and fw is ce:
            return
        self.ribbon.set_contextual("content", False)

    def _editor_saved(self, _id=None) -> None:
        self._refresh_timer.start()
        if self.sel_kind == "phrase" and self.sel_id is not None:
            self.current = self.store.get_phrase(self.sel_id)
        self._update_status()

    def _show_editor(self, kind: str, id_) -> None:
        if kind in ("note", "sticky_notes"):
            # one page for both: a note's text, or a summary for the folder node
            ed = self._editor("note")
            ed.load(id_ if kind == "note" else None)
            self.editor_stack.setCurrentWidget(ed)
            self._content_focus(False)
            return
        if kind in ("phrase", "folder", "clip") and id_ is not None or kind in ("last_used", "clipboard_cache"):
            ed = self._editor(kind)
            load = getattr(ed, "load", None)
            if callable(load) and id_ is not None:
                load(id_)
            elif callable(load) and kind in ("last_used", "clipboard_cache"):
                try:
                    load()
                except TypeError:
                    pass
            self.editor_stack.setCurrentWidget(ed)
        else:
            self.editor_stack.setCurrentWidget(self.blank)
        if kind != "phrase":
            self._content_focus(False)

    # ================================================================= selection
    # Tree nodes whose content the middle column lists in the three-column layout.
    LIST_KINDS = ("folder", "root", "last_used", "clipboard_cache", "sticky_notes")
    TREE_SETTINGS = ("features.last_used_folder", "clipboard_history.enabled", "last_used.max",
                     "features.usage_statistics")

    def _tree_settings(self) -> tuple:
        return tuple(self.store.setting(k, "") for k in self.TREE_SETTINGS)

    def _on_store_change(self, kind: str, _id) -> None:
        if kind == "usage":
            # recorded on the expansion thread: a signal brings it to the UI thread
            self.usage_changed.emit()
            return
        if kind in ("folder", "phrase", "clipboard", "sticky"):
            self._refresh_timer.start()
        elif kind == "setting":
            # only settings that change the tree's special folders trigger a rebuild
            cur = self._tree_settings()
            if cur != getattr(self, "_last_tree_settings", None):
                self._last_tree_settings = cur
                self._refresh_timer.start()

    def _on_usage_changed(self) -> None:
        """A phrase was used: Last Used (and use counts) changed. Rebuild unless the user
        is editing a phrase, so a refresh never takes the selection away while typing."""
        if self.store.setting("features.last_used_folder", "1") == "1":
            self._refresh_timer.start()

    def refresh_tree(self) -> None:
        if getattr(self.store, "closed", False):   # a queued refresh after the store was closed
            return
        self.panel.refresh()
        if self.three_columns:
            k, i = self.panel.current()
            if k in self.LIST_KINDS:
                self.phrase_list.show_folder(k, i)
                if self.sel_kind == "note":         # keep the note being edited selected
                    lst = self.phrase_list.list
                    for r in range(lst.topLevelItemCount()):
                        it = lst.topLevelItem(r)
                        if it.data(0, ROLE_KIND) == "note" and it.data(0, ROLE_ID) == self.sel_id:
                            lst.blockSignals(True)
                            lst.setCurrentItem(it)
                            lst.blockSignals(False)
                            break
        self._update_status()

    def _all_items(self):
        return self.panel.all_items()

    def _on_selected(self, kind: str, id_) -> None:
        if not self.save_current():
            return
        if kind == "folder":
            f = self.store.get_folder(id_)
            if f and f.password_hash and f.id not in self.unlocked:
                if not self.unlock_folder(f):
                    self._set_selection("", None)
                    self.editor_stack.setCurrentWidget(self.blank)
                    return
        self._set_selection(kind, id_)
        if self.three_columns and kind in self.LIST_KINDS:
            self.phrase_list.show_folder(kind, id_)
        self._show_editor(kind, id_)
        self._push_nav(kind, id_)
        self._update_status()
        self._update_actions()

    def _on_list_selected(self, kind: str, id_) -> None:
        if not self.save_current():
            return
        self._set_selection(kind, id_)
        self._show_editor(kind, id_)
        self._push_nav(kind, id_)
        self._update_status()
        self._update_actions()

    def sync_now(self) -> None:
        """Send/Receive updates: synchronize with the cloud (Settings > Backup & Sync)."""
        self.save_current()
        if self.on_command is not None:
            self.on_command("sync_now")

    def _open_sticky_note(self, note_id) -> None:
        if self.on_command is not None and note_id is not None:
            self.on_command(f"open_sticky_notes:{note_id}")

    def _open_folder_from_list(self, folder_id) -> None:
        if folder_id is None:
            self.panel.select("root", None)
        else:
            self.panel.select("folder", folder_id)

    def _set_selection(self, kind: str, id_) -> None:
        self.sel_kind, self.sel_id = (kind or None), id_
        self.current = self.store.get_phrase(id_) if kind == "phrase" and id_ is not None else None

    def select_phrase(self, phrase_id: int) -> None:
        if not self.panel.select("phrase", phrase_id):
            # three-column mode: phrases live in the middle list
            p = self.store.get_phrase(phrase_id)
            if p:
                self.panel.select("folder" if p.folder_id else "root", p.folder_id)
                for i in range(self.phrase_list.list.topLevelItemCount()):
                    it = self.phrase_list.list.topLevelItem(i)
                    if it.data(0, ROLE_KIND) == "phrase" and it.data(0, ROLE_ID) == phrase_id:
                        self.phrase_list.list.setCurrentItem(it)
                        break

    def select_folder(self, folder_id: int | None) -> None:
        self.panel.select("folder" if folder_id is not None else "root", folder_id)

    def selected_folder_id(self) -> int | None:
        if self.sel_kind == "folder":
            return self.sel_id
        if self.sel_kind == "phrase":
            p = self.store.get_phrase(self.sel_id)
            return p.folder_id if p else None
        if self.three_columns and self.phrase_list.kind == "folder":
            return self.phrase_list.folder_id
        return None

    def unlock_folder(self, f: Folder) -> bool:
        from phraseforge.ui.dialogs import ask_folder_password
        if ask_folder_password(self.store, f, self):     # unlocks for the menu and expansion too
            QTimer.singleShot(0, self.refresh_tree)
            return True
        return False

    # ================================================================= status / actions
    def folder_path(self, folder_id: int | None) -> list[Folder]:
        return list(reversed(self.store.folder_chain(folder_id)))

    def _update_status(self) -> None:
        kind, id_ = self.sel_kind, self.sel_id
        crumbs: list[tuple[str, str]] = []
        if kind in ("phrase", "folder"):
            fid = id_ if kind == "folder" else (self.current.folder_id if self.current else None)
            crumbs.append(("root:", "Phrases"))
            crumbs += [(f"folder:{f.id}", f.name) for f in self.folder_path(fid)]
        if crumbs:
            html = " » ".join(f'<a href="{h}" style="color:#0066cc">{t.replace("<", "&lt;")}</a>' for h, t in crumbs)
            self.breadcrumb.setText(html)
        else:
            st = self.store.stats()
            secs = st["chars_saved"] / max(1, int(self.store.setting("stats.typing_speed", "180") or 180)) * 60
            d, rem = divmod(int(secs), 86400)
            h, rem = divmod(rem, 3600)
            m = rem // 60
            def unit(n, word):
                return f"{n} {word}{'' if n == 1 else 's'}"
            saved = ", ".join(x for x in (unit(d, "day") if d else "", unit(h, "hour") if h else "",
                                          unit(m, "minute") if m or not (d or h) else "") if x)
            from phraseforge.ui import i18n
            if i18n.language() == "ar":
                saved_ar = "، ".join(x for x in (f"{d} يوم" if d else "", f"{h} ساعة" if h else "",
                                                 f"{m} دقيقة" if m or not (d or h) else "") if x)
                self.breadcrumb.setText(f"أدرج PhraseForge ‏{st['expansions']} عبارة ووفّر لك {saved_ar}.")
            else:
                self.breadcrumb.setText(f"PhraseForge inserted {st['expansions']} phrases and saved {saved} for you.")
        if kind != "phrase":
            self.info.setText("")

    def _breadcrumb_clicked(self, href: str) -> None:
        kind, _, val = href.partition(":")
        if kind == "root":
            self.panel.select("root", None)
        elif kind == "folder":
            self.panel.select("folder", int(val))

    def _update_actions(self) -> None:
        item = self.sel_kind in ("phrase", "folder")
        for b in (self.btn_restrict, self.btn_up, self.btn_down, self.btn_move, self.btn_dup, self.btn_cut,
                  self.btn_copy, self.btn_color):
            b.setEnabled(item)
        self.btn_paste.setEnabled(bool(self._clip))
        self.btn_two.setChecked(not self.three_columns)
        self.btn_three.setChecked(self.three_columns)
        self.btn_flat.setChecked(self.panel.flat)
        self.act_back.setEnabled(self._nav_pos > 0)
        self.act_forward.setEnabled(self._nav_pos < len(self._nav) - 1)

    # ================================================================= navigation history
    def _push_nav(self, kind, id_) -> None:
        if self._navigating or not kind:
            return
        if self._nav_pos >= 0 and self._nav[self._nav_pos] == (kind, id_):
            return
        del self._nav[self._nav_pos + 1:]
        self._nav.append((kind, id_))
        self._nav_pos = len(self._nav) - 1

    def _go_nav(self, pos: int) -> None:
        if 0 <= pos < len(self._nav):
            self._nav_pos = pos
            self._navigating = True
            try:
                kind, id_ = self._nav[pos]
                if kind == "phrase":
                    self.select_phrase(id_)
                elif self.panel.current() == (kind, id_):
                    # already the tree's current item (three columns: a phrase was open in the
                    # middle list), so no selection signal would fire: show the folder directly
                    self._on_selected(kind, id_)
                else:
                    self.panel.select(kind, id_)
            finally:
                self._navigating = False
            self._update_actions()

    def nav_back(self) -> None:
        self._go_nav(self._nav_pos - 1)

    def nav_forward(self) -> None:
        self._go_nav(self._nav_pos + 1)

    # ================================================================= view
    def set_columns(self, n: int, save: bool = True) -> None:
        self.save_current()
        self.three_columns = n == 3
        self.panel.folders_only = self.three_columns
        self.panel.header.setText('Files and Folders ("Default")' if self.three_columns
                                  else 'Folders and phrases ("Default")')
        self.phrase_list.setVisible(self.three_columns)
        if save:
            self.store.set_setting("view.layout", "three" if self.three_columns else "two")
        self.refresh_tree()
        if hasattr(self, "btn_two"):
            self._update_actions()

    def toggle_flat(self) -> None:
        self.panel.flat = not self.panel.flat
        self.refresh_tree()
        if self.three_columns:
            # the folders leave the tree: show the whole list under "Phrases"
            self.panel.select("root", None)
            self.phrase_list.show_folder("root", None)
        self._update_actions()

    def fit_columns(self) -> None:
        """Resize the visible list's columns to their contents (middle list or tree)."""
        if self.three_columns:
            self.phrase_list.fit_columns()
        else:
            for c in range(self.tree.columnCount()):
                self.tree.resizeColumnToContents(c)

    def set_view_option(self, key: str, on: bool) -> None:
        self.store.set_setting(f"view.{key}", "1" if on else "0")
        ed = self._editors.get("phrase")
        if ed is not None:
            self._push_view_options(ed)

    def view_option(self, key: str) -> bool:
        cb = getattr(self, "view_options", {}).get(key)
        default = "1" if key == "word_wrap" else "0"
        return cb.isChecked() if cb is not None else self.store.setting(f"view.{key}", default) == "1"

    def _push_view_options(self, ed) -> None:
        fn = getattr(ed, "set_view_options", None)
        if callable(fn):
            try:
                fn(word_wrap=self.view_option("word_wrap"), show_special=self.view_option("show_special_chars"),
                   show_macro_params=self.view_option("show_macro_params"), rulers=self.view_option("show_rulers"))
            except Exception:
                logging.getLogger(__name__).exception("applying view options")

    def _editor_status(self, st: dict) -> None:
        if self.sel_kind != "phrase":
            return
        parts = [st.get("language", ""), f"Chars: {st.get('chars', 0)}", f"Words: {st.get('words', 0)}",
                 f"{st.get('zoom', 100)} %"]
        self.info.setText("      ".join(p for p in parts if p))

    # ================================================================= tree operations
    def new_folder(self, name: str | None = None) -> Folder | None:
        self.save_current()
        f = self.store.add_folder(Folder((name or "Folder").strip(), parent_id=self.selected_folder_id()))
        self.refresh_tree()
        self.select_folder(f.id)
        if name is None:
            self._focus_description()
        return f

    def new_phrase(self, rich: bool = False) -> Phrase:
        self.save_current()
        p = self.store.add_phrase(Phrase("New phrase", "", folder_id=self.selected_folder_id(),
                                         content_format="html" if rich else "text"))
        self.refresh_tree()
        self.select_phrase(p.id)
        # Settings > Display: "Prompt for additional information after creating a new phrase"
        if self.store.setting("display.prompt_after_new_phrase", "1") == "1":
            self._focus_description()
        else:
            self._focus_content()
        return p

    def _focus_description(self) -> None:
        """Put the cursor in the editor's Description field with its text selected."""
        def go():
            fn = getattr(self.editor, "focus_description", None)
            if callable(fn):
                fn()
                return
            d = getattr(self.editor, "description", None)
            if d is not None and hasattr(d, "selectAll"):
                d.setFocus()
                d.selectAll()
        QTimer.singleShot(0, go)

    def _focus_content(self) -> None:
        def go():
            ce = getattr(self.editor, "content_edit", None)
            if ce is not None:
                ce.setFocus()
        QTimer.singleShot(0, go)

    @staticmethod
    def _plain_content(p: Phrase) -> str:
        if p.content_format == "html":
            from PySide6.QtGui import QTextDocument
            doc = QTextDocument()
            doc.setHtml(p.content)
            return doc.toPlainText()
        return p.content

    def _busy(self, fn):
        """Run fn on a background thread while the window stays responsive; return its result
        (or raise its error)."""
        import threading
        box: dict = {}

        def run():
            try:
                box["value"] = fn()
            except Exception as e:      # noqa: BLE001 - re-raised below
                box["error"] = e
        t = threading.Thread(target=run, daemon=True)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            t.start()
            while t.is_alive():
                QApplication.processEvents()
                t.join(0.05)
        finally:
            QApplication.restoreOverrideCursor()
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def translate_phrase(self, phrase_id: int, language: str, translate=None) -> Phrase | None:
        """Context menu > Translate: a copy of the phrase translated into `language`, next to
        the original (macros are kept; formatting of rich-text phrases is not)."""
        p = self.store.get_phrase(phrase_id)
        if not p:
            return None
        text = self._plain_content(p)
        if translate is None:
            from phraseforge import ai
            settings = self.store.settings()

            def translate(t, lang):
                return ai.translate_text(settings, t, lang)
        try:
            out = self._busy(lambda: translate(text, language))
        except Exception as e:      # noqa: BLE001 - shown to the user
            if not getattr(self, "_quiet_updates", False):
                QMessageBox.warning(self, "Translate", f"The phrase could not be translated.\n\n{e}")
            return None
        new = Phrase(f"{p.description} ({language})", out, folder_id=p.folder_id, tags=list(p.tags))
        new = self.store.add_phrase(new)
        self.refresh_tree()
        self.select_phrase(new.id)
        return new

    def pin_to_desktop(self, phrase_id: int):
        """Context menu > Pin to desktop: show the phrase as a sticky note on the desktop."""
        p = self.store.get_phrase(phrase_id)
        if not p:
            return None
        text = self._plain_content(p)
        first = next((l.strip() for l in text.splitlines() if l.strip()), "")
        if p.description and first != p.description.strip():
            text = f"{p.description}\n{text}"
        note = self.store.add_sticky_note(text=text)
        if self.on_command is not None:
            self.on_command(f"open_sticky_notes:{note.id}")
        return note

    def duplicate_phrase(self, phrase_id: int) -> Phrase | None:
        p = self.store.get_phrase(phrase_id)
        if not p:
            return None
        p.id = None
        p.description += " (copy)"
        p.use_count = 0
        p.last_used = p.created = None
        # the copy's triggers start disabled so it does not clash with the original
        p.triggers = [Trigger(t.kind, t.value, mode=t.mode, case_sensitive=t.case_sensitive,
                              word_start_only=t.word_start_only, enabled=False) for t in p.triggers]
        p = self.store.add_phrase(p)
        self.refresh_tree()
        self.select_phrase(p.id)
        return p

    def copy_folder(self, folder_id: int, new_parent: int | None) -> Folder | None:
        src = self.store.get_folder(folder_id)
        if not src:
            return None
        dst = self.store.add_folder(Folder(src.name, parent_id=new_parent, enabled=src.enabled,
                                           apps_include=src.apps_include, apps_exclude=src.apps_exclude,
                                           password_hash=src.password_hash, show_in_popup=src.show_in_popup))
        for p in self.store.phrases(folder_id):
            p.id, p.folder_id, p.use_count, p.last_used, p.created = None, dst.id, 0, None, None
            p.triggers = [Trigger(t.kind, t.value, mode=t.mode, case_sensitive=t.case_sensitive,
                                  word_start_only=t.word_start_only, enabled=False) for t in p.triggers]
            self.store.add_phrase(p)
        for sub in self.store.folders(folder_id):
            self.copy_folder(sub.id, dst.id)
        return dst

    def duplicate_selected(self) -> None:
        if self.sel_kind == "phrase":
            self.duplicate_phrase(self.sel_id)
        elif self.sel_kind == "folder":
            f = self.store.get_folder(self.sel_id)
            new = self.copy_folder(self.sel_id, f.parent_id if f else None)
            if new:
                new.name += " (copy)"
                self.store.update_folder(new)
                self.refresh_tree()
                self.select_folder(new.id)

    def toggle_enabled(self, kind: str, id_: int) -> None:
        self.save_current()
        if kind == "folder":
            f = self.store.get_folder(id_)
            f.enabled = not f.enabled
            self.store.update_folder(f)
        else:
            p = self.store.get_phrase(id_)
            p.enabled = not p.enabled
            self.store.update_phrase(p, record_history=False)
            if self.sel_kind == "phrase" and self.sel_id == id_:
                self._show_editor("phrase", id_)
        self.refresh_tree()

    def toggle_popup(self, folder_id: int) -> None:
        f = self.store.get_folder(folder_id)
        f.show_in_popup = not f.show_in_popup
        self.store.update_folder(f)
        self.refresh_tree()

    def delete_item(self, kind: str, id_: int, confirm: bool = True) -> None:
        if confirm:
            name = (self.store.get_folder(id_).name if kind == "folder" else self.store.get_phrase(id_).description)
            msg = f'Delete folder "{name}" and everything in it?' if kind == "folder" else f'Delete phrase "{name}"?'
            if QMessageBox.question(self, "Delete", msg) != QMessageBox.Yes:
                return
        if kind == "folder":
            self.store.delete_folder(id_)
        else:
            self.store.delete_phrase(id_)
        if (self.sel_kind, self.sel_id) == (kind, id_) or (self.current and self.store.get_phrase(self.current.id) is None):
            self._set_selection("", None)
            self.editor_stack.setCurrentWidget(self.blank)
        self.refresh_tree()

    def delete_selected(self) -> None:
        if self.sel_kind in ("phrase", "folder"):
            self.delete_item(self.sel_kind, self.sel_id)
        elif self.sel_kind == "clip":
            self.store.delete_clipboard(self.sel_id)
            self.refresh_tree()

    def rename_selected(self) -> None:
        it = self.tree.currentItem()
        if it and it.data(0, ROLE_KIND) in ("phrase", "folder"):
            self.tree.editItem(it, 0)

    def _item_renamed(self, it, _col) -> None:
        kind, id_ = it.data(0, ROLE_KIND), it.data(0, ROLE_ID)
        text = it.text(0).strip()
        if not text:
            return
        if kind == "folder":
            f = self.store.get_folder(id_)
            if f and f.name != text:
                f.name = text
                self.store.update_folder(f)
                self._show_editor("folder", id_)
        elif kind == "phrase":
            p = self.store.get_phrase(id_)
            if p and p.description != text:
                p.description = text
                self.store.update_phrase(p, record_history=False)
                if self.sel_id == id_:
                    self._show_editor("phrase", id_)

    def folder_properties(self, folder_id: int) -> None:
        f = self.store.get_folder(folder_id)
        if f.password_hash and f.id not in self.unlocked and not self.unlock_folder(f):
            return
        dlg = FolderDialog(f, self)
        if dlg.exec() == QDialog.Accepted:
            self.store.update_folder(dlg.apply())
            self.refresh_tree()

    def properties_selected(self) -> None:
        if self.sel_kind == "folder":
            self.folder_properties(self.sel_id)
        elif self.sel_kind == "phrase":
            self.save_current()
            p = self.store.get_phrase(self.sel_id)
            dlg = PhrasePropertiesDialog(p, self)
            if dlg.exec() == QDialog.Accepted:
                self.store.update_phrase(dlg.apply(), record_history=False)
                self._show_editor("phrase", p.id)
                self.refresh_tree()

    def move_item(self, kind: str, id_: int, new_parent: int | None) -> None:
        self.save_current()
        if kind == "folder":
            if new_parent == id_ or any(f.id == id_ for f in self.store.folder_chain(new_parent)):
                return  # cannot move a folder into itself
            f = self.store.get_folder(id_)
            f.parent_id = new_parent
            self.store.update_folder(f)
        else:
            p = self.store.get_phrase(id_)
            p.folder_id = new_parent
            self.store.update_phrase(p, record_history=False)
            if self.current and self.current.id == id_:
                self.current.folder_id = new_parent
        self.refresh_tree()

    def move_up_down(self, delta: int) -> None:
        kind, id_ = self.sel_kind, self.sel_id
        if kind == "folder":
            f = self.store.get_folder(id_)
            sibs = sorted_folders(self.store, f.parent_id)
            upd = self.store.update_folder
        elif kind == "phrase":
            self.save_current()
            p = self.store.get_phrase(id_)
            sibs = sorted_phrases(self.store, p.folder_id)
            upd = lambda x: self.store.update_phrase(x, record_history=False)  # noqa: E731
        else:
            return
        idx = next(i for i, s in enumerate(sibs) if s.id == id_)
        j = idx + delta
        if not 0 <= j < len(sibs):
            return
        sibs[idx], sibs[j] = sibs[j], sibs[idx]
        for n, s in enumerate(sibs):
            if s.sort != n:
                s.sort = n
                upd(s)
        self.refresh_tree()

    def move_to_dialog(self) -> None:
        if self.sel_kind not in ("phrase", "folder"):
            return
        title = (self.store.get_folder(self.sel_id).name if self.sel_kind == "folder"
                 else self.store.get_phrase(self.sel_id).description)
        dlg = MoveToDialog(self.store, title, self.sel_id if self.sel_kind == "folder" else None, self)
        if dlg.exec() != QDialog.Accepted:
            return
        target = dlg.target()
        if dlg.copy.isChecked():
            if self.sel_kind == "phrase":
                p = self.duplicate_phrase(self.sel_id)
                if p:
                    self.move_item("phrase", p.id, target)
            else:
                self.copy_folder(self.sel_id, target)
                self.refresh_tree()
        else:
            self.move_item(self.sel_kind, self.sel_id, target)

    # ---------------------------------------------------------------- clipboard (cut/copy/paste items)
    def clip_items(self, mode: str) -> None:
        if self.sel_kind in ("phrase", "folder"):
            self._clip = [(self.sel_kind, self.sel_id, mode)]
            self._update_actions()

    def paste_items(self) -> None:
        target = self.selected_folder_id()
        for kind, id_, mode in self._clip:
            if mode == "cut":
                self.move_item(kind, id_, target)
            elif kind == "phrase":
                p = self.duplicate_phrase(id_)
                if p:
                    self.move_item("phrase", p.id, target)
            else:
                self.copy_folder(id_, target)
        if any(m == "cut" for _, _, m in self._clip):
            self._clip = []
        self.refresh_tree()
        self._update_actions()

    def select_all_in_folder(self) -> None:
        it = self.tree.currentItem()
        if it:
            it.setExpanded(True)

    # ---------------------------------------------------------------- color / restrictions
    def set_color(self, color: str | None) -> None:
        if self.sel_kind in ("phrase", "folder"):
            set_item_color(self.store, self.sel_kind, self.sel_id, color)
            self.refresh_tree()

    def program_restrictions(self) -> None:
        if self.sel_kind == "folder":
            obj = self.store.get_folder(self.sel_id)
            title = obj.name
        elif self.sel_kind == "phrase":
            self.save_current()
            obj = self.store.get_phrase(self.sel_id)
            title = obj.description
        else:
            return
        dlg = ProgramRestrictionsDialog(title, obj.apps_include, obj.apps_exclude, self)
        if dlg.exec() == QDialog.Accepted:
            obj.apps_include, obj.apps_exclude = dlg.values()
            if self.sel_kind == "folder":
                self.store.update_folder(obj)
            else:
                self.store.update_phrase(obj, record_history=False)
                self._show_editor("phrase", obj.id)

    # ---------------------------------------------------------------- find / history / languages
    def find_replace(self) -> None:
        self.save_current()
        if self.sel_kind == "phrase":
            dlg = FindReplaceDialog(self.store, self.current.description if self.current else "phrase",
                                    phrase_id=self.sel_id, parent=self)
        elif self.sel_kind == "folder":
            dlg = FindReplaceDialog(self.store, self.store.get_folder(self.sel_id).name, folder_id=self.sel_id,
                                    parent=self)
        else:
            dlg = FindReplaceDialog(self.store, "Phrases", parent=self)
        dlg.found.connect(self.select_phrase)
        self._find_dialog = dlg
        dlg.show()

    def recent_items(self, limit: int = 10) -> list[tuple[str, int, str, str]]:
        """Recently modified phrases and folders visited in this session: (kind, id, title, icon)."""
        out: list[tuple[str, int, str, str]] = []
        seen = set()
        for kind, id_ in reversed(self._nav):
            if kind in ("folder", "phrase") and (kind, id_) not in seen:
                obj = self.store.get_folder(id_) if kind == "folder" else self.store.get_phrase(id_)
                if obj:
                    out.append((kind, id_, obj.name if kind == "folder" else obj.description,
                                "folder" if kind == "folder" else "phrase"))
                    seen.add((kind, id_))
        for p in sorted(self.store.phrases(), key=lambda p: p.modified or "", reverse=True):
            if ("phrase", p.id) not in seen:
                out.append(("phrase", p.id, p.description, "phrase"))
                seen.add(("phrase", p.id))
            if len(out) >= limit:
                break
        return out[:limit]

    def _fill_history_menu(self) -> None:
        m = self.history_menu
        m.clear()
        for kind, id_, title, ic in self.recent_items():
            a = m.addAction(icon(ic), title)
            a.triggered.connect(lambda _=False, k=kind, i=id_: (self.select_phrase(i) if k == "phrase"
                                                                 else self.select_folder(i)))
        if self.sel_kind == "phrase":
            m.addSeparator()
            m.addAction(icon("edit_history"), "Earlier versions of this phrase...", self.show_phrase_history)

    def show_phrase_history(self) -> None:
        if self.sel_kind != "phrase":
            return
        self.save_current()
        dlg = HistoryDialog(self.store, self.sel_id, self)
        if dlg.exec() == QDialog.Accepted and dlg.chosen:
            p = self.store.get_phrase(self.sel_id)
            p.description, p.content = dlg.chosen["description"], dlg.chosen["content"]
            self.store.update_phrase(p)
            self._show_editor("phrase", p.id)

    def _fill_language_menu(self, m: QMenu) -> None:
        m.clear()
        cur = self.store.setting("ui.language", "en")
        for code, text in (("en", "Default (English)"), ("ar", "العربية (Arabic)")):
            a = m.addAction(text)
            a.setCheckable(True)
            a.setChecked(code == cur)
            a.triggered.connect(lambda _=False, c=code: self.set_language(c))

    def set_language(self, code: str) -> None:
        self.store.set_setting("ui.language", code)
        try:
            from phraseforge.ui import i18n
            i18n.install(QApplication.instance(), i18n.resolve_language(code))
        except Exception:
            import logging
            logging.getLogger(__name__).exception("language switch failed")

    # ---------------------------------------------------------------- context menus
    def _tree_menu(self, pos) -> None:
        it = self.tree.itemAt(pos)
        if it is not None:
            self.tree.setCurrentItem(it)
        kind = it.data(0, ROLE_KIND) if it else "root"
        id_ = it.data(0, ROLE_ID) if it else None
        self.build_context_menu(kind, id_).exec(self.tree.viewport().mapToGlobal(pos))

    def _list_menu(self, pos) -> None:
        it = self.phrase_list.list.itemAt(pos)
        if it is None:
            return
        self.phrase_list.list.setCurrentItem(it)
        self.build_context_menu(it.data(0, ROLE_KIND), it.data(0, ROLE_ID)).exec(
            self.phrase_list.list.viewport().mapToGlobal(pos))

    def build_context_menu(self, kind: str, id_) -> QMenu:
        """Context menu of the tree (16_context_menu_phrase / 16_context_menu_folder)."""
        m = QMenu(self)
        if kind == "clip":
            m.addAction(icon("new_phrase"), "Save as new phrase", lambda: self.clip_to_phrase(id_))
            m.addAction(icon("delete"), "Delete", lambda: (self.store.delete_clipboard(id_), self.refresh_tree()))
            return m
        if kind == "clipboard_cache":
            m.addAction(icon("delete"), "Empty clipboard cache",
                        lambda: (self.store.clear_clipboard(keep_pinned=False), self.refresh_tree()))
            return m
        if kind == "note":
            view = self._editor("note")
            if getattr(view.note, "id", None) != id_:
                view.load(id_)
            m.addAction(icon("sticky_notes"), "Open note", view.open_note)
            m.addAction(icon("copy"), "Copy", view.copy)
            m.addAction(icon("new_phrase"), "Create phrase from this note", view.create_phrase)
            m.addSeparator()
            m.addAction(icon("delete"), "Delete", view.delete_note)
            m.addSeparator()
            m.addAction(icon("sticky_notes"), "New sticky note", lambda: view._command("new_sticky_note"))
            return m
        if kind == "sticky_notes":
            m.addAction(icon("sticky_notes"), "New sticky note",
                        lambda: self.on_command and self.on_command("new_sticky_note"))
            m.addAction(icon("sticky_notes"), "Open Sticky Notes",
                        lambda: self.on_command and self.on_command("open_sticky_notes"))
            return m
        item = kind in ("phrase", "folder")
        if kind == "phrase":
            m.addAction(icon("open_tab"), "Open in tab", lambda: self.open_in_window(id_))
            m.addSeparator()
        add = m.addMenu("Add new...")
        add.addAction(icon("new_phrase"), "Phrase", lambda: self.new_phrase())
        add.addAction(icon("phrase_rich"), "Rich text phrase", lambda: self.new_phrase(rich=True))
        add.addAction(icon("new_folder"), "Folder", lambda: self.new_folder())
        m.addSeparator()
        a = m.addAction("Cut", lambda: self.clip_items("cut"))
        a.setEnabled(item)
        a = m.addAction("Copy", lambda: self.clip_items("copy"))
        a.setEnabled(item)
        a = m.addAction("Paste", self.paste_items)
        a.setEnabled(bool(self._clip))
        m.addAction("Select All", self.select_all_in_folder)
        m.addSeparator()
        a = m.addAction("Delete", lambda: self.delete_item(kind, id_))
        a.setEnabled(item)
        tr_menu = m.addMenu(icon("languages"), "Translate")
        tr_menu.setEnabled(kind == "phrase")
        for lang in TRANSLATE_LANGUAGES:
            tr_menu.addAction(lang, lambda l=lang: self.translate_phrase(id_, l))
        if kind in ("folder", "root"):
            fid = id_ if kind == "folder" else None
            bulk = m.addMenu("Bulk edit")
            self._fill_bulk_menu(bulk, fid)
            srt = m.addMenu("Sort")
            from phraseforge.bulk_edit import SORT_KEYS
            for key, (title, _fn) in SORT_KEYS.items():
                srt.addAction(title, lambda k=key: self.bulk_sort_by(fid, k))
        if kind == "folder":
            f = self.store.get_folder(id_)
            m.addSeparator()
            a = m.addAction("Enable triggers", lambda: self.toggle_enabled("folder", id_))
            a.setCheckable(True)
            a.setChecked(bool(f and f.enabled))
            a = m.addAction("Show in phrase menu", lambda: self.toggle_popup(id_))
            a.setCheckable(True)
            a.setChecked(bool(f and f.show_in_popup))
        else:
            m.addSeparator()
        a = m.addAction(icon("sticky_notes"), "Pin to desktop", lambda: self.pin_to_desktop(id_))
        a.setEnabled(kind == "phrase")
        m.addSeparator()
        a = m.addAction("Properties", self.properties_selected)
        a.setShortcut("Alt+Return")
        a.setEnabled(item)
        return m

    def _fill_bulk_menu(self, bulk: QMenu, fid: int | None) -> None:
        """PhraseExpress folder menu > Bulk edit (observed in PhraseExpress 18)."""
        from phraseforge.bulk_edit import TEXT_OP_TITLES
        bulk.addAction("Remove duplicates", lambda: self.bulk_remove_duplicates(fid))
        for target, title in (("description", "Descriptions"), ("content", "Phrase contents"),
                              ("autotext", "Autotexts")):
            sub = bulk.addMenu(title)
            if target == "description":
                sub.addAction("Generate", lambda: self.bulk_run(fid, "generate_descriptions"))
            if target == "content":
                sub.addAction("Convert to plain text", lambda: self.bulk_run(fid, "plain_text"))
            for i, (op, op_title) in enumerate(TEXT_OP_TITLES.items()):
                if i in (0, 2, 4):
                    sub.addSeparator()
                sub.addAction(op_title, lambda t=target, o=op: self.bulk_text(fid, t, o))
        bulk.addSeparator()
        bulk.addAction("Enable all phrases", lambda: self.bulk_enable(fid, True))
        bulk.addAction("Disable all phrases", lambda: self.bulk_enable(fid, False))
        bulk.addAction("Sort phrases alphabetically", lambda: self.bulk_sort(fid))

    def bulk_text(self, folder_id: int | None, target: str, op: str, arg: str | None = None) -> int:
        from phraseforge import bulk_edit
        if op in ("prefix", "append") and arg is None:
            arg, ok = QInputDialog.getText(self, "Bulk edit", "Prefix text:" if op == "prefix" else "Append text:")
            if not ok or not arg:
                return 0
        n = bulk_edit.apply_text_op(self.store, folder_id, target, op, arg or "")
        self.refresh_tree()
        return n

    def bulk_run(self, folder_id: int | None, what: str) -> int:
        from phraseforge import bulk_edit
        fn = {"generate_descriptions": bulk_edit.generate_descriptions,
              "plain_text": bulk_edit.convert_to_plain_text}[what]
        n = fn(self.store, folder_id)
        self.refresh_tree()
        return n

    def bulk_remove_duplicates(self, folder_id: int | None, confirm: bool = True) -> int:
        from phraseforge import bulk_edit
        if confirm and QMessageBox.question(
                self, "Remove duplicates",
                "Delete phrases in this folder whose description and text repeat an earlier phrase?") \
                != QMessageBox.Yes:
            return 0
        n = bulk_edit.remove_duplicates(self.store, folder_id)
        self.refresh_tree()
        return n

    def bulk_sort_by(self, folder_id: int | None, key: str) -> int:
        from phraseforge import bulk_edit
        n = bulk_edit.sort_phrases(self.store, folder_id, key, descending=key in ("times_used", "last_used"))
        self.refresh_tree()
        return n

    def bulk_enable(self, folder_id: int | None, on: bool) -> None:
        for p in self.store.phrases(folder_id):
            if p.enabled != on:
                p.enabled = on
                self.store.update_phrase(p, record_history=False)
        self.refresh_tree()

    def bulk_sort(self, folder_id: int | None) -> None:
        for n, p in enumerate(sorted(self.store.phrases(folder_id), key=lambda p: p.description.lower())):
            p.sort = n
            self.store.update_phrase(p, record_history=False)
        self.refresh_tree()

    def clip_to_phrase(self, entry_id: int) -> Phrase | None:
        e = next((e for e in self.store.clipboard_entries(500) if e.id == entry_id), None)
        if not e:
            return None
        p = self.store.add_phrase(Phrase(" ".join(e.text.split())[:60] or "Clipboard", e.text))
        self.refresh_tree()
        self.select_phrase(p.id)
        return p

    def open_in_window(self, phrase_id: int) -> None:
        """'Open in tab': a separate editor window for one phrase."""
        try:
            from phraseforge.ui.phrase_editor import PhraseEditor
            ed = PhraseEditor(self.store)
        except Exception:
            ed = FallbackPhraseEditor(self.store)
        ed.load(phrase_id)
        w = QMainWindow(self)
        w.setWindowTitle(self.store.get_phrase(phrase_id).description)
        w.setCentralWidget(ed)
        w.resize(760, 560)
        orig = w.closeEvent

        def close(e, ed=ed):
            try:
                ed.save()
            finally:
                orig(e)
        w.closeEvent = close
        w.show()
        self._extra_windows = getattr(self, "_extra_windows", []) + [w]

    # ================================================================= file menu
    def open_phrase_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open phrase file", "",
                                              "PhraseForge files (*.json *.db);;All files (*)")
        if not path:
            return
        if path.lower().endswith(".db"):
            if QMessageBox.question(self, "Open", "Replace all current phrases with this phrase file?") \
                    != QMessageBox.Yes:
                return
            self.store.restore_from(path, untrusted="imported")
            self.refresh_tree()
        else:
            self._import_path(path)

    def save_as(self) -> None:
        self.save_current()
        path, _ = QFileDialog.getSaveFileName(self, "Save As", "phrases.json",
                                              "PhraseForge JSON (*.json);;Database copy (*.db)")
        if not path:
            return
        try:
            if path.lower().endswith(".db"):
                self.store.backup_to(path)
            else:
                from phraseforge import io_formats
                io_formats.export_json(self.store, path)
        except Exception as e:
            QMessageBox.warning(self, "Save As", str(e))

    def migration_save(self) -> None:
        self.save_current()
        path, _ = QFileDialog.getSaveFileName(self, "Save migration file", "phraseforge-migration.json",
                                              "Migration file (*.json)")
        if not path:
            return
        try:
            d = self.store.export_dict()
            d["settings"] = self.store.settings()
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(d, fh, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "Migration Assistant", f"Saved to {path}")
        except Exception as e:
            QMessageBox.warning(self, "Migration Assistant", str(e))

    def migration_restore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Restore migration file", "", "Migration file (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
            from phraseforge import io_formats
            io_formats.import_dict(self.store, d)
            for k, v in (d.get("settings") or {}).items():
                self.store.set_setting(k, v)
            self.refresh_tree()
            QMessageBox.information(self, "Migration Assistant", "Settings and phrases restored.")
        except Exception as e:
            QMessageBox.warning(self, "Migration Assistant", str(e))

    def restore_backup(self) -> None:
        try:
            from phraseforge import io_formats
            backups = list(io_formats.list_backups())
        except Exception:
            from phraseforge.paths import backups_dir
            backups = sorted(Path(backups_dir()).glob("*.db"))
        dlg = RestoreBackupDialog(backups, "Phrases", self)
        if dlg.exec() != QDialog.Accepted or dlg.selected() is None:
            return
        if QMessageBox.question(self, "Restore from backup",
                                "Replace all current phrases with the selected backup?") != QMessageBox.Yes:
            return
        try:
            self.store.restore_from(dlg.selected())
            self._set_selection("", None)
            self.editor_stack.setCurrentWidget(self.blank)
            self.refresh_tree()
        except Exception as e:
            QMessageBox.warning(self, "Restore from backup", str(e))

    def backup(self) -> Path | None:
        try:
            from phraseforge import io_formats
            return io_formats.backup(self.store)
        except Exception as e:
            QMessageBox.warning(self, "Backup", str(e))
            return None

    # ================================================================= import / export
    def _import_path(self, path: str):
        from phraseforge import io_formats
        res = io_formats.import_file(self.store, path, self.selected_folder_id())
        self.refresh_tree()
        return res

    def import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "File import", "",
                                              "Phrase files (*.json *.csv *.txt *.textexpander);;All files (*)")
        if not path:
            return
        try:
            res = self._import_path(path)
            QMessageBox.information(self, "Import", f"Imported: {res}" if res is not None else "Imported.")
        except Exception as e:
            QMessageBox.warning(self, "Import", str(e))

    def import_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Import files including directory structure")
        if not d:
            return
        try:
            from phraseforge import io_formats
            n = io_formats.import_text_folder(self.store, d, self.selected_folder_id())
            self.refresh_tree()
            QMessageBox.information(self, "Import", f"Imported {n} phrase(s).")
        except Exception as e:
            QMessageBox.warning(self, "Import", str(e))

    def import_phraseexpress(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import from PhraseExpress", "",
                                              "PhraseExpress export (*.csv *.txt *.tsv);;"
                                              "PhraseExpress phrase files (*.pexdb *.pexdbhub *.pxp);;All files (*)")
        if path:
            self.import_phraseexpress_path(path)

    def import_phraseexpress_path(self, path: str, show_message: bool = True):
        """Import a PhraseExpress CSV export; returns the report (None on error)."""
        try:
            from phraseforge.importers.phraseexpress import import_any
            rep = import_any(self.store, path)
        except Exception as e:
            if show_message:
                QMessageBox.warning(self, "Import from PhraseExpress", str(e))
            return None
        self.refresh_tree()
        if rep.folder_id is not None:
            self.select_folder(rep.folder_id)
        self.last_import_summary = f"Imported {rep.imported} phrase(s)." + (
            f" Skipped {rep.skipped} empty row(s)." if rep.skipped else "")
        if show_message:
            QMessageBox.information(self, "Import from PhraseExpress", self.last_import_summary)
        return rep

    EXPORT_KINDS = {
        "phraseexpress": ("Export for PhraseExpress", "phrases-phraseexpress.csv", "CSV (*.csv)"),
        "textexpander": ("Export for TextExpander", "phrases-textexpander.csv", "CSV (*.csv)"),
        "macos": ("Export for macOS Text Replacements", "Text Substitutions.plist", "Property list (*.plist)"),
    }

    def export_for(self, kind: str, path: str | None = None, show_message: bool = True):
        """Export all phrases in another program's format (active phrase language)."""
        self.save_current()
        title, default, flt = self.EXPORT_KINDS[kind]
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, title, default, flt)
            if not path:
                return None
        try:
            from phraseforge.importers.phraseexpress import export_any
            rep = export_any(self.store, path, kind, language=self.store.setting("phrase.active_language", ""))
        except Exception as e:
            if show_message:
                QMessageBox.warning(self, title, str(e))
            return None
        lines = [f"Exported {rep.exported} phrase(s)."] + rep.notes
        if rep.kept_as_text:
            lines.append("Macros without an equivalent were kept as text: "
                         + ", ".join(f"{k} ×{n}" for k, n in sorted(rep.kept_as_text.items())))
        if show_message:
            QMessageBox.information(self, title, "\n".join(lines))
        return rep

    def import_textexpander(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import from TextExpander", "",
                                              "TextExpander / macOS exports (*.csv *.textexpander *.plist);;All files (*)")
        if path:
            self.import_textexpander_path(path)

    def import_textexpander_path(self, path: str, show_message: bool = True):
        """Import a TextExpander export; returns the report (None on error)."""
        try:
            from phraseforge.importers.textexpander import import_any
            rep = import_any(self.store, path)
        except Exception as e:
            if show_message:
                QMessageBox.warning(self, "Import from TextExpander", str(e))
            return None
        self.refresh_tree()
        if rep.folder_id is not None:
            self.select_folder(rep.folder_id)
            it = self.tree.currentItem()
            if it:
                it.setExpanded(True)
        self.last_import_summary = self.textexpander_summary(rep)
        if show_message:
            QMessageBox.information(self, "Import from TextExpander", self.last_import_summary)
        return rep

    # ---- OneNote import
    def import_onenote(self, client_factory=None) -> None:
        """Import > From OneNote...: tick notebooks/sections, each page becomes a phrase."""
        from phraseforge.ui.onenote_picker import OneNotePicker, default_client_factory
        factory = client_factory or default_client_factory(self.store.setting("onenote.exe", ""))
        dlg = OneNotePicker(self, mode="import", client_factory=factory)
        if dlg.exec():
            refs = dlg.checked_refs()
            if refs:
                self.import_onenote_refs(refs, factory)

    def import_onenote_refs(self, refs: list[str], client_factory, show_message: bool = True):
        """Run the import with a progress dialog. Runs on the UI thread (store listeners update
        widgets), keeping the window responsive between pages. Returns the report or None."""
        from PySide6.QtWidgets import QApplication, QProgressDialog
        from phraseforge.importers.onenote import import_nodes
        prog = QProgressDialog("Reading OneNote...", "Cancel", 0, 0, self)
        prog.setWindowTitle("Import from OneNote")
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(300)

        def progress(done: int, total: int, name: str = "") -> bool:
            prog.setMaximum(max(total, 1))
            prog.setValue(done)
            prog.setLabelText(f"Importing {done} of {total}\n{name}")
            QApplication.processEvents()
            return not prog.wasCanceled()

        try:
            rep = import_nodes(self.store, client_factory(), refs,
                               include_ocr=self.store.setting("onenote.include_ocr", "0") == "1",
                               progress=progress)
        except Exception as e:
            prog.close()
            if show_message:
                QMessageBox.warning(self, "Import from OneNote", str(e))
            return None
        prog.close()
        self.refresh_tree()
        if getattr(rep, "folder_id", None) is not None:
            self.select_folder(rep.folder_id)
            it = self.tree.currentItem()
            if it:
                it.setExpanded(True)
        lines = [f"Imported {rep.imported} OneNote page(s) as phrases."]
        errors = list(getattr(rep, "errors", []) or [])
        if errors:
            lines.append(f"{len(errors)} page(s) could not be read:")
            lines += [f"  {e}" for e in errors[:10]]
            if len(errors) > 10:
                lines.append(f"  ... and {len(errors) - 10} more")
        self.last_import_summary = "\n".join(lines)
        if show_message:
            QMessageBox.information(self, "Import from OneNote", self.last_import_summary)
        return rep

    @staticmethod
    def textexpander_summary(rep) -> str:
        lines = [f"Imported {rep.imported} snippet(s)."]
        if getattr(rep, "skipped", 0):
            lines.append(f"Skipped {rep.skipped}.")
        unknown = getattr(rep, "unknown_macros", None) or {}
        if unknown:
            lines.append("These TextExpander macros were kept as plain text:")
            lines += [f"  {name}  ×{n}" for name, n in sorted(unknown.items(), key=lambda kv: -kv[1])]
        return "\n".join(lines)

    def export_file(self) -> None:
        self.save_current()
        path, _ = QFileDialog.getSaveFileName(self, "Export", "phrases.json", "JSON (*.json);;CSV (*.csv)")
        if not path:
            return
        try:
            from phraseforge import io_formats
            io_formats.export_file(self.store, path)
        except Exception as e:
            QMessageBox.warning(self, "Export", str(e))

    def export_text_folder(self) -> None:
        self.save_current()
        d = QFileDialog.getExistingDirectory(self, "Export phrases as text files")
        if not d:
            return
        try:
            from phraseforge import io_formats
            n = io_formats.export_text_folder(self.store, d)
            QMessageBox.information(self, "Export", f"Exported {n} phrase(s).")
        except Exception as e:
            QMessageBox.warning(self, "Export", str(e))

    def phrases_for_print(self) -> list[Phrase]:
        if self.sel_kind == "phrase":
            return [self.store.get_phrase(self.sel_id)]
        if self.sel_kind == "folder":
            return self.store.phrases(self.sel_id)
        return self.store.phrases()

    def export_document(self, kind: str, path: str | None = None, show_message: bool = True):
        """Selected phrase, selected folder or all phrases as .docx / .pdf (Arabic right to left)."""
        self.save_current()
        from phraseforge import documents
        from phraseforge.ui import i18n
        title = "Export as Word document" if kind == "docx" else "Export as PDF"
        if path is None:
            flt = "Word document (*.docx)" if kind == "docx" else "PDF (*.pdf)"
            path, _ = QFileDialog.getSaveFileName(self, title, f"phrases.{kind}", flt)
            if not path:
                return None
            if not path.lower().endswith("." + kind):
                path += "." + kind
        try:
            n = documents.export(self.store, self.phrases_for_print(), path, i18n.language(),
                                 self.store.setting("phrase.active_language", ""))
        except Exception as e:
            if show_message:
                QMessageBox.warning(self, title, str(e))
            return None
        if show_message:
            msg = f"صُدّرت {n} عبارة." if i18n.language() == "ar" else f"Exported {n} phrase(s)."
            box = QMessageBox(QMessageBox.Information, title, msg, QMessageBox.Close, self)
            btn = box.addButton("Open", QMessageBox.AcceptRole)
            box.exec()
            if box.clickedButton() is btn:
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        return n

    def print_phrases(self) -> None:
        self.save_current()
        PrintPreviewDialog(print_html(self.store, self.phrases_for_print()), self).exec()

    # ================================================================= other windows
    def show_settings(self) -> None:
        self.save_current()
        from phraseforge.ui.settings_dialog import SettingsDialog
        SettingsDialog(self.store, parent=self).exec()

    def show_stats(self) -> None:
        from phraseforge.ui.stats_window import StatsWindow
        try:
            self._stats = StatsWindow(self.store, self)
        except TypeError:
            self._stats = StatsWindow(self.store)
        if isinstance(self._stats, QDialog):
            self._stats.exec()
        else:
            self._stats.show()

    def show_clipboard(self) -> None:
        self.panel.select("clipboard_cache", None)

    def show_suggestions(self) -> None:
        from phraseforge.ui.suggestions_dialog import SuggestionsDialog
        SuggestionsDialog(self.store, self).exec()
        self.refresh_tree()

    def about(self) -> None:
        try:
            from phraseforge.ui.about_dialog import AboutDialog
            AboutDialog(self).exec()
            return
        except Exception:
            pass
        from phraseforge import __version__
        QMessageBox.about(self, "About PhraseForge",
                          f"<b>PhraseForge v{__version__}</b><br>An original text expander for Windows.<br>"
                          "Screen OCR by Capture2Text (separate GPLv3 program).")

    def check_updates(self, opener=None) -> str:
        """Ask GitHub Releases (only on request). Returns the message shown."""
        from phraseforge import __version__, updates
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            rel = updates.latest_release(opener=opener) if opener else updates.latest_release()
            err = ""
        except Exception as e:  # network down, proxy, rate limit
            rel, err = None, str(e)
        finally:
            QApplication.restoreOverrideCursor()
        if err:
            msg = f"Could not check for updates: {err}"
        elif rel is None:
            msg = f"No release has been published yet. You have PhraseForge v{__version__}."
        elif updates.is_newer(rel["version"], __version__):
            msg = f"PhraseForge v{rel['version']} is available (you have v{__version__}).\n{rel['url']}"
        else:
            msg = f"You are up to date (PhraseForge v{__version__})."
        if not getattr(self, "_quiet_updates", False):
            box = QMessageBox(QMessageBox.Information, "Check for updates", msg, QMessageBox.Close, self)
            if rel is not None and not err and updates.is_newer(rel["version"], __version__):
                dl = box.addButton("Download", QMessageBox.AcceptRole) if rel.get("setup_url") else None
                btn = box.addButton("Open download page", QMessageBox.AcceptRole)
                box.exec()
                if dl is not None and box.clickedButton() is dl:
                    QDesktopServices.openUrl(QUrl(rel["setup_url"]))
                elif box.clickedButton() is btn:
                    QDesktopServices.openUrl(QUrl(rel["url"]))
            else:
                box.exec()
        return msg

    ISSUES_URL = "https://github.com/bahattab/B-PhraseForgeExpress/issues"

    def diagnostic_info(self) -> str:
        import platform
        from phraseforge import __version__, paths
        return (f"PhraseForge {__version__}\n{platform.platform()}\nPython {platform.python_version()}\n"
                f"Data folder: {paths.data_dir()}")

    def open_data_folder(self) -> None:
        from phraseforge import paths
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.data_dir())))

    def get_support(self) -> None:
        """Help, the log files (phraseforge.log) and a link to report a problem."""
        from phraseforge import paths
        box = QMessageBox(QMessageBox.Information, "Get support",
                          tr("Read the user guide, or report a problem on GitHub.") + "\n\n"
                          + tr("When you report a problem, attach phraseforge.log from the data folder "
                               "and paste the diagnostic information.") + f"\n{paths.data_dir()}",
                          QMessageBox.Close, self)
        guide = box.addButton("User guide", QMessageBox.ActionRole)
        folder = box.addButton("Open data folder", QMessageBox.ActionRole)
        copy = box.addButton("Copy diagnostic info", QMessageBox.ActionRole)
        report = box.addButton("Report a problem", QMessageBox.ActionRole)
        actions = {guide: self.open_help, folder: self.open_data_folder,
                   copy: lambda: QApplication.clipboard().setText(self.diagnostic_info()),
                   report: lambda: QDesktopServices.openUrl(QUrl(self.ISSUES_URL))}
        if getattr(self, "_quiet_updates", False):     # tests: don't block
            self._support_box = box
            return
        box.exec()
        fn = actions.get(box.clickedButton())
        if fn:
            fn()

    def open_help(self) -> None:
        from phraseforge.ui import i18n
        from phraseforge.ui.help_viewer import GuideDialog
        dlg = GuideDialog(i18n.language(), self)
        dlg.show() if getattr(self, "_quiet_updates", False) else dlg.exec()
        return dlg

    def macro_reference(self) -> None:
        from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem
        items = macro_catalog()
        dlg = QDialog(self)
        dlg.setWindowTitle("Macro reference")
        dlg.resize(760, 520)
        lay = QVBoxLayout(dlg)
        t = QTableWidget(len(items), 4)
        t.setHorizontalHeaderLabels(["Category", "Name", "Syntax", "Description"])
        t.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        for i, mi in enumerate(items):
            for j, v in enumerate((getattr(mi, "category", ""), mi.name, getattr(mi, "syntax", ""),
                                   getattr(mi, "description", ""))):
                t.setItem(i, j, QTableWidgetItem(str(v)))
        lay.addWidget(t)
        dlg.exec()

    def changeEvent(self, e):  # noqa: N802
        super().changeEvent(e)
        # coming back from another program: "Enabled in <program>" names that program
        if e.type() == QEvent.ActivationChange and self.isActiveWindow():
            self.refresh_tools()

    def closeEvent(self, e):  # noqa: N802
        if not self.save_current():
            e.ignore()
            return
        super().closeEvent(e)
