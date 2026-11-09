"""FR-TRG-07 and G-10 random delay: time-trigger schedules and the Scheduled tasks list."""
import random
from datetime import date, datetime, timedelta

import pytest

from phraseforge.db import Store
from phraseforge.models import Phrase, Trigger, TriggerKind
from phraseforge.triggers import schedule
from phraseforge.triggers.manager import TriggerManager, parse_time_trigger
from tests.test_triggers import FakeHook, FakeWatcher


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_parse_and_format_round_trip():
    v = "08:30 days=mon,wed,fri from=2026-11-01 to=2026-12-31 random=10 once"
    s = schedule.parse(v)
    assert (s.kind, s.minutes, s.days, s.start, s.end, s.random_minutes, s.once) == (
        "daily", 510, frozenset({0, 2, 4}), date(2026, 11, 1), date(2026, 12, 31), 10, True)
    assert schedule.format(s) == v
    assert schedule.format(schedule.parse("every:15")) == "every:15"
    assert schedule.format(schedule.parse("8:05")) == "08:05"
    assert parse_time_trigger(v) == ("daily", 510)


@pytest.mark.parametrize("bad", ["", "25:00", "every:0", "08:30 days=xyz", "08:30 bogus",
                                 "08:30 from=2026-12-01 to=2026-11-01", "08:30 from=tomorrow"])
def test_bad_values(bad):
    with pytest.raises(ValueError):
        schedule.parse(bad)


def _run(r, key, s, start, minutes):
    fired = []
    for i in range(minutes):
        now = start + timedelta(minutes=i)
        if r.due(key, s, now):
            fired.append(now)
    return fired


def test_weekdays_only():
    s = schedule.parse("09:00 days=sat,sun")
    fired = _run(schedule.Runner(), "k", s, datetime(2026, 11, 9), 7 * 24 * 60)   # Mon 9 Nov .. Sun 15 Nov
    assert [f.strftime("%a %H:%M") for f in fired] == ["Sat 09:00", "Sun 09:00"]


def test_date_range():
    s = schedule.parse("09:00 from=2026-11-10 to=2026-11-11")
    fired = _run(schedule.Runner(), "k", s, datetime(2026, 11, 9), 4 * 24 * 60)
    assert [f.day for f in fired] == [10, 11]


def test_once():
    s = schedule.parse("09:00 once")
    r = schedule.Runner()
    fired = _run(r, "k", s, datetime(2026, 11, 9), 3 * 24 * 60)
    assert len(fired) == 1 and "k" in r.done
    assert s.next_run(datetime(2026, 11, 12), done=True) is None


def test_every_with_weekdays():
    s = schedule.parse("every:60 days=mon")
    fired = _run(schedule.Runner(), "k", s, datetime(2026, 11, 9), 2 * 24 * 60)     # Monday, Tuesday
    assert fired and all(f.weekday() == 0 for f in fired)


def test_random_delay_stays_in_range():
    s = schedule.parse("09:00 random=10")
    for seed in range(20):
        fired = _run(schedule.Runner(random.Random(seed)), "k", s, datetime(2026, 11, 9, 8, 50), 40)
        assert len(fired) == 1
        assert datetime(2026, 11, 9, 9, 0) <= fired[0] <= datetime(2026, 11, 9, 9, 10)


def test_next_run():
    now = datetime(2026, 11, 9, 10, 0)                       # Monday
    assert schedule.parse("09:00").next_run(now) == datetime(2026, 11, 10, 9, 0)
    assert schedule.parse("11:00").next_run(now) == datetime(2026, 11, 9, 11, 0)
    assert schedule.parse("09:00 days=fri").next_run(now) == datetime(2026, 11, 13, 9, 0)
    assert schedule.parse("09:00 to=2026-11-01").next_run(now) is None
    assert schedule.parse("every:15").next_run(now, last=now) == now + timedelta(minutes=15)


def test_manager_once_is_remembered(store):
    p = store.add_phrase(Phrase("Hi", "x", triggers=[Trigger(TriggerKind.TIME, "09:00 once")]))

    def make():
        m = TriggerManager(store, lambda r: None, lambda c: None, hook_factory=FakeHook,
                           watcher_factory=FakeWatcher, foreground_app=lambda: ("n.exe", "t"),
                           foreground_hwnd=lambda: 1, poll_interval_s=3600)
        m.reload()
        return m

    m = make()
    assert m.check_time(datetime(2026, 11, 9, 9, 0)) == [p.id]
    assert make().check_time(datetime(2026, 11, 10, 9, 0)) == []          # also after a restart


def test_schedule_state_stays_on_this_pc():
    from phraseforge.db import is_device_setting
    assert is_device_setting("schedule.done")


def test_editor_keeps_options_when_time_changes(qapp):
    from PySide6.QtCore import QTime
    from phraseforge.ui.trigger_editor import TriggerRow
    w = TriggerRow({"type": "time", "value": "08:30 days=mon once"})
    assert "Mon" in w.schedule_label.text()
    w.time_edit.setTime(QTime(9, 15))
    assert w.data["value"] == "09:15 days=mon once"
    w2 = TriggerRow({"type": "time", "value": "every:15"})
    w2.time_edit.setTime(QTime(7, 0))
    assert w2.data["value"] == "every:15"


def test_schedule_dialog(qapp):
    from phraseforge.ui.schedule_dialog import ScheduleDialog
    d = ScheduleDialog("08:30")
    d.day_boxes[1].setChecked(True)
    d.random.setValue(5)
    d.once.setChecked(True)
    assert d.value() == "08:30 days=tue random=5 once"
    d.use_from.setChecked(True)
    d.use_to.setChecked(True)
    from PySide6.QtCore import QDate
    d.from_date.setDate(QDate(2026, 12, 2))
    d.to_date.setDate(QDate(2026, 12, 1))
    d._ok()
    assert d.error.text() and d.result() == 0


def test_tasks_dialog_lists_next_runs(qapp, store):
    from phraseforge.ui.schedule_dialog import TasksDialog
    store.add_phrase(Phrase("Later", "x", triggers=[Trigger(TriggerKind.TIME, "11:00")]))
    store.add_phrase(Phrase("Sooner", "x", triggers=[Trigger(TriggerKind.TIME, "10:30 days=mon")]))
    store.add_phrase(Phrase("Over", "x", triggers=[Trigger(TriggerKind.TIME, "09:00 to=2026-01-01")]))
    d = TasksDialog(store, now=datetime(2026, 11, 9, 10, 0))
    rows = [[d.tree.topLevelItem(i).text(c) for c in range(3)] for i in range(d.tree.topLevelItemCount())]
    assert [r[0] for r in rows] == ["Sooner", "Later", "Over"]
    assert rows[0][2] == "2026-11-09 10:30" and rows[2][2] == "never"
