"""AutoHotkey hotstring import (G-16)."""
from phraseforge.db import Store
from phraseforge.importers import autohotkey as ahk
from phraseforge.models import AutotextMode

SCRIPT = r"""
#Requires AutoHotkey v2.0
; a comment
::btw::by the way   ; trailing comment
:*:]d::today
:?C:ing::ING
:O:sig1::Line one`nLine two
:R:raw1::{Enter} stays ^+
::keys::Hello{Enter}World{Tab}x{{}y{}}{Left}
:X:run1::MsgBox("hi")
::code1::
Send "x"
return
::fn1::{
    MsgBox "x"
}
/*
::hidden::not imported
*/
::sig::
(
Best regards,
    John
)
^j::Send "not a hotstring"
"""


def test_parse():
    hs, skipped = ahk.parse(SCRIPT)
    got = {h.abbr: h for h in hs}
    assert set(got) == {"btw", "]d", "ing", "sig1", "raw1", "keys", "sig"}
    assert got["btw"].text == "by the way"
    assert got["sig1"].text == "Line one\nLine two"
    assert got["sig"].text == "Best regards,\n    John"
    assert skipped == 3                      # X, code after ::code1::, the v2 function body


def test_convert_keys():
    hs = {h.abbr: h for h in ahk.parse(SCRIPT)[0]}
    unknown = {}
    assert ahk.convert(hs["keys"], unknown) == "Hello\nWorld\tx{y}{Left}"
    assert unknown == {"{Left}": 1}
    assert ahk.convert(hs["raw1"], {}) == "{Enter} stays ^+"


def test_triggers():
    hs = {h.abbr: h for h in ahk.parse(SCRIPT)[0]}
    t = ahk.trigger_for(hs["]d"])
    assert t.mode == AutotextMode.IMMEDIATE and t.word_start_only
    t = ahk.trigger_for(hs["ing"])
    assert t.case_sensitive and not t.word_start_only and t.word_pos == "middle"
    assert ahk.trigger_for(hs["sig1"]).remove_trailing
    assert ahk.trigger_for(hs["btw"]).mode == AutotextMode.DELIMITER


def test_import_file(tmp_path):
    p = tmp_path / "hot.ahk"
    p.write_text(SCRIPT, encoding="utf-8")
    st = Store(tmp_path / "x.db")
    rep = ahk.import_ahk(st, p)
    assert rep.imported == 7 and rep.skipped == 3
    assert rep.folder_id is not None
    st.close()


def test_ansi_and_utf16(tmp_path):
    for enc, data in (("cp1252", "::cafe::café".encode("cp1252")), ("utf-16", "::cafe::café".encode("utf-16"))):
        p = tmp_path / f"{enc}.ahk"
        p.write_bytes(data)
        assert ahk.parse(p.read_bytes().decode(enc))[0][0].text == "café"
        st = Store(":memory:")
        assert ahk.import_ahk(st, p).imported == 1
        st.close()


def test_escapes():
    assert ahk.unescape("a`tb``c`;d") == "a\tb`c;d"
    assert ahk.strip_comment("text `; kept ; dropped") == "text `; kept"
