"""Left-hand phrase tree (and the middle phrase list used by the three-column layout).

Item data: ROLE_KIND in {"last_used", "clipboard_cache", "clip", "sticky_notes", "note", "root",
"folder", "phrase", "up"}, ROLE_ID the folder/phrase/clipboard-entry id, the Sticky Notes note id
for "note" (None for special nodes).
"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from phraseforge.db import Store
from phraseforge.models import Phrase
from phraseforge.ui.i18n import tr
from phraseforge.ui.iconset import icon

ROLE_KIND = Qt.UserRole
ROLE_ID = Qt.UserRole + 1

SPECIAL = ("last_used", "clipboard_cache", "sticky_notes", "root")
LAST_USED_MAX = 20      # default; Settings > Features > Last used phrases (last_used.max)


def sticky_available() -> bool:
    """Sticky notes are built in, so the folder is always available."""
    return True


def sticky_notes(store: Store | None = None) -> list:
    """PhraseForge's sticky notes, newest first (tests monkeypatch this)."""
    if store is None:
        return []
    try:
        return store.sticky_notes()
    except Exception:
        return []


def show_sticky(store: Store) -> bool:
    """The folder appears once the user has a sticky note."""
    return _on(store, "stickynotes.show_folder") and sticky_available() and bool(sticky_notes(store))


def _on(store: Store, key: str, default: str = "1") -> bool:
    try:
        return (store.setting(key, default) or default) == "1"
    except Exception:
        return default == "1"


def last_used_max(store: Store) -> int:
    try:
        return max(1, int(store.setting("last_used.max", str(LAST_USED_MAX)) or LAST_USED_MAX))
    except ValueError:
        return LAST_USED_MAX


def item_colors(store: Store) -> dict[str, str]:
    try:
        return json.loads(store.setting("ui.item_colors", "{}") or "{}")
    except ValueError:
        return {}


def set_item_color(store: Store, kind: str, id_: int, color: str | None) -> None:
    m = item_colors(store)
    key = f"{kind}:{id_}"
    if color:
        m[key] = color
    else:
        m.pop(key, None)
    store.set_setting("ui.item_colors", json.dumps(m))


def sorted_folders(store: Store, parent_id):
    """Folders in display order: manual sort first, then case-insensitive name."""
    return sorted(store.folders(parent_id), key=lambda f: (f.sort, f.name.lower()))


def sorted_phrases(store: Store, folder_id):
    return sorted(store.phrases(folder_id), key=lambda p: (p.sort, p.description.lower()))


def phrase_label(p: Phrase) -> str:
    return p.description or "(no description)"


class PhraseTree(QTreeWidget):
    """Tree with drag & drop; drops are reported to the owner instead of moved by Qt."""
    dropped = Signal(str, int, object)   # kind, id, new parent folder id (None = root)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setEditTriggers(QAbstractItemView.EditKeyPressed)   # F2 renames
        self.setIndentation(14)
        self.setUniformRowHeights(True)

    def dropEvent(self, e):  # noqa: N802
        src = self.currentItem()
        target = self.itemAt(e.position().toPoint())
        e.ignore()
        if not src or src.data(0, ROLE_KIND) not in ("folder", "phrase"):
            return
        pos = self.dropIndicatorPosition()
        if target is None:
            return
        tk = target.data(0, ROLE_KIND)
        if tk == "root":
            new_parent = None
        elif tk == "folder" and pos == QAbstractItemView.OnItem:
            new_parent = target.data(0, ROLE_ID)
        elif tk in ("folder", "phrase"):
            par = target.parent()
            new_parent = par.data(0, ROLE_ID) if par and par.data(0, ROLE_KIND) == "folder" else None
        else:
            return
        self.dropped.emit(src.data(0, ROLE_KIND), src.data(0, ROLE_ID), new_parent)


class TreePanel(QWidget):
    """Header label + PhraseTree. `folders_only` is used by the three-column layout."""
    selected = Signal(str, object)       # kind, id

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self.unlocked: set[int] = set()
        self.folders_only = False
        self.notes_by_id: dict = {}          # Sticky Notes shown in the tree, by note id
        self.flat = False
        self.search_text = ""
        self.search_scope = "all"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.header = QLabel('Folders and phrases ("Default")')
        self.header.setObjectName("PanelHeader")
        lay.addWidget(self.header)
        self.tree = PhraseTree(self)
        lay.addWidget(self.tree, 1)
        self.tree.currentItemChanged.connect(self._emit_selected)

    # -------------------------------------------------- building
    def locked(self, folder_id: int | None) -> bool:
        return any(f.password_hash and f.id not in self.unlocked for f in self.store.folder_chain(folder_id))

    def _apply_color(self, it: QTreeWidgetItem, kind: str, id_: int, colors: dict) -> None:
        c = colors.get(f"{kind}:{id_}")
        if c:
            it.setForeground(0, QBrush(QColor(c)))

    def make_phrase_item(self, p: Phrase, colors: dict | None = None) -> QTreeWidgetItem:
        it = QTreeWidgetItem([phrase_label(p)])
        it.setIcon(0, icon("phrase_rich" if p.content_format == "html" else "phrase"))
        it.setData(0, ROLE_KIND, "phrase")
        it.setData(0, ROLE_ID, p.id)
        it.setFlags((it.flags() | Qt.ItemIsEditable) & ~Qt.ItemIsDropEnabled)
        tips = [t.value for t in p.triggers if t.enabled]
        it.setToolTip(0, f"{p.description}\n" + ("Trigger: " + ", ".join(tips) if tips else ""))
        if not p.enabled:
            it.setForeground(0, QBrush(QColor("#9a9a9a")))
        self._apply_color(it, "phrase", p.id, colors if colors is not None else item_colors(self.store))
        return it

    def _folder_item(self, f, colors) -> QTreeWidgetItem:
        it = QTreeWidgetItem([f.name])
        it.setIcon(0, icon("folder_locked" if f.password_hash else "folder"))
        it.setData(0, ROLE_KIND, "folder")
        it.setData(0, ROLE_ID, f.id)
        it.setFlags(it.flags() | Qt.ItemIsEditable)
        if not f.enabled:
            it.setForeground(0, QBrush(QColor("#9a9a9a")))
        self._apply_color(it, "folder", f.id, colors)
        return it

    def _special(self, kind: str, text: str, icon_name: str) -> QTreeWidgetItem:
        it = QTreeWidgetItem([tr(text)])
        it.setIcon(0, icon(icon_name))
        it.setData(0, ROLE_KIND, kind)
        it.setData(0, ROLE_ID, None)
        it.setFlags(it.flags() & ~Qt.ItemIsDragEnabled)
        if kind != "root":
            it.setFlags(it.flags() & ~Qt.ItemIsDropEnabled)
        return it

    def last_used_phrases(self) -> list[Phrase]:
        ps = [p for p in self.store.phrases() if p.last_used and not self.locked(p.folder_id)]
        ps.sort(key=lambda p: p.last_used or "", reverse=True)
        return ps[:last_used_max(self.store)]

    def matches(self, p: Phrase, q: str) -> bool:
        q = q.lower()
        scope = self.search_scope
        fields = []
        if scope in ("all", "description"):
            fields.append(p.description)
        if scope in ("all", "content"):
            fields.append(p.content)
        if scope in ("all", "autotext"):
            fields += [t.value for t in p.triggers]
        if scope == "all":
            fields += p.tags
        return any(q in (f or "").lower() for f in fields)

    def refresh(self) -> None:
        tree = self.tree
        sel = tree.currentItem()
        sel_key = (sel.data(0, ROLE_KIND), sel.data(0, ROLE_ID)) if sel else None
        expanded = {(it.data(0, ROLE_KIND), it.data(0, ROLE_ID)) for it in self.all_items() if it.isExpanded()}
        first_build = tree.topLevelItemCount() == 0
        colors = item_colors(self.store)
        tree.blockSignals(True)
        tree.clear()
        q = self.search_text.strip()
        if q:
            for p in self.store.phrases():
                if not self.locked(p.folder_id) and self.matches(p, q):
                    tree.addTopLevelItem(self.make_phrase_item(p, colors))
        else:
            # Settings > Features: "Last used phrases folder" / "Clipboard Cache"
            if _on(self.store, "features.last_used_folder"):
                lu = self._special("last_used", "Last Used", "last_used")
                tree.addTopLevelItem(lu)
                if not _on(self.store, "features.usage_statistics"):
                    # usage is not recorded while statistics are off, so the folder stays empty
                    tip = "Last Used stays empty while Settings > Features > Usage statistics is off."
                    lu.setToolTip(0, tip)
                    hint = QTreeWidgetItem(["(turn on Usage statistics to fill this folder)"])
                    hint.setData(0, ROLE_KIND, "hint")
                    hint.setToolTip(0, tip)
                    hint.setFlags(Qt.NoItemFlags)
                    hint.setForeground(0, QBrush(QColor("#8a8a8a")))
                    lu.addChild(hint)
                if not self.folders_only:
                    for p in self.last_used_phrases():
                        child = self.make_phrase_item(p, colors)
                        child.setData(0, ROLE_KIND, "phrase")
                        child.setFlags(child.flags() & ~Qt.ItemIsDragEnabled & ~Qt.ItemIsEditable)
                        lu.addChild(child)
            cc = self._special("clipboard_cache", "Clipboard Cache", "clipboard_cache")
            if _on(self.store, "clipboard_history.enabled"):
                tree.addTopLevelItem(cc)
            if not self.folders_only and _on(self.store, "clipboard_history.enabled"):
                for e in self.store.clipboard_entries(50):
                    text = " ".join(e.text.split())[:90] or "(empty)"
                    c = QTreeWidgetItem([text])
                    c.setIcon(0, icon("phrase"))
                    c.setData(0, ROLE_KIND, "clip")
                    c.setData(0, ROLE_ID, e.id)
                    c.setToolTip(0, e.text[:500])
                    c.setFlags(c.flags() & ~Qt.ItemIsDragEnabled & ~Qt.ItemIsDropEnabled)
                    cc.addChild(c)
            # PhraseForge's own sticky notes (ui/sticky_notes.py)
            self.notes_by_id = {}
            if show_sticky(self.store):
                sn = self._special("sticky_notes", "Sticky Notes", "sticky_notes")
                tree.addTopLevelItem(sn)
                if not self.folders_only:
                    for n in sticky_notes(self.store):
                        self.notes_by_id[n.id] = n
                        c = QTreeWidgetItem([n.title])
                        c.setIcon(0, icon("sticky_notes"))
                        c.setData(0, ROLE_KIND, "note")
                        c.setData(0, ROLE_ID, n.id)
                        c.setToolTip(0, n.text[:500])
                        c.setFlags(c.flags() & ~Qt.ItemIsDragEnabled & ~Qt.ItemIsDropEnabled & ~Qt.ItemIsEditable)
                        sn.addChild(c)
            root = self._special("root", "Phrases", "phrases_root")
            tree.addTopLevelItem(root)
            if self.flat and not self.folders_only:
                for p in sorted(self.store.phrases(), key=lambda p: p.description.lower()):
                    if not self.locked(p.folder_id):
                        root.addChild(self.make_phrase_item(p, colors))
            else:
                self._add_folders(root, None, colors)
                if not self.folders_only:
                    for p in sorted_phrases(self.store, None):
                        root.addChild(self.make_phrase_item(p, colors))
            if first_build:
                root.setExpanded(True)
        for it in self.all_items():
            if (it.data(0, ROLE_KIND), it.data(0, ROLE_ID)) in expanded:
                it.setExpanded(True)
        if sel_key:
            for it in self.all_items():
                if (it.data(0, ROLE_KIND), it.data(0, ROLE_ID)) == sel_key:
                    tree.setCurrentItem(it)
                    break
        tree.blockSignals(False)

    def _add_folders(self, parent_item, parent_id, colors) -> None:
        for f in sorted_folders(self.store, parent_id):
            it = self._folder_item(f, colors)
            parent_item.addChild(it)
            if not (f.password_hash and f.id not in self.unlocked):
                self._add_folders(it, f.id, colors)
                if not self.folders_only:
                    for p in sorted_phrases(self.store, f.id):
                        it.addChild(self.make_phrase_item(p, colors))

    # -------------------------------------------------- queries
    def all_items(self) -> list[QTreeWidgetItem]:
        out = []

        def walk(it):
            out.append(it)
            for i in range(it.childCount()):
                walk(it.child(i))
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))
        return out

    def select(self, kind: str, id_) -> bool:
        for it in self.all_items():
            if it.data(0, ROLE_KIND) == kind and it.data(0, ROLE_ID) == id_:
                # phrases may also appear under Last Used: prefer the real location
                if kind == "phrase" and it.parent() and it.parent().data(0, ROLE_KIND) == "last_used":
                    continue
                p = it.parent()
                while p:
                    p.setExpanded(True)
                    p = p.parent()
                self.tree.setCurrentItem(it)
                return True
        return False

    def current(self) -> tuple[str | None, object]:
        it = self.tree.currentItem()
        return (it.data(0, ROLE_KIND), it.data(0, ROLE_ID)) if it else (None, None)

    def _emit_selected(self, cur, _prev) -> None:
        if cur is None:
            self.selected.emit("", None)
        else:
            self.selected.emit(cur.data(0, ROLE_KIND), cur.data(0, ROLE_ID))


class PhraseList(QWidget):
    """Middle column of the three-column layout: content of one folder."""
    selected = Signal(str, object)
    open_folder = Signal(object)          # folder id (None = root)

    def __init__(self, store: Store, panel: TreePanel, parent=None):
        super().__init__(parent)
        self.store = store
        self.panel = panel
        self.folder_id: int | None = None
        self.kind = "root"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        h = QLabel("Folders and phrases")
        h.setObjectName("PanelHeader")
        lay.addWidget(h)
        self.list = QTreeWidget(self)
        self.list.setHeaderLabels(["Description", "Autotext", "Hotkey"])
        self.list.setRootIsDecorated(False)
        self.list.setUniformRowHeights(True)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.header().setSectionResizeMode(0, QHeaderView.Interactive)
        self.list.setColumnWidth(0, 150)
        self.list.setColumnWidth(1, 70)
        lay.addWidget(self.list, 1)
        self.list.currentItemChanged.connect(self._sel)
        self.list.itemDoubleClicked.connect(self._open)

    def show_folder(self, kind: str, folder_id) -> None:
        self.kind, self.folder_id = kind, folder_id
        self.list.blockSignals(True)
        self.list.clear()
        colors = item_colors(self.store)
        if kind == "folder":
            up = QTreeWidgetItem([".."])
            up.setData(0, ROLE_KIND, "up")
            self.list.addTopLevelItem(up)
        if kind == "last_used":
            phrases = self.panel.last_used_phrases()
            folders = []
        elif kind == "clipboard_cache":
            phrases, folders = [], []
            for e in self.store.clipboard_entries(50):
                it = QTreeWidgetItem([" ".join(e.text.split())[:80]])
                it.setIcon(0, icon("phrase"))
                it.setData(0, ROLE_KIND, "clip")
                it.setData(0, ROLE_ID, e.id)
                self.list.addTopLevelItem(it)
        elif kind == "sticky_notes":
            phrases, folders = [], []
            for n in sticky_notes(self.store):
                self.panel.notes_by_id[n.id] = n
                it = QTreeWidgetItem([n.title])
                it.setIcon(0, icon("sticky_notes"))
                it.setData(0, ROLE_KIND, "note")
                it.setData(0, ROLE_ID, n.id)
                it.setToolTip(0, n.text[:500])
                self.list.addTopLevelItem(it)
        elif kind in ("folder", "root"):
            fid = folder_id if kind == "folder" else None
            folders = [] if self.panel.locked(fid) else sorted_folders(self.store, fid)
            phrases = [] if self.panel.locked(fid) else sorted_phrases(self.store, fid)
        else:
            folders, phrases = [], []
        for f in folders:
            it = QTreeWidgetItem([f.name, "", ""])
            it.setIcon(0, icon("folder"))
            it.setData(0, ROLE_KIND, "folder")
            it.setData(0, ROLE_ID, f.id)
            self.list.addTopLevelItem(it)
        for p in phrases:
            ab = ", ".join(t.value for t in p.autotexts())
            hk = ", ".join(t.value for t in p.hotkeys())
            it = QTreeWidgetItem([phrase_label(p), ab, hk])
            it.setIcon(0, icon("phrase"))
            it.setData(0, ROLE_KIND, "phrase")
            it.setData(0, ROLE_ID, p.id)
            c = colors.get(f"phrase:{p.id}")
            if c:
                it.setForeground(0, QBrush(QColor(c)))
            self.list.addTopLevelItem(it)
        self.list.blockSignals(False)

    def fit_columns(self) -> None:
        for c in range(3):
            self.list.resizeColumnToContents(c)

    def _sel(self, cur, _prev) -> None:
        if cur is not None and cur.data(0, ROLE_KIND) in ("phrase", "clip", "note"):
            self.selected.emit(cur.data(0, ROLE_KIND), cur.data(0, ROLE_ID))

    def _open(self, it, _col) -> None:
        k = it.data(0, ROLE_KIND)
        if k == "folder":
            self.open_folder.emit(it.data(0, ROLE_ID))
        elif k == "up":
            f = self.store.get_folder(self.folder_id) if self.folder_id else None
            self.open_folder.emit(f.parent_id if f else None)
