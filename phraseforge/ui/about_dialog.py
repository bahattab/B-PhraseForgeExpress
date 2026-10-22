"""About PhraseForge: version, links, license status and third-party credits."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout,
)

from phraseforge import __version__
from phraseforge.ui.icons import about_artwork, app_icon

PROJECT_README = Path(__file__).resolve().parents[2] / "README.md"

CREDITS = [
    ("PySide6 / Qt", "LGPL v3", "user interface"),
    ("QtAwesome", "MIT", "icons (Material Design Icons, Apache 2.0)"),
    ("Capture2Text", "GPL v3", "screen OCR — a separate program PhraseForge starts; not bundled"),
    ("SQLite", "Public domain", "phrase database"),
    ("httpx", "BSD", "HTTP and AI requests"),
    ("openpyxl", "MIT", "Excel macros"),
]


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About PhraseForge")
        self.setWindowIcon(app_icon())
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 12, 12)
        outer.setSpacing(14)
        art = QLabel()
        art.setPixmap(about_artwork(180, 300))
        art.setAlignment(Qt.AlignTop)
        outer.addWidget(art)

        right = QVBoxLayout()
        right.setContentsMargins(0, 14, 0, 0)
        right.setSpacing(8)
        self.version_label = QLabel(f"PhraseForge v{__version__}")
        right.addWidget(self.version_label)
        right.addWidget(QLabel("© 2026 PhraseForge contributors"))
        link = QLabel(f'<a href="{QUrl.fromLocalFile(str(PROJECT_README)).toString()}">Project page (README)</a>')
        link.setObjectName("Hyperlink")
        link.setOpenExternalLinks(True)
        right.addWidget(link)

        box = QGroupBox("License Information")
        grid = QGridLayout(box)
        grid.setColumnMinimumWidth(0, 80)
        grid.addWidget(QLabel("Status:"), 0, 0, Qt.AlignRight)
        status = QLabel("Free to use — no registration needed")
        status.setStyleSheet("color: #2f7d32;")
        grid.addWidget(status, 0, 1)
        grid.addWidget(QLabel("Data:"), 1, 0, Qt.AlignRight)
        grid.addWidget(QLabel("Stored only on this computer"), 1, 1)
        right.addWidget(box)
        right.addStretch(1)

        bottom = QHBoxLayout()
        credits = QLabel('<a href="#credits">Credits</a>')
        credits.setObjectName("Hyperlink")
        credits.linkActivated.connect(lambda _l: self.show_credits())
        bottom.addWidget(credits)
        bottom.addStretch(1)
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        bottom.addWidget(ok)
        right.addLayout(bottom)
        outer.addLayout(right, 1)
        self.setFixedSize(620, 300)

    @staticmethod
    def credits_text() -> str:
        lines = ["PhraseForge is built on these components:", ""]
        lines += [f"• {name} — {lic} — {what}" for name, lic, what in CREDITS]
        lines += ["", "PhraseForge's design and artwork are original. It is not affiliated with "
                      "any other text-expander product."]
        return "\n".join(lines)

    def show_credits(self) -> None:
        QMessageBox.information(self, "Credits", self.credits_text())


def open_project_page() -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(PROJECT_README)))
