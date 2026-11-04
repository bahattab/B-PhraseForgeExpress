"""Sticky Notes reader/import/macro against a fake plum.sqlite (never the user's file)."""
import sqlite3
from datetime import datetime

from phraseforge import stickynotes as sn
from phraseforge.db import Store
from phraseforge.importers.stickynotes import import_notes

TICKS_2026 = int((datetime(2026, 10, 22) - datetime(1, 1, 1)).total_seconds() * 10_000_000)


def make_db(path, rows):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE Note (Text, Theme, Id, CreatedAt, UpdatedAt, DeletedAt)")
    con.executemany("INSERT INTO Note VALUES (?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


def sample(tmp_path):
    p = tmp_path / "plum.sqlite"
    make_db(p, [
        ("\\id=aaaa-1 Shopping list\n\\id=aaaa-2 milk, eggs", "Yellow", "n1", TICKS_2026, TICKS_2026, None),
        ("\\id=bbbb-1 Paths\n\\id=bbbb-2 \"C:\\Users\\b\\docs\"", "Blue", "n2", TICKS_2026, TICKS_2026 + 10_000_000, None),
        ("\\id=cccc-1 deleted note", "", "n3", TICKS_2026, TICKS_2026, TICKS_2026),
        ("\\id=dddd-1 ", "", "n4", TICKS_2026, TICKS_2026, None),       # empty
    ])
    return p


def test_read_notes_parses_and_filters(tmp_path):
    notes = sn.read_notes(sample(tmp_path), use_cache=False)
    assert [n.title for n in notes] == ["Paths", "Shopping list"]           # newest first, no deleted/empty
    assert notes[1].text == "Shopping list\nmilk, eggs"
    assert notes[0].text.endswith('"C:\\Users\\b\\docs"')                   # real backslashes kept
    assert notes[0].updated.year == 2026


def test_original_file_is_untouched(tmp_path):
    p = sample(tmp_path)
    before = p.read_bytes()
    sn.read_notes(p, use_cache=False)
    assert p.read_bytes() == before


def test_find(tmp_path):
    notes = sn.read_notes(sample(tmp_path), use_cache=False)
    assert sn.find(notes, "shopping list").id == "n1"
    assert sn.find(notes, "eggs").id == "n1"
    assert sn.find(notes, "nothing here") is None


def test_missing_file_returns_empty(tmp_path):
    assert sn.read_notes(tmp_path / "nope.sqlite") == []


def test_import_notes(tmp_path):
    store = Store(tmp_path / "s.db")
    notes = sn.read_notes(sample(tmp_path), use_cache=False)
    rep = import_notes(store, notes)
    assert rep.imported == 2
    ph = {p.description: p for p in store.phrases(rep.folder_id)}
    assert ph["Shopping list"].content == "Shopping list\nmilk, eggs"
    assert "sticky-notes" in ph["Paths"].tags


def test_stickynote_macro():
    from phraseforge.host import ExpansionContext
    from phraseforge.macros import MacroEngine
    from tests.fakehost import FakeHost
    store = Store(":memory:")
    store.add_sticky_note("Shopping list\nmilk, eggs")
    store.add_sticky_note("Paths\nC:\\docs")
    eng = MacroEngine(FakeHost(), store)
    assert eng.expand_to_text('{#stickynote "eggs"}', ExpansionContext()) == "Shopping list\nmilk, eggs"
    out = eng.expand_to_text('{#stickynote -all -sep "|"}', ExpansionContext())
    assert set(out.split("|")) == {"Shopping list\nmilk, eggs", "Paths\nC:\\docs"}
