"""Theme entry point used by app.py.

PhraseForge uses one light, Office-like look (phraseforge.ui.pe_style) that matches
the PhraseExpress reference screenshots. `mode` is kept for compatibility: "dark"
only darkens the palette of plain dialogs; the ribbon look stays light.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from phraseforge.ui import i18n, pe_style

ACCENT = pe_style.ACCENT


def is_dark(mode: str) -> bool:
    if mode == "dark":
        return True
    if mode == "light":
        return False
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return False


def apply_theme(app: QApplication, mode: str = "system", language: str | None = None) -> None:
    pe_style.apply(app)
    if language is not None:
        i18n.set_language(language)
        app.setLayoutDirection(Qt.RightToLeft if language == "ar" else Qt.LeftToRight)
