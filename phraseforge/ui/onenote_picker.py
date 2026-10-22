"""Choose OneNote notebooks / sections / pages.

Modes:
  "target"  pick one page or section (output target, default target, macro)
  "page"    pick one page only (Insert from OneNote macro)
  "import"  tick sections / section groups / notebooks (Import from OneNote)

The hierarchy is loaded in a background thread: COM objects belong to the thread
that created them, so the thread creates its own client (client_factory()).
References are stored as paths ("Notebook/Section/Page"), which stay valid on
other PCs where OneNote IDs differ.
"""
from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QStackedWidget,
    QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator, QVBoxLayout, QWidget,
)

from phraseforge.ui.iconset import icon

ROLE_REF = Qt.UserRole
ROLE_KIND = Qt.UserRole + 1
KIND_ICON = {"notebook": "on_notebook", "group": "on_group", "section": "on_section", "page": "on_page"}


def default_client_factory(exe: str = ""):
    from phraseforge.onenote import OneNote
    return lambda: OneNote(exe)


class _Loader(QObject):
    done = Signal(object)        # list[Node]
    failed = Signal(str)


class OneNotePicker(QDialog):
    def __init__(self, parent=None, mode: str = "target", current: str = "",
                 client_factory: Callable | None = None, exe: str = "", synchronous: bool = False):
        super().__init__(parent)
        self.mode = mode
        self.current = current or ""
        self.client_factory = client_factory or default_client_factory(exe)
        self.synchronous = synchronous           # tests: load on the calling thread
        self.nodes: list = []
        self.setWindowTitle({"import": "Import from OneNote", "page": "Choose a OneNote page"}
                            .get(mode, "Choose a OneNote page or section"))
        self.resize(460, 560)

        lay = QVBoxLayout(self)
        hint = {"import": "Tick the notebooks, section groups or sections to import. Each page becomes a phrase.",
                "page": "Choose the page whose text is inserted."}.get(
            mode, "Choose a page (text is added to it) or a section (a new page is created there).")
        lab = QLabel(hint)
        lab.setWordWrap(True)
        lay.addWidget(lab)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter")
        self.filter.textChanged.connect(self._apply_filter)
        lay.addWidget(self.filter)

        self.stack = QStackedWidget()
        self.status = QLabel("Loading OneNote notebooks...")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setWordWrap(True)
        err = QWidget()
        el = QVBoxLayout(err)
        el.addStretch(1)
        el.addWidget(self.status)
        self.retry = QPushButton("Retry")
        self.retry.clicked.connect(self.load)
        self.retry.setVisible(False)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.retry)
        row.addStretch(1)
        el.addLayout(row)
        el.addStretch(1)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemSelectionChanged.connect(self._update_ok)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.itemDoubleClicked.connect(lambda *_: self.ok.isEnabled() and self.accept())
        self.stack.addWidget(err)
        self.stack.addWidget(self.tree)
        lay.addWidget(self.stack, 1)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok = bb.button(QDialogButtonBox.Ok)
        self.ok.setText("Import" if mode == "import" else "OK")
        self.ok.setEnabled(False)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        self._loader = _Loader()
        self._loader.done.connect(self._loaded)
        self._loader.failed.connect(self._failed)
        self.load()

    # ---------------------------------------------------- loading
    def load(self) -> None:
        self.retry.setVisible(False)
        self.status.setText("Loading OneNote notebooks...")
        self.stack.setCurrentIndex(0)
        self.ok.setEnabled(False)

        def work():
            try:
                nodes = self.client_factory().notebooks()
            except Exception as e:  # OneNote missing, not running, COM error...
                self._loader.failed.emit(str(e) or e.__class__.__name__)
                return
            self._loader.done.emit(nodes)

        if self.synchronous:
            work()
        else:
            threading.Thread(target=work, name="onenote-picker", daemon=True).start()

    def _failed(self, msg: str) -> None:
        self.status.setText(f"OneNote is not available.\n\n{msg}\n\n"
                            "Make sure the OneNote desktop app is installed and opened once.")
        self.retry.setVisible(True)
        self.stack.setCurrentIndex(0)

    def _loaded(self, nodes: list) -> None:
        self.nodes = nodes
        self.tree.blockSignals(True)
        self.tree.clear()
        for n in nodes:
            self._add(self.tree.invisibleRootItem(), n)
        self.tree.blockSignals(False)
        self.stack.setCurrentIndex(1)
        if not nodes:
            self.status.setText("No OneNote notebooks found.")
            self.stack.setCurrentIndex(0)
            return
        for it in self._items():                 # open the notebooks; select the current ref
            if it.data(0, ROLE_KIND) == "notebook":
                it.setExpanded(True)
            if self.current and it.data(0, ROLE_REF).lower() == self.current.replace("\\", "/").lower():
                self.tree.setCurrentItem(it)
                p = it.parent()
                while p is not None:
                    p.setExpanded(True)
                    p = p.parent()
        self._update_ok()

    def _add(self, parent: QTreeWidgetItem, node) -> None:
        if self.mode == "import" and node.kind == "page":
            return                                # import picks containers only
        it = QTreeWidgetItem(parent, [node.name or "(untitled)"])
        it.setIcon(0, icon(KIND_ICON.get(node.kind, "")))
        it.setData(0, ROLE_REF, node.path)
        it.setData(0, ROLE_KIND, node.kind)
        it.setToolTip(0, node.path)
        if self.mode == "import":
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Unchecked)
        else:
            selectable = node.kind == "page" or (self.mode == "target" and node.kind == "section")
            if not selectable:
                it.setFlags(it.flags() & ~Qt.ItemIsSelectable)
        for c in node.children:
            self._add(it, c)

    # ---------------------------------------------------- interaction
    def _items(self):
        itr = QTreeWidgetItemIterator(self.tree)
        while itr.value():
            yield itr.value()
            itr += 1

    def _apply_filter(self, text: str) -> None:
        t = text.strip().lower()

        def visit(item: QTreeWidgetItem) -> bool:
            child_match = any([visit(item.child(i)) for i in range(item.childCount())])
            match = not t or t in item.text(0).lower() or child_match
            item.setHidden(not match)
            if t and child_match:
                item.setExpanded(True)
            return match

        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            visit(root.child(i))

    def _item_changed(self, item: QTreeWidgetItem, _col: int) -> None:
        if self.mode != "import":
            return
        # ticking a container ticks everything inside (and vice versa)
        state = item.checkState(0)
        self.tree.blockSignals(True)
        stack = [item.child(i) for i in range(item.childCount())]
        while stack:
            c = stack.pop()
            c.setCheckState(0, state)
            stack.extend(c.child(i) for i in range(c.childCount()))
        self.tree.blockSignals(False)
        self._update_ok()

    def _update_ok(self) -> None:
        if self.mode == "import":
            self.ok.setEnabled(bool(self.checked_refs()))
        else:
            self.ok.setEnabled(self.selected_ref() is not None)

    # ---------------------------------------------------- results
    def selected_ref(self) -> str | None:
        it = self.tree.currentItem()
        if it is None or not (it.flags() & Qt.ItemIsSelectable):
            return None
        kind = it.data(0, ROLE_KIND)
        if kind == "page" or (self.mode == "target" and kind == "section"):
            return it.data(0, ROLE_REF)
        return None

    def selected_kind(self) -> str | None:
        it = self.tree.currentItem()
        return it.data(0, ROLE_KIND) if it is not None else None

    def checked_refs(self) -> list[str]:
        """Top-most ticked items (a ticked notebook is returned once, not with all its sections)."""
        out = []

        def visit(item: QTreeWidgetItem) -> None:
            if item.checkState(0) == Qt.Checked:
                out.append(item.data(0, ROLE_REF))
                return
            for i in range(item.childCount()):
                visit(item.child(i))

        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            visit(root.child(i))
        return out
