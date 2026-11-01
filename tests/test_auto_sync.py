"""Auto sync: a ribbon toggle next to Send/Receive, and a sync shortly after phrases change."""
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from phraseforge import app as app_mod
from phraseforge.db import Store


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def test_ribbon_button_shows_and_sets_auto_sync(qapp, store):
    from phraseforge.ui.main_window import MainWindow
    store.set_setting("sync.auto", "1")
    w = MainWindow(store)
    assert w.btn_auto_sync.isCheckable() and w.btn_auto_sync.isChecked()
    w.btn_auto_sync.setChecked(False)
    assert store.setting("sync.auto") == "0"
    store.set_setting("sync.auto", "1")          # changed in Settings
    w.refresh_auto_sync()
    assert w.btn_auto_sync.isChecked()
    w.close()


class FakeTimer:
    def __init__(self):
        self.starts = 0

    def start(self):
        self.starts += 1


def _fake_app(store, tick_result=True):
    ticks = []
    fake = SimpleNamespace(store=store, _change_sync_timer=FakeTimer())
    fake._cloud_tick = lambda force_sync=False, manual=False: ticks.append(force_sync) or tick_result
    return fake, ticks


def test_change_starts_the_wait_only_when_auto_sync_is_on(store):
    fake, _ = _fake_app(store)
    store.set_setting("sync.provider", "folder")
    store.set_setting("sync.auto", "1")
    app_mod.PhraseForgeApp._schedule_sync_after_change(fake)
    assert fake._change_sync_timer.starts == 1
    store.set_setting("sync.auto", "0")
    app_mod.PhraseForgeApp._schedule_sync_after_change(fake)
    store.set_setting("sync.auto", "1")
    store.set_setting("sync.provider", "off")
    app_mod.PhraseForgeApp._schedule_sync_after_change(fake)
    assert fake._change_sync_timer.starts == 1


def test_wait_over_syncs_and_retries_when_busy(store):
    store.set_setting("sync.provider", "gdrive")
    store.set_setting("sync.auto", "1")
    fake, ticks = _fake_app(store)
    app_mod.PhraseForgeApp._sync_after_change(fake)
    assert ticks == [True] and fake._change_sync_timer.starts == 0
    busy, ticks = _fake_app(store, tick_result=False)
    app_mod.PhraseForgeApp._sync_after_change(busy)
    assert ticks == [True] and busy._change_sync_timer.starts == 1


def test_no_sync_when_turned_off_meanwhile(store):
    store.set_setting("sync.provider", "folder")
    store.set_setting("sync.auto", "0")
    fake, ticks = _fake_app(store)
    app_mod.PhraseForgeApp._sync_after_change(fake)
    assert ticks == [] and fake._change_sync_timer.starts == 0


def test_after_change_wait_is_about_a_minute():
    assert 30_000 <= app_mod.AFTER_CHANGE_SYNC_MS <= 120_000


def test_interval_menu_sets_minutes(qapp, store):
    from phraseforge.ui import main_window as mw
    w = mw.MainWindow(store)
    assert w.sync_interval() == 7 and "7" in w.btn_sync_interval.text()
    w._fill_sync_interval_menu()
    acts = [a for a in w.sync_interval_menu.actions() if a.isCheckable()]
    assert [a.isChecked() for a in acts].count(True) == 1
    next(a for a in acts if a.text().startswith("Every 30")).trigger()
    assert store.setting("sync.interval_min") == "30" and "30" in w.btn_sync_interval.text()
    w.btn_auto_sync.setChecked(False)
    assert not w.btn_sync_interval.isEnabled()
    w.close()


def test_other_interval_asks_for_minutes(qapp, store, monkeypatch):
    from phraseforge.ui import main_window as mw
    w = mw.MainWindow(store)
    monkeypatch.setattr(mw.QInputDialog, "getInt", lambda *a, **k: (42, True))
    w._ask_sync_interval()
    assert store.setting("sync.interval_min") == "42"
    w.close()


def test_old_default_of_15_moves_to_7_once():
    from phraseforge.ui.settings_schema import ensure_defaults
    s = Store(":memory:")
    s.set_setting("sync.interval_min", "15")          # the default before 0.5.8
    ensure_defaults(s)
    assert s.setting("sync.interval_min") == "7"
    s.set_setting("sync.interval_min", "15")          # chosen again by the user: kept
    ensure_defaults(s)
    assert s.setting("sync.interval_min") == "15"
    other = Store(":memory:")
    other.set_setting("sync.interval_min", "30")      # a value the user picked
    ensure_defaults(other)
    assert other.setting("sync.interval_min") == "30"
