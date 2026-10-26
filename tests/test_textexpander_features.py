"""TextExpander-inspired features: group (folder) abbreviation prefix and the
"you already have an abbreviation for this" reminder."""
import pytest

from phraseforge.db import Store
from phraseforge.io_formats import export_json, import_json
from phraseforge.learning import Learner
from phraseforge.models import Folder, Phrase, Trigger, TriggerKind
from phraseforge.triggers.autotext import AutotextMatcher, apply_group_prefixes, folder_prefixes
from phraseforge.triggers.manager import TriggerManager

from tests.test_triggers import Ev, FakeHook, FakeWatcher, _drain, type_into


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


# ------------------------------------------------------------------ group prefix
def test_prefix_is_stored_and_inherited(store):
    top = store.add_folder(Folder("Mail", abbrev_prefix=";"))
    sub = store.add_folder(Folder("Replies", parent_id=top.id))
    own = store.add_folder(Folder("Code", parent_id=top.id, abbrev_prefix="/"))
    plain = store.add_folder(Folder("Other"))
    assert store.get_folder(top.id).abbrev_prefix == ";"
    f = store.get_folder(plain.id)
    f.abbrev_prefix = "!"
    store.update_folder(f)
    assert store.get_folder(plain.id).abbrev_prefix == "!"
    pre = folder_prefixes(store.folders())
    assert pre == {top.id: ";", sub.id: ";", own.id: "/", plain.id: "!"}


def test_folder_prefixes_survive_a_parent_cycle():
    a, b = Folder("A", id=1, parent_id=2), Folder("B", id=2, parent_id=1)
    assert folder_prefixes([a, b]) == {1: "", 2: ""}


def test_apply_group_prefixes_only_touches_phrase_autotexts():
    ts = [Trigger(TriggerKind.AUTOTEXT, "sig", phrase_id=1),
          Trigger(TriggerKind.AUTOTEXT, ";ad", phrase_id=1),        # already prefixed
          Trigger(TriggerKind.AUTOTEXT, "x", phrase_id=2),          # folder without prefix
          Trigger(TriggerKind.AUTOTEXT, "menu", folder_id=10),      # folder popup trigger
          Trigger(TriggerKind.HOTKEY, "ctrl+alt+s", phrase_id=1)]
    out = apply_group_prefixes(ts, {1: 10, 2: 11}, {10: ";", 11: ""})
    assert [t.value for t in out] == [";sig", ";ad", "x", "menu", "ctrl+alt+s"]
    assert ts[0].value == "sig"                                    # originals untouched
    assert apply_group_prefixes(ts, {1: 10}, {10: ""}) is ts


def test_prefixed_abbreviation_matches_only_with_prefix():
    m = AutotextMatcher()
    m.load(apply_group_prefixes([Trigger(TriggerKind.AUTOTEXT, "sig", phrase_id=1)], {1: 5}, {5: ";"}))
    assert all(m.feed(c) is None for c in " sig")
    assert m.feed(" ") is None
    hit = None
    for c in " ;sig ":
        hit = m.feed(c) or hit
    assert hit is not None and hit.erase_chars == 4 and hit.trigger.value == ";sig"


def test_manager_uses_folder_prefix_and_reloads(store):
    f = store.add_folder(Folder("F", abbrev_prefix=";"))
    p = store.add_phrase(Phrase("Sig", "Best", folder_id=f.id, triggers=[Trigger(TriggerKind.AUTOTEXT, "sg")]))
    expands = []
    mgr = TriggerManager(store, expands.append, lambda c: None, hook_factory=FakeHook,
                         watcher_factory=FakeWatcher, foreground_app=lambda: ("notepad.exe", "t"),
                         foreground_hwnd=lambda: 1, poll_interval_s=3600)
    mgr.start()
    try:
        assert type_into(mgr, " sg ") == [False] * 4                # no prefix typed: nothing
        assert type_into(mgr, " ;sg ")[-1] is True
        _drain(mgr)
        assert expands and expands[0].phrase_id == p.id and expands[0].erase_chars == 3
        f.abbrev_prefix = ""
        store.update_folder(f)
        mgr.reload()
        assert type_into(mgr, " sg ")[-1] is True
    finally:
        mgr.stop()


def test_prefix_round_trips_through_json(store, tmp_path):
    store.add_folder(Folder("Mail", abbrev_prefix=";"))
    path = tmp_path / "x.json"
    export_json(store, path)
    other = Store(":memory:")
    try:
        import_json(other, path)
        assert [f.abbrev_prefix for f in other.folders() if f.name == "Mail"] == [";"]
    finally:
        other.close()


def test_old_database_gets_prefix_column(tmp_path):
    import sqlite3
    db = tmp_path / "old.db"
    s = Store(str(db))
    s.add_folder(Folder("Old"))
    s.close()
    con = sqlite3.connect(db)
    con.execute("ALTER TABLE folders DROP COLUMN abbrev_prefix")
    con.commit()
    con.close()
    s = Store(str(db))
    try:
        assert [f.abbrev_prefix for f in s.folders()] == [""]
    finally:
        s.close()


# ------------------------------------------------------------------ reminder
class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _learner(store, clock=None, password=False):
    got = []
    L = Learner(store, password_check=lambda: password, on_reminder=lambda a, d: got.append((a, d)),
                clock=clock or Clock())
    return L, got


def _phrase(store, content="Best regards, Sam", abbr="brg", **kw):
    return store.add_phrase(Phrase("Regards", content, triggers=[Trigger(TriggerKind.AUTOTEXT, abbr)], **kw))


def test_typing_a_phrase_in_full_reminds_of_its_abbreviation(store):
    _phrase(store)
    L, got = _learner(store)
    L.feed_text("Thanks. best regards, sam")
    assert got == [("brg", "Regards")]


def test_reminder_throttled_and_backspace_aware(store):
    _phrase(store)
    clock = Clock()
    L, got = _learner(store, clock)
    L.feed_text("Best regards, Sam ")
    L.feed_text("Best regards, Sam ")
    assert len(got) == 1                                            # once per 5 minutes
    clock.t += 301
    L.feed_text("Best regards, SaX")
    L.feed_key("backspace")
    L.feed_text("m")
    assert len(got) == 2


def test_reminder_skips_short_macro_disabled_and_password(store):
    _phrase(store, content="Hi you", abbr="hy")                      # too short
    _phrase(store, content="Date: {#date}", abbr="dt")                # macro
    _phrase(store, content="Disabled phrase text", abbr="dp", enabled=False)
    store.add_phrase(Phrase("No abbr", "No abbreviation here"))
    L, got = _learner(store)
    L.feed_text("Hi you Date: {#date} Disabled phrase text No abbreviation here")
    assert got == []
    _phrase(store, content="Secret words here", abbr="sw")
    L.invalidate_phrases()
    L2, got2 = _learner(store, password=True)
    L2.feed_text("Secret words here")
    assert got2 == []


def test_reminder_setting_and_cache_refresh(store):
    L, got = _learner(store)
    L.feed_text("Best regards, Sam")
    assert got == []                                                # phrase not there yet
    _phrase(store)
    L.feed_text("Best regards, Sam")
    assert got == []                                                # cached list
    L.invalidate_phrases()
    L.feed_text("Best regards, Sam")
    assert got == [("brg", "Regards")]
    store.set_setting("learning.remind_abbreviation", "0")
    L.invalidate_phrases()
    L._reminded.clear()
    L.feed_text("Best regards, Sam")
    assert len(got) == 1


# ------------------------------------------------------------------ hotkeys and tray (Preferences > Hotkeys)
def test_textexpander_hotkeys_are_commands():
    from phraseforge.triggers.manager import COMMAND_HOTKEY_SETTINGS
    from phraseforge.ui.settings_schema import SCHEMA
    for key, cmd in (("hotkey.new_phrase_from_clipboard", "new_phrase_from_clipboard"),
                     ("hotkey.toggle_expansion", "toggle_expansion"),
                     ("hotkey.open_main", "open_main"),
                     ("hotkey.popup_search", "popup_search")):      # TextExpander "Inline search"
        assert COMMAND_HOTKEY_SETTINGS[key] == cmd
        assert key in SCHEMA


def test_tray_has_clipboard_and_edit_last_items(qapp_tray):
    from phraseforge.ui.tray import Tray
    t = Tray()
    hits = []
    t.new_phrase_from_clipboard.connect(lambda: hits.append("clip"))
    t.edit_last_phrase.connect(lambda: hits.append("last"))
    acts = {a.text(): a for a in t._menu.actions()}
    acts["New phrase from clipboard"].trigger()
    acts["Edit last used phrase"].trigger()
    assert hits == ["clip", "last"]


def test_app_new_phrase_from_clipboard_and_toggle(qapp_tray, store):
    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication

    from phraseforge.app import PhraseForgeApp
    QApplication.clipboard().setText("Kind regards\nThe team")
    selected, notes = [], []
    fake = SimpleNamespace(store=store, show_main=lambda: None,
                           main_window=SimpleNamespace(select_phrase=selected.append))
    p = PhraseForgeApp._new_phrase_from_clipboard(fake)
    assert p.description == "Kind regards" and store.get_phrase(p.id).content == "Kind regards\nThe team"
    assert selected == [p.id]
    QApplication.clipboard().clear()

    state = SimpleNamespace(paused=False)
    from phraseforge.ui.tray import Tray
    tray = Tray()
    tray.toggle_pause.connect(lambda on: setattr(state, "paused", on))
    tray.notify = lambda title, text: notes.append(text)
    fake = SimpleNamespace(triggers=state, tray=tray, set_paused=lambda on: setattr(state, "paused", on))
    PhraseForgeApp._toggle_expansion(fake)
    assert state.paused is True and tray.pause_action.isChecked()
    PhraseForgeApp._toggle_expansion(fake)
    assert state.paused is False and notes == ["Text expansion paused.", "Text expansion resumed."]


@pytest.fixture
def qapp_tray():
    from PySide6.QtWidgets import QApplication
    yield QApplication.instance() or QApplication([])
