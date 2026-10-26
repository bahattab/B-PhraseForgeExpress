"""Dialogs and menus opened from the main window's ribbon (layout follows reference/phraseexpress/14_*, 19_*)."""
from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QPainter, QPixmap, QTextDocument
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMenu, QMessageBox,
    QPlainTextEdit, QPushButton, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
    QWidgetAction,
)

from phraseforge.db import Store, hash_password
from phraseforge.models import Folder, Phrase, TriggerKind
from phraseforge.ui.i18n import tr
from phraseforge.ui.iconset import icon

NO_WINDOW = 0x08000000 if os.name == "nt" else 0


# ======================================================================= properties
class FolderDialog(QDialog):
    """Folder properties (Alt+Enter): name, enabled, popup, program rules, password."""

    def __init__(self, folder: Folder, parent=None):
        super().__init__(parent)
        self.folder = folder
        self.setWindowTitle(f'Properties of "{folder.name}"')
        f = QFormLayout(self)
        self.name = QLineEdit(folder.name)
        self.enabled = QCheckBox("Enable triggers")
        self.enabled.setChecked(folder.enabled)
        self.popup = QCheckBox("Show in phrase menu")
        self.popup.setChecked(folder.show_in_popup)
        self.inc = QLineEdit(folder.apps_include)
        self.inc.setPlaceholderText("winword.exe, outlook.exe")
        self.exc = QLineEdit(folder.apps_exclude)
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText("leave empty to keep" if folder.password_hash else "no password")
        self.clear_pw = QCheckBox("Remove password")
        self.clear_pw.setVisible(bool(folder.password_hash))
        for label, w in (("Name:", self.name), ("", self.enabled), ("", self.popup),
                         ("Only in programs:", self.inc), ("Not in programs:", self.exc),
                         ("Password:", self.pw), ("", self.clear_pw)):
            f.addRow(label, w) if label else f.addRow(w)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def apply(self) -> Folder:
        f = self.folder
        f.name = self.name.text().strip() or f.name
        f.enabled = self.enabled.isChecked()
        f.show_in_popup = self.popup.isChecked()
        f.apps_include = self.inc.text().strip()
        f.apps_exclude = self.exc.text().strip()
        if self.clear_pw.isChecked():
            f.password_hash = ""
        elif self.pw.text():
            f.password_hash = hash_password(self.pw.text())
        return f


class PhrasePropertiesDialog(QDialog):
    def __init__(self, phrase: Phrase, parent=None):
        super().__init__(parent)
        self.phrase = phrase
        self.setWindowTitle(f'Properties of "{phrase.description}"')
        f = QFormLayout(self)
        self.enabled = QCheckBox("Enable triggers")
        self.enabled.setChecked(phrase.enabled)
        self.inc = QLineEdit(phrase.apps_include)
        self.exc = QLineEdit(phrase.apps_exclude)
        self.notes = QPlainTextEdit(phrase.notes)
        self.notes.setFixedHeight(80)
        info = QLabel(f"Created: {phrase.created or '-'}\nModified: {phrase.modified or '-'}\n"
                      f"Used: {phrase.use_count} times (last {phrase.last_used or 'never'})")
        for label, w in (("", self.enabled), ("Only in programs:", self.inc), ("Not in programs:", self.exc),
                         ("Notes:", self.notes), ("", info)):
            f.addRow(label, w) if label else f.addRow(w)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def apply(self) -> Phrase:
        p = self.phrase
        p.enabled = self.enabled.isChecked()
        p.apps_include = self.inc.text().strip()
        p.apps_exclude = self.exc.text().strip()
        p.notes = self.notes.toPlainText()
        return p


# ======================================================================= program restrictions
def running_programs() -> list[str]:
    """Exe names of running programs (sorted, unique)."""
    if os.name != "nt":
        return []
    try:
        out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, timeout=10,
                             creationflags=NO_WINDOW).stdout.decode("utf-8", "replace")
    except Exception:
        return []
    names = {line.split('","')[0].strip('"').lower() for line in out.splitlines() if line.startswith('"')}
    return sorted(n for n in names if n.endswith(".exe"))


class ProgramCombo(QComboBox):
    """'Select program...' combo filled with running programs when opened."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.lineEdit().setPlaceholderText("Select program...")
        self.setMinimumWidth(170)
        self._filled = False

    def showPopup(self):  # noqa: N802
        if not self._filled:
            self.addItems(running_programs())
            self._filled = True
        super().showPopup()


class ProgramRestrictionsDialog(QDialog):
    """Restrict a phrase or folder to (or exclude it from) specific programs."""

    def __init__(self, title: str, include: str, exclude: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'Restrict "{title}" to specific programs')
        self.resize(680, 440)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f'Restrict "{title}" to specific programs. Launch the program to add it to '
                             "below drop-down selection:"))
        self.rows_lay = QVBoxLayout()
        lay.addLayout(self.rows_lay)
        self.rows: list[tuple[QComboBox, QComboBox, QWidget]] = []
        mode = "Restrict to" if include else "Exclude from"
        for exe in [e.strip() for e in (include or exclude).split(",") if e.strip()]:
            self.add_row(mode, exe)
        if include and exclude:
            for exe in [e.strip() for e in exclude.split(",") if e.strip()]:
                self.add_row("Exclude from", exe)
        self.add_row(mode, "")
        lay.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Help)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.helpRequested.connect(lambda: QMessageBox.information(
            self, "Help", "Choose 'Restrict to' to use the item only in the listed programs, or "
                          "'Exclude from' to block it there. Program names are exe file names."))
        lay.addWidget(bb)

    def add_row(self, mode: str, exe: str) -> None:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        m = QComboBox()
        m.addItems(["Restrict to", "Exclude from"])
        m.setCurrentText(mode)
        m.setFixedWidth(90)
        p = ProgramCombo()
        p.setEditText(exe)
        p.currentTextChanged.connect(lambda _t, r=row: self._maybe_extend(r))
        x = QToolButton()
        x.setIcon(icon("remove"))
        x.setAutoRaise(True)
        x.clicked.connect(lambda _=False, r=row: self._remove(r))
        h.addWidget(m)
        h.addWidget(p)
        h.addWidget(x)
        h.addStretch(1)
        self.rows_lay.addWidget(row)
        self.rows.append((m, p, row))

    def _maybe_extend(self, row) -> None:
        if self.rows and self.rows[-1][2] is row and self.rows[-1][1].currentText().strip():
            self.add_row(self.rows[-1][0].currentText(), "")

    def _remove(self, row) -> None:
        self.rows = [r for r in self.rows if r[2] is not row]
        row.deleteLater()
        if not self.rows:
            self.add_row("Restrict to", "")

    def values(self) -> tuple[str, str]:
        inc = [p.currentText().strip().lower() for m, p, _ in self.rows
               if p.currentText().strip() and m.currentText() == "Restrict to"]
        exc = [p.currentText().strip().lower() for m, p, _ in self.rows
               if p.currentText().strip() and m.currentText() == "Exclude from"]
        return ", ".join(inc), ", ".join(exc)


# ======================================================================= move to
class MoveToDialog(QDialog):
    """Select target folder (with filter box) and optional 'Copy instead of move'."""

    def __init__(self, store: Store, title: str, moving_folder_id: int | None = None, parent=None):
        super().__init__(parent)
        self.store = store
        self.moving = moving_folder_id
        self.setWindowTitle(f'Select target folder for "{title}"…')
        self.resize(400, 530)
        lay = QVBoxLayout(self)
        self.filter = QLineEdit()
        self.filter.addAction(icon("search"), QLineEdit.TrailingPosition)
        self.filter.textChanged.connect(self._apply_filter)
        lay.addWidget(self.filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        lay.addWidget(self.tree, 1)
        root = QTreeWidgetItem(["Phrases"])
        root.setIcon(0, icon("phrases_root"))
        root.setData(0, Qt.UserRole, None)
        self.tree.addTopLevelItem(root)
        self._add(root, None)
        root.setExpanded(True)
        self.tree.expandAll()
        self.tree.setCurrentItem(root)
        bottom = QHBoxLayout()
        self.copy = QCheckBox("Copy instead of move")
        bottom.addWidget(self.copy)
        bottom.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bottom.addWidget(bb)
        lay.addLayout(bottom)
        self.tree.itemDoubleClicked.connect(lambda *_: self.accept())

    def _add(self, parent, parent_id) -> None:
        for f in self.store.folders(parent_id):
            if f.id == self.moving:
                continue        # a folder cannot go into itself
            it = QTreeWidgetItem([f.name])
            it.setIcon(0, icon("folder"))
            it.setData(0, Qt.UserRole, f.id)
            parent.addChild(it)
            self._add(it, f.id)

    def _apply_filter(self, text: str) -> None:
        t = text.lower().strip()

        def walk(it) -> bool:
            child_vis = False
            for i in range(it.childCount()):
                child_vis |= walk(it.child(i))
            vis = not t or t in it.text(0).lower() or child_vis or it.data(0, Qt.UserRole) is None
            it.setHidden(not vis)
            return vis and (not t or t in it.text(0).lower() or child_vis)
        walk(self.tree.topLevelItem(0))

    def target(self) -> int | None:
        it = self.tree.currentItem()
        return it.data(0, Qt.UserRole) if it else None


# ======================================================================= new phrase info
class NewPhraseInfoDialog(QDialog):
    """PhraseExpress "Enter additional information for the new phrase...": description,
    triggers (same rows as the phrase editor), "Execute only in specific programs" and
    "Save in folder" with a folder picker. Shown after the Create-new-phrase hotkey when
    Settings > Display "Prompt for additional information..." is on."""

    def __init__(self, store: Store, description: str = "", folder_id: int | None = None, parent=None):
        super().__init__(parent)
        from phraseforge.ui.trigger_editor import TriggerList
        self.store = store
        self.setWindowTitle("Enter additional information for the new phrase...")
        self.resize(560, 240)
        lay = QVBoxLayout(self)
        cap = QLabel("<b><u>D</u>escription</b>")
        lay.addWidget(cap)
        self.description = QLineEdit(description)
        cap.setBuddy(self.description)
        lay.addWidget(self.description)
        self.trigger_list = TriggerList("Trigger")
        lay.addWidget(self.trigger_list)
        self.trigger_list.set_rows([])
        self.only_programs = QCheckBox("Execute only in specific programs")
        lay.addWidget(self.only_programs)
        self.programs = QLineEdit()
        self.programs.setPlaceholderText("Program file names, e.g. winword.exe, outlook.exe")
        self.programs.setVisible(False)
        self.only_programs.toggled.connect(self.programs.setVisible)
        lay.addWidget(self.programs)
        row = QHBoxLayout()
        row.addSpacing(30)
        row.addWidget(QLabel("Save in folder"))
        self.folder = QComboBox()
        self.folder.setProperty("pf_user", True)        # the user's folder names
        self.folder.setMinimumWidth(180)
        self._fill_folders(folder_id)
        row.addWidget(self.folder)
        self.pick = QToolButton()
        self.pick.setIcon(icon("folder"))
        self.pick.setToolTip("Select target folder...")
        self.pick.clicked.connect(self._pick_folder)
        row.addWidget(self.pick)
        row.addStretch(1)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.description.setFocus()
        self.description.selectAll()

    def _fill_folders(self, select_id) -> None:
        self.folder.clear()
        self.folder.addItem("Phrases", None)

        def walk(parent_id, depth):
            for f in self.store.folders(parent_id):
                self.folder.addItem("    " * depth + f.name, f.id)
                walk(f.id, depth + 1)
        walk(None, 1)
        self.set_folder(select_id)

    def set_folder(self, folder_id) -> None:
        i = self.folder.findData(folder_id)
        self.folder.setCurrentIndex(max(0, i))

    def _pick_folder(self) -> None:
        dlg = MoveToDialog(self.store, "", parent=self)
        dlg.setWindowTitle("Select target folder...")
        dlg.copy.setVisible(False)
        if dlg.exec():
            self.set_folder(dlg.target())

    def folder_id(self):
        return self.folder.currentData()

    def phrase(self, content: str = "") -> Phrase:
        """The new phrase described by the dialog (not yet stored)."""
        desc = self.description.text().strip() or (content.strip().splitlines() or ["New phrase"])[0][:60]
        p = Phrase(desc, content, folder_id=self.folder_id())
        if self.only_programs.isChecked():
            p.apps_include = self.programs.text().strip()
        p.triggers = self.trigger_list.triggers()
        return p


# ======================================================================= find & replace
class FindReplaceDialog(QDialog):
    """Find (and replace) across phrases of a scope (folder subtree, or all)."""
    found = Signal(int)          # phrase id of the current hit

    def __init__(self, store: Store, scope_title: str, folder_id: int | None = None,
                 phrase_id: int | None = None, parent=None):
        super().__init__(parent)
        self.store = store
        self.folder_id, self.phrase_id = folder_id, phrase_id
        self.setWindowTitle(f"Find and Replace in: {scope_title}")
        self.hits: list[int] = []
        self.pos = -1
        grid = QGridLayout(self)
        sb = QGroupBox("Search")
        sg = QGridLayout(sb)
        self.in_desc = QCheckBox("Description")
        self.in_text = QCheckBox("Phrase text")
        self.in_auto = QCheckBox("Autotext")
        self.in_hotkey = QCheckBox("Hotkey")
        for c in (self.in_desc, self.in_text, self.in_auto):
            c.setChecked(True)
        sg.addWidget(self.in_desc, 0, 0)
        sg.addWidget(self.in_auto, 0, 1)
        sg.addWidget(self.in_text, 1, 0)
        sg.addWidget(self.in_hotkey, 1, 1)
        grid.addWidget(sb, 0, 0, 1, 2)
        grid.addWidget(QLabel("Find:"), 1, 0)
        self.find = QLineEdit()
        grid.addWidget(self.find, 1, 1)
        grid.addWidget(QLabel("Replace:"), 2, 0)
        self.replace = QLineEdit()
        grid.addWidget(self.replace, 2, 1)
        ob = QGroupBox("Options")
        og = QGridLayout(ob)
        self.match_case = QCheckBox("Match case")
        self.whole = QCheckBox("Match whole word")
        self.regex = QCheckBox("RegEx")
        self.exact = QCheckBox("Exact match")
        self.subfolders = QCheckBox("Include sub folders")
        self.subfolders.setChecked(True)
        self.subfolders.setEnabled(phrase_id is None)
        og.addWidget(self.match_case, 0, 0)
        og.addWidget(self.whole, 0, 1)
        og.addWidget(self.regex, 0, 2)
        og.addWidget(self.exact, 1, 0)
        og.addWidget(self.subfolders, 1, 1)
        grid.addWidget(ob, 4, 0, 1, 2)
        grid.setRowStretch(3, 1)
        col = QVBoxLayout()
        self.b_next = QPushButton("Find Next")
        self.b_prev = QPushButton("Find Previous")
        self.b_repl = QPushButton("Replace")
        self.b_all = QPushButton("Replace All")
        for b in (self.b_next, self.b_prev):
            col.addWidget(b)
        col.addSpacing(8)
        for b in (self.b_repl, self.b_all):
            col.addWidget(b)
        col.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        col.addWidget(close)
        hb = QPushButton("Help")
        hb.clicked.connect(lambda: QMessageBox.information(self, "Help", "Searches the selected scope."))
        col.addWidget(hb)
        grid.addLayout(col, 0, 2, 5, 1)
        self.b_next.clicked.connect(lambda: self.step(1))
        self.b_prev.clicked.connect(lambda: self.step(-1))
        self.b_repl.clicked.connect(self.replace_current)
        self.b_all.clicked.connect(self.replace_all)
        self.find.textChanged.connect(self._update_buttons)
        self.find.textChanged.connect(lambda *_: setattr(self, "hits", []))
        self._update_buttons()

    def _update_buttons(self) -> None:
        has = bool(self.find.text())
        for b in (self.b_next, self.b_prev, self.b_repl, self.b_all):
            b.setEnabled(has)

    def _pattern(self) -> re.Pattern:
        text = self.find.text()
        pat = text if self.regex.isChecked() else re.escape(text)
        if self.exact.isChecked():
            pat = f"^{pat}$"
        elif self.whole.isChecked():
            pat = rf"\b{pat}\b"
        return re.compile(pat, 0 if self.match_case.isChecked() else re.IGNORECASE)

    def _scope_phrases(self) -> list[Phrase]:
        if self.phrase_id is not None:
            p = self.store.get_phrase(self.phrase_id)
            return [p] if p else []
        if self.folder_id is None:
            return self.store.phrases()
        ids = {self.folder_id}
        if self.subfolders.isChecked():
            todo = [self.folder_id]
            while todo:
                for f in self.store.folders(todo.pop()):
                    ids.add(f.id)
                    todo.append(f.id)
        return [p for p in self.store.phrases() if p.folder_id in ids]

    def _fields(self, p: Phrase) -> list[str]:
        out = []
        if self.in_desc.isChecked():
            out.append(p.description)
        if self.in_text.isChecked():
            out.append(p.content)
        if self.in_auto.isChecked():
            out += [t.value for t in p.triggers if t.kind in (TriggerKind.AUTOTEXT, TriggerKind.REGEX)]
        if self.in_hotkey.isChecked():
            out += [t.value for t in p.triggers if t.kind == TriggerKind.HOTKEY]
        return out

    def search(self) -> list[int]:
        try:
            rx = self._pattern()
        except re.error as e:
            QMessageBox.warning(self, "RegEx", str(e))
            return []
        self.hits = [p.id for p in self._scope_phrases() if any(rx.search(f or "") for f in self._fields(p))]
        return self.hits

    def step(self, d: int) -> int | None:
        if not self.hits:
            self.search()
            self.pos = -1 if d > 0 else len(self.hits)
        if not self.hits:
            QMessageBox.information(self, "Find", "Text not found.")
            return None
        self.pos = (self.pos + d) % len(self.hits)
        self.found.emit(self.hits[self.pos])
        return self.hits[self.pos]

    def _replace_in(self, p: Phrase) -> int:
        rx = self._pattern()
        repl = self.replace.text()
        n = 0
        if self.in_desc.isChecked():
            p.description, k = rx.subn(repl, p.description)
            n += k
        if self.in_text.isChecked():
            p.content, k = rx.subn(repl, p.content)
            n += k
        for t in p.triggers:
            if (self.in_auto.isChecked() and t.kind in (TriggerKind.AUTOTEXT, TriggerKind.REGEX)) or \
                    (self.in_hotkey.isChecked() and t.kind == TriggerKind.HOTKEY):
                t.value, k = rx.subn(repl, t.value)
                n += k
        if n:
            self.store.update_phrase(p)
        return n

    def replace_current(self) -> int:
        if not self.hits or self.pos < 0:
            if self.step(1) is None:
                return 0
        p = self.store.get_phrase(self.hits[self.pos])
        n = self._replace_in(p) if p else 0
        self.hits = []
        return n

    def replace_all(self, confirm: bool = False) -> int:
        total = sum(self._replace_in(p) for p in self._scope_phrases())
        self.hits = []
        if confirm or self.isVisible():
            QMessageBox.information(self, "Replace All", f"{total} replacement(s) made.")
        return total


# ======================================================================= print
def print_html(store: Store, phrases: list[Phrase]) -> str:
    """Two-column printout: Description | Trigger (as in the reference print preview)."""
    def esc(s: str) -> str:
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    rows = []
    for p in phrases:
        trig = ", ".join(t.value for t in p.triggers if t.enabled)
        rows.append(f"<tr><td>{esc(p.description)}</td><td>{esc(trig)}</td></tr>")
    return ("<html><body style='font-family:Arial;font-size:9pt'>"
            "<table width='100%' cellspacing='0' cellpadding='4'>"
            "<tr><th align='left' width='50%'>Description:</th><th align='left'>Trigger:</th></tr>"
            + "".join(rows) + "</table></body></html>")


class PrintPreviewDialog(QDialog):
    def __init__(self, html: str, parent=None):
        super().__init__(parent)
        from PySide6.QtPrintSupport import QPrinter, QPrintPreviewWidget, QPrintDialog
        self.setWindowTitle("Print preview")
        self.resize(740, 600)
        self.doc = QTextDocument()
        self.doc.setHtml(html)
        self.printer = QPrinter(QPrinter.HighResolution)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 8)
        self.preview = QPrintPreviewWidget(self.printer, self)
        self.preview.paintRequested.connect(self.doc.print_)
        lay.addWidget(self.preview, 1)
        bb = QHBoxLayout()
        bb.addStretch(1)
        pb = QPushButton("Print")
        cb = QPushButton("Cancel")
        bb.addWidget(pb)
        bb.addWidget(cb)
        bb.setContentsMargins(0, 0, 10, 0)
        lay.addLayout(bb)
        cb.clicked.connect(self.reject)

        def do_print():
            d = QPrintDialog(self.printer, self)
            if d.exec() == QDialog.Accepted:
                self.doc.print_(self.printer)
                self.accept()
        pb.clicked.connect(do_print)


# ======================================================================= restore
class RestoreBackupDialog(QDialog):
    """List of archived backups (timestamp), delete button, 'Restore selected file version'."""

    def __init__(self, backups: list[Path], title: str = "Phrases", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'Restore from "{title}"')
        self.resize(360, 570)
        self.backups = sorted(backups, key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
        lay = QVBoxLayout(self)
        self.count = QLabel()
        lay.addWidget(self.count)
        self.list = QTreeWidget()
        self.list.setHeaderLabels(["Timestamp"])
        self.list.setRootIsDecorated(False)
        lay.addWidget(self.list, 1)
        delete = QToolButton()
        delete.setIcon(icon("delete"))
        delete.setToolTip("Delete selected backup")
        delete.clicked.connect(self.delete_selected)
        lay.addWidget(delete)
        row = QHBoxLayout()
        self.restore_btn = QPushButton("Restore selected file version")
        self.restore_btn.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(self.restore_btn, 1)
        row.addWidget(cancel)
        lay.addLayout(row)
        self._fill()

    def _fill(self) -> None:
        self.list.clear()
        for p in self.backups:
            ts = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M") if p.exists() else p.name
            it = QTreeWidgetItem([ts])
            it.setToolTip(0, str(p))
            self.list.addTopLevelItem(it)
        self.count.setText(f"{len(self.backups)} archived files:")
        if self.backups:
            self.list.setCurrentItem(self.list.topLevelItem(0))
        self.restore_btn.setEnabled(bool(self.backups))

    def selected(self) -> Path | None:
        i = self.list.indexOfTopLevelItem(self.list.currentItem()) if self.list.currentItem() else -1
        return self.backups[i] if 0 <= i < len(self.backups) else None

    def delete_selected(self) -> None:
        p = self.selected()
        if p and QMessageBox.question(self, "Delete", f"Delete backup {p.name}?") == QMessageBox.Yes:
            try:
                p.unlink()
            except OSError as e:
                QMessageBox.warning(self, "Delete", str(e))
            self.backups.remove(p)
            self._fill()


# ======================================================================= history
class HistoryDialog(QDialog):
    def __init__(self, store: Store, phrase_id: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit history")
        self.resize(640, 420)
        self.chosen: dict | None = None
        lay = QHBoxLayout(self)
        self.list = QListWidget()
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.items = store.history(phrase_id)
        for h in self.items:
            self.list.addItem(f"{h['saved']}  —  {h['description']}")
        self.list.currentRowChanged.connect(
            lambda i: self.view.setPlainText(self.items[i]["content"] if i >= 0 else ""))
        side = QVBoxLayout()
        side.addWidget(self.list)
        b = QPushButton("Restore this version")
        b.clicked.connect(self._restore)
        side.addWidget(b)
        lay.addLayout(side, 1)
        lay.addWidget(self.view, 2)
        if self.items:
            self.list.setCurrentRow(0)

    def _restore(self) -> None:
        i = self.list.currentRow()
        if i >= 0:
            self.chosen = self.items[i]
            self.accept()


# ======================================================================= color gallery
THEME_TOP = ["#ffffff", "#000000", "#5b6272", "#c8d1d9", "#d0694a", "#c3a72a", "#8aa9a6", "#8b7b6e",
             "#73a35a", "#d29a4c"]
STANDARD = ["#c00000", "#ff0000", "#ffc000", "#ffff00", "#92d050", "#00b050", "#00b0f0", "#0070c0",
            "#002060", "#7030a0"]


def _shades(hex_color: str) -> list[str]:
    c = QColor(hex_color)
    out = []
    for f in (0.8, 0.6, 0.4, -0.25, -0.5):
        if f > 0:
            out.append(QColor(int(c.red() + (255 - c.red()) * f), int(c.green() + (255 - c.green()) * f),
                              int(c.blue() + (255 - c.blue()) * f)).name())
        else:
            out.append(c.darker(int(100 / (1 + f))).name())
    return out


class ColorGallery(QWidget):
    """Auto / Theme Colors grid / Standard Colors / More Colors... (like 14_dropdown_color)."""
    picked = Signal(object)      # hex string or None (Auto)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("QLabel#GalleryHeader{background:#e8e8e8;font-weight:600;padding:3px 6px;}"
                           "QToolButton{border:1px solid transparent;}"
                           "QToolButton:hover{border:1px solid #f29436;}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        auto = QToolButton()
        auto.setText("  Auto")
        auto.setIcon(self._swatch("#000000"))
        auto.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        auto.clicked.connect(lambda: self.picked.emit(None))
        lay.addWidget(auto)
        lay.addWidget(self._header("Theme Colors"))
        g = QGridLayout()
        g.setSpacing(3)
        for col, base in enumerate(THEME_TOP):
            g.addWidget(self._btn(base), 0, col)
            for row, s in enumerate(_shades(base), start=1):
                g.addWidget(self._btn(s), row + (1 if row else 0), col)
        lay.addLayout(g)
        lay.addWidget(self._header("Standard Colors"))
        h = QHBoxLayout()
        h.setSpacing(3)
        for c in STANDARD:
            h.addWidget(self._btn(c))
        lay.addLayout(h)
        more = QToolButton()
        more.setText("More Colors...")
        more.clicked.connect(self._more)
        lay.addWidget(more)

    @staticmethod
    def _swatch(color: str) -> "QIcon":
        from PySide6.QtGui import QIcon
        pm = QPixmap(14, 14)
        pm.fill(QColor(color))
        p = QPainter(pm)
        p.setPen(QColor("#a0a0a0"))
        p.drawRect(0, 0, 13, 13)
        p.end()
        return QIcon(pm)

    def _header(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("GalleryHeader")
        return lab

    def _btn(self, color: str) -> QToolButton:
        b = QToolButton()
        b.setIcon(self._swatch(color))
        b.setIconSize(QSize(14, 14))
        b.setToolTip(color)
        b.clicked.connect(lambda _=False, c=color: self.picked.emit(c))
        return b

    def _more(self) -> None:
        c = QColorDialog.getColor(parent=self)
        if c.isValid():
            self.picked.emit(c.name())


def color_menu(parent, on_pick: Callable[[str | None], None]) -> QMenu:
    m = QMenu(parent)
    gal = ColorGallery(m)
    wa = QWidgetAction(m)
    wa.setDefaultWidget(gal)
    m.addAction(wa)
    gal.picked.connect(lambda c: (m.close(), on_pick(c)))
    m.gallery = gal
    return m


# ======================================================================= big-icon File menu
class _BigIconStyle:
    """Proxy style that makes menu icons 32px (created lazily: needs a QApplication)."""
    _inst = None

    @classmethod
    def get(cls):
        if cls._inst is None:
            from PySide6.QtWidgets import QProxyStyle, QStyle

            class S(QProxyStyle):
                def pixelMetric(self, metric, option=None, widget=None):  # noqa: N802
                    if metric == QStyle.PM_SmallIconSize:
                        return 32
                    return super().pixelMetric(metric, option, widget)
            cls._inst = S("Fusion")
        return cls._inst


class FileMenu(QMenu):
    """Application menu with a blue 'File' header and 32px icons (04_file_menu)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FileMenu")
        self.setStyle(_BigIconStyle.get())
        self.setStyleSheet(
            "QMenu#FileMenu{background:white;border:1px solid #2b579a;padding:0 0 4px 0;}"
            "QMenu#FileMenu::item{padding:10px 40px 10px 8px;font-weight:600;}"
            "QMenu#FileMenu::item:selected{background:#cce4f7;}"
            "QMenu#FileMenu::icon{padding-left:8px;}"
            "QMenu#FileMenu::separator{height:1px;background:#d0d0d0;margin:2px 10px 2px 46px;}")
        head = QLabel("File")
        head.setStyleSheet("background:#2b579a;color:white;font-size:11pt;padding:6px 12px;")
        wa = QWidgetAction(self)
        wa.setDefaultWidget(head)
        self.addAction(wa)

    def add(self, text: str, icon_name: str, target, shortcut: str = "", enabled: bool = True) -> QAction:
        if isinstance(target, QMenu):
            target.setTitle(text)
            target.setIcon(icon(icon_name))
            a = self.addMenu(target)
        else:
            a = QAction(icon(icon_name), text, self)
            if target:
                a.triggered.connect(lambda _=False, f=target: f())
            self.addAction(a)
        if shortcut:
            a.setShortcut(shortcut)
        a.setEnabled(enabled)
        return a


def big_submenu(parent, items: list[tuple[str, str, Callable | None, bool]]) -> QMenu:
    """Sub menu with 32px icons (File > Open, Migration Assistant)."""
    m = QMenu(parent)
    m.setStyle(_BigIconStyle.get())
    m.setStyleSheet("QMenu{background:white;border:1px solid #c6c6c6;}"
                    "QMenu::item{padding:12px 30px 12px 8px;font-weight:600;}"
                    "QMenu::item:selected{background:#cce4f7;}QMenu::icon{padding-left:8px;}")
    for text, icon_name, cb, enabled in items:
        a = QAction(icon(icon_name), text, m)
        if cb:
            a.triggered.connect(lambda _=False, f=cb: f())
        a.setEnabled(enabled)
        m.addAction(a)
    return m
