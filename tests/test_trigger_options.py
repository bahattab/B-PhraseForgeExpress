"""PRD G-10 / FR-TRG-01..05: fast typing only, global prefix, delimiter classes, regex presets,
skip-next and learned auto-skip."""
import pytest

from phraseforge.db import Store
from phraseforge.models import Phrase, Trigger, TriggerKind
from phraseforge.triggers import regex_presets
from phraseforge.triggers.autoskip import AutoSkip
from phraseforge.triggers.autotext import AutotextMatcher, apply_global_prefix
from phraseforge.triggers.manager import TriggerManager
from phraseforge.triggers.rows import row_to_trigger, trigger_to_row
from tests.test_triggers import Ev, FakeHook, FakeWatcher, _drain, type_into


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def _feed(m, text, step):
    hit, t = None, 0.0
    for c in text:
        hit = m.feed(c, now=t) or hit
        t += step
    return hit


# ---------------------------------------------------------------- FR-TRG-01
def test_fast_only_fires_when_typed_quickly_only():
    m = AutotextMatcher()
    m.load([Trigger(TriggerKind.AUTOTEXT, "brb", word_pos="middle", trail_delim="None", fast_only=True)])
    assert _feed(m, "brb", 0.05) is not None
    m.reset()
    assert _feed(m, "brb", 0.30) is None            # 300 ms per key: stays text
    m.set_fast_ms(400)
    m.reset()
    assert _feed(m, "brb", 0.30) is not None


def test_fast_only_with_trailing_delimiter_ignores_the_delimiter_pause():
    m = AutotextMatcher()
    m.load([Trigger(TriggerKind.AUTOTEXT, "sg", trail_delim="Default", fast_only=True)])
    hit = None
    for c, t in ((" ", 0.0), ("s", 1.0), ("g", 1.05), (" ", 5.0)):
        hit = m.feed(c, now=t) or hit
    assert hit is not None and hit.trailing_delimiter == " "


def test_normal_triggers_do_not_care_about_speed():
    m = AutotextMatcher()
    m.load([Trigger(TriggerKind.AUTOTEXT, "brb", word_pos="middle", trail_delim="None")])
    assert _feed(m, "brb", 5.0) is not None


def test_fast_only_survives_storage_and_editor_rows(store):
    p = store.add_phrase(Phrase("x", "y", triggers=[Trigger(TriggerKind.AUTOTEXT, "ab", fast_only=True)]))
    t = store.get_phrase(p.id).triggers[0]
    assert t.fast_only
    row = trigger_to_row(t)
    assert row["fast_only"] is True and row_to_trigger(row).fast_only
    assert Trigger.from_dict(t.to_dict()).fast_only


def test_old_trigger_table_gets_the_column(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    s = Store(str(path))
    s.add_phrase(Phrase("x", "y", triggers=[Trigger(TriggerKind.AUTOTEXT, "ab")]))
    s.close()
    con = sqlite3.connect(path)
    con.execute("ALTER TABLE triggers DROP COLUMN fast_only")
    con.commit()
    con.close()
    s = Store(str(path))
    try:
        assert s.phrases()[0].triggers[0].fast_only is False
    finally:
        s.close()


# ---------------------------------------------------------------- FR-TRG-02
def test_global_prefix():
    ts = apply_global_prefix([Trigger(TriggerKind.AUTOTEXT, "sig"), Trigger(TriggerKind.HOTKEY, "ctrl+a")], "#")
    assert [t.value for t in ts] == ["#sig", "ctrl+a"]
    assert apply_global_prefix(ts, "") is ts
    m = AutotextMatcher()
    m.load(ts)
    assert _feed(m, " sig ", 0.01) is None
    m.reset()
    hit = _feed(m, " #sig ", 0.01)
    assert hit is not None and hit.erase_chars == 4          # the prefix goes too


def test_manager_reads_global_prefix(store):
    p = store.add_phrase(Phrase("Sig", "Best", triggers=[Trigger(TriggerKind.AUTOTEXT, "sg")]))
    store.set_setting("autotext.global_prefix", "#")
    expands = []
    mgr = TriggerManager(store, expands.append, lambda c: None, hook_factory=FakeHook,
                         watcher_factory=FakeWatcher, foreground_app=lambda: ("notepad.exe", "t"),
                         foreground_hwnd=lambda: 1, poll_interval_s=3600)
    mgr.start()
    try:
        assert not any(type_into(mgr, " sg "))
        assert type_into(mgr, " #sg ")[-1] is True
        _drain(mgr)
        assert expands and expands[0].phrase_id == p.id
    finally:
        mgr.stop()


# ---------------------------------------------------------------- FR-TRG-03
CLASS_CASES = [
    # choice, chars that count, chars that do not
    ("All", "a1 .,\n", ""),
    ("Letters", "aZ", "1 ."),
    ("Numbers", "07", "a ."),
    ("Space", " ", "a\t"),
    ("Enter", "\n", " "),
    ("Tab", "\t", " "),
    ("Point", ".", ","),
    ("Comma", ",", "."),
    ("Punctuation", ".,;", "a "),
    ("Any non-letter", "1 .", "a"),
    ("Standard", " .", "a"),
    ("Default", " .", "a"),
    ("Custom:-_", "-_", " a"),
    ("Space+Comma", " ,", ".a"),
    ("Letters+Numbers", "a1", " "),
]


@pytest.mark.parametrize("choice,good,bad", CLASS_CASES)
def test_trailing_delimiter_classes(choice, good, bad):
    for c in good:
        m = AutotextMatcher()
        m.load([Trigger(TriggerKind.AUTOTEXT, "qq", word_pos="middle", trail_delim=choice)])
        hit = _feed(m, "qq" + c, 0.01)
        assert hit is not None and hit.trailing_delimiter == c, (choice, c)
    for c in bad:
        m = AutotextMatcher()
        m.load([Trigger(TriggerKind.AUTOTEXT, "qq", word_pos="middle", trail_delim=choice)])
        assert _feed(m, "qq" + c, 0.01) is None, (choice, c)


@pytest.mark.parametrize("choice,good,bad", CLASS_CASES)
def test_leading_delimiter_classes(choice, good, bad):
    for c in good:
        m = AutotextMatcher()
        m.load([Trigger(TriggerKind.AUTOTEXT, "qq", word_pos="start", lead_delim=choice, trail_delim="None")])
        assert _feed(m, "x" + c + "qq", 0.01) is not None, (choice, c)
    for c in bad:
        m = AutotextMatcher()
        m.load([Trigger(TriggerKind.AUTOTEXT, "qq", word_pos="start", lead_delim=choice, trail_delim="None")])
        assert _feed(m, "x" + c + "qq", 0.01) is None, (choice, c)


# ---------------------------------------------------------------- FR-TRG-04
@pytest.mark.parametrize("name", list(regex_presets.PRESETS))
def test_regex_presets(name):
    good, bad = regex_presets.FIXTURES[name]
    assert good and bad
    for t in good:
        assert regex_presets.full_match(name, t), t
    for t in bad:
        assert not regex_presets.full_match(name, t), t


def test_regex_preset_works_as_autotext_trigger():
    m = AutotextMatcher()
    m.load([Trigger(TriggerKind.REGEX, regex_presets.PRESETS["Time (HH:MM[:SS])"] + " ")])
    hit = _feed(m, "at 09:30 ", 0.01)
    assert hit is not None and hit.typed == "09:30 "


def test_trigger_editor_offers_presets(qapp):
    from phraseforge.ui.trigger_editor import TriggerRow
    w = TriggerRow({"type": "regex_autotext", "value": ""})
    items = [w.regex_edit.itemText(i) for i in range(w.regex_edit.count())]
    assert regex_presets.PRESETS["Email address"] in items
    w.regex_edit.activated.emit(items.index(regex_presets.PRESETS["Email address"]))
    assert w.data["value"] == regex_presets.PRESETS["Email address"]


def test_expert_options_custom_and_fast(qapp):
    from phraseforge.ui.trigger_editor import ExpertOptionsDialog
    d = ExpertOptionsDialog({"lead_delim": "Default", "trail_delim": "None"})
    d.trail.setEditText("Custom:-_")
    d.fast_only.setChecked(True)
    v = d.values()
    assert v["trail_delim"] == "Custom:-_" and v["fast_only"] is True


# ---------------------------------------------------------------- FR-TRG-05
def test_skip_next_ignores_one_match():
    m = AutotextMatcher()
    m.load([Trigger(TriggerKind.AUTOTEXT, "qq", word_pos="middle", trail_delim="None")])
    m.skip_next()
    assert m.skipping
    assert _feed(m, "qq", 0.01) is None
    assert not m.skipping
    assert _feed(m, "qq", 0.01) is not None


def test_skip_next_hotkey(store):
    store.add_phrase(Phrase("Sig", "Best", triggers=[Trigger(TriggerKind.AUTOTEXT, "sg")]))
    store.set_setting("hotkey.skip_next", "ctrl+alt+k")
    mgr = TriggerManager(store, lambda r: None, lambda c: None, hook_factory=FakeHook,
                         watcher_factory=FakeWatcher, foreground_app=lambda: ("notepad.exe", "t"),
                         foreground_hwnd=lambda: 1, poll_interval_s=3600)
    mgr.start()
    try:
        assert mgr.hotkeys.on_key_down(0x4B, {"ctrl", "alt"}) == ("cmd", "skip_next")
        assert mgr._on_hotkey(Ev(None, vk=0x4B, mods=("ctrl", "alt")), ("cmd", "skip_next")) is True
        assert type_into(mgr, " sg ")[-1] is False
        assert type_into(mgr, " sg ")[-1] is True
    finally:
        mgr.stop()


def test_autoskip_counts_undos_per_program(store):
    now = [1000.0]
    a = AutoSkip(store, clock=lambda: now[0])
    assert not a.record_undo(1, "Word.exe")
    assert not a.record_undo(1, "notepad.exe")
    assert not a.record_undo(1, "word.exe")
    assert a.record_undo(1, "WORD.EXE")                  # third time in Word
    assert a.blocked(1, "word.exe") and not a.blocked(1, "notepad.exe") and not a.blocked(2, "word.exe")
    assert AutoSkip(store).blocked(1, "word.exe")         # kept
    a.restore(1, "word.exe")
    assert not a.blocked(1, "word.exe")


def test_autoskip_forgets_after_a_week(store):
    now = [0.0]
    a = AutoSkip(store, clock=lambda: now[0])
    a.record_undo(5, "x.exe")
    a.record_undo(5, "x.exe")
    now[0] = 8 * 24 * 3600
    assert not a.record_undo(5, "x.exe")


def test_autoskip_settings(store):
    a = AutoSkip(store)
    store.set_setting("triggers.skip_threshold", "1")
    assert a.record_undo(3, "x.exe")
    store.set_setting("triggers.autoskip", "0")
    assert not a.record_undo(4, "x.exe")


def test_autoskip_state_stays_on_this_pc():
    from phraseforge.db import is_device_setting
    assert is_device_setting("autoskip.off") and is_device_setting("autoskip.log")
    assert not is_device_setting("triggers.skip_threshold")


def test_manager_learns_to_skip(store):
    from phraseforge.platform import keys as K
    p = store.add_phrase(Phrase("Sig", "Best", triggers=[Trigger(TriggerKind.AUTOTEXT, "sg")]))
    store.set_setting("features.detect_unwanted_replacements", "1")
    store.set_setting("triggers.skip_threshold", "2")
    cmds = []
    mgr = TriggerManager(store, lambda r: None, cmds.append, hook_factory=FakeHook,
                         watcher_factory=FakeWatcher, foreground_app=lambda: ("winword.exe", "t"),
                         foreground_hwnd=lambda: 1, poll_interval_s=3600)
    mgr.start()
    try:
        for _ in range(2):
            assert type_into(mgr, " sg ")[-1] is True
            assert mgr._on_key(Ev(None, vk=K.VK_BACK)) is True
        _drain(mgr)
        assert f"autoskip:{p.id}:winword.exe" in cmds
        assert type_into(mgr, " sg ")[-1] is False        # no longer fires in Word
        mgr.autoskip.restore(p.id, "winword.exe")
        assert type_into(mgr, " sg ")[-1] is True
    finally:
        mgr.stop()
