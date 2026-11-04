"""Spell check (PRD FR-EDT-01): word splitting, per-script dictionaries, user words,
dictionary download, the editor underline and the suggestions menu."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import httpx
import pytest

from phraseforge import spell
from phraseforge.db import Store

TINY_AFF = "SET UTF-8\nTRY esianrtolcdugmphbyfvkwz\n"
TINY_DIC = "4\nhello\nworld\nphrase\nforge\n"
TINY_AR_AFF = "SET UTF-8\nTRY اليمونتهبرعدسقفكحجشصطزخضغثذظةىءئؤأإآ\n"
TINY_AR_DIC = "3\nمرحبا\nكتاب\nسلام\n"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("PHRASEFORGE_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def install_tiny(home):
    d = home / "dictionaries"
    d.mkdir(exist_ok=True)
    (d / "en_US.aff").write_text(TINY_AFF, encoding="utf-8")
    (d / "en_US.dic").write_text(TINY_DIC, encoding="utf-8")
    (d / "ar.aff").write_text(TINY_AR_AFF, encoding="utf-8")
    (d / "ar.dic").write_text(TINY_AR_DIC, encoding="utf-8")


class FakeDict:
    def __init__(self, good):
        self.good, self.lookups = set(good), 0

    def lookup(self, w):
        self.lookups += 1
        return w in self.good

    def suggest(self, w):
        return iter(sorted(self.good))


def fake_checker(settings=None, dicts=None):
    settings = dict(settings or {})
    dicts = dicts or {"en_US": FakeDict({"hello", "world"}), "ar": FakeDict({"مرحبا"})}
    c = spell.SpellChecker(lambda k, d="": settings.get(k, d), settings.__setitem__, loader=lambda code: dicts[code])
    for code in dicts:
        c.dictionary(code, wait=True)
    return c, settings, dicts


# ---------------------------------------------------------------- words
def test_words_skip_urls_mail_paths_and_digits():
    text = "helo see https://exmple.com mail me@exmple.org C:\\Temp\\filez abc123 x9 ok it's"
    got = [w for _s, _n, w in spell.words(text)]
    assert got == ["helo", "see", "mail", "ok", "it's"]
    s, n, w = next(spell.words("  مرحبا بكم"))
    assert (s, n, w) == (2, 5, "مرحبا")


def test_arabic_marks_and_tatweel_are_ignored_for_lookup():
    assert spell.normalize("مَرْحَبـــا") == "مرحبا"
    assert spell.script_of("مرحبا") == "arabic" and spell.script_of("hello") == "latin"


# ---------------------------------------------------------------- checker
def test_each_script_uses_its_own_dictionary():
    c, _s, _d = fake_checker()
    assert not c.is_misspelled("hello") and c.is_misspelled("helo")
    assert not c.is_misspelled("مرحبا") and c.is_misspelled("مرحبى")
    assert not c.is_misspelled("Hello")             # capitalised at the start of a sentence
    assert not c.is_misspelled("مَرْحَبا")             # with harakat


def test_lookups_are_cached():
    c, _s, d = fake_checker()
    for _ in range(5):
        c.is_misspelled("helo")
    assert d["en_US"].lookups == 1


def test_user_words_ignore_and_disable(store):
    c, settings, _d = fake_checker()
    c.add_word("PhraseForge")
    assert "PhraseForge" in settings["spell.user_words"] and not c.is_misspelled("PhraseForge")
    c.ignore("zzzz")
    assert not c.is_misspelled("zzzz")
    settings["spell.enabled"] = "0"
    assert c.is_misspelled("helo")                   # settings are cached ...
    c.refresh()
    assert not c.is_misspelled("helo")               # ... until refresh()
    settings.update({"spell.enabled": "1", "spell.latin": ""})
    c.refresh()
    assert not c.is_misspelled("helo")               # Latin dictionary switched off


def test_a_missing_dictionary_marks_nothing(home, store):
    c = spell.checker_for(store)
    assert not c.is_misspelled("helo") and c.suggest("helo") == []
    assert c.status("en_US") == "missing"
    assert spell.checker_for(store) is c             # one checker per store


def test_a_broken_dictionary_reports_an_error():
    def boom(code):
        raise ValueError("bad affix file")
    c = spell.SpellChecker(lambda k, d="": d, loader=boom)
    c.dictionary("en_US", wait=True)
    assert c.status("en_US") == "error: bad affix file" and not c.is_misspelled("helo")


def test_real_hunspell_files_with_spylls(home):
    pytest.importorskip("spylls")
    install_tiny(home)
    c = spell.SpellChecker(lambda k, d="": d)
    c.dictionary("en_US", wait=True)
    c.dictionary("ar", wait=True)
    assert c.status("en_US") == "ready"
    assert not c.is_misspelled("hello") and c.is_misspelled("helo")
    assert "hello" in c.suggest("helo")
    assert not c.is_misspelled("كتاب") and c.is_misspelled("كتابب")
    assert "كتاب" in c.suggest("كتابب")


# ---------------------------------------------------------------- download
def test_download_writes_both_files(home):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, content=b"SET UTF-8\n" if request.url.path.endswith(".aff") else b"1\nhello\n")
    base = spell.download("en_US", client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    assert seen == [spell.SOURCE + "en/en_US.aff", spell.SOURCE + "en/en_US.dic"]
    assert base.with_suffix(".dic").read_bytes() == b"1\nhello\n" and spell.installed("en_US")


def test_failed_download_leaves_nothing(home):
    def handler(request):
        if request.url.path.endswith(".dic"):
            return httpx.Response(404)
        return httpx.Response(200, content=b"SET UTF-8\n")
    with pytest.raises(httpx.HTTPStatusError):
        spell.download("ar", client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    assert not spell.installed("ar") and not list((home / "dictionaries").iterdir())
    with pytest.raises(ValueError):
        spell.download("xx_XX")


# ---------------------------------------------------------------- editor
@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _underlined(doc):
    out = []
    block = doc.begin()
    while block.isValid():
        for r in block.layout().formats():
            out.append(block.text()[r.start:r.start + r.length])
        block = block.next()
    return out


def test_highlighter_underlines_only_misspelt_words(app):
    from PySide6.QtGui import QTextDocument
    from phraseforge.ui.spell_ui import SpellHighlighter
    c, _s, _d = fake_checker()
    doc = QTextDocument()
    h = SpellHighlighter(doc, c)
    doc.setPlainText("hello helo world\nمرحبا مرحبى https://wrld.example")
    h.rehighlight()
    assert _underlined(doc) == ["helo", "مرحبى"]
    assert "helo" in doc.toPlainText() and "underline" not in doc.toHtml().lower()   # display only


def test_context_menu_suggests_and_replaces(app):
    from PySide6.QtGui import QTextCursor
    from PySide6.QtWidgets import QMenu, QTextEdit
    from phraseforge.ui.spell_ui import add_spelling_actions
    c, settings, _d = fake_checker()
    ed = QTextEdit()
    ed.setPlainText("world helo")
    cur = QTextCursor(ed.document())
    cur.setPosition(8)                                # inside "helo"
    m = QMenu()
    assert add_spelling_actions(m, ed, cur, c)
    texts = [a.text() for a in m.actions()]
    assert texts[:2] == ["hello", "world"] and "Add to dictionary" in texts and "Ignore all" in texts
    m.actions()[0].trigger()
    assert ed.toPlainText() == "world hello"
    cur = QTextCursor(ed.document())
    cur.setPosition(1)                                # "world" is fine: nothing added
    assert not add_spelling_actions(QMenu(), ed, cur, c)
    ed.setPlainText("world helo")
    cur = QTextCursor(ed.document())
    cur.setPosition(8)
    m = QMenu()
    add_spelling_actions(m, ed, cur, c)
    next(a for a in m.actions() if a.text() == "Add to dictionary").trigger()
    assert "helo" in settings["spell.user_words"] and not c.is_misspelled("helo")


def test_phrase_editor_has_spell_check_and_menu(app, store, monkeypatch):
    from phraseforge.models import Phrase
    from phraseforge.ui.phrase_editor import PhraseEditor
    c, _s, _d = fake_checker()
    monkeypatch.setattr(spell, "checker_for", lambda st: c)
    p = store.add_phrase(Phrase("Greeting", "helo world"))
    ed = PhraseEditor(store)
    ed.load(p.id)
    ed.spell_highlighter.rehighlight()
    assert _underlined(ed.content_edit.document()) == ["helo"]
    from PySide6.QtGui import QTextCursor
    from PySide6.QtWidgets import QMenu
    cur = QTextCursor(ed.content_edit.document())
    cur.setPosition(2)
    ed.content_edit.menu_cursor = cur
    m = QMenu()
    ed._build_context_menu(m, None)
    texts = [a.text() for a in m.actions()]
    assert texts[0] == "hello" and "Insert macro" in texts
    ed.save()
    assert store.get_phrase(p.id).content == "helo world"     # the underline is never saved
