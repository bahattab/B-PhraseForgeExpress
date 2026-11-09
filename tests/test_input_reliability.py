"""Typing reliability (PRD G-05, G-06, G-33): the native keyboard hook (pfhook.dll), keys that
reach the program because Python answered late, the hook paused while the PC is locked, and the
notice for windows that run as administrator."""
import ctypes
import os
import subprocess
import sys
import textwrap
import time

import pytest

from phraseforge.db import Store
from phraseforge.models import Folder, Phrase, Trigger, TriggerKind
from phraseforge.platform import native_hook as nh
from phraseforge.platform.native_hook import (ST_DOWN, ST_NATIVE, ST_WAITED, WHEN_ALWAYS, WHEN_DEGRADED,
                                              NativeKeyboardHook, PFEvent, bits_to_mods, mods_to_bits)
from phraseforge.triggers.manager import TriggerManager

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows keyboard hook")


# ---------------------------------------------------------------- the DLL wrapper, with a fake DLL
class FakeLib:
    def __init__(self):
        self.replies = []
        self.rules = []
        self.started = 0
        self.stopped = 0
        self.answer_in_time = True

    def pf_set_options(self, *a):
        self.options = a

    def pf_set_rules(self, arr, n):
        self.rules = [(arr[i].vk, arr[i].mods, arr[i].when) for i in range(n)]
        return n

    def pf_start(self):
        self.started += 1
        return 0

    def pf_stop(self):
        self.stopped += 1

    def pf_next(self, ev, timeout):
        time.sleep(0.01)
        return 0

    def pf_reply(self, seq, swallow):
        self.replies.append((seq, swallow))
        return 1 if self.answer_in_time else 0

    def pf_stats(self, ref):
        pass


def raw(vk, chars="", status=ST_DOWN | ST_WAITED, mods=0, seq=7):
    e = PFEvent()
    e.seq, e.vk, e.status, e.mods, e.nchars = seq, vk, status, mods, len(chars)
    e.chars = chars
    return e


def test_modifier_bits_round_trip():
    for mods in ({"ctrl"}, {"ctrl", "alt"}, {"shift", "win"}, set()):
        assert bits_to_mods(mods_to_bits(mods)) == mods


def test_events_are_translated_and_answered():
    seen = []
    lib = FakeLib()
    hook = NativeKeyboardHook(lambda ev: seen.append(ev) or ev.char == " ", lib=lib)
    hook.handle(raw(0x41, "a", seq=1))
    hook.handle(raw(0x20, " ", seq=2))
    hook.handle(raw(0x0D, "\r", seq=3))
    assert [e.char for e in seen] == ["a", " ", "\n"]          # Enter becomes "\n" like the Python hook
    assert lib.replies == [(1, 0), (2, 1), (3, 0)]
    assert not any(e.late or e.native for e in seen)


def test_late_and_native_events_are_flagged_and_not_answered():
    seen = []
    lib = FakeLib()
    hook = NativeKeyboardHook(lambda ev: seen.append(ev) or True, lib=lib)
    hook.handle(raw(0x41, "a", status=ST_DOWN, seq=4))                      # Python was late
    hook.handle(raw(0x53, "", status=ST_DOWN | ST_NATIVE, mods=6, seq=5))   # hotkey swallowed by the DLL
    assert seen[0].late and not seen[0].native
    assert seen[1].native and not seen[1].late and seen[1].modifiers == {"ctrl", "alt"}
    assert lib.replies == []


def test_a_failing_callback_still_answers():
    lib = FakeLib()
    hook = NativeKeyboardHook(lambda ev: 1 / 0, lib=lib)
    hook.handle(raw(0x41, "a", seq=9))
    assert lib.replies == [(9, 0)]


def test_rules_are_pushed_on_start_and_on_change():
    lib = FakeLib()
    hook = NativeKeyboardHook(lambda ev: False, lib=lib)
    hook.set_rules([(0x53, {"ctrl", "alt"}, WHEN_DEGRADED)])
    assert lib.rules == [(0x53, 6, WHEN_DEGRADED)]
    hook.start()
    try:
        assert lib.started == 1 and hook.running
        assert lib.rules == [(0x53, 6, WHEN_DEGRADED)]
    finally:
        hook.stop()
    assert lib.stopped == 1 and not hook.running


def test_make_keyboard_hook_falls_back_to_python(monkeypatch):
    monkeypatch.setenv("PHRASEFORGE_HOOK", "python")
    from phraseforge.platform.keyboard_hook import KeyboardHook
    assert isinstance(nh.make_keyboard_hook(lambda ev: False), KeyboardHook)


# ---------------------------------------------------------------- the trigger manager
class FakeHook:
    native = True

    def __init__(self, on_key):
        self.on_key = on_key
        self.running = False
        self.rules = None
        self.starts = self.stops = 0

    def start(self):
        self.running = True
        self.starts += 1

    def stop(self):
        self.running = False
        self.stops += 1

    def set_rules(self, rules):
        self.rules = list(rules)


class FakeWatcher:
    def __init__(self, cb):
        pass

    def start(self):
        pass

    def stop(self):
        pass


class Ev:
    def __init__(self, char=None, vk=0x41, down=True, mods=(), late=False, native=False):
        self.char, self.vk, self.down, self.modifiers = char, vk, down, set(mods)
        self.scan, self.injected, self.late, self.native = 0, False, late, native

    @property
    def altgr(self):
        return False


@pytest.fixture
def env():
    store = Store(":memory:")
    f = store.add_folder(Folder("F"))
    p = store.add_phrase(Phrase("Sig", "Best", folder_id=f.id, triggers=[
        Trigger(TriggerKind.AUTOTEXT, "sg"), Trigger(TriggerKind.HOTKEY, "ctrl+alt+s")]))
    expands, cmds = [], []
    state = {"session": "active", "elevated": set(), "hwnd": 1, "exe": "notepad.exe"}
    mgr = TriggerManager(store, expands.append, cmds.append, hook_factory=FakeHook, watcher_factory=FakeWatcher,
                         foreground_app=lambda: (state["exe"], "t"), foreground_hwnd=lambda: state["hwnd"],
                         poll_interval_s=3600, session_state=lambda: state["session"],
                         window_elevated=lambda h: h in state["elevated"])
    mgr.start()
    yield store, mgr, expands, cmds, state, p
    mgr.stop()
    store.close()


def drain(mgr):
    for _ in range(100):
        if mgr._queue.empty():
            break
        time.sleep(0.01)
    time.sleep(0.05)


def typed(mgr, text, late_last=False):
    out = []
    for i, ch in enumerate(text):
        late = late_last and i == len(text) - 1
        out.append(mgr._on_key(Ev(ch, vk=0x20 if ch == " " else 0x41, late=late)))
    return out


def test_native_rules_list_hotkeys_and_caps_lock(env):
    store, mgr, *_ = env
    hook = mgr._hook
    assert mgr.hook_kind == "native"
    assert (0x53, frozenset({"ctrl", "alt"}), WHEN_DEGRADED) in hook.rules
    assert not any(vk == 0x14 for vk, _, _ in hook.rules)
    store.set_setting("features.disable_capslock", "1")
    mgr.reload()
    assert (0x14, frozenset(), WHEN_ALWAYS) in hook.rules


def test_on_time_match_erases_the_abbreviation_only(env):
    _, mgr, expands, _, _, p = env
    assert typed(mgr, " sg ")[-1] is True
    drain(mgr)
    assert expands[-1].phrase_id == p.id and expands[-1].erase_chars == 2 and expands[-1].trailing_delimiter == " "


def test_late_delimiter_is_erased_too(env):
    """The space reached the program before Python answered: erase it and type it again."""
    _, mgr, expands, *_ = env
    typed(mgr, " sg ", late_last=True)
    drain(mgr)
    assert expands[-1].erase_chars == 3 and expands[-1].trailing_delimiter == " "


def test_late_capitalisation_erases_the_lower_case_letter(env):
    store, mgr, _, cmds, *_ = env
    store.set_setting("autocorrect.capitalize_sentences", "1")
    mgr.reload()
    typed(mgr, "ok. ")
    mgr._on_key(Ev("w", late=True))
    drain(mgr)
    assert cmds[-1] == "autocorrect:1:W"


def test_late_backspace_does_not_undo(env):
    store, mgr, _, cmds, *_ = env
    store.set_setting("features.detect_unwanted_replacements", "1")
    mgr.reload()
    typed(mgr, " sg ")
    assert mgr._on_key(Ev(None, vk=0x08, late=True)) is False
    drain(mgr)
    assert not any(c.startswith("undo_expansion") for c in cmds)


def test_session_lock_stops_and_unlock_restarts_the_hook(env):
    _, mgr, expands, _, state, _ = env
    hook = mgr._hook
    typed(mgr, " s")
    state["session"] = "locked"
    assert mgr.check_session() == "locked" and not mgr.session_active
    assert hook.stops == 1 and mgr.matcher.buffer == ""
    assert mgr.check_session() == "locked" and hook.stops == 1       # no repeat
    state["session"] = "active"
    assert mgr.check_session() == "active"
    assert mgr._hook.running and mgr._hook.starts >= 1
    state["session"] = "disconnected"
    assert mgr.check_session() == "disconnected"


def test_elevated_window_is_reported_once_per_program(env):
    _, mgr, _, cmds, state, _ = env
    state["elevated"] = {5}
    assert mgr.check_elevated() is None              # hwnd 1: normal window
    state["hwnd"], state["exe"] = 5, "Regedit.exe"
    assert mgr.check_elevated() == "regedit.exe"
    state["hwnd"] = 1
    mgr.check_elevated()
    state["hwnd"] = 5
    assert mgr.check_elevated() is None              # warned already
    drain(mgr)
    assert cmds.count("elevated:regedit.exe") == 1


def test_native_hook_that_fails_to_start_falls_back(monkeypatch):
    class Broken(FakeHook):
        def start(self):
            raise OSError("no hook")

    started = []
    from phraseforge.platform import keyboard_hook
    monkeypatch.setattr(keyboard_hook.KeyboardHook, "start", lambda self: started.append(self))
    monkeypatch.setattr(keyboard_hook.KeyboardHook, "stop", lambda self: None)
    store = Store(":memory:")
    mgr = TriggerManager(store, lambda r: None, lambda c: None, hook_factory=Broken, watcher_factory=FakeWatcher,
                         poll_interval_s=3600, session_state=lambda: "active", window_elevated=lambda h: False)
    mgr.start()
    try:
        assert mgr.hook_kind == "python" and started
    finally:
        mgr.stop()
        store.close()


def test_session_flags_map_to_states():
    from phraseforge.platform import session as s
    assert s.classify(0, s.WTS_SESSIONSTATE_UNLOCK) == "active"
    assert s.classify(0, s.WTS_SESSIONSTATE_LOCK) == "locked"
    assert s.classify(s.WTSDisconnected, s.WTS_SESSIONSTATE_UNLOCK) == "disconnected"
    assert s.classify(0, -1) == "active"            # unknown: never switch expansion off
    assert s.session_state() in ("active", "locked", "disconnected")


def test_integrity_comparison():
    from phraseforge.platform import session as s
    assert s.higher_than_us(0x3000, 0x2000) and not s.higher_than_us(0x2000, 0x2000)
    assert s.higher_than_us(-1, 0x2000) and not s.higher_than_us(-1, 0x3000)
    assert not s.higher_than_us(None, 0x2000)
    assert s.own_integrity() >= 0x2000


# ---------------------------------------------------------------- the real DLL (built in CI)
needs_dll = pytest.mark.skipif(nh.load_library() is None, reason=f"pfhook.dll: {nh.library_error()}")

INJECTOR = textwrap.dedent("""
    import ctypes, sys, time
    from ctypes import wintypes as wt
    class KI(ctypes.Structure):
        _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                    ("dwExtraInfo", ctypes.c_size_t)]
    class MI(ctypes.Structure):
        _fields_ = [("a", ctypes.c_long * 2), ("b", wt.DWORD * 3), ("c", ctypes.c_size_t)]
    class U(ctypes.Union):
        _fields_ = [("ki", KI), ("mi", MI)]
    class INPUT(ctypes.Structure):
        _fields_ = [("type", wt.DWORD), ("u", U)]
    time.sleep(float(sys.argv[1]))
    for i in range(int(sys.argv[2])):
        for up in (0, 2):
            inp = INPUT(type=1)
            inp.u.ki = KI(wVk=0x87, wScan=0, dwFlags=up)      # F24: no program reacts to it
            ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        time.sleep(0.05)
""")


def _inject(delay, count):
    return subprocess.Popen([sys.executable, "-I", "-c", INJECTOR, str(delay), str(count)])


@needs_dll
def test_real_hook_sees_and_swallows_keys():
    seen = []
    hook = NativeKeyboardHook(lambda ev: seen.append(ev) or ev.vk == 0x87, budget_ms=200)
    hook.start()
    try:
        _inject(0.2, 3).wait(10)
        deadline = time.time() + 3
        while len(seen) < 6 and time.time() < deadline:
            time.sleep(0.05)
        if not seen:
            pytest.skip("no keyboard input reaches hooks on this machine (no interactive desktop)")
        f24 = [e for e in seen if e.vk == 0x87]
        assert len(f24) == 6 and sum(e.down for e in f24) == 3
        assert not any(e.late for e in f24)
        st = hook.stats()
        assert st["running"] and st["timeouts"] == 0 and st["waited"] >= 6
    finally:
        hook.stop()


@needs_dll
def test_real_hook_survives_python_holding_the_gil():
    """FR-INP-01: Python stops answering (GIL held for 2 s); keys still pass promptly and
    are reported late, and the hook stays installed."""
    seen = []
    hook = NativeKeyboardHook(lambda ev: seen.append(ev) or False, budget_ms=40)
    hook.start()
    try:
        proc = _inject(0.3, 5)
        ctypes.PyDLL("kernel32").Sleep(2000)          # PyDLL keeps the GIL during the call
        proc.wait(10)
        deadline = time.time() + 3
        while len(seen) < 10 and time.time() < deadline:
            time.sleep(0.05)
        if not seen:
            pytest.skip("no keyboard input reaches hooks on this machine (no interactive desktop)")
        st = hook.stats()
        assert st["running"], st
        assert st["timeouts"] >= 1, st                  # the first key waited, then the hook stopped waiting
        assert st["max_us"] < 300_000, st               # never close to LowLevelHooksTimeout
        f24 = [e for e in seen if e.vk == 0x87]
        assert len(f24) == 10 and any(e.late for e in f24)
        assert not st["degraded"]                       # Python caught up
    finally:
        hook.stop()
