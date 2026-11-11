"""The instant translation window (phraseforge/instant_translate.py)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QVBoxLayout)

from phraseforge import instant_translate as it


class TranslateBubble(QFrame):
    """Shows the original and its translation next to (x, y). Buttons: Copy, Replace, Swap,
    Listen and a target-language list. replace_requested(text) asks the app to put the
    translation in place of the selection; retranslate(text, lang) asks for another target."""
    replace_requested = Signal(str)
    retranslate = Signal(str, str)
    speak_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setObjectName("TranslateBubble")
        self.setFrameShape(QFrame.StyledPanel)
        self.setMinimumWidth(340)
        self.setMaximumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        top = QHBoxLayout()
        self.title = QLabel("Translation")
        self.title.setTextFormat(Qt.PlainText)
        top.addWidget(self.title, 1)
        self.lang = QComboBox()
        self.lang.addItems(it.LANGUAGES)
        self.lang.activated.connect(lambda _i: self.retranslate.emit(self.original, self.lang.currentText()))
        top.addWidget(self.lang)
        close = QPushButton("×")
        close.setFixedWidth(26)
        close.setToolTip("Close (Esc)")
        close.clicked.connect(self.hide)
        top.addWidget(close)
        lay.addLayout(top)
        self.source = QLabel()
        self.source.setTextFormat(Qt.PlainText)        # text from another program: never rich text
        self.source.setWordWrap(True)
        self.source.setStyleSheet("color: palette(mid);")
        lay.addWidget(self.source)
        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setFixedHeight(120)
        lay.addWidget(self.result)
        row = QHBoxLayout()
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.clicked.connect(self._copy)
        self.replace_btn = QPushButton("Replace selection")
        self.replace_btn.clicked.connect(lambda: (self.replace_requested.emit(self.translation), self.hide()))
        self.swap_btn = QPushButton("Swap")
        self.swap_btn.setToolTip("Translate the translation back")
        self.swap_btn.clicked.connect(self._swap)
        self.listen_btn = QPushButton("Listen")
        self.listen_btn.clicked.connect(lambda: self.speak_requested.emit(self.translation))
        for b in (self.copy_btn, self.replace_btn, self.swap_btn, self.listen_btn):
            row.addWidget(b)
        lay.addLayout(row)
        self.original = self.translation = ""
        self.source_lang = ""

    def show_busy(self, text: str, x: int, y: int) -> None:
        self.original, self.translation = text, ""
        self.source.setText(_short(text))
        self.result.setPlainText("Translating…")
        self._buttons(False)
        self._place(x, y)

    def show_result(self, text: str, translation: str, target: str) -> None:
        self.original, self.translation = text, translation
        self.source.setText(_short(text))
        self.result.setPlainText(translation)
        rtl = target.lower() in ("arabic", "persian", "urdu", "hebrew")
        self.result.document().setDefaultTextOption(_option(rtl))
        self.title.setText(f"Translation · {target}")
        i = self.lang.findText(target)
        if i >= 0:
            self.lang.setCurrentIndex(i)
        self._buttons(True)

    def show_error(self, message: str) -> None:
        self.result.setPlainText(message)
        self._buttons(False)

    def _buttons(self, on: bool) -> None:
        for b in (self.copy_btn, self.replace_btn, self.swap_btn, self.listen_btn):
            b.setEnabled(on)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.translation)
        self.copy_btn.setText("Copied")

    def _swap(self) -> None:
        if self.translation:
            back = "English" if self.lang.currentText() != "English" else "Arabic"
            self.retranslate.emit(self.translation, back)

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(e)

    def _place(self, x: int, y: int) -> None:
        self.copy_btn.setText("Copy")
        self.adjustSize()
        screen = QGuiApplication.screenAt(self.mapToGlobal(self.rect().center())) or QGuiApplication.primaryScreen()
        from PySide6.QtCore import QPoint
        scr = QGuiApplication.screenAt(QPoint(x, y)) or screen
        g = scr.availableGeometry()
        w, h = self.sizeHint().width(), self.sizeHint().height()
        px = min(max(g.left(), x), g.right() - w)
        py = y + 12 if y + 12 + h <= g.bottom() else max(g.top(), y - h - 24)
        self.move(px, py)
        self.show()
        self.raise_()
        self.activateWindow()


def _short(text: str, limit: int = 240) -> str:
    t = " ".join(text.split())
    return t if len(t) <= limit else t[:limit] + "…"


def _option(rtl: bool):
    from PySide6.QtGui import QTextOption
    o = QTextOption()
    o.setTextDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
    o.setWrapMode(QTextOption.WordWrap)
    return o
