import pytest

from phraseforge.db import Store
from phraseforge.models import Folder, Phrase, Trigger, TriggerKind


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def test_phrase_roundtrip_with_triggers_and_tags(store):
    f = store.add_folder(Folder("Work"))
    p = store.add_phrase(Phrase("Signature", "Best regards", folder_id=f.id, tags=["mail", "sig"],
                                triggers=[Trigger(TriggerKind.AUTOTEXT, "sig#"),
                                          Trigger(TriggerKind.HOTKEY, "ctrl+alt+s")]))
    got = store.get_phrase(p.id)
    assert got.content == "Best regards"
    assert got.tags == ["mail", "sig"]
    assert [t.value for t in got.triggers] == ["sig#", "ctrl+alt+s"]
    assert store.search("regards")[0].id == p.id
    assert store.search("sig#")[0].id == p.id


def test_history_and_stats(store):
    p = store.add_phrase(Phrase("A", "one"))
    p.content = "two"
    store.update_phrase(p)
    assert store.history(p.id)[0]["content"] == "one"
    store.record_use(p.id, app="notepad.exe", chars=3)
    st = store.stats()
    assert st["expansions"] == 1 and st["chars_saved"] == 3


def test_app_filters_and_disabled_folder(store):
    f = store.add_folder(Folder("Word only", apps_include="winword.exe"))
    p = store.add_phrase(Phrase("X", "x", folder_id=f.id, triggers=[Trigger(TriggerKind.AUTOTEXT, "xx")]))
    assert store.phrase_allowed_in_app(p.id, "WINWORD.EXE")
    assert not store.phrase_allowed_in_app(p.id, "notepad.exe")
    f.enabled = False
    store.update_folder(f)
    assert store.triggers(TriggerKind.AUTOTEXT) == []


def test_clipboard_history_dedup(store):
    store.add_clipboard("a")
    store.add_clipboard("b")
    store.add_clipboard("a")
    assert [e.text for e in store.clipboard_entries()] == ["a", "b"]
    assert store.clipboard_at(1) == "b"
