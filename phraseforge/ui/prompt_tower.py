"""Prompt Tower window: pick project files, add text before/after, copy the prompt.

Workflow of the Prompt Tower VS Code extension, rebuilt for PhraseForge (see
phraseforge/prompttower.py and docs/PROMPT_TOWER_SPEC.md).
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
    QToolButton, QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator, QVBoxLayout, QWidget,
)

from phraseforge import prompttower as pt
from phraseforge.ui.i18n import tr
from phraseforge.ui.icons import app_icon

ROLE_REL = Qt.UserRole
ROLE_DIR = Qt.UserRole + 1
ROLE_SIZE = Qt.UserRole + 2
BIG_FILE_KB = 500             # ask before adding a file bigger than this (like the extension)
TOKEN_WARNING = 200_000       # colour the token count when the prompt gets this big
FORMATS = (("XML tags", "xml"), ("Markdown", "markdown"), ("Custom", "custom"))
TREE_TYPES = (("Whole project tree", "full"), ("Folders only", "directories"),
              ("Selected files only", "selected"), ("No tree", "none"))


class TemplateDialog(QDialog):
    """Edit the output templates (Custom format)."""

    def __init__(self, fmt: pt.OutputFormat, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Prompt templates"))
        self.resize(640, 520)
        f = QFormLayout(self)

        def edit(text: str, h: int = 70) -> QPlainTextEdit:
            e = QPlainTextEdit(text)
            e.setFont(QFont("Consolas", 9))
            e.setFixedHeight(h)
            return e
        self.block = edit(fmt.block, 90)
        self.separator = QLineEdit(fmt.separator.encode("unicode_escape").decode("ascii"))
        self.tree = edit(fmt.tree_template)
        self.wrapper = edit(fmt.wrapper, 90)
        self.trim = QCheckBox(tr("Trim blank lines at the start and end of each file"))
        self.trim.setChecked(fmt.trim_blank_lines)
        f.addRow(QLabel(tr("Each file: {fileContent} {rawFilePath} {fileNameWithExtension} {fileName} "
                           "{fileExtension} {fullPath}")))
        f.addRow(tr("File block:"), self.block)
        f.addRow(tr("Between files (\\n = new line):"), self.separator)
        f.addRow(tr("Project tree ({projectTree}):"), self.tree)
        f.addRow(QLabel(tr("Whole prompt: {treeBlock} {blocks} {fileCount} {timestamp} {workspaceRoot}. "
                           "Leave empty for no wrapper.")))
        f.addRow(tr("Wrapper:"), self.wrapper)
        f.addRow(self.trim)
        row = QHBoxLayout()
        for label, maker in ((tr("XML defaults"), pt.OutputFormat), (tr("Markdown defaults"), pt.OutputFormat.markdown)):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, m=maker: self._load(m()))
            row.addWidget(b)
        row.addStretch(1)
        f.addRow(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self._tree_type, self._sizes = fmt.tree_type, fmt.tree_sizes

    def _load(self, fmt: pt.OutputFormat) -> None:
        self.block.setPlainText(fmt.block)
        self.separator.setText(fmt.separator.encode("unicode_escape").decode("ascii"))
        self.tree.setPlainText(fmt.tree_template)
        self.wrapper.setPlainText(fmt.wrapper)
        self.trim.setChecked(fmt.trim_blank_lines)

    def value(self) -> pt.OutputFormat:
        try:
            sep = self.separator.text().encode("ascii", "backslashreplace").decode("unicode_escape")
        except UnicodeDecodeError:
            sep = self.separator.text()
        return pt.OutputFormat(block=self.block.toPlainText(), separator=sep,
                               trim_blank_lines=self.trim.isChecked(), tree_type=self._tree_type,
                               tree_sizes=self._sizes, tree_template=self.tree.toPlainText(),
                               wrapper=self.wrapper.toPlainText())


class PromptTowerWindow(QWidget):
    """Folder tree with checkboxes on the left, prompt parts and actions on the right."""
    save_as_phrase = Signal(str, str)        # description, prompt text

    def __init__(self, store, parent=None):
        super().__init__(parent, Qt.Window)
        self.store = store
        self.tstore = pt.TowerStore(store)
        self.root: Path | None = None
        self.entries: list[pt.Entry] = []
        self._token_cache: dict[tuple[str, float, bool], int] = {}
        self._custom = pt.OutputFormat.from_dict(self._json_setting("prompttower.custom_format"))
        self.setWindowTitle("Prompt Tower - PhraseForge")
        self.setWindowIcon(app_icon())
        self.resize(1050, 680)
        lay = QVBoxLayout(self)

        # folder row
        top = QHBoxLayout()
        top.addWidget(QLabel(tr("Folder:")))
        self.folder = QComboBox()
        self.folder.setEditable(True)
        self.folder.setMinimumWidth(420)
        self.folder.addItems(self._recent_folders())
        self.folder.lineEdit().returnPressed.connect(lambda: self.open_folder(self.folder.currentText()))
        self.folder.activated.connect(lambda _i: self.open_folder(self.folder.currentText()))
        top.addWidget(self.folder, 1)
        b = QPushButton(tr("Browse..."))
        b.clicked.connect(self._browse)
        top.addWidget(b)
        b = QPushButton(tr("Refresh"))
        b.clicked.connect(lambda: self.open_folder(str(self.root or self.folder.currentText()), keep=True))
        top.addWidget(b)
        top.addSpacing(12)
        top.addWidget(QLabel(tr("Saved prompt:")))
        self.sets = QComboBox()
        self.sets.setMinimumWidth(160)
        self.sets.activated.connect(lambda _i: self.load_set(self.sets.currentText()))
        top.addWidget(self.sets)
        sm = QToolButton()
        sm.setText(tr("Save / delete"))
        sm.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(sm)
        m.addAction(tr("Save as a saved prompt..."), self._save_set_dialog)
        m.addAction(tr("Delete the selected saved prompt"), self._delete_set)
        sm.setMenu(m)
        top.addWidget(sm)
        lay.addLayout(top)

        split = QSplitter(Qt.Horizontal)
        lay.addWidget(split, 1)

        # left: files
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(tr("Filter files…"))
        self.filter.textChanged.connect(self._apply_filter)
        ll.addWidget(self.filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("File"), tr("Size")])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._preview_file(it))
        ll.addWidget(self.tree, 1)
        row = QHBoxLayout()
        for text, fn in ((tr("Select all"), lambda: self._check_all(True)),
                         (tr("Clear selection"), lambda: self._check_all(False))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        ll.addLayout(row)
        split.addWidget(left)

        # right: prompt parts
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 0, 0, 0)
        self.prefix = self._text_part(rl, tr("Text before the files (task, instructions):"), "prefix")
        self.suffix = self._text_part(rl, tr("Text after the files:"), "suffix")
        opts = QFormLayout()
        self.fmt_combo = QComboBox()
        for label, v in FORMATS:
            self.fmt_combo.addItem(tr(label), v)
        edit_tpl = QPushButton(tr("Templates..."))
        edit_tpl.clicked.connect(self._edit_templates)
        h = QHBoxLayout()
        h.addWidget(self.fmt_combo, 1)
        h.addWidget(edit_tpl)
        opts.addRow(tr("Format:"), h)
        self.tree_combo = QComboBox()
        for label, v in TREE_TYPES:
            self.tree_combo.addItem(tr(label), v)
        opts.addRow(tr("Project tree:"), self.tree_combo)
        self.sizes = QCheckBox(tr("Show file sizes in the tree"))
        self.no_comments = QCheckBox(tr("Remove code comments"))
        opts.addRow(self.sizes)
        opts.addRow(self.no_comments)
        rl.addLayout(opts)
        for w in (self.fmt_combo, self.tree_combo):
            w.currentIndexChanged.connect(lambda _i: self._schedule_tokens())
        for w in (self.sizes, self.no_comments):
            w.toggled.connect(lambda _on: self._schedule_tokens())
        self.tokens = QLabel()
        f = self.tokens.font()
        f.setBold(True)
        self.tokens.setFont(f)
        rl.addWidget(self.tokens)
        rl.addStretch(1)
        actions = QHBoxLayout()
        self.copy_btn = QPushButton(tr("Copy prompt"))
        self.copy_btn.setDefault(True)
        self.copy_btn.clicked.connect(self.copy_prompt)
        actions.addWidget(self.copy_btn)
        b = QPushButton(tr("Preview"))
        b.clicked.connect(self.preview)
        actions.addWidget(b)
        b = QPushButton(tr("Save as phrase"))
        b.clicked.connect(self._save_as_phrase)
        actions.addWidget(b)
        chat = QToolButton()
        chat.setText(tr("Open in AI chat"))
        chat.setPopupMode(QToolButton.InstantPopup)
        cm = QMenu(chat)
        for name, url in pt.CHAT_SITES.items():
            cm.addAction(name, lambda u=url: self.open_in_chat(u))
        chat.setMenu(cm)
        chat.setMinimumWidth(chat.fontMetrics().horizontalAdvance(chat.text()) + 36)
        actions.addWidget(chat)
        rl.addLayout(actions)
        split.addWidget(right)
        split.setSizes([560, 490])

        self._token_timer = QTimer(self, singleShot=True, interval=300)
        self._token_timer.timeout.connect(self._update_tokens)
        self._load_options()
        self._refresh_sets()
        if self.folder.count():
            self.open_folder(self.folder.itemText(0))
        else:
            self._update_tokens()

    # ---------------------------------------------------------------- settings helpers
    def _json_setting(self, key: str):
        import json
        try:
            return json.loads(self.store.setting(key, "") or "null")
        except ValueError:
            return None

    def _recent_folders(self) -> list[str]:
        v = self._json_setting("prompttower.recent")
        return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []

    def _remember_folder(self, path: str) -> None:
        import json
        items = [path] + [x for x in self._recent_folders() if os.path.normcase(x) != os.path.normcase(path)]
        self.store.set_setting("prompttower.recent", json.dumps(items[:10], ensure_ascii=False))

    def _load_options(self) -> None:
        o = self._json_setting("prompttower.options") or {}
        self._select(self.fmt_combo, o.get("format", "xml"))
        self._select(self.tree_combo, o.get("tree", "full"))
        self.sizes.setChecked(bool(o.get("sizes", False)))
        self.no_comments.setChecked(bool(o.get("no_comments", False)))

    def _save_options(self) -> None:
        import json
        self.store.set_setting("prompttower.options", json.dumps({
            "format": self.fmt_combo.currentData(), "tree": self.tree_combo.currentData(),
            "sizes": self.sizes.isChecked(), "no_comments": self.no_comments.isChecked()}))

    @staticmethod
    def _select(combo: QComboBox, value) -> None:
        i = combo.findData(value)
        if i >= 0:
            combo.setCurrentIndex(i)

    def boost_prefix(self, complete_fn=None) -> bool:
        """PromptBoost on the text before the files (the task description)."""
        from phraseforge.ui.ai_ui import enhance
        out = enhance(self.store, self.prefix.toPlainText(), parent=self,
                      quiet=getattr(self, "quiet", False), complete_fn=complete_fn, mode="boost")
        if not out:
            return False
        c = self.prefix.textCursor()
        c.select(c.SelectionType.Document)
        c.insertText(out)                     # one Ctrl+Z restores the original
        return True

    def _text_part(self, lay, label: str, kind: str) -> QPlainTextEdit:
        row = QHBoxLayout()
        row.addWidget(QLabel(label), 1)
        if kind == "prefix":
            bb = QToolButton()
            bb.setText(tr("Boost"))
            bb.setToolTip(tr("PromptBoost: rewrite the task as a detailed, structured prompt (Settings > AI)."))
            bb.clicked.connect(lambda: self.boost_prefix())
            row.addWidget(bb)
        hb = QToolButton()
        hb.setText(tr("History"))
        hb.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(hb)
        hb.setMenu(menu)
        row.addWidget(hb)
        lay.addLayout(row)
        edit = QPlainTextEdit()
        edit.setFixedHeight(110)
        edit.textChanged.connect(self._schedule_tokens)
        lay.addWidget(edit)

        def fill():
            menu.clear()
            items = self.tstore.history(kind)
            if not items:
                a = menu.addAction(tr("(empty)"))
                a.setEnabled(False)
            for text in items:
                short = " ".join(text.split())
                a = menu.addAction(short[:70] + ("…" if len(short) > 70 else ""))
                a.triggered.connect(lambda _=False, t=text: edit.setPlainText(t))
        menu.aboutToShow.connect(fill)
        return edit

    # ---------------------------------------------------------------- folder and tree
    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, tr("Choose the project folder"),
                                             str(self.root or Path.home()))
        if d:
            self.open_folder(d)

    def open_folder(self, path: str, keep: bool = False) -> bool:
        path = (path or "").strip().strip('"')
        if not path or not Path(path).is_dir():
            self.tokens.setText(tr("Choose a project folder."))
            return False
        checked = set(self.selected_files()) if keep else set()
        self.root = Path(path)
        rules = pt.load_rules(self.root, self.store.setting("prompttower.use_gitignore", "1") == "1",
                              self.store.setting("prompttower.ignore", ""))
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.entries = pt.scan(self.root, rules)
        finally:
            QApplication.restoreOverrideCursor()
        self._fill_tree(checked)
        self._remember_folder(str(self.root))
        if self.folder.currentText() != str(self.root):
            self.folder.setEditText(str(self.root))
        self._schedule_tokens()
        return True

    def _fill_tree(self, checked: set[str]) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        items: dict[str, QTreeWidgetItem] = {}
        for e in self.entries:
            parent_rel = e.rel.rsplit("/", 1)[0] if "/" in e.rel else ""
            parent = items.get(parent_rel)
            it = QTreeWidgetItem([e.rel.rsplit("/", 1)[-1], "" if e.is_dir else pt.human_size(e.size)])
            it.setData(0, ROLE_REL, e.rel)
            it.setData(0, ROLE_DIR, e.is_dir)
            it.setData(0, ROLE_SIZE, e.size)
            flags = it.flags() | Qt.ItemIsUserCheckable
            if e.is_dir:
                flags |= Qt.ItemIsAutoTristate
            it.setFlags(flags)
            it.setCheckState(0, Qt.Checked if e.rel in checked else Qt.Unchecked)
            (parent.addChild(it) if parent else self.tree.addTopLevelItem(it))
            items[e.rel] = it
        self.tree.blockSignals(False)
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setExpanded(self.tree.topLevelItemCount() < 15)

    def _iter_items(self):
        it = QTreeWidgetItemIterator(self.tree)
        while it.value():
            yield it.value()
            it += 1

    def selected_files(self) -> list[str]:
        return [i.data(0, ROLE_REL) for i in self._iter_items()
                if not i.data(0, ROLE_DIR) and i.checkState(0) == Qt.Checked]

    def set_selected(self, files) -> None:
        wanted = set(files)
        self.tree.blockSignals(True)
        for i in self._iter_items():
            if not i.data(0, ROLE_DIR):
                i.setCheckState(0, Qt.Checked if i.data(0, ROLE_REL) in wanted else Qt.Unchecked)
        self.tree.blockSignals(False)
        # folders update their tri-state from the children
        for i in self._iter_items():
            if not i.data(0, ROLE_DIR) and i.checkState(0) == Qt.Checked:
                p = i.parent()
                while p is not None:
                    p.setExpanded(True)
                    p = p.parent()
        self.tree.viewport().update()
        self._schedule_tokens()

    def _check_all(self, on: bool) -> None:
        self.set_selected([i.data(0, ROLE_REL) for i in self._iter_items() if not i.data(0, ROLE_DIR)] if on else [])

    def _item_changed(self, item: QTreeWidgetItem, col: int) -> None:
        if col != 0:
            return
        if (not item.data(0, ROLE_DIR) and item.checkState(0) == Qt.Checked
                and (item.data(0, ROLE_SIZE) or 0) > BIG_FILE_KB * 1024 and not getattr(self, "quiet", False)):
            ok = QMessageBox.question(self, "Prompt Tower",
                                      tr("This file is large ({size}). Add it to the prompt?").replace(
                                          "{size}", pt.human_size(item.data(0, ROLE_SIZE))))
            if ok != QMessageBox.Yes:
                self.tree.blockSignals(True)
                item.setCheckState(0, Qt.Unchecked)
                self.tree.blockSignals(False)
        self._schedule_tokens()

    def _apply_filter(self, text: str) -> None:
        words = text.lower().split()
        for i in self._iter_items():
            if i.data(0, ROLE_DIR):
                continue
            rel = i.data(0, ROLE_REL).lower()
            i.setHidden(bool(words) and not all(w in rel for w in words))
        for i in reversed(list(self._iter_items())):       # hide folders with no visible files
            if i.data(0, ROLE_DIR):
                visible = any(not i.child(k).isHidden() for k in range(i.childCount()))
                i.setHidden(bool(words) and not visible)
                if words and visible:
                    i.setExpanded(True)

    def _preview_file(self, item: QTreeWidgetItem) -> None:
        if item is None or item.data(0, ROLE_DIR) or self.root is None:
            return
        text = pt.read_text(self.root / item.data(0, ROLE_REL))
        self._show_text(item.data(0, ROLE_REL), text if text is not None else tr("(binary file)"))

    # ---------------------------------------------------------------- building
    def current_format(self) -> pt.OutputFormat:
        kind = self.fmt_combo.currentData()
        fmt = pt.OutputFormat.markdown() if kind == "markdown" else (
            pt.OutputFormat.from_dict(self._custom.__dict__) if kind == "custom" else pt.OutputFormat())
        fmt.tree_type = self.tree_combo.currentData()
        fmt.tree_sizes = self.sizes.isChecked()
        return fmt

    def build(self) -> pt.Result:
        if self.root is None:
            return pt.Result(self.prefix.toPlainText().strip(), 0, 0)
        return pt.build_prompt(self.root, self.selected_files(), self.current_format(),
                               self.prefix.toPlainText(), self.suffix.toPlainText(),
                               self.no_comments.isChecked(), self.entries)

    def _schedule_tokens(self) -> None:
        self._token_timer.start()

    def _update_tokens(self) -> None:
        files = self.selected_files()
        if self.root is None:
            self.tokens.setText(tr("Choose a project folder."))
            return
        try:
            n = self.build().tokens
        except Exception as e:      # noqa: BLE001
            self.tokens.setText(str(e))
            return
        self.tokens.setText(tr("{files} files selected · about {tokens} tokens")
                            .replace("{files}", str(len(files))).replace("{tokens}", f"{n:,}"))
        self.tokens.setStyleSheet("color:#c42b1c" if n >= TOKEN_WARNING else "")

    def _remember_texts(self) -> None:
        self.tstore.remember("prefix", self.prefix.toPlainText())
        self.tstore.remember("suffix", self.suffix.toPlainText())
        self._save_options()

    def copy_prompt(self) -> str:
        res = self.build()
        QApplication.clipboard().setText(res.text)
        self._remember_texts()
        note = tr("Copied: {files} files, about {tokens} tokens.").replace(
            "{files}", str(res.files)).replace("{tokens}", f"{res.tokens:,}")
        if res.skipped:
            note += " " + tr("Skipped (binary or unreadable): ") + ", ".join(res.skipped[:5])
        self.tokens.setText(note)
        return res.text

    def preview(self) -> None:
        res = self.build()
        self._show_text(tr("Prompt preview"), res.text)

    def _show_text(self, title: str, text: str) -> None:
        if getattr(self, "quiet", False):
            self._last_shown = text
            return
        d = QDialog(self)
        d.setWindowTitle(title)
        d.resize(820, 620)
        v = QVBoxLayout(d)
        e = QPlainTextEdit(text)
        e.setReadOnly(True)
        e.setFont(QFont("Consolas", 9))
        v.addWidget(e)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        cp = bb.addButton(tr("Copy"), QDialogButtonBox.ActionRole)
        cp.clicked.connect(lambda: QApplication.clipboard().setText(text))
        bb.rejected.connect(d.reject)
        v.addWidget(bb)
        d.exec()

    def open_in_chat(self, url: str) -> None:
        """Copy the prompt and open the chat site; paste it there with Ctrl+V."""
        self.copy_prompt()
        QDesktopServices.openUrl(QUrl(url))
        self.tokens.setText(self.tokens.text() + " " + tr("Paste it in the chat with Ctrl+V."))

    def _save_as_phrase(self) -> None:
        res = self.build()
        name = (self.sets.currentText() or (self.root.name if self.root else "")) or "Prompt"
        self._remember_texts()
        self.save_as_phrase.emit(f"Prompt: {name}", res.text)
        self.tokens.setText(tr("Saved as a phrase."))

    def _edit_templates(self) -> None:
        d = TemplateDialog(self._custom, self)
        if d.exec() == QDialog.Accepted:
            import json
            self._custom = d.value()
            self.store.set_setting("prompttower.custom_format", json.dumps(self._custom.__dict__))
            self._select(self.fmt_combo, "custom")
            self._schedule_tokens()

    # ---------------------------------------------------------------- saved prompts
    def _refresh_sets(self, current: str = "") -> None:
        self.sets.clear()
        self.sets.addItems([s.name for s in self.tstore.sets()])
        if current:
            self.sets.setCurrentText(current)

    def current_set(self, name: str) -> pt.PromptSet:
        kind = self.fmt_combo.currentData()
        fmt = self.current_format().__dict__ if kind == "custom" else {
            **(pt.OutputFormat.markdown() if kind == "markdown" else pt.OutputFormat()).__dict__,
            "tree_type": self.tree_combo.currentData(), "tree_sizes": self.sizes.isChecked()}
        return pt.PromptSet(name=name, root=str(self.root or ""), files=self.selected_files(),
                            prefix=self.prefix.toPlainText(), suffix=self.suffix.toPlainText(),
                            remove_comments=self.no_comments.isChecked(), format={**fmt, "kind": kind})

    def save_set(self, name: str) -> None:
        name = name.strip()
        if not name:
            return
        self.tstore.save(self.current_set(name))
        self._remember_texts()
        self._refresh_sets(name)

    def _save_set_dialog(self) -> None:
        name, ok = QInputDialog.getText(self, "Prompt Tower", tr("Name of the saved prompt:"),
                                        text=self.sets.currentText())
        if ok and name.strip():
            self.save_set(name)

    def _delete_set(self) -> None:
        name = self.sets.currentText()
        if name and QMessageBox.question(self, "Prompt Tower", tr("Delete the saved prompt?") + f"\n{name}") \
                == QMessageBox.Yes:
            self.tstore.delete(name)
            self._refresh_sets()

    def load_set(self, name: str) -> bool:
        s = self.tstore.get(name)
        if s is None:
            return False
        if s.root and (self.root is None or Path(s.root) != self.root):
            self.open_folder(s.root)
        kind = (s.format or {}).get("kind", "xml")
        if kind == "custom":
            self._custom = pt.OutputFormat.from_dict(s.format)
        self._select(self.fmt_combo, kind)
        self._select(self.tree_combo, (s.format or {}).get("tree_type", "full"))
        self.sizes.setChecked(bool((s.format or {}).get("tree_sizes", False)))
        self.no_comments.setChecked(s.remove_comments)
        self.prefix.setPlainText(s.prefix)
        self.suffix.setPlainText(s.suffix)
        self.set_selected(s.files)
        self.sets.setCurrentText(s.name)
        return True

    def closeEvent(self, e) -> None:      # noqa: N802
        import sqlite3
        try:
            self._save_options()
        except sqlite3.ProgrammingError:     # the database was already closed (app quitting)
            pass
        super().closeEvent(e)
