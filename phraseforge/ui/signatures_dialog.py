"""Signature manager: e-mail signatures, dated footers, random quotes, export to Outlook."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QTextBrowser, QVBoxLayout,
)

from phraseforge import signatures
from phraseforge.db import Store
from phraseforge.models import Phrase
from phraseforge.ui.i18n import tr
from phraseforge.ui.icons import app_icon


class FooterDatesDialog(QDialog):
    def __init__(self, start: str, end: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Footer dates"))
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("Show the footer only between these dates. MM-DD repeats every year "
                                "(12-15 to 01-05 spans New Year), YYYY-MM-DD is one time. Empty = always.")))
        form = QFormLayout()
        self.start, self.end = QLineEdit(start), QLineEdit(end)
        for w in (self.start, self.end):
            w.setPlaceholderText("MM-DD")
        form.addRow(tr("From:"), self.start)
        form.addRow(tr("To:"), self.end)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class SignaturesDialog(QDialog):
    def __init__(self, store: Store, parent=None, on_edit=None, expand=None):
        super().__init__(parent)
        self.store = store
        self.on_edit = on_edit                         # on_edit(phrase_id): open the phrase in the editor
        self.expand = expand or signatures.preview_expand(store)
        self.setWindowTitle(tr("Signatures"))
        self.setWindowIcon(app_icon())
        self.resize(640, 560)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("Signatures are phrases in the Signatures folder. Insert the default one with "
                                "{#signature}, or export them to Outlook.")))
        row = QHBoxLayout()
        self.list = QListWidget()
        self.list.currentRowChanged.connect(lambda _r: self.refresh_preview())
        self.list.itemDoubleClicked.connect(lambda _i: self.edit())
        row.addWidget(self.list, 1)
        col = QVBoxLayout()
        for label, fn in (("New signature...", self.new), ("Edit", self.edit), ("Set as default", self.make_default),
                          ("Export to Outlook...", self.export_outlook)):
            b = QPushButton(tr(label))
            b.clicked.connect(fn)
            col.addWidget(b)
        col.addStretch()
        row.addLayout(col)
        lay.addLayout(row)
        self.preview = QTextBrowser()
        self.preview.setMaximumHeight(150)
        lay.addWidget(self.preview)

        g = QGroupBox(tr("Footers below the signature"))
        gl = QHBoxLayout(g)
        self.footer_list = QListWidget()
        gl.addWidget(self.footer_list, 1)
        fc = QVBoxLayout()
        for label, fn in (("New footer...", self.new_footer), ("Dates...", self.footer_dates)):
            b = QPushButton(tr(label))
            b.clicked.connect(fn)
            fc.addWidget(b)
        fc.addStretch()
        gl.addLayout(fc)
        lay.addWidget(g)
        q = QHBoxLayout()
        self.quote = QCheckBox(tr("Add a random quote from the Quotes folder"))
        self.quote.setChecked(store.setting("signature.random_quote", "0") == "1")
        self.quote.toggled.connect(self._quote_toggled)
        q.addWidget(self.quote)
        b = QPushButton(tr("New quote..."))
        b.clicked.connect(self.new_quote)
        q.addWidget(b)
        q.addStretch()
        lay.addLayout(q)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.refresh()

    # ---------------------------------------------------------------- lists
    def selected(self) -> Phrase | None:
        it = self.list.currentItem()
        return self.store.get_phrase(it.data(Qt.UserRole)) if it else None

    def refresh(self, select: int | None = None) -> None:
        cur = select if select is not None else (self.selected().id if self.selected() else None)
        d = signatures.default(self.store)
        self.list.blockSignals(True)
        self.list.clear()
        for p in signatures.signatures(self.store):
            it = QListWidgetItem(p.description + (f"  ({tr('default')})" if d and p.id == d.id else ""))
            it.setData(Qt.UserRole, p.id)
            self.list.addItem(it)
            if p.id == cur or (cur is None and d and p.id == d.id):
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        dates = signatures.footer_dates(self.store)
        active = {p.id for p in signatures.active_footers(self.store)}
        self.footer_list.clear()
        for p in signatures.footers(self.store):
            a, b = dates.get(p.id, ("", ""))
            when = f"{a or '…'} – {b or '…'}" if (a or b) else tr("always")
            state = tr("shown now") if p.id in active else tr("not shown now")
            it = QListWidgetItem(f"{p.description}   [{when}, {state}]")
            it.setData(Qt.UserRole, p.id)
            self.footer_list.addItem(it)
        self.refresh_preview()

    def preview_html(self) -> str:
        p = self.selected()
        if p is None:
            return ""
        content, fmt = signatures.compose(self.store, sig=p)
        try:
            out = self.expand(content, fmt)
        except Exception as e:                          # a macro that fails shows its error, not a crash
            return f"<i>{type(e).__name__}: {e}</i>"
        return out if fmt == "html" else signatures._text_to_html(out)

    def refresh_preview(self) -> None:
        self.preview.setHtml(self.preview_html())

    # ---------------------------------------------------------------- actions
    def _ask(self, title: str, label: str, default: str = "") -> str:
        text, ok = QInputDialog.getText(self, tr(title), tr(label), text=default)
        return text.strip() if ok else ""

    def new(self) -> None:
        name = self._ask("New signature", "Name of the signature:", tr("Business"))
        if name:
            p = signatures.new_signature(self.store, name)
            self.refresh(select=p.id)
            self.edit()

    def edit(self) -> None:
        p = self.selected()
        if p is not None and self.on_edit is not None:
            self.on_edit(p.id)
            self.accept()

    def make_default(self) -> None:
        p = self.selected()
        if p is not None:
            signatures.set_default(self.store, p.id)
            self.refresh(select=p.id)

    def new_footer(self) -> None:
        text = self._ask("New footer", "Footer text (for example a holiday greeting):")
        if text:
            f = signatures.subfolder(self.store, signatures.FOOTERS, create=True)
            self.store.add_phrase(Phrase(text[:60], text, folder_id=f.id))
            self.refresh()

    def footer_dates(self) -> None:
        it = self.footer_list.currentItem()
        if it is None:
            return
        pid = it.data(Qt.UserRole)
        a, b = signatures.footer_dates(self.store).get(pid, ("", ""))
        d = FooterDatesDialog(a, b, self)
        if d.exec() != QDialog.Accepted:
            return
        try:
            signatures.set_footer_dates(self.store, pid, d.start.text().strip(), d.end.text().strip())
        except ValueError as e:
            QMessageBox.warning(self, tr("Footer dates"), str(e))
        self.refresh()

    def new_quote(self) -> None:
        text = self._ask("New quote", "Quote:")
        if text:
            f = signatures.subfolder(self.store, signatures.QUOTES, create=True)
            self.store.add_phrase(Phrase(text[:60], text, folder_id=f.id))
            self.refresh()

    def _quote_toggled(self, on: bool) -> None:
        self.store.set_setting("signature.random_quote", "1" if on else "0")
        self.refresh_preview()

    def export_outlook(self, target=None, winreg=None) -> list:
        from phraseforge import paths
        if target is None and paths.is_portable():
            QMessageBox.information(self, tr("Signatures"), tr(
                "Exporting to Outlook is not available in portable mode: Outlook's signature folder is in "
                "this PC's user profile. Copy the signature text instead."))
            return []
        if not signatures.signatures(self.store):
            QMessageBox.information(self, tr("Signatures"), tr("There are no signatures yet."))
            return []
        try:
            written = signatures.export_outlook(self.store, self.expand, target)
        except OSError as e:
            QMessageBox.warning(self, tr("Signatures"), str(e))
            return []
        d = signatures.default(self.store)
        msg = tr("{n} signatures saved for Outlook in {folder}.").format(
            n=len(written), folder=str(written[0].parent) if written else "")
        if d is not None and (winreg is not None or sys.platform == "win32"):
            ans = QMessageBox.question(self, tr("Signatures"), msg + "\n\n" + tr(
                "Make \"{name}\" Outlook's default signature for new mail and replies?").format(name=d.description))
            if ans == QMessageBox.Yes:
                try:
                    signatures.set_outlook_default(signatures.outlook_names(self.store)[d.id], winreg=winreg)
                except OSError as e:
                    QMessageBox.warning(self, tr("Signatures"), str(e))
        else:
            QMessageBox.information(self, tr("Signatures"), msg)
        return written
