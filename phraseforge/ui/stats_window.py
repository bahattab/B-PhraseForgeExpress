"""Statistics dialog: time and money PhraseForge saved you.

Layout follows the classic text-expander statistics dialog: intro text,
"Today's savings", "Total savings", Settings (typing speed with a
Re-determine typing test, hourly wage), a "Usage statistics" switch, OK/Help,
plus a "Details" section with per-day chart and top phrases/apps.

Settings: stats.typing_speed (chars/minute, default 200), stats.hourly_wage
(default 0), stats.currency (default from locale), features.usage_statistics ("1", shared with
Settings > Features: when off, expansions are not counted).
"""
from __future__ import annotations

import time
from datetime import date

from PySide6.QtCore import QLocale, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDoubleSpinBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QToolButton, QVBoxLayout, QWidget,
)

from phraseforge.db import Store
from phraseforge.ui.icons import app_icon

ACCENT = "#2b579a"
DEFAULT_CPM = 200
TEST_TEXT = ("The quick brown fox jumps over the lazy dog while the five boxing "
             "wizards jump quickly over the bright yellow fence.")


# ---------------------------------------------------------------- math
def time_saved_minutes(chars: int, cpm: float) -> float:
    """Minutes it would take to type `chars` at `cpm` characters per minute."""
    return (chars / cpm) if cpm > 0 else 0.0


def format_duration(minutes: float) -> str:
    total = int(round(minutes))
    if total < 1:
        return "less than a minute"
    days, rem = divmod(total, 1440)
    hours, mins = divmod(rem, 60)
    parts = []
    for n, word in ((days, "day"), (hours, "hour"), (mins, "minute")):
        if n:
            parts.append(f"{n} {word}{'' if n == 1 else 's'}")
    return ", ".join(parts)


def compute_cpm(chars: int, seconds: float) -> int:
    return int(round(chars * 60 / seconds)) if seconds > 0 else 0


# ---------------------------------------------------------------- widgets
class BarChart(QWidget):
    """Simple bar chart of (label, value)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data: list[tuple[str, float]] = []
        self.setMinimumHeight(140)

    def set_data(self, data: list[tuple[str, float]]) -> None:
        self.data = data
        self.update()

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("white"))
        w, h = self.width(), self.height()
        if not self.data:
            p.setPen(QColor("#8a8a8a"))
            p.drawText(self.rect(), Qt.AlignCenter, "No usage yet")
            return
        mx = max(v for _, v in self.data) or 1
        n = len(self.data)
        gap = 4
        bw = max(2.0, (w - gap * (n + 1)) / n)
        base = h - 18
        p.setPen(QColor("#555555"))
        for i, (label, v) in enumerate(self.data):
            x = gap + i * (bw + gap)
            bh = (base - 6) * (v / mx)
            p.fillRect(QRectF(x, base - bh, bw, bh), QColor(ACCENT))
            if n <= 15 or i % max(1, n // 10) == 0:
                p.drawText(QRectF(x - 10, base + 2, bw + 20, 14), Qt.AlignCenter, label[-5:])


class TypingTestDialog(QDialog):
    """Measures typing speed: type the sample sentence, speed counts correct characters."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Determine typing speed")
        self.setWindowIcon(app_icon())
        self.cpm = 0
        self._start: float | None = None
        lay = QVBoxLayout(self)
        intro = QLabel("Type the following text as fast and as accurately as you normally do. "
                       "The timer starts with your first keystroke.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        sample = QLabel(TEST_TEXT)
        sample.setWordWrap(True)
        sample.setStyleSheet("font-size: 11pt; padding: 6px; background: white; border: 1px solid #d0d0d0;")
        lay.addWidget(sample)
        self.edit = QPlainTextEdit()
        self.edit.setFixedHeight(70)
        self.edit.textChanged.connect(self._changed)
        lay.addWidget(self.edit)
        self.result = QLabel(" ")
        lay.addWidget(self.result)
        row = QHBoxLayout()
        row.addStretch(1)
        self.ok = QPushButton("OK")
        self.ok.setEnabled(False)
        self.ok.setDefault(True)
        self.ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(self.ok)
        row.addWidget(cancel)
        lay.addLayout(row)
        self.resize(520, 260)

    def _changed(self) -> None:
        text = self.edit.toPlainText()
        if text and self._start is None:
            self._start = time.monotonic()
        if not text or self._start is None:
            return
        correct = sum(1 for a, b in zip(text, TEST_TEXT) if a == b)
        secs = time.monotonic() - self._start
        if len(text) >= len(TEST_TEXT) * 0.9 and secs > 0:
            self.cpm = compute_cpm(correct, secs)
            self.result.setText(f"Your typing speed: <b>{self.cpm}</b> characters per minute")
            self.ok.setEnabled(self.cpm > 0)


def _group(title: str) -> tuple[QFrame, QVBoxLayout]:
    """Light-bordered panel with a bold caption on its first line."""
    g = QFrame()
    g.setObjectName("StatsPanel")
    g.setStyleSheet("#StatsPanel{border:1px solid #dcdcdc;background:transparent}")
    lay = QVBoxLayout(g)
    lay.setContentsMargins(8, 4, 8, 8)
    lay.setSpacing(6)
    cap = QLabel(title)
    f = QFont(cap.font())
    f.setBold(True)
    cap.setFont(f)
    lay.addWidget(cap)
    return g, lay


class StatsWindow(QDialog):
    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Statistics")
        self.setWindowIcon(app_icon())
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        intro = QLabel(
            "PhraseForge inserts text faster than anyone can type it, and its statistics show how much "
            "time that saves you.<br><br>"
            "PhraseForge counts the characters it inserts and compares them with your typing speed "
            "to calculate the time you save.<br><br>"
            "Enter your hourly rate to see the money you save, too.")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        g, gl = _group("Today's savings")
        self.today_label = QLabel()
        self.today_label.setWordWrap(True)
        gl.addWidget(self.today_label)
        lay.addWidget(g)

        g, gl = _group("Total savings")
        self.total_label = QLabel()
        self.total_label.setWordWrap(True)
        gl.addWidget(self.total_label)
        lay.addWidget(g)

        g, gl = _group("Settings")
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Determined typing speed:"))
        self.speed = QSpinBox()
        self.speed.setLocale(QLocale.c())          # Western digits, like the rest of the dialog
        self.speed.setMinimumWidth(64)
        self.speed.setRange(20, 1500)
        self.speed.setValue(self._int("stats.typing_speed", DEFAULT_CPM))
        self.speed.valueChanged.connect(self.refresh)
        r1.addWidget(self.speed)
        r1.addWidget(QLabel("characters per minute"))
        r1.addStretch(1)
        redo = QPushButton("Re-determine")
        redo.clicked.connect(self.redetermine)
        r1.addWidget(redo)
        gl.addLayout(r1)
        r2 = QHBoxLayout()
        r2.addSpacing(40)
        r2.addWidget(QLabel("Your hourly wage:"))
        self.wage = QDoubleSpinBox()
        self.wage.setLocale(QLocale.c())
        self.wage.setMinimumWidth(80)
        self.wage.setRange(0, 100000)
        self.wage.setDecimals(2)
        self.wage.setValue(self._float("stats.hourly_wage", 0))
        self.wage.valueChanged.connect(self.refresh)
        r2.addWidget(self.wage)
        self.currency = store.setting("stats.currency", "") or QLocale().currencySymbol() or "$"
        r2.addWidget(QLabel(self.currency))
        r2.addStretch(1)
        gl.addLayout(r2)
        lay.addWidget(g)

        self.usage = QCheckBox("Usage statistics")
        self.usage.setChecked(store.setting("features.usage_statistics", "1") != "0")
        lay.addWidget(self.usage)

        # details (our addition): chart + top phrases + apps
        self.details_button = QToolButton()
        self.details_button.setText("Details")
        self.details_button.setCheckable(True)
        self.details_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.details_button.setArrowType(Qt.RightArrow)
        self.details_button.setAutoRaise(True)
        self.details_button.toggled.connect(self._toggle_details)
        lay.addWidget(self.details_button)
        self.details = QWidget()
        dl = QVBoxLayout(self.details)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.addWidget(QLabel("Expansions per day"))
        self.chart = BarChart()
        dl.addWidget(self.chart)
        row = QHBoxLayout()
        self.top = self._table(["Phrase", "Uses", "Chars"])
        self.apps = self._table(["App", "Uses"])
        row.addWidget(self.top, 2)
        row.addWidget(self.apps, 1)
        dl.addLayout(row)
        self.details.setVisible(False)
        lay.addWidget(self.details)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        help_ = QPushButton("Help")
        help_.clicked.connect(self._help)
        buttons.addWidget(ok)
        buttons.addWidget(help_)
        lay.addLayout(buttons)
        self.setFixedWidth(660)
        self.refresh()

    # -------------------------------------------------- helpers
    def _int(self, key, default):
        try:
            return int(float(self.store.setting(key, str(default)) or default))
        except ValueError:
            return default

    def _float(self, key, default):
        try:
            return float(self.store.setting(key, str(default)) or default)
        except ValueError:
            return default

    @staticmethod
    def _table(headers) -> QTableWidget:
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.setMinimumHeight(140)
        return t

    def _money(self, minutes: float) -> str:
        wage = self.wage.value()
        if wage <= 0:
            return ""
        return f" That is worth {wage * minutes / 60:,.2f} {self.currency}."

    def _today(self) -> tuple[int, int]:
        today = date.today().isoformat()
        with self.store.lock:
            r = self.store.conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(chars),0) FROM usage_log WHERE substr(used,1,10)=?",
                (today,)).fetchone()
        return int(r[0]), int(r[1])

    # -------------------------------------------------- content
    def refresh(self) -> None:
        s = self.store.stats()
        cpm = self.speed.value()
        n, chars = self._today()
        if n < 1:
            self.today_label.setText("Please use PhraseForge a bit more, so it can calculate the time you "
                                     "save today.")
        else:
            m = time_saved_minutes(chars, cpm)
            self.today_label.setText(f"{n} phrases ({chars} chars) saved you {format_duration(m)} today."
                                     + self._money(m))
        m = time_saved_minutes(s["chars_saved"], cpm)
        self.total_label.setText(f"{s['expansions']} phrases ({s['chars_saved']} chars) saved you a total of "
                                 f"{format_duration(m)}." + self._money(m))
        self.chart.set_data([(d["day"], d["uses"]) for d in reversed(s["per_day"])])
        self.top.setRowCount(len(s["top"]))
        for i, r in enumerate(s["top"]):
            for j, v in enumerate((r["description"], r["uses"], r["chars"])):
                self.top.setItem(i, j, QTableWidgetItem(str(v)))
        self.apps.setRowCount(len(s["per_app"]))
        for i, r in enumerate(s["per_app"]):
            self.apps.setItem(i, 0, QTableWidgetItem(r["app"] or "—"))
            self.apps.setItem(i, 1, QTableWidgetItem(str(r["uses"])))

    def _toggle_details(self, on: bool) -> None:
        self.details_button.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.details.setVisible(on)
        self.adjustSize()

    def redetermine(self) -> None:
        d = TypingTestDialog(self)
        if d.exec() and d.cpm > 0:
            self.speed.setValue(d.cpm)

    def _help(self) -> None:
        QMessageBox.information(
            self, "Statistics",
            "The time saved is the number of characters PhraseForge inserted for you divided by your "
            "typing speed. Use Re-determine to measure your speed, and enter an hourly wage to see "
            "the money saved. Turn off Usage statistics to stop showing these numbers.")

    def accept(self) -> None:
        self.store.set_setting("stats.typing_speed", str(self.speed.value()))
        self.store.set_setting("stats.hourly_wage", f"{self.wage.value():g}")
        self.store.set_setting("features.usage_statistics", "1" if self.usage.isChecked() else "0")
        super().accept()

    def showEvent(self, e):  # noqa: N802
        self.refresh()
        super().showEvent(e)
