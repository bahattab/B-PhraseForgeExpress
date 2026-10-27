"""Capture2Text-style OCR options: replace rules, log format, quick-access languages,
re-capture last area, tray language menu (docs/menus/capture2text.md)."""
import os
from datetime import datetime

import pytest

from phraseforge.ocr import apply_replacements, format_log_entry, parse_replace_rules, quick_languages


def test_replace_rules_global_and_per_language():
    rules = parse_replace_rules("""
# comment
\\s+([.,]) => \\1
[Arabic]
ي => ى
bad[ => skipped
[English]
teh => the
""")
    assert ("Arabic", "ي", "ى") in rules
    assert all(r[1] != "bad[" for r in rules)
    assert apply_replacements("teh cat , ok", rules, "English") == "the cat, ok"
    assert apply_replacements("teh في", rules, "Arabic") == "teh فى"


def test_replace_rule_escapes():
    rules = parse_replace_rules(r" ; => \n")
    assert apply_replacements("a;b", rules) == "a\nb"


def test_log_format():
    when = datetime(2026, 10, 25, 8, 30, 0)
    assert format_log_entry("x", "${capture}${linebreak}") == "x\n"
    assert format_log_entry("x", "${timestamp}${tab}${capture}", when) == "2026-10-25 08:30:00\tx"
    assert format_log_entry("x", "") == "x\n"


def test_quick_languages():
    assert quick_languages("Arabic, English; Arabic, Russian, French") == ["Arabic", "English", "Russian"]
    assert quick_languages("") == []


class _Host:
    def __init__(self, text="hello"):
        self.text, self.calls, self.clip, self.last_ocr_rect = text, [], None, None

    def ocr_region(self, language="", rect=None, keep_line_breaks=None):
        self.calls.append((language, rect))
        self.last_ocr_rect = rect or (1, 2, 3, 4)
        return self.text

    def set_clipboard(self, t):
        self.clip = t


class _Tray:
    def __init__(self):
        self.notes = []

    def notify(self, *a):
        self.notes.append(a)


class _Poster:
    class posted:
        @staticmethod
        def emit(fn):
            fn()


@pytest.fixture
def app_like(tmp_path):
    from phraseforge.app import PhraseForgeApp
    from phraseforge.db import Store
    store = Store(":memory:")
    obj = PhraseForgeApp.__new__(PhraseForgeApp)
    obj.store, obj.host, obj.tray, obj.poster = store, _Host(), _Tray(), _Poster()
    yield obj
    store.close()


def test_ocr_modes_log_and_clipboard(app_like, tmp_path):
    a = app_like
    log = tmp_path / "ocr.txt"
    a.store.set_setting("ocr.log_file", str(log))
    a.store.set_setting("ocr.quick_languages", "Arabic, English")
    a._ocr_to_clipboard("recapture")                 # nothing captured yet
    assert a.host.calls == [] and "Nothing captured" in a.tray.notes[-1][1]
    a._ocr_to_clipboard("")
    assert a.host.calls[-1] == ("", None) and a.host.clip == "hello"
    a._ocr_to_clipboard("recapture")
    assert a.host.calls[-1] == ("", (1, 2, 3, 4))
    a._ocr_to_clipboard("quick2")
    assert a.host.calls[-1] == ("English", None)
    a._ocr_to_clipboard("quick3")                    # slot 3 empty
    assert "not set" in a.tray.notes[-1][1]
    assert log.read_text(encoding="utf-8") == "hello\n" * 3
    a.store.set_setting("ocr.save_to_clipboard", "0")
    a.host.clip = None
    a._ocr_to_clipboard("")
    assert a.host.clip is None


def test_tray_language_menu(app_like):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from phraseforge.ui.tray import Tray
    a = app_like
    a.store.set_setting("ocr.language", "Russian")
    a.store.set_setting("ocr.quick_languages", "Arabic, English")
    t = Tray()
    t.ocr_languages_provider = a._ocr_language_choices
    got = []
    t.ocr_language.connect(got.append)
    t._before_show()
    acts = t.ocr_lang_menu.actions()
    assert [x.text() for x in acts] == ["Auto", "Russian", "Arabic", "English"]
    assert acts[1].isChecked() and not acts[0].isChecked() and not acts[2].isChecked()
    acts[2].trigger()
    acts[0].trigger()
    assert got == ["Arabic", "Auto"]


def test_ocr_hotkeys_map_to_commands():
    from phraseforge.triggers.manager import COMMAND_HOTKEY_SETTINGS as M
    assert M["ocr.recapture_hotkey"] == "ocr:recapture"
    assert [M[f"ocr.quick{i}_hotkey"] for i in (1, 2, 3)] == ["ocr:quick1", "ocr:quick2", "ocr:quick3"]
