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
    assert "CSV" in str(e.value)
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
