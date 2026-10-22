"""First-run wizard."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QCheckBox, QLabel, QVBoxLayout, QWizard, QWizardPage

from phraseforge.db import Store
from phraseforge.models import Folder, Phrase, Trigger, TriggerKind
from phraseforge.ui.hotkey_picker import HotkeyPicker
from phraseforge.ui.i18n import tr
from phraseforge.ui.icons import about_artwork, app_icon, paint_mark

SAMPLES = [
    ("Email signature", "Best regards,\n{#input \"Your name\"}", "sig#"),
    ("Today's date", "{#date -format \"yyyy-MM-dd\"}", "dt#"),
    ("OCR Arabic text from screen", "{#ocr -lang Arabic}", "ocr#"),
]


def _banner(width: int = 600, height: int = 64) -> QPixmap:
    pm = QPixmap(width, height)
    p = QPainter(pm)
    g = QLinearGradient(0, 0, 0, height)
    g.setColorAt(0, QColor("#3a8ad6"))
    g.setColorAt(1, QColor("#1d5fa8"))
    p.fillRect(pm.rect(), g)
    paint_mark(p, QRectF(width - height + 8, 8, height - 16, height - 16), tile=False)
    p.end()
    return pm


def _page(title: str, subtitle: str) -> QWizardPage:
    pg = QWizardPage()
    pg.setTitle(f"<span style='color:white;font-size:13pt;font-weight:600'>{title}</span>")
    pg.setSubTitle(f"<span style='color:#e8f1fb'>{subtitle}</span>")
    return pg


class FirstRunWizard(QWizard):
    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("PhraseForge setup")
        self.setWindowIcon(app_icon())
        self.setWizardStyle(QWizard.ModernStyle)
        self.setPixmap(QWizard.BannerPixmap, _banner())
        self.setPixmap(QWizard.WatermarkPixmap, about_artwork(160, 320))
        self.setOption(QWizard.NoBackButtonOnStartPage, True)

        p1 = _page(tr("Welcome"), "Type less. PhraseForge types for you.")
        l1 = QVBoxLayout(p1)
        t = QLabel("Type a short abbreviation such as <b>sig#</b> and PhraseForge expands it into a full "
                   "phrase. Or press a hotkey to pick a phrase from the popup menu.<br><br>"
                   "This short setup picks your popup hotkey and adds a few sample phrases.")
        t.setWordWrap(True)
        l1.addWidget(t)
        self.addPage(p1)

        p2 = _page(tr("Hotkeys"), "Choose the hotkey that opens the phrase menu.")
        l2 = QVBoxLayout(p2)
        l2.addWidget(QLabel(tr("Phrase menu")))
        self.popup_hotkey = HotkeyPicker(store.setting("popup.hotkey", "ctrl+alt+space"), clearable=False)
        l2.addWidget(self.popup_hotkey)
        tip = QLabel("Tip: you can change all hotkeys later in Settings › Hotkeys.")
        tip.setStyleSheet("color:#666666")
        l2.addWidget(tip)
        l2.addStretch(1)
        self.addPage(p2)

        p3 = _page("Sample phrases", "Start with a few ready-made phrases.")
        l3 = QVBoxLayout(p3)
        self.create_samples = QCheckBox("Create sample phrases (signature, date, screen OCR)")
        self.create_samples.setChecked(True)
        l3.addWidget(self.create_samples)
        for desc, _content, abbr in SAMPLES:
            lab = QLabel(f"&nbsp;&nbsp;•&nbsp;{desc} — type <b>{abbr}</b>")
            l3.addWidget(lab)
        l3.addStretch(1)
        self.addPage(p3)

    def apply(self) -> None:
        if self.popup_hotkey.value():
            self.store.set_setting("popup.hotkey", self.popup_hotkey.value())
        if self.create_samples.isChecked():
            f = self.store.add_folder(Folder("Samples"))
            for desc, content, abbr in SAMPLES:
                self.store.add_phrase(Phrase(desc, content, folder_id=f.id,
                                             triggers=[Trigger(TriggerKind.AUTOTEXT, abbr)]))
        self.store.set_setting("app.first_run_done", "1")

    def accept(self) -> None:
        self.apply()
        super().accept()
