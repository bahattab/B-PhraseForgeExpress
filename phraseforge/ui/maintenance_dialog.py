"""File > Maintenance: duplicates, compare with a backup, check and compact (maintenance.py)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from phraseforge import io_formats, maintenance
from phraseforge.ui.i18n import tr


def _folder_name(store, fid) -> str:
    return " / ".join(f.name for f in reversed(store.folder_chain(fid))) if fid is not None else ""


class MaintenanceDialog(QDialog):
    show_phrase = Signal(int)

    def __init__(self, store, parent=None, backup_dir: str | None = None):
        super().__init__(parent)
        self.store = store
        self.backup_dir = backup_dir
        self.changes: list = []
        self.setWindowTitle(tr("Maintenance"))
        self.resize(760, 480)
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._dup_tab(), tr("Duplicates"))
        self.tabs.addTab(self._cmp_tab(), tr("Compare with backup"))
        self.tabs.addTab(self._db_tab(), tr("Database"))
        lay.addWidget(self.tabs)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.find_duplicates()

    # ------------------------------------------------ duplicates
    def _dup_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel(tr("Phrases with the same text in any folder, and abbreviations used by more than "
                                "one phrase.")))
        self.dups = QTreeWidget()
        self.dups.setHeaderLabels([tr("Phrase"), tr("Folder"), tr("Abbreviations")])
        self.dups.itemDoubleClicked.connect(self._open_dup)
        lay.addWidget(self.dups)
        row = QHBoxLayout()
        b = QPushButton(tr("Search again"))
        b.clicked.connect(self.find_duplicates)
        row.addWidget(b)
        self.dup_delete = QPushButton(tr("Delete selected phrases"))
        self.dup_delete.clicked.connect(self.delete_duplicates)
        row.addWidget(self.dup_delete)
        row.addStretch(1)
        self.dup_count = QLabel("")
        row.addWidget(self.dup_count)
        lay.addLayout(row)
        return w

    def find_duplicates(self) -> None:
        self.dups.clear()
        groups = maintenance.find_duplicates(self.store)
        for g in groups:
            head = QTreeWidgetItem([(tr("Same text:") + " " + g.key) if g.kind == "content"
                                    else (tr("Same abbreviation:") + " " + g.key), "", ""])
            head.setFlags(head.flags() & ~Qt.ItemIsSelectable)
            for pid in g.phrase_ids:
                p = self.store.get_phrase(pid)
                if p is None:
                    continue
                it = QTreeWidgetItem([p.description, _folder_name(self.store, p.folder_id) or tr("(top level)"),
                                      ", ".join(t.value for t in p.autotexts())])
                it.setData(0, Qt.UserRole, pid)
                head.addChild(it)
            self.dups.addTopLevelItem(head)
            head.setExpanded(True)
        self.dups.setSelectionMode(QTreeWidget.ExtendedSelection)
        for i in range(3):
            self.dups.resizeColumnToContents(i)
        self.dup_count.setText(tr("{n} groups").format(n=len(groups)) if groups else tr("No duplicates found."))
        self.dup_delete.setEnabled(bool(groups))

    def _open_dup(self, it, _col=0) -> None:
        pid = it.data(0, Qt.UserRole)
        if pid:
            self.show_phrase.emit(pid)

    def delete_duplicates(self) -> None:
        ids = [it.data(0, Qt.UserRole) for it in self.dups.selectedItems() if it.data(0, Qt.UserRole)]
        if not ids or QMessageBox.question(self, self.windowTitle(), tr("Move {n} phrases to the Trash?")
                                           .format(n=len(ids))) != QMessageBox.Yes:
            return
        for pid in ids:
            try:
                self.store.trash_phrase(pid)
            except Exception as e:
                QMessageBox.warning(self, self.windowTitle(), str(e))
                break
        self.find_duplicates()

    # ------------------------------------------------ compare
    def _cmp_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Backup:")))
        self.backups = QComboBox()
        for path in io_formats.list_backups(self.backup_dir):
            self.backups.addItem(path.name, str(path))
        row.addWidget(self.backups, 1)
        other = QPushButton(tr("Other file..."))
        other.clicked.connect(self._pick_backup)
        row.addWidget(other)
        go = QPushButton(tr("Compare with now"))
        go.clicked.connect(self.compare)
        row.addWidget(go)
        lay.addLayout(row)
        self.cmp = QTreeWidget()
        self.cmp.setHeaderLabels([tr("Change"), tr("Phrase"), tr("Folder"), tr("What changed")])
        self.cmp.setRootIsDecorated(False)
        lay.addWidget(self.cmp)
        row = QHBoxLayout()
        self.take_back = QPushButton(tr("Bring back the backup's version"))
        self.take_back.setToolTip(tr("Adds the phrase as it was in the backup (the current one stays)"))
        self.take_back.clicked.connect(self.restore_selected)
        self.take_back.setEnabled(False)
        row.addWidget(self.take_back)
        row.addStretch(1)
        self.cmp_count = QLabel("")
        row.addWidget(self.cmp_count)
        lay.addLayout(row)
        self.cmp.currentItemChanged.connect(lambda *_: self.take_back.setEnabled(self._current_change() is not None
                                                                              and self._current_change().old is not None))
        return w

    def _pick_backup(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("Backup"), self.backup_dir or "",
                                              tr("PhraseForge phrase file (*.db)"))
        if path:
            self.backups.insertItem(0, Path(path).name, path)
            self.backups.setCurrentIndex(0)

    def compare(self) -> None:
        path = self.backups.currentData()
        if not path:
            return
        try:
            self.changes = maintenance.compare(path, self.store)
        except Exception as e:
            QMessageBox.warning(self, self.windowTitle(), str(e))
            return
        names = {"added": tr("Added since"), "removed": tr("Removed since"), "changed": tr("Changed since")}
        self.cmp.clear()
        for n, c in enumerate(self.changes):
            it = QTreeWidgetItem([names[c.kind], c.description, c.folder or tr("(top level)"), ", ".join(tr(f) for f in c.fields)])
            it.setData(0, Qt.UserRole, n)
            self.cmp.addTopLevelItem(it)
        for i in range(4):
            self.cmp.resizeColumnToContents(i)
        counts = {k: sum(1 for c in self.changes if c.kind == k) for k in names}
        self.cmp_count.setText(tr("{a} added, {r} removed, {c} changed").format(
            a=counts["added"], r=counts["removed"], c=counts["changed"]) if self.changes else tr("No differences."))

    def _current_change(self):
        it = self.cmp.currentItem()
        return self.changes[it.data(0, Qt.UserRole)] if it is not None else None

    def restore_selected(self) -> None:
        c = self._current_change()
        if c is None or c.old is None:
            return
        try:
            p = maintenance.restore_phrase(self.store, c)
        except Exception as e:
            QMessageBox.warning(self, self.windowTitle(), str(e))
            return
        QMessageBox.information(self, self.windowTitle(),
                                tr('"{name}" was added at the top level, as it was in the backup.').replace(
                                    "{name}", p.description))
        self.show_phrase.emit(p.id)

    # ------------------------------------------------ database
    def _db_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        info = QLabel(tr("Check the phrase file for damage, or compact it to give back the space that deleted "
                         "phrases still take."))
        info.setWordWrap(True)
        lay.addWidget(info)
        row = QHBoxLayout()
        b = QPushButton(tr("Check"))
        b.clicked.connect(self.check)
        row.addWidget(b)
        b = QPushButton(tr("Compact"))
        b.clicked.connect(self.compact)
        row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.db_result = QLabel("")
        self.db_result.setWordWrap(True)
        lay.addWidget(self.db_result)
        lay.addStretch(1)
        return w

    def check(self) -> None:
        problems = maintenance.check(self.store)
        self.db_result.setText(tr("The phrase file is in good order.") if not problems else
                               tr("Problems found:") + "\n" + "\n".join(problems[:20]))

    def compact(self) -> None:
        before, after = maintenance.compact(self.store)
        self.db_result.setText(tr("Compacted: {a} KB → {b} KB.").format(a=before // 1024, b=after // 1024))
