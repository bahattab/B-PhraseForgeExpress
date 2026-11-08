"""Learned suggestions: text typed or e-mailed often -> offer to make it a phrase."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QProgressDialog, QPushButton, QVBoxLayout,
)

from phraseforge import mail_analysis
from phraseforge.db import Store
from phraseforge.models import Folder, Phrase, Trigger, TriggerKind
from phraseforge.ui.i18n import tr
from phraseforge.ui.icons import app_icon


class SuggestionsDialog(QDialog):
    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle(tr("Suggestions"))
        self.setWindowIcon(app_icon())
        self.resize(520, 420)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("You typed or e-mailed these often. Turn them into phrases?")))
        self.list = QListWidget()
        lay.addWidget(self.list)
        row = QHBoxLayout()
        b1 = QPushButton(tr("Create phrase"))
        b1.setObjectName("primary")
        b1.clicked.connect(self._create)
        b2 = QPushButton(tr("Dismiss"))
        b2.clicked.connect(self._dismiss)
        b3 = QPushButton(tr("Clear list"))
        b3.setToolTip(tr("Forget every suggestion, dismissed ones included"))
        b3.clicked.connect(self._clear)
        row.addWidget(b1)
        row.addWidget(b2)
        row.addWidget(b3)
        row.addStretch()
        lay.addLayout(row)
        g = QHBoxLayout()
        g.addWidget(QLabel(tr("Find text you write often in your e-mails:")))
        self.outlook_button = QPushButton(tr("Analyze Outlook..."))
        self.outlook_button.setToolTip(tr("Reads the newest mails in Sent Items (classic Outlook for Windows)"))
        self.outlook_button.setEnabled(mail_analysis.outlook_available())
        self.outlook_button.clicked.connect(self.analyze_outlook)
        files = QPushButton(tr("Analyze mail files..."))
        files.setToolTip(tr("Saved mails (.eml) or mailboxes (.mbox) from any mail program"))
        files.clicked.connect(self.analyze_files)
        g.addWidget(self.outlook_button)
        g.addWidget(files)
        g.addStretch()
        lay.addLayout(g)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        mc = int(self.store.setting("learning.min_count", "3") or 3)
        for s in self.store.suggestions(mc):
            it = QListWidgetItem(f"{s['count']}×  {s['text']}")
            it.setData(Qt.UserRole, s["text"])
            self.list.addItem(it)

    def _target_folder(self) -> int:
        for f in self.store.folders(None):
            if f.name == "Learned":
                return f.id
        return self.store.add_folder(Folder("Learned")).id

    def create_phrase(self, text: str, abbreviation: str) -> Phrase:
        """A suggestion is plain text someone typed or mailed, never macros: "{" is written
        as "{{" so a mailed {#run ...} stays literal text in the new phrase (security R20)."""
        trig = [Trigger(TriggerKind.AUTOTEXT, abbreviation)] if abbreviation else []
        content = text.replace("{", "{{")
        p = self.store.add_phrase(Phrase(text[:60], content, folder_id=self._target_folder(), triggers=trig))
        self.store.dismiss_suggestion(text)
        return p

    def _create(self) -> None:
        it = self.list.currentItem()
        if not it:
            return
        abbr, ok = QInputDialog.getText(self, tr("Create phrase"), "Abbreviation (optional):")
        if not ok:
            return
        self.create_phrase(it.data(Qt.UserRole), abbr.strip())
        self.refresh()

    def _clear(self) -> None:
        if QMessageBox.question(self, tr("Suggestions"), tr(
                "Forget every suggestion, dismissed ones included? Text you write often may be suggested again "
                "later.")) == QMessageBox.Yes:
            self.store.clear_suggestions()
            self.refresh()

    def _dismiss(self) -> None:
        it = self.list.currentItem()
        if it:
            self.store.dismiss_suggestion(it.data(Qt.UserRole))
            self.refresh()

    # ---------------------------------------------------------------- mail analysis
    def run_analysis(self, bodies, total: int = 0) -> tuple[int, int] | None:
        """Analyze mail bodies with a progress window; None when it failed."""
        prog = QProgressDialog(tr("Analyzing e-mails..."), tr("Cancel"), 0, total, self)
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(400)

        def step(n: int) -> bool:
            prog.setValue(min(n, total) if total else 0)
            prog.setLabelText(tr("Analyzing e-mails...") + f" {n}")
            QApplication.processEvents()
            return not prog.wasCanceled()
        try:
            found, n = mail_analysis.analyze_into(self.store, bodies, step)
        except mail_analysis.MailSourceError as e:
            QMessageBox.warning(self, tr("Suggestions"), tr(str(e)))
            return None
        finally:
            prog.close()
        self.status.setText(tr("{found} sentences repeated in {mails} e-mails.").format(found=found, mails=n))
        self.refresh()
        return found, n

    def analyze_outlook(self) -> None:
        limit, ok = QInputDialog.getInt(self, tr("Analyze Outlook..."),
                                        tr("Number of newest sent e-mails to analyze:"), 500, 10, 20000, 100)
        if ok:
            self.run_analysis(mail_analysis.outlook_messages(limit), limit)

    def analyze_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, tr("Analyze mail files..."), "",
                                                tr("Mail files") + " (*.eml *.mbox *.mbx);;" + tr("All files") + " (*)")
        if paths:
            self.run_analysis(mail_analysis.file_messages(paths))
