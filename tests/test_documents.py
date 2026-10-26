"""Export phrases as Word (.docx) and PDF with Arabic right to left (synthetic data)."""
import re
import zipfile
from xml.etree import ElementTree as ET

import pytest

from phraseforge import documents
from phraseforge.db import Store
from phraseforge.models import Folder, Phrase, Trigger, TriggerKind

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    f = s.add_folder(Folder("رسائل"))
    p = s.add_phrase(Phrase("تحية", "السلام عليكم\nورحمة الله", folder_id=f.id,
                            triggers=[Trigger(TriggerKind.AUTOTEXT, "slm")]))
    s.set_phrase_version(p.id, "English", "Peace be upon you", "text")
    s.add_phrase(Phrase("Bold one", "<p>Hello <b>world</b></p>", content_format="html",
                        triggers=[Trigger(TriggerKind.HOTKEY, "ctrl+alt+1")]))
    s.add_phrase(Phrase("Braces", "use {{x} and {#date}"))
    yield s
    s.close()


def test_plain_text_and_rtl_detection():
    assert documents.plain_text("<p>a<br>b</p>", "html") == "a\nb"
    assert documents.plain_text("x {{y}", "text") == "x {y}"
    assert documents.is_rtl("  مرحبا hello") and not documents.is_rtl("hello مرحبا")


def test_collect_includes_triggers_and_versions(store):
    entries = documents.collect(store, store.phrases())
    by = {e.description: e for e in entries}
    assert by["تحية"].triggers == [("autotext", "slm")] and by["تحية"].folder == "رسائل"
    assert by["تحية"].versions == [("English", "Peace be upon you")]
    assert by["Bold one"].text == "Hello world"
    assert by["Braces"].text == "use {x} and {#date}"


def test_docx_is_valid_and_arabic_is_bidi(store, tmp_path):
    out = tmp_path / "p.docx"
    assert documents.export(store, store.phrases(), out, "ar") == 3
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        assert {"[Content_Types].xml", "word/document.xml", "word/styles.xml", "_rels/.rels"} <= names
        root = ET.fromstring(z.read("word/document.xml"))
    paras = root.iter(W + "p")
    texts = {}
    for p in paras:
        t = "".join(x.text or "" for x in p.iter(W + "t"))
        texts[t] = p
    arabic = texts["السلام عليكمورحمة الله"]            # two lines joined by <w:br/>
    assert arabic.find(f"{W}pPr/{W}bidi") is not None and arabic.find(f".//{W}rtl") is not None
    english = texts["Peace be upon you"]
    assert english.find(f"{W}pPr/{W}bidi") is None
    assert "الاختصار: slm" in texts                      # Arabic labels in the Arabic interface
    assert root.find(f".//{W}sectPr/{W}bidi") is not None


def test_docx_opens_with_python_docx_when_available(store, tmp_path):
    docx = pytest.importorskip("docx")
    out = tmp_path / "p.docx"
    documents.export(store, store.phrases(), out, "en")
    d = docx.Document(str(out))
    texts = [p.text for p in d.paragraphs]
    assert "تحية" in texts and "Autotext: slm" in texts and "Hotkey: ctrl+alt+1" in texts


def test_pdf_written_with_rtl_blocks(store, tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QTextDocument
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    out = tmp_path / "p.pdf"
    assert documents.export(store, store.phrases(), out, "ar") == 3
    data = out.read_bytes()
    assert data.startswith(b"%PDF") and len(data) > 1000
    doc = QTextDocument()
    doc.setHtml(documents.to_html(documents.collect(store, store.phrases()), "ar"))
    dirs = {}
    b = doc.begin()
    while b.isValid():
        dirs[b.text()] = b.textDirection()
        b = b.next()
    assert dirs["تحية"] == Qt.RightToLeft
    assert dirs["Peace be upon you"] == Qt.LeftToRight


def test_unknown_extension(store, tmp_path):
    with pytest.raises(ValueError):
        documents.export(store, store.phrases(), tmp_path / "x.rtf")


def test_main_window_export_document(store, tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from phraseforge.ui.main_window import MainWindow
    mw = MainWindow(store)
    assert mw.export_document("docx", str(tmp_path / "a.docx"), show_message=False) == 3
    assert mw.export_document("pdf", str(tmp_path / "a.pdf"), show_message=False) == 3
    assert (tmp_path / "a.pdf").read_bytes().startswith(b"%PDF")
    mw.close()
