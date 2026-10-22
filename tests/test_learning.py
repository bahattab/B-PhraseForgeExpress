import pytest

from phraseforge.clipboard_history import ClipboardHistory
from phraseforge.db import Store
from phraseforge.learning import Learner


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def test_repeated_sentence_becomes_suggestion(store):
    L = Learner(store, password_check=lambda: False)
    for _ in range(3):
        L.feed_text("Thank you for your message. ")
    sugg = L.suggestions()
    assert sugg and sugg[0]["text"] == "Thank you for your message." and sugg[0]["count"] == 3


def test_short_and_nonalpha_ignored(store):
    L = Learner(store, password_check=lambda: False)
    assert L.feed_text("Hi there. 1234567890123456. ") == []


def test_backspace_and_reset(store):
    L = Learner(store, password_check=lambda: False)
    L.feed_text("Kind regards to youX")
    L.feed_key("backspace")
    assert L.feed_text(".") == ["Kind regards to you."]
    L.feed_text("Kind regards")
    L.feed_key("left")
    assert L.feed_text(" to all of you.") == ["to all of you."]


def test_disabled_and_password(store):
    store.set_setting("learning.enabled", "0")
    L = Learner(store, password_check=lambda: False)
    assert L.feed_text("Thank you for your message. ") == []
    store.set_setting("learning.enabled", "1")
    L2 = Learner(store, password_check=lambda: True)
    assert L2.feed_text("SuperSecretPassword123. ") == []


def test_dismissed_suggestion_hidden(store):
    L = Learner(store, password_check=lambda: False)
    for _ in range(3):
        L.feed_text("See you at the meeting!\n")
    store.dismiss_suggestion("See you at the meeting!")
    assert L.suggestions() == []


def test_clipboard_history_filters(store):
    class W:
        def __init__(self, cb):
            self.cb = cb

        def start(self):
            pass

        def stop(self):
            pass

    fg = {"exe": "notepad.exe"}
    h = ClipboardHistory(store, watcher_factory=W, foreground_app=lambda: (fg["exe"], ""))
    h.start()
    h.on_clipboard_text("one")
    h.paused = True
    h.on_clipboard_text("two")
    h.paused = False
    store.set_excluded_apps(["keepass.exe"])
    fg["exe"] = "keepass.exe"
    h.on_clipboard_text("secret")
    fg["exe"] = "notepad.exe"
    h.on_clipboard_text("   ")
    h.on_clipboard_text("three")
    h.stop()
    assert [e.text for e in store.clipboard_entries()] == ["three", "one"]
    assert store.clipboard_entries()[0].source_app == "notepad.exe"
