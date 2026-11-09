"""Rest of G-11 (contents, dictionary, parse, decstr, checktext, headfootfilled) and G-30
(convertlayout, speak): FR-MAC-02/03/05, golden outputs."""
import random
from datetime import datetime

import pytest

from phraseforge.db import Store
from phraseforge.host import ExpansionContext
from phraseforge.macros import MacroEngine, catalog, commands_pe, layouts
from phraseforge.models import Folder, Phrase
from tests.fakehost import FakeHost


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


@pytest.fixture
def eng(store):
    return MacroEngine(FakeHost(), store=store, clock=lambda: datetime(2026, 11, 9, 9, 0), rng=random.Random(1))


def T(eng, s, **ctx):
    return eng.expand_to_text(s, ExpansionContext(**ctx))


def test_in_catalog():
    names = {m.name for m in catalog()}
    for n in ("contents", "dictionary", "parse", "decstr", "checktext", "headfootfilled", "convertlayout", "speak"):
        assert n in names, n


def test_contents_does_not_run_macros(eng, store):
    store.add_phrase(Phrase("Tpl", "Hi {#date -format yyyy}"))
    assert T(eng, '{#contents "Tpl"}') == "Hi {#date -format yyyy}"
    assert T(eng, '{#insert "Tpl"}') == "Hi 2026"
    assert "not found" in T(eng, '{#contents "Nope"}')


def test_dictionary(eng, store):
    store.add_phrase(Phrase("Dict", "cat=قطة\ndog\tكلب\nHouse = بيت\nbad line"))
    assert T(eng, '{#dictionary cat -from Dict}') == "قطة"
    assert T(eng, '{#dictionary DOG -from Dict}') == "كلب"
    assert T(eng, '{#dictionary house -from Dict}') == "بيت"
    assert T(eng, '{#dictionary fish -from Dict -default ?}') == "?"
    assert T(eng, '{#dictionary fish -from Dict -keep}') == "fish"
    assert "-from" in T(eng, "{#dictionary cat}")


@pytest.mark.parametrize("src,out", [
    ('{#parse "Order: [1234]" -start "[" -end "]"}', "1234"),
    ('{#parse "<a><b><c>" -start "<" -end ">" -index 2}', "b"),
    ('{#parse "<a><b><c>" -start "<" -end ">" -index -1}', "c"),
    ('{#parse "<a><b><c>" -start "<" -end ">" -all -join ","}', "a,b,c"),
    ('{#parse "<a><b><c>" -start "<" -end ">" -count}', "3"),
    ('{#parse "<a><b>" -start "<" -end ">" -index 5}', ""),
    ('{#parse "key: value" -start ": "}', "value"),
    ('{#parse "name@example.com" -end "@"}', "name"),
])
def test_parse(eng, src, out):
    assert T(eng, src) == out


@pytest.mark.parametrize("src,out", [
    ('{#decstr "INV-0010"}', "INV-0009"),
    ('{#decstr "Room 12b"}', "Room 11b"),
    ('{#decstr "v100" -by 25}', "v075"),
    ('{#decstr "0"}', "0"),
    ('{#decstr "no number"}', "no number"),
])
def test_decstr(eng, src, out):
    assert T(eng, src) == out


@pytest.mark.parametrize("src,out", [
    ('{#checktext "Hello world" -contains world}', "1"),
    ('{#checktext "Hello world" -contains WORLD}', "0"),
    ('{#checktext "Hello world" -contains WORLD -i}', "1"),
    ('{#checktext "Hello" -startswith He}', "1"),
    ('{#checktext "Hello" -endswith xx}', "0"),
    ('{#checktext "A-123" -regex "\\d{3}"}', "1"),
    ('{#checktext "  " -empty}', "1"),
    ('{#if {#checktext "abc" -contains b} == 1}yes{#else}no{#endif}', "yes"),
])
def test_checktext(eng, src, out):
    assert T(eng, src) == out


def test_headfootfilled(eng, store):
    f = store.add_folder(Folder("Mail", text_before="Dear,\n"))
    p = store.add_phrase(Phrase("A", "x", folder_id=f.id))
    q = store.add_phrase(Phrase("B", "x"))
    assert T(eng, "{#headfootfilled}", phrase_id=p.id) == "1"
    assert T(eng, "{#headfootfilled}", phrase_id=q.id) == "0"
    assert T(eng, "{#headfootfilled}") == "0"


@pytest.mark.parametrize("text,src,dst,out", [
    ("hgsghl ugd;l", "en", "ar", "السلام عليكم"),
    ("السلام عليكم", "ar", "en", "hgsghl ugd;l"),
    ("Ghbdtn", "en", "ru", "Привет"),
    ("Руддщ", "ru", "en", "Hello"),
    ("Qwertz", "de", "en", "Qwerty"),
    ("azerty", "fr", "en", "qwerty"),
    ("123 !", "en", "ar", "123 !"),
])
def test_convertlayout_tables(text, src, dst, out):
    assert layouts.convert(text, src, dst) == out


def test_layout_tables_cover_every_key():
    for name, (plain, shifted) in layouts.LAYOUTS.items():
        assert len(plain) == len(shifted) == 47, name


def test_convertlayout_macro(eng):
    assert T(eng, "{#convertlayout hgsghl -from en -to arabic}") == "السلام"
    assert "unknown layout" in T(eng, "{#convertlayout x -from xx -to en}")


def test_speak(eng, monkeypatch):
    said = []
    monkeypatch.setattr(commands_pe, "SPEAKER", lambda t, v, r: said.append((t, v, r)))
    assert T(eng, '{#speak "Done" -voice Zira -rate 3}') == ""
    assert said == [("Done", "Zira", 3)]
    assert "-rate" in T(eng, '{#speak "x" -rate fast}')
