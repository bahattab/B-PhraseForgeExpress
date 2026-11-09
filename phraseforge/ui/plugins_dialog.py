"""Phrases > Plugins: install, switch on and off, permissions, secrets, errors (FR-PLG-08)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from phraseforge.plugins import manager as pm
from phraseforge.plugins.manifest import ManifestError
from phraseforge.ui.i18n import tr


def consent_text(manifest, asked: list[str], update: bool) -> str:
    head = (tr('"{name}" {version} asks for more than before:') if update
            else tr('Install "{name}" {version}? It may:'))
    head = head.replace("{name}", manifest.name).replace("{version}", manifest.version)
    return head + "\n\n• " + "\n• ".join(asked) + "\n\n" + tr(
        "Plugins run as separate programs. Install only plugins you trust.")


class PluginsDialog(QDialog):
    def __init__(self, parent=None, manager: pm.PluginManager | None = None, ask=None):
        super().__init__(parent)
        self.mgr = manager or pm.current()
        self.ask = ask or (lambda text: QMessageBox.question(self, self.windowTitle(), text) == QMessageBox.Yes)
        self.setWindowTitle(tr("Plugins"))
        self.resize(640, 420)
        lay = QVBoxLayout(self)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Plugin"), tr("Version"), tr("Macros"), tr("May")])
        self.tree.setRootIsDecorated(False)
        self.tree.itemChanged.connect(self._toggled)
        self.tree.currentItemChanged.connect(lambda *_: self._show_errors())
        lay.addWidget(self.tree)
        row = QHBoxLayout()
        for text, fn in ((tr("Install..."), self.install_dialog), (tr("Set secret..."), self.secret_dialog),
                         (tr("Remove"), self.remove_selected)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(QLabel(tr("Last errors of the selected plugin:")))
        self.errors = QPlainTextEdit()
        self.errors.setReadOnly(True)
        self.errors.setMaximumHeight(110)
        lay.addWidget(self.errors)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.refresh()

    def refresh(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        for pid, m in self.mgr.installed().items():
            it = QTreeWidgetItem([m.name, m.version, ", ".join(f"{{#{pid}.{x}}}" for x in m.macros),
                                  "; ".join(m.permissions.describe())])
            it.setData(0, Qt.UserRole, pid)
            allowed = self.mgr.allowed_by_policy(pid)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable if allowed else it.flags() & ~Qt.ItemIsEnabled)
            it.setCheckState(0, Qt.Checked if self.mgr.is_enabled(pid) else Qt.Unchecked)
            if not allowed:
                it.setToolTip(0, tr("Your administrator does not allow this plugin."))
            self.tree.addTopLevelItem(it)
        for name, err in self.mgr.load_errors.items():
            it = QTreeWidgetItem([name, "", "", tr("cannot be loaded:") + " " + err])
            it.setFlags(it.flags() & ~Qt.ItemIsEnabled)
            self.tree.addTopLevelItem(it)
        for i in range(4):
            self.tree.resizeColumnToContents(i)
        self.tree.blockSignals(False)

    def _selected(self) -> str | None:
        it = self.tree.currentItem()
        return it.data(0, Qt.UserRole) if it is not None else None

    def _toggled(self, it, col) -> None:
        pid = it.data(0, Qt.UserRole)
        if col != 0 or not pid:
            return
        on = it.checkState(0) == Qt.Checked
        if on:
            m = self.mgr.installed()[pid]
            g = self.mgr.granted(pid)
            asked = m.permissions.wider_than(g) if g is not None else m.permissions.describe()
            if asked and not self.ask(consent_text(m, asked, g is not None)):
                self.refresh()
                return
            self.mgr.store.set_setting(f"plugins.granted.{pid}", pm._perm_json(m.permissions))
        self.mgr.set_enabled(pid, on)
        self.refresh()

    def install_from(self, path: str) -> bool:
        try:
            m, asked = self.mgr.preview(path)
        except (ManifestError, OSError) as e:
            QMessageBox.warning(self, self.windowTitle(), tr("This is not a plugin PhraseForge can install:")
                                + "\n" + str(e))
            return False
        update = m.id in self.mgr.installed()
        if (asked or not update) and not self.ask(consent_text(m, asked or m.permissions.describe(), update)):
            return False
        try:
            self.mgr.install(path, accept=True)
        except (PermissionError, OSError, ManifestError) as e:
            QMessageBox.warning(self, self.windowTitle(), str(e))
            return False
        self.refresh()
        return True

    def install_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("Install plugin"), "",
                                              tr("PhraseForge plugin (*.pfplugin plugin.toml);;All files (*)"))
        if path:
            from pathlib import Path
            self.install_from(str(Path(path).parent) if Path(path).name == "plugin.toml" else path)

    def secret_dialog(self) -> None:
        pid = self._selected()
        m = self.mgr.installed().get(pid) if pid else None
        if m is None or not m.permissions.secrets:
            QMessageBox.information(self, self.windowTitle(), tr("This plugin asks for no secrets."))
            return
        name, ok = QInputDialog.getItem(self, self.windowTitle(), tr("Secret:"), list(m.permissions.secrets), 0, False)
        if not ok:
            return
        value, ok = QInputDialog.getText(self, self.windowTitle(), name, QLineEdit.Password)
        if ok:
            self.mgr.set_secret(pid, name, value)

    def remove_selected(self) -> None:
        pid = self._selected()
        if pid and self.ask(tr('Remove the plugin "{id}"?').replace("{id}", pid)):
            self.mgr.remove(pid)
            self.refresh()

    def _show_errors(self) -> None:
        pid = self._selected()
        self.errors.setPlainText("\n".join(self.mgr.errors(pid)) if pid else "")
