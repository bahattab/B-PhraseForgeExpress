"""Keyboard blocking during output (FR-TRG-06, T-TRG-06)."""
import sys
import time

import pytest

from phraseforge.triggers import keyblock
from phraseforge.triggers.keyblock import KeyBlocker


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


@pytest.fixture
def kb():
    out, native = [], []
    clock = Clock()
    b = KeyBlocker(out.extend, native.append, clock=clock, start_worker=False)
    return b, out, native, clock


def press(b, vk, **kw):
    return b.feed(vk, True, **kw), b.feed(vk, False, **kw)


def test_xyz_typed_during_output_comes_after_it(kb):
    b, out, native, _ = kb
    assert press(b, ord("Q")) == (False, False)          # no output: keys pass
    b.begin()
    assert native == [True]
    for ch in "XYZ":
        assert press(b, ord(ch)) == (True, True)
    assert b.flush() is False and out == []               # still typing the phrase
    b.end()
    assert b.flush() is True
    assert out == [(ord("X"), True), (ord("X"), False), (ord("Y"), True), (ord("Y"), False),
                   (ord("Z"), True), (ord("Z"), False)]
    assert native == [True, False]
    assert press(b, ord("Q")) == (False, False)


def test_key_held_before_output_is_released_normally(kb):
    b, out, *_ = kb
    assert b.feed(0x10, True) is False                   # Shift down before output
    b.begin()
    assert b.feed(0x10, False) is False                  # its release passes
    assert b.feed(0x41, True) is True
    b.end()
    assert b.feed(0x41, False) is True                   # up of a held down is held too
    b.flush()
    assert out == [(0x41, True), (0x41, False)]


def test_keys_after_output_wait_for_the_replay(kb):
    b, out, *_ = kb
    b.begin()
    b.feed(0x41, True)
    b.end()
    assert b.feed(0x42, True) is True                     # replay pending: cannot overtake
    b.flush()
    assert [vk for vk, _ in out] == [0x41, 0x42]
    assert b.feed(0x43, True) is False


def test_injected_and_late_keys_pass(kb):
    b, out, *_ = kb
    b.begin()
    assert b.feed(0x41, True, injected=True) is False
    assert b.feed(0x41, True, late=True) is False
    b.end()
    b.flush()
    assert out == []


def test_native_blocked_events_are_recorded(kb):
    b, out, *_ = kb
    b.begin()
    assert b.feed(0x41, True, blocked=True) is True
    b.end()
    assert b.feed(0x41, False, blocked=True) is True      # up arrives after output ended
    b.flush()
    assert out == [(0x41, True), (0x41, False)]


def test_discard_and_off(kb):
    b, out, native, _ = kb
    b.mode = "discard"
    b.begin()
    assert press(b, 0x41) == (True, True)
    b.end()
    assert b.flush() is True and out == []
    b.mode = "off"
    native.clear()
    b.begin()
    assert native == [] and press(b, 0x41) == (False, False)


def test_blocking_ends_by_itself(kb):
    b, out, native, clock = kb
    b.begin()
    b.feed(0x41, True)
    clock.t += keyblock.MAX_BLOCK_S + 1
    assert b.flush() is True                               # output stuck: give the keyboard back
    assert out == [(0x41, True)] and native[-1] is False
    assert b.feed(0x42, True) is False


def test_held_events_are_capped(kb, monkeypatch):
    b, out, *_ = kb
    monkeypatch.setattr(keyblock, "MAX_HELD", 3)
    b.begin()
    for _ in range(5):
        b.feed(0x41, True)
    assert b.dropped == 2
    b.end()
    b.flush()
    assert len(out) == 3


def test_worker_replays_after_end():
    out = []
    b = KeyBlocker(out.extend, None)
    b.begin()
    b.feed(0x41, True)
    b.end()
    for _ in range(100):
        if out:
            break
        time.sleep(0.01)
    assert out == [(0x41, True)]


@pytest.mark.skipif(sys.platform != "win32", reason="the native hook module loads Win32 APIs")
def test_native_hook_set_block():
    from phraseforge.platform.native_hook import ST_BLOCKED, NativeKeyboardHook, PFEvent

    class Lib:
        calls = []

        def pf_set_block(self, on):
            self.calls.append(on)
    hook = NativeKeyboardHook(lambda ev: False, lib=Lib())
    hook.set_block(True)
    hook.set_block(False)
    assert Lib.calls == [1, 0]
    raw = PFEvent()
    raw.vk, raw.status = 0x41, 0x01 | 0x10 | ST_BLOCKED
    ev = hook.event_from(raw)
    assert ev.blocked and ev.native and ev.down


def test_dll_source_declares_block():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "native" / "pfhook" / "pfhook.c").read_text()
    assert "PF_API void pf_set_block(int on)" in src and "#define PF_VERSION 2" in src


def test_key_down_after_output_releases_normally(kb):
    """Shift held through the end of output: its repeat downs pass, so its up must pass too."""
    b, out, *_ = kb
    b.mode = "discard"
    b.begin()
    assert b.feed(0x10, True) is True
    b.end()
    b.flush()
    assert b.feed(0x10, True) is False                    # auto-repeat after output
    assert b.feed(0x10, False) is False                   # release reaches Windows


def test_begin_turns_native_block_on_again(kb):
    b, out, native, _ = kb
    b.begin()
    b.end()
    b.flush()
    b.begin()
    assert native == [True, False, True]


def test_dll_clears_block_up_on_passed_down():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "native" / "pfhook" / "pfhook.c").read_text()
    assert "g_block_up[ev.vk] = 0;" in src
