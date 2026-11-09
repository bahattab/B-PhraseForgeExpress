"""Phrase libraries: mount other phrase files next to your own (libraries.py)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from phraseforge import libraries
from phraseforge.ui.i18n import tr


class MountDialog(QDialog):
    """Name, file and mode of a library to mount (an existing file or a new one)."""

    def __init__(self, parent=None, create: bool = False):
        super().__init__(parent)
        self.create = create
        self.setWindowTitle(tr("New phrase library") if create else tr("Add phrase library"))
        f = QFormLayout(self)
        self.path = QLineEdit()
        browse = QPushButton(tr("Browse..."))
        browse.clicked.connect(self.browse)
        row = QHBoxLayout()
        row.addWidget(self.path, 1)
        row.addWidget(browse)
        self.name = QLineEdit()
        self.mode = QComboBox()
        self.mode.addItem(tr("Read only (use the phrases, do not change them)"), "ro")
        self.mode.addItem(tr("Read and write (changes are saved to the library file)"), "rw")
        if create:
            self.mode.setCurrentIndex(1)
        f.addRow(tr("Phrase file:"), row)
        f.addRow(tr("Name:"), self.name)
        f.addRow(tr("Access:"), self.mode)
        note = QLabel(tr("A library on a shared folder lets a team use the same phrases. Its phrases need "
                         "your approval before they can run programs or other privileged macros."))
        note.setWordWrap(True)
        f.addRow(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def browse(self) -> None:
        flt = tr("PhraseForge phrase file (*.db)")
        if self.create:
            path, _ = QFileDialog.getSaveFileName(self, self.windowTitle(), self.path.text(), flt)
        else:
            path, _ = QFileDialog.getOpenFileName(self, self.windowTitle(), self.path.text(), flt)
        if path:
            self.path.setText(path)
            if not self.name.text():
                self.name.setText(Path(path).stem)


class LibrariesDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.mgr = libraries.manager(store)
        self.setWindowTitle(tr("Phrase libraries"))
        self.resize(720, 380)
        lay = QVBoxLayout(self)
        intro = QLabel(tr("Use phrases from other phrase files next to your own, for example a team file on a "
                          "shared folder. Each library is a folder of its own. When two have the same "
                          "abbreviation, your own phrase wins, then the library higher in this list."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.list = QTreeWidget()
        self.list.setHeaderLabels([tr("Name"), tr("Access"), tr("File"), tr("Status")])
        self.list.setRootIsDecorated(False)
        lay.addWidget(self.list)
        row = QHBoxLayout()
        self.buttons = {}
        for key, text, fn in (("add", tr("Add..."), self.add), ("new", tr("New library..."), self.new),
                              ("mode", tr("Read only / read and write"), self.toggle_mode),
                              ("up", tr("Move up"), lambda: self.move(-1)),
                              ("down", tr("Move down"), lambda: self.move(1)),
                              ("refresh", tr("Update now"), self.refresh),
                              ("remove", tr("Remove"), self.remove)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
            self.buttons[key] = b
        row.addStretch(1)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.list.currentItemChanged.connect(lambda *_: self._enable())
        self.load()

    def load(self) -> None:
        cur = self._current()
        self.list.clear()
        for lib in self.mgr.libraries():
            it = QTreeWidgetItem([lib.name, tr("Read and write") if lib.writable else tr("Read only"), lib.path,
                                  self.mgr.status(lib) or tr("OK")])
            it.setData(0, Qt.UserRole, lib.id)
            it.setToolTip(2, lib.path)
            self.list.addTopLevelItem(it)
            if cur and lib.id == cur:
                self.list.setCurrentItem(it)
        for i in range(4):
            self.list.resizeColumnToContents(i)
        self._enable()

    def _current(self) -> str | None:
        it = self.list.currentItem()
        return it.data(0, Qt.UserRole) if it else None

    def _enable(self) -> None:
        has = self._current() is not None
        for k in ("mode", "up", "down", "remove"):
            self.buttons[k].setEnabled(has)

    def _mount(self, create: bool) -> None:
        dlg = MountDialog(self, create)
        if dlg.exec() != QDialog.Accepted or not dlg.path.text().strip():
            return
        try:
            self.mgr.add(dlg.name.text(), dlg.path.text().strip(), dlg.mode.currentData(), create=create)
        except Exception as e:
            QMessageBox.warning(self, self.windowTitle(), str(e))
        self.load()

    def add(self) -> None:
        self._mount(False)

    def new(self) -> None:
        self._mount(True)

    def toggle_mode(self) -> None:
        lid = self._current()
        lib = self.mgr.get(lid) if lid else None
        if lib:
            self.mgr.set_mode(lib.id, "ro" if lib.writable else "rw")
            self.load()

    def move(self, step: int) -> None:
        lid = self._current()
        if lid:
            self.mgr.move(lid, step)
            self.load()

    def refresh(self) -> None:
        errors = self.mgr.refresh(force=True)
        self.load()
        if errors:
            QMessageBox.warning(self, self.windowTitle(), "\n".join(f"{lib.name}: {e}" for lib, e in errors))

    def remove(self) -> None:
        lid = self._current()
        lib = self.mgr.get(lid) if lid else None
        if lib and QMessageBox.question(self, self.windowTitle(),
                                        tr('Remove "{name}" from this PC? The phrase file itself is not deleted.')
                                        .replace("{name}", lib.name)) == QMessageBox.Yes:
            self.mgr.remove(lib.id)
            self.load()
