"""Instant translation of the selected text, and the Google sign-in account hint (passkeys)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from phraseforge import instant_translate as it


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_direction_is_automatic():
    assert it.target_for("Hello world", "Arabic", "English") == "Arabic"
    assert it.target_for("مرحبا بالعالم", "Arabic", "English") == "English"
    assert it.target_for("Hello", "English", "Arabic") == "Arabic"


def test_translate_uses_the_engine():
    seen = []
    out, lang = it.translate({"translate.instant_to": "Arabic"}, "  Hello  ",
                             translate_fn=lambda t, lang: seen.append((t, lang)) or "مرحبا")
    assert (out, lang) == ("مرحبا", "Arabic") and seen == [("Hello", "Arabic")]
    with pytest.raises(ValueError, match="Select"):
        it.translate({}, "   ")
    it.translate({}, "x" * 9000, translate_fn=lambda t, lang: seen.append(len(t)) or "")
    assert seen[-1] == it.MAX_CHARS


def test_bubble(app):
    from phraseforge.ui.translate_bubble import TranslateBubble
    b = TranslateBubble()
    b.show_busy("<b>Hello</b>", 100, 100)
    assert not b.copy_btn.isEnabled()
    b.show_result("<b>Hello</b>", "مرحبا", "Arabic")
    assert b.result.toPlainText() == "مرحبا" and b.copy_btn.isEnabled()
    assert b.source.text() == "<b>Hello</b>"                 # plain text, never rich text
    got = []
    b.replace_requested.connect(got.append)
    b.retranslate.connect(lambda t, lang: got.append((t, lang)))
    b.replace_btn.click()
    b._swap()
    assert got == ["مرحبا", ("مرحبا", "English")]
    b._copy()
    assert QApplication.clipboard().text() == "مرحبا"
    b.show_error("Could not translate: offline")
    assert not b.replace_btn.isEnabled()


def test_bubble_drops_stale_answers_and_guards_cut_text(app):
    from phraseforge.ui.translate_bubble import TranslateBubble
    b = TranslateBubble()
    b.show_busy("new", 10, 10, request=2)
    b.show_result("old", "قديم", "Arabic", request=1)        # an earlier request answers late
    assert b.result.toPlainText() != "قديم"
    b.show_result("new", "جديد", "Arabic", request=2, cut=True)
    assert b.result.toPlainText() == "جديد" and not b.replace_btn.isEnabled() and b.copy_btn.isEnabled()
    assert b.testAttribute(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.WA_ShowWithoutActivating)


def test_swap_uses_the_back_language(app):
    from phraseforge.ui.translate_bubble import TranslateBubble
    b = TranslateBubble()
    b.back_language = "French"
    b.show_busy("x", 1, 1, request=1)
    b.show_result("x", "y", "Arabic", request=1)
    got = []
    b.retranslate.connect(lambda t, lang: got.append(lang))
    b._swap()
    assert got == ["French"]


def test_app_hotkey_flow(app):
    from phraseforge.app import PhraseForgeApp
    shown = []

    class Fake:
        store = type("S", (), {"settings": lambda self: {"translate.instant_to": "Arabic"}})()
        poster = type("P", (), {"posted": type("E", (), {"emit": lambda self, fn: fn()})()})()
        tray = type("T", (), {"notify": lambda self, t, m: shown.append(("notify", m))})()

        def _caret_or_cursor(self):
            return (10, 10)

        def _bubble(self):
            return type("B", (), {"show_busy": lambda s, t, x, y, request=0: shown.append(("busy", t)),
                                  "show_result": lambda s, t, o, l, request=0, cut=False: shown.append(("result", o, l)),
                                  "show_error": lambda s, m, request=0: shown.append(("error", m))})()
    f = Fake()
    PhraseForgeApp._instant_translate(f, 1, lambda: "Hello", lambda t, lang: "مرحبا", sync=True)
    assert shown == [("busy", "Hello"), ("result", "مرحبا", "Arabic")]
    shown.clear()
    PhraseForgeApp._instant_translate(f, 1, lambda: "")
    assert shown[0][0] == "notify"
    shown.clear()

    def boom(t, lang):
        raise RuntimeError("offline")
    PhraseForgeApp._instant_translate(f, 1, lambda: "Hello", boom, sync=True)
    assert shown[-1] == ("error", "Could not translate: offline")


def test_hotkey_registered():
    from phraseforge.triggers import manager
    from phraseforge.ui.settings_schema import SCHEMA
    table = next(v for v in vars(manager).values() if isinstance(v, dict) and "hotkey.pause" in v)
    assert table["translate.instant_hotkey"] == "instant_translate"
    assert SCHEMA["translate.instant_hotkey"] == "ctrl+alt+t"


@pytest.mark.parametrize("hint,ok", [("ali@gmail.com", True), ("", False), ("no-at", False),
                                     ("a@b.c&prompt=none", True), ("x y@g.com", False), ('a"@b.com', False)])
def test_login_hint_check(hint, ok):
    from phraseforge.cloud import gdrive
    assert gdrive.valid_hint(hint) is ok


def test_login_hint_reaches_google(monkeypatch):
    pytest.importorskip("google_auth_oauthlib")
    from google_auth_oauthlib import flow as F
    from phraseforge.cloud import gdrive
    got = {}

    class Flow:
        @classmethod
        def from_client_config(cls, cfg, scopes):
            return cls()

        def run_local_server(self, **kw):
            got.update(kw)
            return None
    monkeypatch.setattr(F, "InstalledAppFlow", Flow)
    monkeypatch.setattr(gdrive, "client_config", lambda: {"installed": {}})
    with pytest.raises(gdrive.GDriveError):
        gdrive.GoogleDrive().sign_in(login_hint="ali@gmail.com")
    assert got["login_hint"] == "ali@gmail.com"
    got.clear()
    with pytest.raises(gdrive.GDriveError):
        gdrive.GoogleDrive().sign_in(login_hint="bad hint")
    assert "login_hint" not in got
