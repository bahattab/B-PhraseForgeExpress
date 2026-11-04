"""Shared database settings: server, sign-in, test, create tables, sync now."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSpinBox, QVBoxLayout,
)

from phraseforge.shared import service
from phraseforge.shared.connect import ENGINES
from phraseforge.ui.i18n import tr
from phraseforge.ui.icons import app_icon

AUTH = (("windows", "Windows account (integrated security)"), ("password", "Database user name and password"))


class SharedDialog(QDialog):
    def __init__(self, store, parent=None, connectors: dict | None = None):
        super().__init__(parent)
        self.store = store
        self.connectors = connectors                       # tests: engine -> DB-API connection factory
        self.setWindowTitle(tr("Shared database"))
        self.setWindowIcon(app_icon())
        st = store.setting
        lay = QVBoxLayout(self)
        intro = QLabel(tr("Share folders and phrases with your team through Microsoft SQL Server or PostgreSQL. "
                          "The shared phrases appear in a local folder and are synchronized automatically."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.enabled = QCheckBox(tr("Synchronize with the shared database"))
        self.enabled.setChecked(st("shared.enabled", "0") == "1")
        lay.addWidget(self.enabled)
        form = QFormLayout()
        self.engine = QComboBox()
        for key, name in ENGINES.items():
            self.engine.addItem(name, key)
        self.engine.setCurrentIndex(max(0, self.engine.findData(st("shared.engine", "sqlserver"))))
        self.server = QLineEdit(st("shared.server", ""))
        self.server.setPlaceholderText("sql01.company.local\\PHRASES")
        self.port = QLineEdit(st("shared.port", ""))
        self.port.setPlaceholderText(tr("default"))
        self.database = QLineEdit(st("shared.database", "PhraseForge"))
        self.auth = QComboBox()
        for key, label in AUTH:
            self.auth.addItem(tr(label), key)
        self.auth.setCurrentIndex(max(0, self.auth.findData(st("shared.auth", "windows"))))
        self.user = QLineEdit(st("shared.user", ""))
        self.password = QLineEdit(st("shared.password", ""))
        self.password.setEchoMode(QLineEdit.Password)
        self.encrypt = QCheckBox(tr("Encrypted connection"))
        self.encrypt.setChecked(st("shared.encrypt", "1") == "1")
        self.trust_cert = QCheckBox(tr("Trust the server certificate (self-signed)"))
        self.trust_cert.setChecked(st("shared.trust_cert", "0") == "1")
        self.interval = QSpinBox()
        self.interval.setRange(15, 3600)
        self.interval.setSuffix(" s")
        self.interval.setValue(service.interval_s(store))
        self.root_name = QLineEdit(st("shared.root_name", "Shared"))
        for label, w in (("Database type:", self.engine), ("Server:", self.server), ("Port:", self.port),
                         ("Database:", self.database), ("Sign in with:", self.auth), ("User name:", self.user),
                         ("Password:", self.password), ("", self.encrypt), ("", self.trust_cert),
                         ("Synchronize every:", self.interval), ("Local folder:", self.root_name)):
            form.addRow(tr(label) if label else "", w)
        lay.addLayout(form)
        self.auth.currentIndexChanged.connect(self._auth_changed)
        self._auth_changed()
        row = QHBoxLayout()
        for label, fn in (("Test connection", self.test), ("Create tables", self.create_tables),
                          ("Sync now", self.sync_now)):
            b = QPushButton(tr(label))
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        self.status = QLabel(tr("Last sync:") + " " + (st("shared.last_sync", "") or tr("never")))
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _auth_changed(self) -> None:
        pw = self.auth.currentData() == "password"
        self.user.setEnabled(pw)
        self.password.setEnabled(pw)

    def save(self) -> None:
        put = self.store.set_setting
        put("shared.enabled", "1" if self.enabled.isChecked() else "0")
        put("shared.engine", self.engine.currentData())
        for key, w in (("shared.server", self.server), ("shared.port", self.port), ("shared.database", self.database),
                       ("shared.user", self.user), ("shared.root_name", self.root_name)):
            put(key, w.text().strip())
        put("shared.password", self.password.text())
        put("shared.auth", self.auth.currentData())
        put("shared.encrypt", "1" if self.encrypt.isChecked() else "0")
        put("shared.trust_cert", "1" if self.trust_cert.isChecked() else "0")
        put("shared.interval", str(self.interval.value()))

    def accept(self) -> None:
        self.save()
        super().accept()

    def _run(self, fn):
        self.save()
        try:
            return fn()
        except Exception as e:
            self.status.setText(str(e))
            QMessageBox.warning(self, tr("Shared database"), str(e))
            return None

    def test(self):
        out = self._run(lambda: service.test_connection(self.store, self.connectors))
        if out is not None:
            user, ready = out
            self.status.setText(tr("Connected as {user}.").format(user=user) + " " +
                                (tr("The tables are ready.") if ready else
                                 tr("The PhraseForge tables do not exist yet: click Create tables.")))
        return out

    def create_tables(self):
        user = self._run(lambda: service.create_tables(self.store, self.connectors))
        if user is not None:
            self.status.setText(tr("The tables are ready.") + " " + tr("Connected as {user}.").format(user=user))
        return user

    def sync_now(self):
        res = self._run(lambda: service.sync(self.store, self.connectors))
        if res is not None:
            self.status.setText(tr("Connected as {user}.").format(user=res.user) + " " + res.summary())
        return res
