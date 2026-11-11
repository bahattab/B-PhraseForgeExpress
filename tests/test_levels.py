"""Language levels (G-17): level hotkey and spell check that follows the phrase's language."""
import pytest

from phraseforge import levels, spell


@pytest.mark.parametrize("current,stored,expect", [
    ("", '["German", "Arabic"]', "German"),
    ("German", '["German", "Arabic"]', "Arabic"),
    ("Arabic", '["German", "Arabic"]', ""),
    ("Klingon", '["German"]', "German"),
    ("", "[]", ""),
    ("", "not json", ""),
    ("", '{"a": 1}', ""),
    ("", '[" German ", "German", ""]', "German"),
])
def test_next_language(current, stored, expect):
    assert levels.next_language(current, stored) == expect


def test_hotkey_is_registered():
    from phraseforge.triggers import manager
    from phraseforge.ui.settings_schema import SCHEMA as DEFAULTS
    table = next(v for v in vars(manager).values() if isinstance(v, dict) and "hotkey.pause" in v)
    assert table["hotkey.next_language"] == "next_language"
    assert DEFAULTS["hotkey.next_language"] == ""


@pytest.mark.parametrize("name,code", [
    ("German", "de_DE"), ("deutsch", "de_DE"), ("de", "de_DE"), ("de_DE", "de_DE"), ("de-de", "de_DE"),
    ("English (UK)", "en_GB"), ("العربية", "ar"), ("Farsi", "fa_IR"), ("Klingon", ""), ("", ""),
])
def test_code_for_language(name, code):
    assert spell.code_for_language(name) == code


class FakeDict:
    def __init__(self, words):
        self.words = set(words)

    def lookup(self, w):
        return w in self.words

    def suggest(self, w):
        return sorted(self.words)


def make(monkeypatch, have=("en_US", "de_DE", "ar")):
    monkeypatch.setattr(spell, "installed", lambda code: code in have)
    dicts = {"en_US": FakeDict({"house"}), "de_DE": FakeDict({"haus"}), "ar": FakeDict({"بيت"})}
    c = spell.SpellChecker(lambda k, d="": d, loader=lambda code: dicts[code])
    for code in have:
        c.dictionary(code, wait=True)
    return c


def test_version_language_picks_its_dictionary(monkeypatch):
    c = make(monkeypatch)
    view = spell.LanguageChecker(c)
    assert view.is_misspelled("haus") and not view.is_misspelled("house")
    view.language = "German"
    assert not view.is_misspelled("haus") and view.is_misspelled("house")
    assert view.code_for("latin") == "de_DE"
    assert view.code_for("arabic") == "ar"            # other scripts keep their own dictionary
    assert view.suggest("hxus") == ["haus"]


def test_missing_dictionary_falls_back(monkeypatch):
    c = make(monkeypatch, have=("en_US", "ar"))
    view = spell.LanguageChecker(c, "German")
    assert view.code_for("latin") == "en_US"


def test_wrong_script_language_is_ignored(monkeypatch):
    c = make(monkeypatch)
    assert spell.LanguageChecker(c, "Arabic").code_for("latin") == "en_US"


def test_view_shares_the_checker(monkeypatch):
    c = make(monkeypatch)
    view = spell.LanguageChecker(c, "German")
    assert view.enabled() is c.enabled()
    assert view.listeners is c.listeners
