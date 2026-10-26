"""In-app user guide: the Arabic guide for the Arabic interface, else the README."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout

ROOT = Path(__file__).resolve().parents[2]


def guide_path(lang: str) -> Path:
    ar = ROOT / "docs" / "USER_GUIDE.ar.md"
    if lang == "ar" and ar.is_file():
        return ar
    return ROOT / "README.md"


class GuideDialog(QDialog):
    def __init__(self, lang: str = "en", parent=None):
        super().__init__(parent)
        self.setWindowTitle("User guide")
        self.resize(820, 640)
        lay = QVBoxLayout(self)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setProperty("pf_user", True)            # document text, not UI strings
        path = guide_path(lang)
        self.path = path
        text = path.read_text(encoding="utf-8") if path.is_file() else "Guide not found."
        self.view.setMarkdown(text)
        if lang == "ar":
            self.view.setLayoutDirection(Qt.RightToLeft)
            opt = self.view.document().defaultTextOption()
            opt.setTextDirection(Qt.RightToLeft)
            opt.setAlignment(Qt.AlignRight)
            self.view.document().setDefaultTextOption(opt)
        lay.addWidget(self.view)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
