"""Dynamic folder settings: where the folder's phrases come from."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from phraseforge import dynamic
from phraseforge.ui.i18n import tr

SOURCE_LABELS = (("text", "Text file (one phrase per line)"), ("table", "CSV or Excel file (one phrase per row)"),
                 ("folder", "Folder on disk (one phrase per file)"), ("sqlite", "SQLite database (query)"),
                 ("odbc", "ODBC data source (query)"))


class DynamicFolderDialog(QDialog):
    def __init__(self, store, folder_id: int, parent=None, odbc_connect=None):
        super().__init__(parent)
        self.store, self.folder_id, self.odbc_connect = store, folder_id, odbc_connect
        f = store.get_folder(folder_id)
        self.setWindowTitle(tr("Dynamic folder") + (f" – {f.name}" if f else ""))
        self.resize(560, 460)
        cfg = dynamic.config(store, folder_id) or dynamic.DynamicConfig("table")
        lay = QVBoxLayout(self)
        note = QLabel(tr("The phrases of this folder come from the source below and are updated when it changes. "
                         "Phrases edited by hand here are replaced at the next update."))
        note.setWordWrap(True)
        lay.addWidget(note)
        form = QFormLayout()
        self.source = QComboBox()
        for key, label in SOURCE_LABELS:
            self.source.addItem(tr(label), key)
        self.source.setCurrentIndex(max(0, self.source.findData(cfg.source)))
        self.path = QLineEdit(cfg.path)
        browse = QPushButton(tr("Browse..."))
        browse.clicked.connect(self.browse)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.path)
        rl.addWidget(browse)
        self.browse_button = browse
        self.sheet = QLineEdit(cfg.sheet)
        self.sheet.setPlaceholderText(tr("first sheet"))
        self.query = QPlainTextEdit(cfg.query)
        self.query.setPlaceholderText("SELECT name AS Description, body AS Content FROM phrases")
        self.query.setMaximumHeight(80)
        cols = cfg.columns or {}
        self.col_desc = QLineEdit(cols.get("description", ""))
        self.col_content = QLineEdit(cols.get("content", ""))
        self.col_autotext = QLineEdit(cols.get("autotext", ""))
        for w in (self.col_desc, self.col_content, self.col_autotext):
            w.setPlaceholderText(tr("column name or number (optional)"))
        self.recursive = QCheckBox(tr("Include subfolders"))
        self.recursive.setChecked(cfg.recursive)
        self.link = QCheckBox(tr("Read the file again on every use (keep a link, not a copy)"))
        self.link.setChecked(cfg.link)
        self.ttl = QSpinBox()
        self.ttl.setRange(30, 86400)
        self.ttl.setSuffix(" s")
        self.ttl.setValue(int(cfg.ttl_s or 300))
        self.rows = {}
        for label, w, key in (("Source:", self.source, "source"), ("File, folder or connection:", row, "path"),
                              ("Sheet:", self.sheet, "sheet"), ("Query:", self.query, "query"),
                              ("Description column:", self.col_desc, "cols"), ("Content column:", self.col_content, "cols"),
                              ("Autotext column:", self.col_autotext, "cols"), ("", self.recursive, "folder"),
                              ("", self.link, "folder"), ("Run the query every:", self.ttl, "ttl")):
            lbl = QLabel(tr(label)) if label else QLabel("")
            form.addRow(lbl, w)
            self.rows.setdefault(key, []).append((lbl, w))
        lay.addLayout(form)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.refresh_button = bb.addButton(tr("Save and update now"), QDialogButtonBox.ActionRole)
        self.refresh_button.clicked.connect(self.save_and_refresh)
        self.remove_button = bb.addButton(tr("Make it an ordinary folder"), QDialogButtonBox.ActionRole)
        self.remove_button.clicked.connect(self.make_ordinary)
        self.remove_button.setEnabled(dynamic.config(store, folder_id) is not None)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.source.currentIndexChanged.connect(self._source_changed)
        self._source_changed()
        self._show_status()

    def _source_changed(self) -> None:
        src = self.source.currentData()
        show = {"sheet": src == "table", "query": src in ("sqlite", "odbc"), "cols": src in ("table", "sqlite", "odbc"),
                "folder": src == "folder", "ttl": src in ("sqlite", "odbc"), "path": True, "source": True}
        for key, pairs in self.rows.items():
            for lbl, w in pairs:
                lbl.setVisible(show[key])
                w.setVisible(show[key])
        self.browse_button.setEnabled(src != "odbc")
        self.path.setPlaceholderText("DSN=Phrases;Trusted_Connection=yes" if src == "odbc" else "")

    def _show_status(self) -> None:
        if dynamic.config(self.store, self.folder_id) is None:
            self.status.setText(tr("This is an ordinary folder."))
            return
        st = dynamic.status(self.store, self.folder_id)
        text = tr("{n} phrases from the source.").format(n=st["items"])
        if not dynamic.approved(self.store, self.folder_id):
            text += " " + tr("This source has not been approved on this PC yet: save to approve it.")
        if st["error"]:
            text += " " + tr("Last update failed:") + " " + st["error"]
        self.status.setText(text)

    def browse(self) -> None:
        src = self.source.currentData()
        if src == "folder":
            path = QFileDialog.getExistingDirectory(self, tr("Folder"), self.path.text())
        else:
            filters = {"text": "Text (*.txt)", "table": "Tables (*.csv *.tsv *.txt *.xlsx *.xlsm)",
                       "sqlite": "SQLite (*.db *.sqlite *.sqlite3)"}.get(src, "*")
            path, _ = QFileDialog.getOpenFileName(self, tr("File"), self.path.text(), filters)
        if path:
            self.path.setText(path)

    def config(self) -> dynamic.DynamicConfig:
        cols = {k: w.text().strip() for k, w in (("description", self.col_desc), ("content", self.col_content),
                                                 ("autotext", self.col_autotext)) if w.text().strip()}
        return dynamic.DynamicConfig(self.source.currentData(), self.path.text().strip(),
                                     self.query.toPlainText().strip(), self.sheet.text().strip(), cols,
                                     self.recursive.isChecked(), self.link.isChecked(), self.ttl.value())

    def save(self) -> bool:
        cfg = self.config()
        if not cfg.path:
            QMessageBox.warning(self, tr("Dynamic folder"), tr("Choose the source first."))
            return False
        try:
            dynamic.set_config(self.store, self.folder_id, cfg)
        except Exception as e:
            QMessageBox.warning(self, tr("Dynamic folder"), str(e))
            return False
        return True

    def save_and_refresh(self):
        if not self.save():
            return None
        try:
            res = dynamic.refresh(self.store, self.folder_id, self.odbc_connect)
        except Exception as e:
            self._show_status()
            QMessageBox.warning(self, tr("Dynamic folder"), str(e))
            return None
        self._show_status()
        self.status.setText(self.status.text() + " " + tr("{a} added, {u} updated, {r} removed.").format(
            a=res[0], u=res[1], r=res[2]))
        self.remove_button.setEnabled(True)
        return res

    def make_ordinary(self) -> None:
        dynamic.remove(self.store, self.folder_id)
        self._show_status()
        self.remove_button.setEnabled(False)

    def accept(self) -> None:
        if self.save_and_refresh() is not None:
            super().accept()
