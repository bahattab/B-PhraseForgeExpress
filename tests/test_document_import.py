"""Import Word, RTF, Excel and image files as phrases (PhraseExpress's four file-import
options: copy, link, open, line by line), and the readers behind {#document}."""
import struct
import zipfile
import zlib

import pytest

from phraseforge import io_formats
from phraseforge.db import Store
from phraseforge.importers import files
from phraseforge.models import Folder, TriggerKind
from tests.test_macros_extra import run

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("PHRASEFORGE_HOME", str(tmp_path / "data"))
    return tmp_path


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def make_docx(path, paragraphs, extra=""):
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = f'<?xml version="1.0"?>{extra}<w:document {W}><w:body>{body}' \
          '<w:p><w:r><w:t>A</w:t><w:tab/><w:t>B</w:t><w:br/><w:t>C</w:t></w:r></w:p></w:body></w:document>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)
    return path


def make_png(path):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    raw = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b"")
    path.write_bytes(raw)
    return path


def make_xlsx(path, sheets):
    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    wb.save(path)
    return path


# ---------------------------------------------------------------- readers
def test_docx_paragraphs_keep_tabs_and_breaks(tmp_path):
    p = make_docx(tmp_path / "a.docx", ["Dear customer", "مرحبا بكم"])
    assert files.docx_paragraphs(p) == ["Dear customer", "مرحبا بكم", "A\tB\nC"]


def test_docx_with_a_dtd_is_refused(tmp_path):
    p = make_docx(tmp_path / "evil.docx", ["x"], extra='<!DOCTYPE d [<!ENTITY e SYSTEM "file:///etc/passwd">]>')
    with pytest.raises(ValueError, match="DTD"):
        files.docx_paragraphs(p)


def test_rtf_reader_handles_code_pages_unicode_and_destinations():
    english = r"{\rtf1\ansi\ansicpg1252{\fonttbl{\f0 Arial;}}{\colortbl;\red0\green0\blue0;}" \
              r"{\*\generator Riched20;}\f0 Hello \b world\b0\par Tab\tab here \{x\}\line End\par}"
    assert files.rtf_to_text(english) == "Hello world\nTab\there {x}\nEnd"
    # Arabic as Windows-1256 hex escapes (WordPad) and as \uN with a "?" fallback (Word)
    arabic_cp = r"{\rtf1\ansi\ansicpg1256{\fonttbl{\f0 Arial;}}\f0 \'e3\'d1\'cd\'c8\'c7\par}"
    assert files.rtf_to_text(arabic_cp) == "مرحبا"
    arabic_u = "{\\rtf1\\ansi\\uc1 \\u1605?\\u1585?\\u1581?\\u1576?\\u1575?\\par}"   # the form Word writes
    assert files.rtf_to_text(arabic_u) == "مرحبا"
    assert files.rtf_to_text("{\\rtf1\\uc2 \\u1605??x}") == "مx"


def test_document_macro_reads_arabic_rtf(tmp_path):
    p = tmp_path / "ar.rtf"
    p.write_bytes(rb"{\rtf1\ansi\ansicpg1256 \'e3\'d1\'cd\'c8\'c7 \'c8\'df\'e3\par}")
    assert run(f'{{#document "{p}"}}') == "مرحبا بكم"


def test_xlsx_rows_drop_empty_trailing_cells(tmp_path):
    p = make_xlsx(tmp_path / "t.xlsx", {"S": [["a", 1, None], [None, None], ["b", "c"]]})
    assert files.xlsx_rows(p) == [("S", [["a", "1"], ["b", "c"]])]


# ---------------------------------------------------------------- modes
def test_modes_per_file_type(tmp_path):
    assert files.modes_for("a.docx") == ("copy", "link", "open", "lines")
    assert files.modes_for("a.PNG") == ("copy", "link", "open")
    assert files.modes_for("a.xlsx") == ("lines", "copy", "open")
    with pytest.raises(ValueError):
        files.phrases_from_file(make_png(tmp_path / "x.png"), "lines")
    with pytest.raises(ValueError):
        files.phrases_from_file(tmp_path / "x.pdf")


def test_word_copy_link_open_and_lines(tmp_path):
    p = make_docx(tmp_path / "Letter.docx", ["Dear customer", "", "Kind regards"])
    [copy] = files.phrases_from_file(p, "copy")
    assert copy.description == "Letter" and copy.content == "Dear customer\n\nKind regards\nA\tB\nC"
    [link] = files.phrases_from_file(p, "link")
    assert link.content == '{#document "' + str(p) + '"}'
    [opened] = files.phrases_from_file(p, "open")
    assert opened.content == '{#open "' + str(p) + '"}'
    lines = files.phrases_from_file(p, "lines")
    assert [x.content for x in lines] == ["Dear customer", "Kind regards", "A\tB\nC"]
    assert lines[0].description == "Dear customer"
    assert run(link.content) == copy.content          # the link macro reads the same text


def test_image_copy_goes_to_assets_and_link_keeps_the_path(home):
    src = make_png(home / "Logo.png")
    [copy] = files.phrases_from_file(src, "copy")
    asset = files.assets_dir() / next(files.assets_dir().iterdir()).name
    assert copy.description == "Logo" and copy.content == '{#image "' + str(asset) + '"}'
    assert asset.read_bytes() == src.read_bytes()
    files.phrases_from_file(src, "copy")                # importing again reuses the copy
    assert len(list(files.assets_dir().iterdir())) == 1
    [link] = files.phrases_from_file(src, "link")
    assert link.content == '{#image "' + str(src) + '"}'


def test_excel_with_a_header_row_maps_columns(tmp_path):
    p = make_xlsx(tmp_path / "phrases.xlsx", {"Sheet1": [
        ["Description", "Content", "Autotext", "Hotkey", "Folder"],
        ["Greeting", "Hello!", "hi#|hey#", "ctrl+alt+h", "Mail/Openers"],
        ["تحية", "السلام عليكم", "سلام#", None, None],
        [None, None, None],
    ]})
    ph = files.phrases_from_file(p, "lines")
    assert [(x.description, x.content) for x in ph] == [("Greeting", "Hello!"), ("تحية", "السلام عليكم")]
    assert [(t.kind, t.value) for t in ph[0].triggers] == [
        (TriggerKind.AUTOTEXT, "hi#"), (TriggerKind.AUTOTEXT, "hey#"), (TriggerKind.HOTKEY, "ctrl+alt+h")]
    assert ph[0].folder_path == "Mail/Openers"


def test_excel_without_a_header_and_copy_per_sheet(tmp_path):
    p = make_xlsx(tmp_path / "list.xlsx", {"A": [["Thanks", "Thank you very much"], ["Only one cell"]],
                                            "B": [["x", "y", "z"]]})
    ph = files.phrases_from_file(p, "lines")
    assert [(x.description, x.content) for x in ph] == [
        ("Thanks", "Thank you very much"), ("Only one cell", "Only one cell"), ("x", "y\tz")]
    copies = files.phrases_from_file(p, "copy")
    assert [(x.description, x.content) for x in copies] == [
        ("list - A", "Thanks\tThank you very much\nOnly one cell"), ("list - B", "x\ty\tz")]


# ---------------------------------------------------------------- import into the store
def test_import_file_stores_phrases_in_folders_and_quarantines_them(tmp_path, store):
    target = store.add_folder(Folder("Imported"))
    p = make_xlsx(tmp_path / "phrases.xlsx", {"S": [["Description", "Content", "Folder"],
                                                     ["One", "{#run \"calc.exe\"}", "Sub"], ["Two", "b", ""]]})
    assert io_formats.import_file(store, p, target.id, mode="lines") == 2
    by_name = {x.description: x for x in store.phrases()}
    sub = store.get_folder(by_name["One"].folder_id)
    assert sub.name == "Sub" and sub.parent_id == target.id and by_name["Two"].folder_id == target.id
    assert {store.quarantine_origin(x.id) for x in by_name.values()} == {"imported"}
    doc = make_docx(tmp_path / "Note.docx", ["text"])
    assert io_formats.import_file(store, doc) == 1                 # default mode: copy
    assert any(x.description == "Note" for x in store.phrases())
