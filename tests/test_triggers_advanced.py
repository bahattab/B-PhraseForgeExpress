"""Trigger options that used to be saved-only: word position, delimiters, execution
modes, SmartComplete, folder/special triggers, window triggers, undo, auto-correct,
Caps Lock, AutoComplete words, program restriction, pause, schema migration."""
import json
import os
import sqlite3

import pytest

from phraseforge.db import Store
from phraseforge.models import AutotextMode, Folder, Phrase, Trigger, TriggerKind
from phraseforge.triggers.autotext import AutotextMatcher
from phraseforge.triggers.manager import TriggerManager, window_trigger_hit
from phraseforge.triggers.rows import default_row, row_to_trigger, trigger_to_row


# ---------------------------------------------------------------- helpers
class Ev:
    def __init__(self, char=None, vk=0x41, down=True, mods=()):
        self.char, self.vk, self.down, self.modifiers, self.scan, self.injected = char, vk, down, set(mods), 0, False

    @property
    def altgr(self):
        return False


def vk_for(ch):
    return {" ": 0x20, "\n": 0x0D, "\t": 0x09}.get(ch, 0x41)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeTimer:
    made = []

    def __init__(self, interval, fn, args=()):
        self.interval, self.fn, self.args, self.daemon = interval, fn, args, False
        FakeTimer.made.append(self)

    def start(self):
        pass

    def fire(self):
        self.fn(*self.args)


def manager(store, exe="notepad.exe", title="Untitled - Notepad", **settings):
    for k, v in settings.items():
        store.set_setting(k.replace("__", "."), v)
    expands, cmds = [], []
    fg = {"exe": exe, "title": title, "hwnd": 1}
    clock = Clock()
    FakeTimer.made = []
    m = TriggerManager(store, expands.append, cmds.append, foreground_app=lambda: (fg["exe"], fg["title"]),
                       foreground_hwnd=lambda: fg["hwnd"], clock=clock, timer_factory=FakeTimer)
    m._emit = lambda fn, arg: fn(arg)          # synchronous for tests
    m.reload()
    return m, expands, cmds, fg, clock


def type_text(m, text):
    return [m._on_key(Ev(ch, vk=vk_for(ch))) for ch in text]


def at(value, **kw):
    t = Trigger(TriggerKind.AUTOTEXT, value, mode=AutotextMode.IMMEDIATE)
    for k, v in kw.items():
        setattr(t, k, v)
    return t


# ---------------------------------------------------------------- 1. data model + migration
V1_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE folders (id INTEGER PRIMARY KEY, parent_id INTEGER, name TEXT NOT NULL, sort INTEGER DEFAULT 0,
  enabled INTEGER DEFAULT 1, apps_include TEXT DEFAULT '', apps_exclude TEXT DEFAULT '',
  password_hash TEXT DEFAULT '', show_in_popup INTEGER DEFAULT 1);
CREATE TABLE phrases (id INTEGER PRIMARY KEY, folder_id INTEGER, description TEXT NOT NULL, content TEXT DEFAULT '',
  content_format TEXT DEFAULT 'text', output_mode TEXT DEFAULT 'auto', apps_include TEXT DEFAULT '',
  apps_exclude TEXT DEFAULT '', enabled INTEGER DEFAULT 1, sort INTEGER DEFAULT 0, use_count INTEGER DEFAULT 0,
  last_used TEXT, created TEXT, modified TEXT, notes TEXT DEFAULT '');
CREATE TABLE triggers (id INTEGER PRIMARY KEY, phrase_id INTEGER NOT NULL REFERENCES phrases(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, value TEXT NOT NULL, mode TEXT DEFAULT 'delimiter', case_sensitive INTEGER DEFAULT 0,
  word_start_only INTEGER DEFAULT 1, enabled INTEGER DEFAULT 1);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
INSERT INTO meta VALUES ('schema_version', '1');
"""


def test_v1_database_and_trigger_extras_migrate(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript(V1_SCHEMA)
    con.execute("INSERT INTO folders (id, name) VALUES (1, 'Mail')")
    con.execute("INSERT INTO phrases (id, folder_id, description, content) VALUES (1, 1, 'Sig', 'Best')")
    con.execute("INSERT INTO triggers (phrase_id, kind, value, mode) VALUES (1, 'autotext', 'sg', 'immediate')")
    extras = {
        "p:1": {"rows": [dict(default_row("autotext"), value="sg", word_pos="end", exec="pause",
                              lead_delim="Space", trail_delim="Punctuation", remove_trailing=True),
                         dict(default_row("smartcomplete"), value="")],
                "output_target": "clipboard"},
        "f:1": {"rows": [dict(default_row("hotkey"), value="ctrl+alt+m")], "notes": "mail stuff"},
        "s:last_used": {"rows": [dict(default_row("autotext"), value="lu#")]},
    }
    con.execute("INSERT INTO settings VALUES ('ui.trigger_extras', ?)", (json.dumps(extras),))
    con.commit()
    con.close()

    s = Store(path)
    assert s.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "2"
    p = s.get_phrase(1)
    t = p.triggers[0]
    assert (t.word_pos, t.exec_mode, t.lead_delim, t.trail_delim, t.remove_trailing) == \
           ("end", "pause", "Space", "Punctuation", True)
    assert p.triggers[1].kind == TriggerKind.SMARTCOMPLETE
    assert p.output_target == "clipboard"
    f = s.get_folder(1)
    assert f.notes == "mail stuff" and f.triggers[0].value == "ctrl+alt+m" and f.triggers[0].phrase_id is None
    assert s.special_triggers("last_used")[0].value == "lu#"
    assert s.setting("ui.trigger_extras", "") == ""
    s.close()
    Store(path).close()          # second open: migration is idempotent


def test_rows_roundtrip_every_option():
    for type_ in ("autotext", "smartcomplete", "regex_autotext", "hotkey", "window", "time",
                  "clipboard", "regex_clipboard"):
        row = dict(default_row(type_), value="x.exe" if type_ == "window" else ("ctrl+a" if type_ == "hotkey" else "abc"))
        if type_ == "autotext":
            row.update(word_pos="entire", exec="continue", lead_delim="Tab", trail_delim="Enter",
                       remove_trailing=True, case_sensitive=True)
        if type_ == "window":
            row["window_scope"] = "program"
        back = trigger_to_row(row_to_trigger(row))
        for k in ("type", "value", "word_pos", "exec", "lead_delim", "trail_delim", "remove_trailing",
                  "window_scope", "case_sensitive"):
            if type_ == "autotext" or k in ("type", "value"):
                assert back[k] == row[k], (type_, k)


def test_export_and_from_dict_keep_new_fields():
    s = Store(":memory:")
    s.add_phrase(Phrase("P", "x", triggers=[at("ab", word_pos="middle", exec_mode="continue", trail_delim="Space")]))
    d = s.export_dict()
    t = Trigger.from_dict(d["phrases"][0]["triggers"][0])
    assert (t.word_pos, t.exec_mode, t.trail_delim) == ("middle", "continue", "Space")


# ---------------------------------------------------------------- 2./4. word position + delimiters
def matcher_with(*triggers, **kw):
    m = AutotextMatcher(**kw)
    for i, t in enumerate(triggers):
        t.phrase_id = i + 1
    m.load(list(triggers))
    return m


def feed(m, text):
    hits = []
    for ch in text:
        r = m.feed(ch)
        if r:
            hits.append((r.trigger.value, r.erase_chars, r.trailing_delimiter))
    return hits


def test_word_positions():
    assert feed(matcher_with(at("cat", word_pos="start")), "the cat") == [("cat", 2, "")]
    assert feed(matcher_with(at("cat", word_pos="start")), "thecat") == []
    assert feed(matcher_with(at("ing", word_pos="end")), "walking ") == [("ing", 3, " ")]
    assert feed(matcher_with(at("ing", word_pos="end")), "walking") == []          # needs the word end
    assert feed(matcher_with(at("lk", word_pos="middle")), "walk") == [("lk", 1, "")]
    assert feed(matcher_with(at("cat", word_pos="entire")), "the cat.") == [("cat", 3, ".")]
    assert feed(matcher_with(at("cat", word_pos="entire")), "bobcat.") == []


def test_delimiter_choices_and_leading():
    assert feed(matcher_with(at("x#", trail_delim="Space")), "x#.") == []
    assert feed(matcher_with(at("x#", trail_delim="Space")), "x# ") == [("x#", 2, " ")]
    assert feed(matcher_with(at("x#", trail_delim="Punctuation")), "x#!") == [("x#", 2, "!")]
    assert feed(matcher_with(at("x#", trail_delim="Any non-letter")), "x#5") == [("x#", 2, "5")]
    assert feed(matcher_with(at("ab", lead_delim="Punctuation")), " ab") == []
    assert feed(matcher_with(at("ab", lead_delim="Punctuation")), "(ab") == [("ab", 1, "")]
    # global leading set: only "(" may precede
    assert feed(matcher_with(at("ab"), leading="("), " ab") == []
    assert feed(matcher_with(at("ab"), leading="("), "(ab") == [("ab", 1, "")]


def test_route_enter_tab_controls_enter_as_delimiter():
    t = at("ok", trail_delim="Default")
    assert feed(matcher_with(t, route_enter_tab=False), "ok\n") == []
    t2 = at("ok", trail_delim="Default")
    assert feed(matcher_with(t2, route_enter_tab=True), "ok\n") == [("ok", 2, "\n")]


# ---------------------------------------------------------------- 3. execution modes
@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def test_pause_mode_expands_after_quiet_time(store):
    p = store.add_phrase(Phrase("P", "x", triggers=[at("pz", exec_mode="pause")]))
    m, exp, cmds, fg, clock = manager(store)
    assert type_text(m, "pz") == [False, False]          # nothing swallowed
    assert exp == [] and len(FakeTimer.made) == 1
    FakeTimer.made[0].fire()
    assert exp[0].phrase_id == p.id and exp[0].erase_chars == 2


def test_pause_mode_cancelled_by_next_key(store):
    store.add_phrase(Phrase("P", "x", triggers=[at("pz", exec_mode="pause")]))
    m, exp, *_ = manager(store)
    type_text(m, "pzz")
    FakeTimer.made[0].fire()
    assert exp == []


def test_continue_mode_expands_on_quick_next_key(store):
    p = store.add_phrase(Phrase("P", "x", triggers=[at("cq", exec_mode="continue")]))
    m, exp, cmds, fg, clock = manager(store)
    assert type_text(m, "cq") == [False, False]
    clock.t += 0.2
    assert m._on_key(Ev("a")) is True                    # swallowed, re-typed after the phrase
    assert exp[0].phrase_id == p.id and exp[0].erase_chars == 2 and exp[0].trailing_delimiter == "a"


def test_continue_mode_too_slow_does_nothing(store):
    store.add_phrase(Phrase("P", "x", triggers=[at("cq", exec_mode="continue")]))
    m, exp, cmds, fg, clock = manager(store)
    type_text(m, "cq")
    clock.t += 5
    assert m._on_key(Ev("a")) is False and exp == []


def test_confirm_and_remove_trailing(store):
    p = store.add_phrase(Phrase("P", "x", triggers=[at("rt", trail_delim="Space", remove_trailing=True)]))
    q = store.add_phrase(Phrase("Q", "y", triggers=[at("cf", exec_mode="confirm", trail_delim="Space")]))
    m, exp, cmds, *_ = manager(store)
    type_text(m, "rt ")
    assert exp[0].phrase_id == p.id and exp[0].trailing_delimiter == ""
    type_text(m, " cf ")
    assert cmds[-1] == f"confirm:{q.id}:3"


# ---------------------------------------------------------------- 5. SmartComplete
def test_smartcomplete_suggests_and_tab_accepts(store):
    p = store.add_phrase(Phrase("Regards", "Best regards,\nMe",
                                triggers=[Trigger(TriggerKind.SMARTCOMPLETE, "")]))
    m, exp, cmds, *_ = manager(store, smartcomplete__min_chars="3")
    type_text(m, "Be")
    assert not any(c.startswith("smartcomplete") for c in cmds)
    type_text(m, "st")
    assert cmds[-1] == f"smartcomplete:{p.id}:4"
    type_text(m, " r")
    assert cmds[-1] == f"smartcomplete:{p.id}:6"
    assert m._on_key(Ev(None, vk=0x09)) is True          # Tab accepts
    assert exp[-1].phrase_id == p.id and exp[-1].erase_chars == 6
    assert cmds[-1] == "suggest_hide"


def test_smartcomplete_value_and_escape(store):
    store.add_phrase(Phrase("Addr", "12 Main Street", triggers=[Trigger(TriggerKind.SMARTCOMPLETE, "address")]))
    m, exp, cmds, *_ = manager(store)
    type_text(m, "addr")
    assert cmds[-1].startswith("smartcomplete:")
    assert m._on_key(Ev(None, vk=0x1B)) is False         # Esc dismisses, not swallowed
    assert cmds[-1] == "suggest_hide"
    type_text(m, "xyz")
    assert cmds[-1] == "suggest_hide"


# ---------------------------------------------------------------- 6. folder triggers
def test_folder_autotext_and_hotkey_open_folder_popup(store):
    f = store.add_folder(Folder("Mail"))
    store.set_folder_triggers(f.id, [at("ml#"), Trigger(TriggerKind.HOTKEY, "ctrl+alt+m")])
    store.set_special_triggers("last_used", [at("lu#")])
    m, exp, cmds, *_ = manager(store)
    assert type_text(m, "ml#")[-1] is True
    assert cmds[-1] == f"folder_popup:{f.id}:2"
    m._on_key(Ev(None, vk=ord("M"), mods={"ctrl", "alt"}))
    assert cmds[-1] == f"folder_popup:{f.id}:0"
    type_text(m, " lu#")
    assert cmds[-1] == "folder_popup:last_used:2"
    assert exp == []


def test_disabled_folder_triggers_are_ignored(store):
    f = store.add_folder(Folder("Off", enabled=False))
    store.set_folder_triggers(f.id, [at("of#")])
    m, exp, cmds, *_ = manager(store)
    type_text(m, "of#")
    assert cmds == []


# ---------------------------------------------------------------- 7. window triggers
def test_window_trigger_title_and_exe():
    t_title = Trigger(TriggerKind.APP_FOCUS, "Inbox", window_scope="any")
    t_exe = Trigger(TriggerKind.APP_FOCUS, "excel.exe", window_scope="program")
    assert window_trigger_hit(t_title, "outlook.exe", "Inbox - Outlook")
    assert not window_trigger_hit(t_title, "outlook.exe", "Calendar")
    assert window_trigger_hit(t_exe, "EXCEL.EXE", "Book1")
    assert window_trigger_hit(Trigger(TriggerKind.APP_FOCUS, "excel", window_scope="program"), "excel.exe", "")


def test_window_trigger_fires_once_per_focus(store):
    p = store.add_phrase(Phrase("W", "w", triggers=[Trigger(TriggerKind.APP_FOCUS, "Inbox", window_scope="any")]))
    m, *_ = manager(store)
    assert m.check_focus("outlook.exe", "Inbox - Outlook") == [p.id]
    assert m.check_focus("outlook.exe", "Inbox - Outlook (1)") == []      # still the same window
    assert m.check_focus("notepad.exe", "x") == []
    assert m.check_focus("outlook.exe", "Inbox - Outlook") == [p.id]


# ---------------------------------------------------------------- 8. undo unwanted replacement
def test_backspace_right_after_expansion_undoes(store):
    p = store.add_phrase(Phrase("P", "x", triggers=[at("tz", trail_delim="Space")]))
    m, exp, cmds, *_ = manager(store, features__detect_unwanted_replacements="1")
    type_text(m, "tz ")
    assert m._on_key(Ev(None, vk=0x08)) is True
    assert cmds[-2:] == [f"undo_expansion:{p.id}:tz ", "sound:unwanted_detected"]
    assert m._on_key(Ev(None, vk=0x08)) is False         # only the first key counts


def test_undo_off_by_default(store):
    store.add_phrase(Phrase("P", "x", triggers=[at("tz", trail_delim="Space")]))
    m, exp, cmds, *_ = manager(store)
    type_text(m, "tz ")
    assert m._on_key(Ev(None, vk=0x08)) is False


# ---------------------------------------------------------------- 9. auto-correction
def test_capitalize_sentence_start(store):
    m, exp, cmds, *_ = manager(store, autocorrect__capitalize_sentences="1")
    sw = type_text(m, "ok. then")
    assert sw[4] is True and cmds == ["autocorrect:0:T"]
    type_text(m, "\nnew")
    assert cmds[-1] == "autocorrect:0:N"


def test_capitalize_needs_known_context(store):
    m, exp, cmds, *_ = manager(store, autocorrect__capitalize_sentences="1")
    type_text(m, "hello")               # start of input in an unknown field: leave it
    assert cmds == []


def test_two_initial_capitals(store):
    m, exp, cmds, *_ = manager(store, autocorrect__two_initial_capitals="1",
                               autocorrect__capitalize_sentences="0")
    sw = type_text(m, "THis ")
    assert sw[-1] is True and cmds == ["autocorrect:4:This "]
    cmds.clear()
    type_text(m, "NASA OK ")
    assert cmds == []


# ---------------------------------------------------------------- 10. Caps Lock
def test_capslock_disabled(store):
    m, *_ = manager(store, features__disable_capslock="1")
    assert m._on_key(Ev(None, vk=0x14)) is True
    assert m._on_key(Ev(None, vk=0x14, down=False)) is True
    m2, *_ = manager(store, features__disable_capslock="0")
    assert m2._on_key(Ev(None, vk=0x14)) is False


# ---------------------------------------------------------------- 11. AutoComplete words
def test_autocomplete_learns_and_suggests(store):
    m, exp, cmds, *_ = manager(store, autocomplete__suggest_words="1", smartcomplete__min_chars="3")
    type_text(m, "wonderful ")
    type_text(m, "won")
    assert cmds[-1] == "autocomplete:wonderful:3"
    assert m._on_key(Ev(None, vk=0x0D)) is True          # Enter accepts
    assert "autocorrect:3:wonderful" in cmds


def test_autocomplete_filters_and_corrections(store):
    from phraseforge.learning import WordLearner
    store.set_setting("autocomplete.suggest_words", "1")
    w = WordLearner(store)
    for ch in "x123abc ":
        w.feed_char(ch)
    assert "x123abc" in w.counts                         # begins with a letter: allowed
    store.set_setting("autocomplete.filter_letter", "0")
    store.set_setting("autocomplete.filter_upper", "1")
    for ch in "lowerword ":
        w.feed_char(ch)
    assert "lowerword" not in w.counts                   # must begin with UPPER CASE now
    for ch in "Typoo":
        w.feed_char(ch)
    w.feed_key("backspace")
    w.feed_char(" ")
    assert "Typo" not in w.counts                        # corrected words not learned by default
    store.set_setting("autocomplete.learn_corrections", "1")
    for ch in "Typoo":
        w.feed_char(ch)
    w.feed_key("backspace")
    w.feed_char(" ")
    assert "Typo" in w.counts


def test_word_learner_persists(tmp_path, store):
    from phraseforge.learning import WordLearner
    store.set_setting("autocomplete.suggest_words", "1")
    path = tmp_path / "words.json"
    w = WordLearner(store, path)
    for ch in "persistent ":
        w.feed_char(ch)
    w.save()
    assert WordLearner(store, path).suggest("pers") == "persistent"


# ---------------------------------------------------------------- 12. restricted programs
def test_execute_only_in_specific_programs(store):
    store.add_phrase(Phrase("P", "x", triggers=[at("rs")]))
    m, exp, cmds, fg, _ = manager(store, app__restrict_enabled="1", app__restrict_programs="winword.exe, outlook")
    type_text(m, "rs")
    assert exp == []
    fg["exe"] = "outlook.exe"
    fg["hwnd"] = 2
    type_text(m, "rs")
    assert len(exp) == 1


# ---------------------------------------------------------------- 13. pause for a short time
def test_pause_for_repetitions_or_seconds(store):
    store.add_phrase(Phrase("P", "x", triggers=[at("pp")]))
    m, exp, cmds, fg, clock = manager(store)
    m.pause_for(repetitions=1, seconds=10)
    type_text(m, "pp")
    assert exp == []                                     # first one skipped
    type_text(m, " pp")
    assert len(exp) == 1                                 # pause used up
    m.pause_for(repetitions=5, seconds=10)
    clock.t += 11
    type_text(m, " pp")
    assert len(exp) == 2                                 # time ran out first
    store.set_setting("pause.repetitions", "2")
    store.set_setting("pause.seconds", "30")
    assert m.pause_from_settings() == (2, 30.0)
    type_text(m, " pp pp pp")
    assert len(exp) == 3                                 # two skipped, the third expands


# ---------------------------------------------------------------- 14. default format / font
@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_new_phrase_uses_default_format_and_font(qapp, store):
    from phraseforge.ui.phrase_editor import PhraseEditor
    store.set_setting("format.default", "rich")
    store.set_setting("format.font", "Consolas,12")
    p = store.add_phrase(Phrase("New", ""))
    ed = PhraseEditor(store)
    ed.load(p.id)
    assert ed.content_edit.rich is True
    f = ed.content_edit.document().defaultFont()
    assert f.family() == "Consolas" and round(f.pointSizeF()) == 12
    store.set_setting("format.default", "plain")
    q = store.add_phrase(Phrase("Old", "text"))
    ed.load(q.id)
    assert ed.content_edit.rich is False


def test_editor_saves_trigger_options_and_output_target(qapp, store):
    from phraseforge.ui.phrase_editor import FolderEditor, PhraseEditor, SpecialFolderEditor
    p = store.add_phrase(Phrase("P", "x", triggers=[at("ab", word_pos="end", exec_mode="pause",
                                                       trail_delim="Space")]))
    ed = PhraseEditor(store)
    ed.load(p.id)
    row = ed.triggers.rows[0].row()
    assert (row["word_pos"], row["exec"], row["trail_delim"]) == ("end", "pause", "Space")
    ed.output_target.set("program", "notepad.exe")
    ed.dirty = True
    ed.save()
    got = store.get_phrase(p.id)
    assert (got.output_target, got.output_target_arg) == ("program", "notepad.exe")
    assert got.triggers[0].exec_mode == "pause"

    f = store.add_folder(Folder("F"))
    fe = FolderEditor(store)
    fe.load(f.id)
    fe.triggers.set_rows([dict(default_row("autotext"), value="fo#")])
    fe.notes.setPlainText("hello")
    fe.dirty = True
    fe.save()
    got_f = store.get_folder(f.id)
    assert got_f.notes == "hello" and got_f.triggers[0].value == "fo#"

    se = SpecialFolderEditor(store, "last_used")
    se.triggers.set_rows([dict(default_row("autotext"), value="lu#")])
    se.dirty = True
    se.save()
    assert store.special_triggers("last_used")[0].value == "lu#"



def test_double_ctrl_opens_file_search():
    """Listary-style double Ctrl emits the file_search command through the trigger layer."""
    store = Store(":memory:")
    m, _exp, cmds, _fg, clock = manager(store)
    for _ in range(2):
        m._on_key(Ev(None, vk=0xA2, down=True, mods=("ctrl",)))
        m._on_key(Ev(None, vk=0xA2, down=False))
        clock.t += 0.15
    assert "file_search" in cmds
    m2, _e, cmds2, _f, _c = manager(Store(":memory:"), filesearch__double_ctrl="0")
    for _ in range(2):
        m2._on_key(Ev(None, vk=0xA2, down=True, mods=("ctrl",)))
        m2._on_key(Ev(None, vk=0xA2, down=False))
    assert "file_search" not in cmds2
