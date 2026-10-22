from datetime import datetime, timedelta

import pytest

from phraseforge.db import Store
from phraseforge.host import ExpansionRequest
from phraseforge.models import AutotextMode, Folder, Phrase, Trigger, TriggerKind
from phraseforge.triggers.autotext import AutotextMatcher, apply_case, typed_len
from phraseforge.triggers.hotkeys import HotkeyMatcher, format_hotkey, normalize_hotkey, parse_hotkey
from phraseforge.triggers.manager import TriggerManager, clipboard_trigger_hit, parse_time_trigger


def T(value, mode=AutotextMode.DELIMITER, pid=1, **kw):
    return Trigger(TriggerKind.AUTOTEXT, value, phrase_id=pid, mode=mode, **kw)


def feed(m, text):
    res = None
    for ch in text:
        r = m.feed(ch)
        res = r or res
        if r:
            return r
    return res


# ---------------------------------------------------------------- autotext matcher
def test_delimiter_match_sets_trailing_and_erase():
    m = AutotextMatcher()
    m.load([T("brb")])
    assert feed(m, "brb") is None
    r = m.feed(" ")
    assert r and r.trailing_delimiter == " " and r.erase_chars == 3 and r.typed == "brb"
    assert typed_len(r) == 4


def test_immediate_match_erases_one_less():
    m = AutotextMatcher()
    m.load([T("sig#", AutotextMode.IMMEDIATE)])
    r = feed(m, "xx sig#")
    assert r and r.erase_chars == 3 and r.trailing_delimiter == "" and r.typed == "sig#"


def test_word_start_only():
    m = AutotextMatcher()
    m.load([T("ty")])
    assert feed(m, "party ") is None
    assert feed(m, " ty ") is not None
    m2 = AutotextMatcher()
    m2.load([T("ty", word_start_only=False)])
    assert feed(m2, "party ") is not None


def test_case_sensitivity():
    m = AutotextMatcher()
    m.load([T("Abc", case_sensitive=True)])
    assert feed(m, "abc ") is None
    assert feed(m, "Abc ") is not None
    m2 = AutotextMatcher()
    m2.load([T("abc")])
    r = feed(m2, "ABC ")
    assert r and r.typed == "ABC"


def test_longest_match_wins():
    m = AutotextMatcher()
    m.load([T("ab", pid=1), T("xab", pid=2, word_start_only=False)])
    r = feed(m, "xab ")
    assert r.trigger.phrase_id == 2


def test_backspace_and_reset_keys():
    m = AutotextMatcher()
    m.load([T("brb")])
    feed(m, "brx")
    m.feed(None, "backspace")
    assert m.buffer == "br"
    assert feed(m, "b ") is not None
    feed(m, "br")
    m.feed(None, "left")
    assert feed(m, "b ") is None


def test_enter_is_delimiter_and_boundary():
    m = AutotextMatcher()
    m.load([T("brb")])
    feed(m, "hello")
    m.feed("\n")
    assert feed(m, "brb\n").trailing_delimiter == "\n"


def test_regex_trigger_groups():
    m = AutotextMatcher()
    m.load([Trigger(TriggerKind.REGEX, r"(\d+)eur", phrase_id=9)])
    r = feed(m, "pay 25eur")
    assert r and r.groups == ("25",) and r.erase_chars == len("25eur") - 1


def test_arabic_abbreviation():
    m = AutotextMatcher()
    m.load([T("سلم")])
    assert feed(m, "سلم ").typed == "سلم"


def test_apply_case():
    assert apply_case("best regards", "Br", "br") == "Best regards"
    assert apply_case("best regards", "BR", "br") == "BEST REGARDS"
    assert apply_case("best regards", "br", "br") == "best regards"


# ---------------------------------------------------------------- hotkeys
def test_parse_hotkey():
    hk = parse_hotkey("Ctrl+Alt+K")
    assert hk.modifiers == {"ctrl", "alt"} and hk.vk == ord("K")
    assert parse_hotkey("control + shift + f5").vk == 0x74
    assert parse_hotkey("win+space").vk == 0x20
    assert format_hotkey(parse_hotkey("alt+ctrl+k")) == "Ctrl+Alt+K"
    assert normalize_hotkey("shift+ctrl+left") == "Ctrl+Shift+Left"
    assert parse_hotkey("ctrl++").vk == 0xBB
    with pytest.raises(ValueError):
        parse_hotkey("ctrl+alt")
    with pytest.raises(ValueError):
        parse_hotkey("hyper+k")


def test_hotkey_matcher_exact_modifiers_and_key_up():
    hm = HotkeyMatcher()
    hm.register("ctrl+alt+k", "X")
    hm.register("bogus+", "Y")
    assert hm.errors
    assert hm.on_key_down(ord("K"), {"ctrl"}) is None
    assert hm.on_key_down(ord("K"), {"ctrl", "alt", "shift"}) is None
    assert hm.on_key_down(ord("K"), {"ctrl", "alt"}) == "X"
    assert hm.on_key_up(ord("K")) is True
    assert hm.on_key_up(ord("K")) is False


# ---------------------------------------------------------------- manager helpers
def test_parse_time_trigger():
    assert parse_time_trigger("08:30") == ("daily", 510)
    assert parse_time_trigger("every:15") == ("every", 15)
    for bad in ("25:00", "every:0", "8.30"):
        with pytest.raises(ValueError):
            parse_time_trigger(bad)


def test_clipboard_trigger_hit():
    t = Trigger(TriggerKind.CLIPBOARD_REGEX, r"order (\d+)", phrase_id=1)
    assert clipboard_trigger_hit(t, "see Order 42 now") == (True, ("42",))
    t2 = Trigger(TriggerKind.CLIPBOARD, "hello", phrase_id=1)
    assert clipboard_trigger_hit(t2, " HELLO ")[0]


# ---------------------------------------------------------------- manager with fakes
class FakeHook:
    def __init__(self, on_key):
        self.on_key = on_key

    def start(self):
        pass

    def stop(self):
        pass


class FakeWatcher(FakeHook):
    pass


class Ev:
    def __init__(self, char=None, vk=0x41, down=True, mods=()):
        self.char, self.vk, self.down, self.modifiers, self.scan, self.injected = char, vk, down, set(mods), 0, False

    @property
    def altgr(self):
        return "ctrl" in self.modifiers and "alt" in self.modifiers and self.char is not None


@pytest.fixture
def setup():
    store = Store(":memory:")
    f = store.add_folder(Folder("F"))
    p1 = store.add_phrase(Phrase("Sig", "Best", folder_id=f.id, triggers=[
        Trigger(TriggerKind.AUTOTEXT, "sg"), Trigger(TriggerKind.HOTKEY, "ctrl+alt+s")]))
    p2 = store.add_phrase(Phrase("Conf", "C", folder_id=f.id, apps_exclude="bad.exe", triggers=[
        Trigger(TriggerKind.AUTOTEXT, "cf", mode=AutotextMode.CONFIRM)]))
    p3 = store.add_phrase(Phrase("Clip", "K", triggers=[Trigger(TriggerKind.CLIPBOARD_REGEX, r"id=(\d+)")]))
    p4 = store.add_phrase(Phrase("Time", "T", triggers=[Trigger(TriggerKind.TIME, "every:5"),
                                                        Trigger(TriggerKind.APP_FOCUS, "excel.exe")]))
    expands, cmds = [], []
    fg = {"exe": "notepad.exe"}
    mgr = TriggerManager(store, expands.append, cmds.append, hook_factory=FakeHook,
                         watcher_factory=FakeWatcher, foreground_app=lambda: (fg["exe"], "title"),
                         foreground_hwnd=lambda: 1, poll_interval_s=3600)
    mgr.start()
    yield store, mgr, expands, cmds, fg, (p1, p2, p3, p4)
    mgr.stop()
    store.close()


def _drain(mgr):
    import time
    for _ in range(50):
        if mgr._queue.empty():
            break
        time.sleep(0.01)
    time.sleep(0.05)


def type_into(mgr, text):
    swallowed = []
    for ch in text:
        swallowed.append(mgr._on_key(Ev(ch, vk=0x20 if ch == " " else 0x41)))
    return swallowed


def test_manager_autotext_and_hotkey(setup):
    store, mgr, expands, cmds, fg, (p1, *_ ) = setup
    sw = type_into(mgr, "sg ")
    assert sw == [False, False, True]
    assert mgr._on_key(Ev(None, vk=ord("S"), mods={"ctrl", "alt"})) is True
    assert mgr._on_key(Ev(None, vk=ord("P"), mods={"ctrl", "alt"})) is False  # unbound chord passes through
    _drain(mgr)
    assert isinstance(expands[0], ExpansionRequest)
    assert expands[0].phrase_id == p1.id and expands[0].erase_chars == 2 and expands[0].trailing_delimiter == " "
    assert expands[0].context.app_exe == "notepad.exe" and expands[0].context.typed_abbreviation == "sg"
    assert expands[1].phrase_id == p1.id and expands[1].erase_chars == 0


def test_manager_command_hotkey_confirm_and_app_filter(setup):
    store, mgr, expands, cmds, fg, (p1, p2, *_ ) = setup
    assert mgr._on_key(Ev(" ", vk=0x20, mods={"ctrl", "alt"})) is True   # popup.hotkey ctrl+alt+space
    assert type_into(mgr, " cf ") == [False, False, False, False]
    fg["exe"] = "bad.exe"
    assert type_into(mgr, " cf ") == [False] * 4
    _drain(mgr)
    assert cmds == ["popup", f"confirm:{p2.id}:3"]


def test_manager_pause_and_busy(setup):
    store, mgr, expands, cmds, *_ = setup
    mgr.paused = True
    assert type_into(mgr, "sg ") == [False] * 3
    mgr.paused = False
    with mgr.suspend():
        assert type_into(mgr, "sg ") == [False] * 3
    assert type_into(mgr, " sg ")[-1] is True


def test_manager_ctrl_resets_buffer(setup):
    store, mgr, expands, *_ = setup
    type_into(mgr, "s")
    mgr._on_key(Ev(None, vk=ord("V"), mods={"ctrl"}))
    assert type_into(mgr, "g ") == [False, False]


def test_manager_clipboard_time_focus(setup):
    store, mgr, expands, cmds, fg, (p1, p2, p3, p4) = setup
    mgr._on_clipboard("user id=77")
    _drain(mgr)
    assert expands[-1].phrase_id == p3.id and expands[-1].context.regex_groups == ("77",)
    now = datetime(2026, 1, 1, 10, 0)
    assert mgr.check_time(now) == []
    assert mgr.check_time(now + timedelta(minutes=5)) == [p4.id]
    assert mgr.check_focus("EXCEL.EXE", "") == [p4.id]
    assert mgr.check_focus("excel.exe", "") == []


def test_manager_reload_picks_up_new_phrase(setup):
    store, mgr, expands, *_ = setup
    store.add_phrase(Phrase("New", "n", triggers=[Trigger(TriggerKind.AUTOTEXT, "nw")]))
    assert type_into(mgr, " nw ")[-1] is False
    mgr.reload()
    assert type_into(mgr, " nw ")[-1] is True


def test_injected_vk_packet_does_not_reset_buffer():
    """Windows 11 autocorrect injects VK_PACKET keys; they must not break matching."""
    from types import SimpleNamespace
    from phraseforge.triggers.manager import TriggerManager
    ev = SimpleNamespace(vk=0xE7, scan=ord("H"), char=None, modifiers=set(), injected=True, altgr=False)
    assert TriggerManager._classify(ev) == (None, None)
    ev.injected = False
    assert TriggerManager._classify(ev) == ("H", None)
