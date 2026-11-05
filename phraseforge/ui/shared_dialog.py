"""Shared database settings: server, sign-in, test, create tables, sync now."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
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
                          ("Sync now", self.sync_now), ("Permissions...", self.permissions)):
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

    def permissions(self):
        self.save()
        try:
            dlg = PermissionsDialog(self.store, self, self.connectors)
        except Exception as e:
            QMessageBox.warning(self, tr("Shared database"), str(e))
            return None
        dlg.exec()
        return dlg

    def sync_now(self):
        res = self._run(lambda: service.sync(self.store, self.connectors))
        if res is not None:
            self.status.setText(tr("Connected as {user}.").format(user=res.user) + " " + res.summary())
        return res


ACCESS = (("read", "Read"), ("write", "Read and write"), ("none", "No access"))


class PermissionsDialog(QDialog):
    """Who may read or change which shared folder. Applied by PhraseForge, not by the database."""

    def __init__(self, store, parent=None, connectors: dict | None = None):
        super().__init__(parent)
        from phraseforge.shared.server import EVERYONE
        self.store, self.connectors, self.everyone = store, connectors, EVERYONE
        self.setWindowTitle(tr("Shared folder permissions"))
        self.resize(640, 460)
        lay = QVBoxLayout(self)
        note = QLabel(tr("Permissions are applied by PhraseForge. Anyone who can connect to the database with "
                         "another program can still read and change it: use database permissions for that."))
        note.setWordWrap(True)
        lay.addWidget(note)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([tr("Folder"), tr("User or group"), tr("Type"), tr("Access")])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table)
        form = QHBoxLayout()
        self.folder = QComboBox()
        self.principal = QLineEdit()
        self.principal.setPlaceholderText("CONTOSO\\Sales  /  ali  /  *")
        self.kind = QComboBox()
        self.kind.addItem(tr("User"), "user")
        self.kind.addItem(tr("Group"), "group")
        self.access = QComboBox()
        for key, label in ACCESS:
            self.access.addItem(tr(label), key)
        self.admin = QCheckBox(tr("Administrator"))
        for w in (self.folder, self.principal, self.kind, self.access, self.admin):
            form.addWidget(w)
        lay.addLayout(form)
        row = QHBoxLayout()
        self.add_button = QPushButton(tr("Add"))
        self.add_button.clicked.connect(self.add)
        self.remove_button = QPushButton(tr("Remove"))
        self.remove_button.clicked.connect(self.remove)
        row.addWidget(self.add_button)
        row.addWidget(self.remove_button)
        row.addStretch()
        lay.addLayout(row)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.refresh()

    def _server(self, fn):
        return service.with_server(self.store, fn, self.connectors)

    def refresh(self) -> None:
        def read(server):
            folders, _p, _t = server.changes_since(0)
            return server.acl(), {f.id: f for f in folders if not f.deleted}, server.is_admin(), server.user()
        acl, folders, self.is_admin, user = self._server(read)
        self.folders = folders

        def path(fid):
            parts, seen = [], set()
            while fid is not None and fid in folders and fid not in seen:
                seen.add(fid)
                parts.append(folders[fid].name)
                fid = folders[fid].parent_id
            return "/".join(reversed(parts)) or tr("(whole database)")
        self.folder.clear()
        self.folder.addItem(tr("(whole database)"), None)
        for fid in sorted(folders, key=lambda f: path(f).casefold()):
            self.folder.addItem(path(fid), fid)
        self.entries = acl
        self.table.setRowCount(len(acl))
        for row, e in enumerate(acl):
            access = "write" if e.can_write else ("read" if e.can_read else "none")
            label = dict(ACCESS)[access] + (" + " + tr("Administrator") if e.can_admin else "")
            who = tr("Everyone") if e.principal == self.everyone else e.principal
            for col, text in enumerate((path(e.folder_id), who, tr(e.kind.capitalize()), tr(label))):
                it = QTableWidgetItem(text)
                it.setData(Qt.UserRole, e.id)
                self.table.setItem(row, col, it)
        for w in (self.add_button, self.remove_button, self.folder, self.principal, self.kind, self.access, self.admin):
            w.setEnabled(self.is_admin)
        self.status.setText(tr("Signed in as {user}.").format(user=user) + " " +
                            (tr("You are an administrator.") if self.is_admin else
                             tr("Only administrators can change permissions.")))

    def add(self):
        from phraseforge.shared.server import AclEntry
        who = self.principal.text().strip()
        if not who:
            return None
        access = self.access.currentData()
        e = AclEntry(0, self.folder.currentData(), who, self.kind.currentData(), access != "none", access == "write",
                     self.admin.isChecked())
        try:
            new_id = self._server(lambda s: s.add_acl(e))
        except Exception as ex:
            QMessageBox.warning(self, tr("Shared folder permissions"), str(ex))
            return None
        self.principal.clear()
        self.refresh()
        return new_id

    def remove(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        acl_id = self.table.item(row, 0).data(Qt.UserRole)
        try:
            self._server(lambda s: s.remove_acl(acl_id))
        except Exception as ex:
            QMessageBox.warning(self, tr("Shared folder permissions"), str(ex))
        self.refresh()


class SharedHistoryDialog(QDialog):
    """Earlier versions of a shared phrase; one can be restored for everyone."""

    def __init__(self, store, phrase_id: int, parent=None, connectors: dict | None = None):
        super().__init__(parent)
        self.store, self.connectors = store, connectors
        self.remote_id = service.remote_phrase_id(store, phrase_id)
        self.setWindowTitle(tr("Shared history"))
        self.resize(640, 480)
        lay = QVBoxLayout(self)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([tr("When"), tr("Who"), tr("Change"), tr("Description")])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.currentCellChanged.connect(lambda *_: self._show())
        lay.addWidget(self.table)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        lay.addWidget(self.text)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        self.restore_button = bb.addButton(tr("Restore this version"), QDialogButtonBox.ActionRole)
        self.restore_button.clicked.connect(self.restore)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.versions = []
        if self.remote_id is not None:
            self.versions = service.with_server(store, lambda s: s.history("phrase", self.remote_id), connectors)
        names = {"create": "Created", "update": "Changed", "delete": "Deleted", "restore": "Restored"}
        self.table.setRowCount(len(self.versions))
        for row, h in enumerate(self.versions):
            for col, text in enumerate((h.changed.replace("T", " ").rstrip("Z"), h.changed_by,
                                        tr(names.get(h.action, h.action)), h.name)):
                self.table.setItem(row, col, QTableWidgetItem(text))
        if self.versions:
            self.table.selectRow(0)
        self._show()

    def _show(self) -> None:
        row = self.table.currentRow()
        h = self.versions[row] if 0 <= row < len(self.versions) else None
        self.text.setPlainText(h.content if h else "")
        self.restore_button.setEnabled(bool(h) and h.action != "delete" and row > 0)

    def restore(self):
        row = self.table.currentRow()
        if not (0 < row < len(self.versions)):
            return None
        h = self.versions[row]
        try:
            rev = service.with_server(self.store, lambda s: s.restore_phrase(h.id), self.connectors)
        except Exception as e:
            QMessageBox.warning(self, tr("Shared history"), str(e))
            return None
        self.accept()
        return rev
