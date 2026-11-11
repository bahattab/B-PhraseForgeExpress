"""Markdown/Word/RTF into the phrase editor (G-21) and the editor's spell language (G-17)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from phraseforge.db import Store
from phraseforge.models import Phrase
from phraseforge.ui import editor_files


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def test_markdown_becomes_html(app, tmp_path):
    p = tmp_path / "a.md"
    p.write_text("# Title\n\nSome **bold** text {#date}\n", encoding="utf-8")
    html, is_html = editor_files.read_for_editor(p)
    assert is_html and "<body" not in html and "Title" in html and "font-weight" in html


def test_text_and_errors(app, tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("plain", encoding="utf-8")
    assert editor_files.read_for_editor(p) == ("plain", False)
    bad = tmp_path / "a.exe"
    bad.write_bytes(b"MZ")
    with pytest.raises(ValueError, match="cannot be inserted"):
        editor_files.read_for_editor(bad)
    big = tmp_path / "big.md"
    big.write_bytes(b"x" * (editor_files.MAX_FILE + 1))
    with pytest.raises(ValueError, match="4 MB"):
        editor_files.read_for_editor(big)


def test_docx_text(app, tmp_path):
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_paragraph("From Word")
    p = tmp_path / "w.docx"
    d.save(p)
    text, is_html = editor_files.read_for_editor(p)
    assert "From Word" in text and not is_html


def test_insert_into_rich_and_plain_phrase(app, store):
    from phraseforge.ui.phrase_editor import PhraseEditor
    rich = store.add_phrase(Phrase("R", "<p>x</p>", content_format="html"))
    plain = store.add_phrase(Phrase("P", "x"))
    ed = PhraseEditor(store)
    ed.load(rich.id)
    ed.insert_document("<b>bold</b> {#date}", True)
    out = ed.content_edit.content()
    assert "bold" in out and "{#date}" in out and "font-weight" in out
    ed.load(plain.id)
    ed.insert_document("<b>bold</b> {#date}", True)
    out = ed.content_edit.content()
    assert "<b>" not in out and "bold {#date}" in out


def test_editor_spell_follows_version(app, store):
    from phraseforge.ui.phrase_editor import PhraseEditor
    store.set_phrase_languages(["German"])
    p = store.add_phrase(Phrase("G", "Hello"))
    ed = PhraseEditor(store)
    ed.load(p.id)
    if ed.spell_checker is None:
        pytest.skip("spell check unavailable here")
    assert ed.spell_checker.language == ""
    ed.lang_bar.setCurrentIndex(1)
    assert ed.spell_checker.language == "German"
    ed.lang_bar.setCurrentIndex(0)
    assert ed.spell_checker.language == ""


def test_untrusted_markdown_is_cleaned(app, tmp_path):
    p = tmp_path / "evil.md"
    p.write_text("![x](file://attacker/share/a.png) ![y](C:/secret.png) "
                 "[ok](https://example.com) [bad](file:///C:/x) [js](javascript:alert(1))\n", encoding="utf-8")
    html, _ = editor_files.read_for_editor(p)
    assert "<img" not in html and "attacker" not in html and "secret.png" not in html
    assert 'href="https://example.com"' in html and "javascript" not in html and "file:" not in html


def test_inserted_macros_quarantine_the_phrase(app, store):
    from phraseforge.ui.phrase_editor import PhraseEditor
    p = store.add_phrase(Phrase("P", "<p>keep {#date}</p>", content_format="html"))
    ed = PhraseEditor(store)
    ed.load(p.id)
    store.release_quarantine(p.id)
    from PySide6.QtGui import QTextCursor
    ed.content_edit.moveCursor(QTextCursor.End)
    ed.insert_document("<table><tr><td>a</td></tr></table><p>{#run calc}</p>", True)
    ed.save()
    assert store.quarantine_origin(p.id) == "imported"
    assert "{#run calc}" in ed.content_edit.content() and "{#date}" in ed.content_edit.content()
    ed.content_edit.insert_content("typed")
    ed._mark_dirty()
    ed.save()                                            # the next save by the user approves it again
    assert store.quarantine_origin(p.id) is None


def test_chipify_range_only_touches_the_insert(app, store):
    from phraseforge.ui.phrase_editor import PhraseEditor
    p = store.add_phrase(Phrase("P", "<p>x</p>", content_format="html"))
    ed = PhraseEditor(store)
    ed.load(p.id)
    ce = ed.content_edit
    c = ce.textCursor()
    from PySide6.QtGui import QTextCursor
    c.movePosition(QTextCursor.End)
    c.insertText("{#literal}")                           # plain text, not a chip yet
    start = c.position()
    c.insertHtml("<table><tr><td>t</td></tr></table><p>{#date}</p>")
    ce.chipify_range(start, c.position())
    assert len(ce._chip_positions(ce.document())) == 1
