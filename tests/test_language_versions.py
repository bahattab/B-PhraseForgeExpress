"""Phrase language versions (PhraseExpress-style) and right-to-left writing."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from phraseforge.db import Store
from phraseforge.models import Phrase


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def test_store_versions_and_fallback(store):
    p = store.add_phrase(Phrase("Greeting", "Hello"))
    store.set_phrase_languages(["Arabic", "German", "arabic", " "])
    assert store.phrase_languages() == ["Arabic", "German"]
    store.set_phrase_version(p.id, "Arabic", "مرحبا")
    assert store.phrase_versions(p.id) == {"Arabic": ("مرحبا", "text")}
    assert store.phrase_text(p, "arabic") == ("مرحبا", "text")
    assert store.phrase_text(p, "German") == ("Hello", "text")      # no German text: default
    assert store.phrase_text(p) == ("Hello", "text")
    store.delete_phrase_version(p.id, "Arabic")
    assert store.phrase_versions(p.id) == {}
    store.set_phrase_version(p.id, "Arabic", "مرحبا")
    store.delete_phrase(p.id)
    assert store.conn.execute("SELECT COUNT(*) FROM phrase_versions").fetchone()[0] == 0


def test_json_round_trip_keeps_versions(store, tmp_path):
    from phraseforge import io_formats
    p = store.add_phrase(Phrase("Greeting", "Hello"))
    store.set_phrase_version(p.id, "Arabic", "<p dir='rtl'>مرحبا</p>", "html")
    path = tmp_path / "x.json"
    io_formats.export_json(store, path)
    other = Store(":memory:")
    io_formats.import_json(other, path)
    q = other.phrases()[0]
    assert other.phrase_versions(q.id) == {"Arabic": ("<p dir='rtl'>مرحبا</p>", "html")}
    other.close()


def test_editor_language_tabs_save_and_translate(app, store):
    from phraseforge.ui.phrase_editor import PhraseEditor
    store.set_phrase_languages(["Arabic"])
    p = store.add_phrase(Phrase("Greeting", "Hello"))
    ed = PhraseEditor(store)
    ed.load(p.id)
    bar = ed.lang_bar
    assert [bar.tabText(i) for i in range(bar.count())] == ["Default", "Arabic"]
    bar.setCurrentIndex(1)
    assert ed.content_edit.content() == "Hello"              # unedited: shows the default text
    ed.content_edit.set_content("أهلا")
    ed._mark_dirty()
    bar.setCurrentIndex(0)
    assert ed.content_edit.content() == "Hello"
    ed.save()
    assert store.phrase_versions(p.id) == {"Arabic": ("أهلا", "text")}
    assert store.get_phrase(p.id).content == "Hello"
    bar.setCurrentIndex(1)
    assert ed.translate_current(lambda text, lang: f"[{lang}] {text}")
    ed.save()
    assert store.phrase_versions(p.id)["Arabic"][0] == "[Arabic] Hello"
    ed.remove_language_version()
    ed.save()
    assert store.phrase_versions(p.id) == {}
    ed.add_language("French")
    assert store.phrase_languages() == ["Arabic", "French"] and ed.current_language() == "French"


def test_popup_language_buttons_and_cycle(app, store):
    from phraseforge.ui.popup import PhrasePopup
    store.set_phrase_languages(["Arabic", "German"])
    p = store.add_phrase(Phrase("Greeting", "Hello"))
    store.set_phrase_version(p.id, "Arabic", "مرحبا")
    pop = PhrasePopup(store)
    pop.show_at(10, 10, caret=None)
    assert not pop.lang_strip.isHidden()
    assert [b.text() for b in pop.lang_buttons] == ["Default", "Arabic", "German"]
    ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Right, Qt.ControlModifier)
    assert pop.language_key_matches(ev)
    pop.cycle_language(1)
    assert pop.language == "Arabic" and pop.preview_text("phrase", p.id) == "مرحبا"
    pop.cycle_language(-1)
    assert pop.language == ""
    pop.cycle_language(-1)
    assert pop.language == "German"
    store.set_setting("menu.language_buttons", "0")
    pop.show_at(10, 10, caret=None)
    assert pop.lang_strip.isHidden()
    pop.hide_all(force=True)


def test_expansion_uses_requested_language(store):
    from types import SimpleNamespace

    from phraseforge.app import PhraseForgeApp
    from phraseforge.host import ExpansionRequest
    p = store.add_phrase(Phrase("Greeting", "Hello"))
    store.set_phrase_version(p.id, "Arabic", "مرحبا")
    seen = []

    class Engine:
        def expand(self, text, ctx):
            seen.append(text)
            raise RuntimeError("stop")      # only the chosen text matters here
    fake = SimpleNamespace(store=store, engine=Engine())
    with pytest.raises(RuntimeError):
        PhraseForgeApp._expand(fake, ExpansionRequest(phrase_id=p.id, language="Arabic"), 0)
    store.set_setting("phrase.active_language", "Arabic")
    with pytest.raises(RuntimeError):
        PhraseForgeApp._expand(fake, ExpansionRequest(phrase_id=p.id), 0)
    with pytest.raises(RuntimeError):
        PhraseForgeApp._expand(fake, ExpansionRequest(phrase_id=p.id, language="German"), 0)
    assert seen == ["مرحبا", "مرحبا", "Hello"]


def test_rtl_paragraph_direction(app):
    from phraseforge.ui.phrase_editor import ChipTextEdit, first_strong_rtl
    assert first_strong_rtl("123 مرحبا hello") and not first_strong_rtl("hello مرحبا")
    ed = ChipTextEdit()
    ed.set_content("<p>abc</p>", html=True)
    assert not ed.paragraph_is_rtl()
    ed.set_paragraph_direction(True)
    assert ed.paragraph_is_rtl()
    assert ed.textCursor().blockFormat().layoutDirection() == Qt.RightToLeft
    assert 'dir="rtl"' in ed.content() or "direction: rtl" in ed.content().lower() or "rtl" in ed.content()
    ed.set_paragraph_direction(False)
    assert not ed.paragraph_is_rtl()
