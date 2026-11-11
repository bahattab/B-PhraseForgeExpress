"""PhraseExpress / TextExpander / macOS exchange formats (synthetic data only)."""
import csv
import os
import plistlib

import pytest

from phraseforge import io_formats
from phraseforge.db import Store
from phraseforge.importers import phraseexpress as pe
from phraseforge.models import Folder, Phrase, Trigger, TriggerKind


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def test_encrypted_database_is_detected(tmp_path, store):
    f = tmp_path / "sample.pexdb"
    f.write_bytes(os.urandom(8192))
    assert pe.looks_encrypted(f)
    with pytest.raises(pe.EncryptedPhraseFile) as e:
        pe.import_any(store, f)
    assert "Export > text file" in str(e.value)
    with pytest.raises(pe.EncryptedPhraseFile):
        io_formats.import_file(store, f)
    plain = tmp_path / "plain.bin"
    plain.write_bytes(b"SQLite format 3\x00" + b"\x00" * 4000)
    assert not pe.looks_encrypted(plain)


def test_import_csv_header_aliases_semicolon_and_arabic(tmp_path, store):
    f = tmp_path / "export.csv"
    f.write_text("Phrase description;Phrase content;Autotext;Folder\n"
                 "Greeting;مرحبًا بك;mrh;Letters/Arabic\n"
                 "Sign;Kind regards;kr|kreg;Letters\n"
                 ";;;\n", encoding="utf-8-sig")
    rep = pe.import_any(store, f)
    assert rep.imported == 2
    by = {p.description: p for p in store.phrases()}
    assert by["Greeting"].content == "مرحبًا بك"
    assert [t.value for t in by["Sign"].triggers] == ["kr", "kreg"]
    assert io_formats.folder_path(store, by["Greeting"].folder_id) == "export/Letters/Arabic"


def test_import_csv_without_header_uses_default_order(tmp_path, store):
    f = tmp_path / "noheader.csv"
    f.write_text("Alpha,first text,al\n", encoding="utf-8")
    rep = pe.import_csv(store, f)
    p = store.phrases()[0]
    assert rep.imported == 1 and p.description == "Alpha" and p.content == "first text"
    assert p.triggers[0].kind == TriggerKind.AUTOTEXT and p.triggers[0].value == "al"


def _sample(store):
    top = store.add_folder(Folder("Top"))
    sub = store.add_folder(Folder("Sub", parent_id=top.id))
    store.add_phrase(Phrase("One", "Hi {#clipboard} 50% {{x}{#cursor}", folder_id=sub.id,
                            triggers=[Trigger(TriggerKind.AUTOTEXT, "one"), Trigger(TriggerKind.HOTKEY, "ctrl+alt+1")]))
    store.add_phrase(Phrase("Two", "نص عربي {#ask \"x\"}", folder_id=top.id,
                            triggers=[Trigger(TriggerKind.AUTOTEXT, "two")]))
    store.add_phrase(Phrase("Three", "no trigger", folder_id=top.id))
    return top


def test_phraseexpress_csv_round_trip(tmp_path, store, tmp_path_factory):
    _sample(store)
    out = tmp_path / "pe.csv"
    rep = pe.export_phraseexpress_csv(store, out)
    assert rep.exported == 3
    rows = list(csv.reader(open(out, encoding="utf-8-sig")))
    assert rows[0] == pe.PE_HEADER
    s2 = Store(tmp_path_factory.mktemp("b") / "b.db")
    try:
        assert pe.import_csv(s2, out).imported == 3
        by = {p.description: p for p in s2.phrases()}
        assert by["Two"].content == "نص عربي {#ask \"x\"}"
        assert {t.kind for t in by["One"].triggers} == {TriggerKind.AUTOTEXT, TriggerKind.HOTKEY}
        assert io_formats.folder_path(s2, by["One"].folder_id).endswith("Top/Sub")
    finally:
        s2.close()


def test_textexpander_csv_export_converts_macros(tmp_path, store):
    _sample(store)
    out = tmp_path / "te.csv"
    rep = pe.export_textexpander_csv(store, out)
    rows = {r[0]: r for r in csv.reader(open(out, encoding="utf-8"))}
    assert rep.exported == 2 and rep.skipped == 1
    assert rows["one"][1] == "Hi %clipboard 50%% {x}%|"
    assert rows["one"][2] == "One"
    assert rep.kept_as_text == {"ask": 1}
    # and TextExpander's own importer reads it back to the same macros
    from phraseforge.importers.textexpander import import_csv
    s = import_csv(store, out)
    assert s.imported == 2


def test_macos_plist_export_and_folder_filter(tmp_path, store):
    top = _sample(store)
    out = tmp_path / "Text Substitutions.plist"
    rep = pe.export_macos_plist(store, out, folder_id=top.id)
    data = plistlib.load(open(out, "rb"))
    assert rep.exported == 2
    assert {d["shortcut"] for d in data} == {"one", "two"}
    assert all(set(d) == {"phrase", "shortcut"} for d in data)


def test_export_uses_language_version(tmp_path, store):
    p = store.add_phrase(Phrase("Hello", "Hello", triggers=[Trigger(TriggerKind.AUTOTEXT, "hl")]))
    store.set_phrase_version(p.id, "ar", "مرحبا", "text")
    out = tmp_path / "ar.csv"
    pe.export_any(store, out, "phraseexpress", language="ar")
    rows = list(csv.reader(open(out, encoding="utf-8-sig")))
    assert rows[1][1] == "مرحبا"


def _tree(store):
    top = store.add_folder(Folder("Work"))
    sub = store.add_folder(Folder("Mail", parent_id=top.id))
    store.add_folder(Folder("Empty", parent_id=top.id))
    store.add_phrase(Phrase("Greeting", "Hello {#clipboard}", folder_id=sub.id,
                            triggers=[Trigger(TriggerKind.AUTOTEXT, "hi"), Trigger(TriggerKind.AUTOTEXT, "hey"),
                                      Trigger(TriggerKind.HOTKEY, "Ctrl+Alt+G")]))
    store.add_phrase(Phrase("Formula", "=1+1\x01 <b>&</b>", folder_id=top.id, content_format="html"))
    store.add_phrase(Phrase("عربي", "مرحبا بالعالم"))
    return top


def _snapshot(store, root_id):
    """{(folder path below root, description): (content, format, autotexts, hotkey)}"""
    from phraseforge.io_formats import folder_path
    base = folder_path(store, root_id)
    out = {}
    for p in pe._phrases(store, root_id):
        rel = folder_path(store, p.folder_id)[len(base):].strip("/")
        out[(rel, p.description)] = (p.content, p.content_format, pe._autotexts(p), pe._trigger(p, TriggerKind.HOTKEY))
    return out


EXPECTED = {("Work/Mail", "Greeting"): ("Hello {#clipboard}", "text", "hi|hey", "Ctrl+Alt+G"),
            ("Work", "Formula"): ("=1+1 <b>&</b>", "html", "", ""),
            ("", "عربي"): ("مرحبا بالعالم", "text", "", "")}


def test_xml_export_round_trip(tmp_path, store):
    _tree(store)
    out = tmp_path / "phrases.xml"
    rep = pe.export_any(store, out, "xml")
    assert rep.exported == 3
    text = out.read_text(encoding="utf-8")
    assert "Empty" not in text and "\x01" not in text
    back = pe.import_any(store, out)
    assert back.imported == 3
    assert _snapshot(store, back.folder_id) == EXPECTED


def test_xml_export_of_one_folder(tmp_path, store):
    top = _tree(store)
    out = tmp_path / "work.xml"
    assert pe.export_xml(store, out, folder_id=top.id).exported == 2
    assert "مرحبا" not in out.read_text(encoding="utf-8")


def test_xlsx_export_round_trip_and_no_formula(tmp_path, store):
    from openpyxl import load_workbook
    _tree(store)
    out = tmp_path / "phrases.xlsx"
    rep = pe.export_any(store, out, "xlsx")
    assert rep.exported == 3
    ws = load_workbook(out).active
    assert [c.value for c in ws[1]] == pe.PE_HEADER + ["Format"]
    cell = next(r[1] for r in ws.iter_rows(min_row=2) if r[0].value == "Formula")
    assert cell.data_type == "s" and cell.value == "=1+1 <b>&</b>"        # text, not a formula
    back = pe.import_any(store, out)
    assert back.imported == 3
    assert _snapshot(store, back.folder_id) == EXPECTED


def test_xlsx_export_cuts_very_long_text(tmp_path, store):
    store.add_phrase(Phrase("Long", "x" * (pe.XLSX_CELL_MAX + 10)))
    rep = pe.export_xlsx(store, tmp_path / "l.xlsx")
    assert rep.exported == 1 and "cut" in rep.notes[0]
