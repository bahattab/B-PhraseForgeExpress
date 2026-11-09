"""Encrypt the phrase file on disk (vault.py) and ask for its passphrase at start."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QRadioButton,
    QVBoxLayout, QWidget,
)

from phraseforge import vault
from phraseforge.ui.i18n import tr

MIN_PASSPHRASE = 8


def status_text(store) -> str:
    if not store.encrypted:
        return tr("The phrase file is not encrypted.")
    k = store.vault_key
    if k.opens_without_passphrase and k.has_passphrase:
        return tr("Encrypted. It opens for your Windows account; the passphrase opens it anywhere else.")
    if k.opens_without_passphrase:
        return tr("Encrypted. It opens only for your Windows account on this PC.")
    return tr("Encrypted. PhraseForge asks for the passphrase every time it starts.")


class EncryptionDialog(QDialog):
    def __init__(self, store, parent: QWidget | None = None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle(tr("Encrypt the phrase file"))
        lay = QVBoxLayout(self)
        intro = QLabel(tr("Encryption keeps your phrases unreadable if someone copies the phrase file or "
                          "takes the disk. PhraseForge works on the phrases in memory and saves them "
                          "encrypted (AES-256). Backups made on this PC are encrypted too."))
        # what this does not cover, said where the choice is made (R66, R73)
        cloud = (tr("What Backup & Sync uploads is encrypted with the sync passphrase.")
                 if store.setting("sync.encrypt", "0") == "1" else
                 tr("What Backup & Sync uploads is NOT encrypted: turn on \"Encrypt what is uploaded\" "
                    "in Settings > Backup & Sync."))
        self.scope = QLabel(cloud + " " + tr("Not encrypted: the learned words, imported images (the assets "
                                              "folder), the file search history and the log."))
        self.scope.setWordWrap(True)
        intro.setWordWrap(True)
        lay.addWidget(intro)
        lay.addWidget(self.scope)
        self.status = QLabel(status_text(store))
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.auto = QRadioButton(tr("Open it automatically for my Windows account"))
        self.ask = QRadioButton(tr("Ask for the passphrase every time PhraseForge starts"))
        k = store.vault_key
        (self.ask if k is not None and not k.opens_without_passphrase else self.auto).setChecked(True)
        if not vault.dpapi_available():
            self.auto.setEnabled(False)
            self.ask.setChecked(True)
        lay.addWidget(self.auto)
        lay.addWidget(self.ask)
        form = QFormLayout()
        self.has_pass = bool(k is not None and k.has_passphrase)
        self.current = QLineEdit()           # changing or removing a passphrase needs it (R69)
        self.pass1 = QLineEdit()
        self.pass2 = QLineEdit()
        for e in (self.current, self.pass1, self.pass2):
            e.setEchoMode(QLineEdit.Password)
        if self.has_pass:
            form.addRow(tr("Current passphrase:"), self.current)
        form.addRow(tr("New passphrase:") if self.has_pass else tr("Passphrase:"), self.pass1)
        form.addRow(tr("Repeat it:"), self.pass2)
        lay.addLayout(form)
        self.remove_pass = QCheckBox(tr("Remove the passphrase (the file then opens only for my Windows account)"))
        self.remove_pass.setVisible(self.has_pass)
        lay.addWidget(self.remove_pass)
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        warn = QLabel(tr("Write the passphrase down. Without it, an encrypted phrase file cannot be opened "
                         "on another PC, after Windows is reinstalled, or at all when PhraseForge asks for it "
                         "at every start. Nobody can recover it."))
        warn.setWordWrap(True)
        lay.addWidget(warn)
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.apply_button = bb.addButton(tr("Change") if store.encrypted else tr("Encrypt"), QDialogButtonBox.AcceptRole)
        self.apply_button.clicked.connect(self.apply)
        self.off_button = bb.addButton(tr("Stop encrypting"), QDialogButtonBox.DestructiveRole)
        self.off_button.clicked.connect(self.turn_off)
        self.off_button.setEnabled(store.encrypted)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        for wdg in (self.auto, self.ask):
            wdg.toggled.connect(self._update_hint)
        self._update_hint()

    def _update_hint(self) -> None:
        self.remove_pass.setEnabled(self.auto.isChecked())
        if self.has_pass:
            self.hint.setText(tr("Leave the new passphrase empty to keep the current one."))
            return
        self.hint.setText(tr("Optional: a passphrase also opens the file on another PC.") if self.auto.isChecked()
                          else tr("Required: at least {n} characters.").format(n=MIN_PASSPHRASE))

    def _removing(self) -> bool:
        return self.has_pass and self.auto.isChecked() and self.remove_pass.isChecked()

    def new_passphrase(self) -> str | None:
        """What the file is wrapped with: the new one, else the current one is kept, unless
        "Remove the passphrase" is ticked. Empty fields never drop it silently (R69)."""
        if self.pass1.text():
            return self.pass1.text()
        if self.has_pass and not self._removing():
            return self.current.text()
        return None

    def _current_ok(self) -> bool:
        return not self.has_pass or self.store.check_passphrase(self.current.text())

    def problem(self) -> str:
        p1, p2 = self.pass1.text(), self.pass2.text()
        if not self._current_ok():
            return tr("The current passphrase is wrong.")
        if p1 != p2:
            return tr("The two passphrases are not the same.")
        if p1 and len(p1) < MIN_PASSPHRASE:
            return tr("The passphrase needs at least {n} characters.").format(n=MIN_PASSPHRASE)
        if self.ask.isChecked() and not self.new_passphrase():
            return tr("The passphrase needs at least {n} characters.").format(n=MIN_PASSPHRASE)
        return ""

    def apply(self) -> bool:
        err = self.problem()
        if err:
            QMessageBox.warning(self, self.windowTitle(), err)
            return False
        if self._removing() and QMessageBox.question(
                self, self.windowTitle(), tr("Remove the passphrase? The phrase file then opens only for your "
                                             "Windows account on this PC.")) != QMessageBox.Yes:
            return False
        try:
            left = self.store.enable_encryption(self.new_passphrase(), use_dpapi=self.auto.isChecked())
        except Exception as e:
            QMessageBox.warning(self, self.windowTitle(), str(e))
            return False
        if left:                              # older copies under a passphrase this PC no longer knows
            QMessageBox.information(self, self.windowTitle(), tr(
                "{n} older backups could not be re-encrypted and still open with their old passphrase. "
                "Delete them if that passphrase is no longer safe:").format(n=len(left))
                + "\n" + "\n".join(str(f) for f in left[:10]))
        self.accept()
        return True

    def turn_off(self) -> None:
        if not self._current_ok():
            QMessageBox.warning(self, self.windowTitle(), tr("The current passphrase is wrong."))
            return
        if QMessageBox.question(self, self.windowTitle(),
                                tr("Save the phrase file without encryption again?")) != QMessageBox.Yes:
            return
        try:
            self.store.disable_encryption()
        except Exception as e:
            QMessageBox.warning(self, self.windowTitle(), str(e))
            return
        self.accept()


def ask_passphrase(path: str, parent: QWidget | None = None, attempts: int = 3):
    """Open an encrypted phrase file at start: the Store, or None when the user gave up."""
    from phraseforge.db import Store
    msg = tr("The phrase file is encrypted. Enter its passphrase:")
    for _ in range(attempts):
        text, ok = QInputDialog.getText(parent, "PhraseForge", msg, QLineEdit.Password)
        if not ok:
            return None
        try:
            return Store(path, passphrase=text)
        except vault.WrongPassphrase:
            msg = tr("Wrong passphrase. Try again:")
        except vault.VaultError as e:        # a damaged file: say so instead of crashing (R68)
            QMessageBox.critical(parent, "PhraseForge", f"{tr(str(e))}\n\n{path}")
            return None
    return None


def ask_copy_passphrase(parent: QWidget | None = None) -> str | None:
    """The passphrase of an encrypted backup made under an earlier key (R72)."""
    text, ok = QInputDialog.getText(parent, "PhraseForge", tr("This backup is encrypted. Enter its passphrase:"),
                                    QLineEdit.Password)
    return text if ok else None
