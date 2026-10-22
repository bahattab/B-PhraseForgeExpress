"""SmartComplete / AutoComplete suggestion tip shown near the caret.

The tip never takes keyboard focus (the user keeps typing in their app); the
trigger layer intercepts Tab/Enter (accept) and Esc (dismiss) while it is shown.
Clicking the tip accepts it; the small x dismisses it.

App usage (main thread):
    tip = SmartCompleteTip()
    tip.accepted.connect(triggers.accept_suggestion)
    tip.dismissed.connect(triggers.clear_suggestion)
    on "smartcomplete:<pid>:<n>":  tip.show_for(phrase.description, x, y, preview=first_line)
    on "autocomplete:<word>:<n>":   tip.show_for(word, x, y)
    on "suggest_hide":              tip.hide()
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from phraseforge.ui.iconset import icon


class SmartCompleteTip(QFrame):
    accepted = Signal()
    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setObjectName("SmartCompleteTip")
        self.setStyleSheet(
            "#SmartCompleteTip{background:#ffffe8;border:1px solid #c9b458;border-radius:3px}"
            "#TipTitle{font-weight:600}#TipHint{color:#7a6a20;font-size:8pt}#TipPreview{color:#555}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 4, 4)
        lay.setSpacing(6)
        ic = QLabel()
        ic.setPixmap(icon("exec_mode").pixmap(16, 16))
        lay.addWidget(ic, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.title = QLabel()
        self.title.setObjectName("TipTitle")
        self.preview = QLabel()
        self.preview.setObjectName("TipPreview")
        self.hint = QLabel("Tab or Enter: insert   Esc: ignore")
        self.hint.setObjectName("TipHint")
        col.addWidget(self.title)
        col.addWidget(self.preview)
        col.addWidget(self.hint)
        lay.addLayout(col, 1)
        close = QToolButton()
        close.setIcon(icon("remove"))
        close.setAutoRaise(True)
        close.setToolTip("Ignore this suggestion")
        close.clicked.connect(self._dismiss)
        lay.addWidget(close, 0, Qt.AlignTop)

    def show_for(self, text: str, x: int, y: int, preview: str = "") -> None:
        self.title.setText(text)
        self.preview.setText(preview[:80] + ("…" if len(preview) > 80 else ""))
        self.preview.setVisible(bool(preview))
        self.adjustSize()
        pos = QPoint(int(x), int(y) + 22)              # just below the caret line
        screen = QGuiApplication.screenAt(QPoint(int(x), int(y))) or QGuiApplication.primaryScreen()
        if screen is not None:
            g = screen.availableGeometry()
            pos.setX(max(g.left(), min(pos.x(), g.right() - self.width())))
            if pos.y() + self.height() > g.bottom():
                pos.setY(int(y) - self.height() - 6)
        self.move(pos)
        self.show()
        self.raise_()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.hide()
            self.accepted.emit()
        super().mousePressEvent(e)

    def _dismiss(self):
        self.hide()
        self.dismissed.emit()
