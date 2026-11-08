"""Encrypt the phrase file on disk (vault.py) and ask for its passphrase at start."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QRadioButton,
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
        intro.setWordWrap(True)
        lay.addWidget(intro)
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
        self.pass1 = QLineEdit()
        self.pass2 = QLineEdit()
        for e in (self.pass1, self.pass2):
            e.setEchoMode(QLineEdit.Password)
        form.addRow(tr("Passphrase:"), self.pass1)
        form.addRow(tr("Repeat it:"), self.pass2)
        lay.addLayout(form)
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
        self.hint.setText(tr("Optional: a passphrase also opens the file on another PC.") if self.auto.isChecked()
                          else tr("Required: at least {n} characters.").format(n=MIN_PASSPHRASE))

    def problem(self) -> str:
        p1, p2 = self.pass1.text(), self.pass2.text()
        if p1 != p2:
            return tr("The two passphrases are not the same.")
        if (self.ask.isChecked() or p1) and len(p1) < MIN_PASSPHRASE:
            return tr("The passphrase needs at least {n} characters.").format(n=MIN_PASSPHRASE)
        return ""

    def apply(self) -> bool:
        err = self.problem()
        if err:
            QMessageBox.warning(self, self.windowTitle(), err)
            return False
        try:
            self.store.enable_encryption(self.pass1.text() or None, use_dpapi=self.auto.isChecked())
        except Exception as e:
            QMessageBox.warning(self, self.windowTitle(), str(e))
            return False
        self.accept()
        return True

    def turn_off(self) -> None:
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
    return None
