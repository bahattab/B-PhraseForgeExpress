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


def _plain(text: str, limit: int = 80) -> str:
    """A name from the package: no control or direction characters, bounded (R100)."""
    t = "".join(c for c in str(text) if c.isprintable() and c not in "\u200e\u200f\u202a\u202b\u202c\u202d\u202e"
                "\u2066\u2067\u2068\u2069")
    return t[:limit]


def signature_text(sig) -> str:
    if sig is None or sig.state == "unsigned":
        return tr("Not signed: PhraseForge cannot tell who made it.")
    if sig.state == "trusted":
        return tr("Signed by a publisher you trust ({fp}).").replace("{fp}", sig.fingerprint)
    if sig.state == "untrusted":
        return tr("Signed, but by a publisher you have not marked as trusted ({fp}).").replace("{fp}", sig.fingerprint)
    return tr("The signature is not valid: the files were changed after signing.")


def consent_text(manifest, asked: list[str], update: bool, old=None, sig=None) -> str:
    if update and old is not None:
        head = tr('Replace "{old}" {oldv} with "{name}" {version}?').replace("{old}", _plain(old.name)) \
            .replace("{oldv}", _plain(old.version, 20))
        if _plain(old.name) != _plain(manifest.name):
            head += "\n" + tr("The name is different: make sure it comes from the same author.")
        if asked:
            head += "\n\n" + tr("It asks for more than before:")
    else:
        head = tr('Install "{name}" {version}? It says it needs:')
    head = head.replace("{name}", _plain(manifest.name)).replace("{version}", _plain(manifest.version, 20))
    body = ("\n\n• " + "\n• ".join(asked)) if asked else ""
    # the list is what the plugin declares: nothing enforces it yet (security R97)
    return head + body + "\n\n" + signature_text(sig) + "\n" + tr(
        "A plugin is a program that runs with your Windows rights: it can read your files and reach the "
        "internet whatever it declares. Install only plugins you trust.")


def ask_plain(parent, title: str, text: str) -> bool:
    """Yes/No with the text always shown as plain text: a plugin name cannot hide the list (R100)."""
    box = QMessageBox(QMessageBox.Question, title, text, QMessageBox.Yes | QMessageBox.No, parent)
    box.setTextFormat(Qt.PlainText)
    box.setDefaultButton(QMessageBox.No)
    return box.exec() == QMessageBox.Yes


class PluginsDialog(QDialog):
    def __init__(self, parent=None, manager: pm.PluginManager | None = None, ask=None):
        super().__init__(parent)
        self.mgr = manager or pm.current()
        self.ask = ask or (lambda text: ask_plain(self, self.windowTitle(), text))
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
        from phraseforge.plugins import install as inst
        try:
            staged = inst.stage(path)            # what is shown is what is installed (R99)
        except (ManifestError, OSError) as e:
            QMessageBox.warning(self, self.windowTitle(), tr("This is not a plugin PhraseForge can install:")
                                + "\n" + str(e))
            return False
        try:
            try:
                m, asked = self.mgr.preview(staged)
            except (ManifestError, OSError) as e:
                QMessageBox.warning(self, self.windowTitle(), tr("This is not a plugin PhraseForge can install:")
                                    + "\n" + str(e))
                return False
            sig = self.mgr.signature(staged)
            if sig.state == "invalid":
                QMessageBox.warning(self, self.windowTitle(), signature_text(sig))
                return False
            old = self.mgr.installed().get(m.id)
            # an update always asks: anyone can make a package with the same id (R101)
            if not self.ask(consent_text(m, asked, old is not None, old, sig)):
                return False
            try:
                self.mgr.install(staged, accept=True, expected=m)
            except (PermissionError, OSError, ManifestError) as e:
                QMessageBox.warning(self, self.windowTitle(), str(e))
                return False
        finally:
            inst.unstage(staged)
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
