"""The macro recorder gets its keys from the trigger manager's keyboard hook (one hook per
app: pfhook.dll has a single keyboard hook), and never records injected input."""
import os
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="record_hook needs the Windows API modules")


class FakeRecorder:
    def __init__(self, stop_on=None):
        self.keys = []
        self.stop_on = stop_on
        self.started = False

    def start(self):
        self.started = True

    def key(self, vk, char, mods):
        self.keys.append((vk, char))
        return vk == self.stop_on


class FakeManager:
    def __init__(self, hooked=True):
        self.listeners = []
        self._hooked = hooked

    @property
    def keys_hooked(self):
        return self._hooked

    def add_key_listener(self, fn):
        self.listeners.append(fn)

    def remove_key_listener(self, fn):
        self.listeners.remove(fn)


def _ev(vk, down=True, injected=False):
    return SimpleNamespace(vk=vk, char="a", modifiers=set(), down=down, injected=injected)


def test_session_uses_manager_listener_and_skips_injected(monkeypatch):
    from phraseforge.platform import record_hook
    rec = FakeRecorder(stop_on=0x7B)
    mgr = FakeManager()
    session = record_hook.RecordSession(rec)
    session.mouse = SimpleNamespace(start=lambda: None, stop=lambda: None)   # no mouse hook in this test
    session.use_key_source(mgr)
    session.start()
    assert session.keys is None and mgr.listeners == [session._on_key]
    assert mgr.listeners[0](_ev(0x41)) is False          # a normal key is recorded, not swallowed
    assert mgr.listeners[0](_ev(0x42, injected=True)) is False
    assert mgr.listeners[0](_ev(0x41, down=False)) is False
    assert rec.keys == [(0x41, "a")]
    assert mgr.listeners[0](_ev(0x7B)) is True            # the stop hotkey is swallowed
    session.stop()
    assert mgr.listeners == []


def test_manager_passes_key_to_listener_and_honours_swallow():
    from phraseforge.triggers.manager import TriggerManager
    seen = []
    mgr = TriggerManager.__new__(TriggerManager)
    mgr._key_listeners = []
    mgr._hook = None
    mgr.add_key_listener(lambda ev: seen.append(ev.vk) or ev.vk == 0x7B)
    assert mgr._key_listeners
    assert mgr.keys_hooked is False
    assert TriggerManager._on_key(mgr, _ev(0x7B)) is True     # the listener swallows; nothing else runs
    assert seen == [0x7B]
