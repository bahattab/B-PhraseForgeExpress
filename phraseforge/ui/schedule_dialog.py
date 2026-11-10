"""Time-trigger schedule options and the Scheduled tasks list (PRD FR-TRG-07)."""
from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QDateEdit, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QLabel, QSpinBox, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout,
)

from phraseforge.models import TriggerKind
from phraseforge.triggers import schedule
from phraseforge.ui.i18n import tr

DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


def _pydate(q: QDate) -> date:
    return date(q.year(), q.month(), q.day())


class ScheduleDialog(QDialog):
    """Weekdays, a date range, "only once" and a random delay for one time trigger."""

    def __init__(self, value: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Schedule"))
        try:
            self.sched = schedule.parse(value or "00:00")
        except ValueError:
            self.sched = schedule.Schedule()
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("Run on these days (none ticked: every day):")))
        row = QHBoxLayout()
        self.day_boxes = []
        for i, name in enumerate(DAY_NAMES):
            b = QCheckBox(tr(name))
            b.setChecked(i in self.sched.days)
            self.day_boxes.append(b)
            row.addWidget(b)
        lay.addLayout(row)
        grid = QGridLayout()
        today = date.today()
        self.use_from = QCheckBox(tr("From"))
        self.from_date = QDateEdit(_qdate(self.sched.start or today))
        self.use_to = QCheckBox(tr("Until"))
        self.to_date = QDateEdit(_qdate(self.sched.end or today))
        for w in (self.from_date, self.to_date):
            w.setCalendarPopup(True)
            w.setDisplayFormat("yyyy-MM-dd")
        self.use_from.setChecked(self.sched.start is not None)
        self.use_to.setChecked(self.sched.end is not None)
        grid.addWidget(self.use_from, 0, 0)
        grid.addWidget(self.from_date, 0, 1)
        grid.addWidget(self.use_to, 1, 0)
        grid.addWidget(self.to_date, 1, 1)
        lay.addLayout(grid)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Random delay up to")))
        self.random = QSpinBox()
        self.random.setRange(0, 24 * 60)
        self.random.setValue(self.sched.random_minutes)
        row.addWidget(self.random)
        row.addWidget(QLabel(tr("minutes")))
        row.addStretch(1)
        lay.addLayout(row)
        self.once = QCheckBox(tr("Run only once"))
        self.once.setChecked(self.sched.once)
        lay.addWidget(self.once)
        self.error = QLabel("")
        self.error.setStyleSheet("color: #b00020")
        lay.addWidget(self.error)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def schedule(self) -> schedule.Schedule:
        s = schedule.Schedule(self.sched.kind, self.sched.minutes)
        s.days = frozenset(i for i, b in enumerate(self.day_boxes) if b.isChecked())
        s.start = _pydate(self.from_date.date()) if self.use_from.isChecked() else None
        s.end = _pydate(self.to_date.date()) if self.use_to.isChecked() else None
        s.random_minutes = self.random.value()
        s.once = self.once.isChecked()
        return s

    def value(self) -> str:
        return schedule.format(self.schedule())

    def _ok(self) -> None:
        s = self.schedule()
        if s.start and s.end and s.start > s.end:
            self.error.setText(tr("The start date is after the end date."))
            return
        self.accept()


class TasksDialog(QDialog):
    """Every time-triggered phrase with its schedule and next run."""
    show_phrase = Signal(int)

    def __init__(self, store, parent=None, done: set | None = None, now: datetime | None = None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle(tr("Scheduled tasks"))
        self.resize(640, 360)
        lay = QVBoxLayout(self)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Phrase"), tr("Schedule"), tr("Next run")])
        self.tree.setRootIsDecorated(False)
        self.tree.itemDoubleClicked.connect(self._open)
        lay.addWidget(self.tree)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.fill(done, now)

    def fill(self, done: set | None = None, now: datetime | None = None) -> None:
        import json
        from phraseforge.triggers.manager import schedule_key
        if done is None:
            try:
                done = set(json.loads(self.store.setting("schedule.done", "") or "[]"))
            except ValueError:
                done = set()
        now = now or datetime.now()
        rows = []
        for t in self.store.triggers(TriggerKind.TIME):
            p = self.store.get_phrase(t.phrase_id) if t.phrase_id is not None else None
            if p is None:
                continue
            from phraseforge.security import LOCKS
            if LOCKS.is_locked(self.store, p.folder_id):     # the tree hides it too (R92)
                continue
            try:
                s = schedule.parse(t.value)
            except ValueError:
                rows.append((None, p, tr("not understood:") + " " + t.value, tr("never")))
                continue
            nxt = s.next_run(now, done=schedule_key(t) in done)
            rows.append((nxt, p, s.describe(), nxt.strftime("%Y-%m-%d %H:%M") if nxt else tr("never")))
        rows.sort(key=lambda r: (r[0] is None, r[0] or datetime.max, r[1].description.lower()))
        self.tree.clear()
        for _, p, desc, nxt in rows:
            it = QTreeWidgetItem([p.description + ("" if p.enabled else " " + tr("(off)")), desc, nxt])
            it.setData(0, Qt.UserRole, p.id)
            self.tree.addTopLevelItem(it)
        for i in range(3):
            self.tree.resizeColumnToContents(i)

    def _open(self, it, _col=0) -> None:
        self.show_phrase.emit(it.data(0, Qt.UserRole))
