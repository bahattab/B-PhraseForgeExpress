"""PhraseExpress macros added for G-11 (FR-MAC-02/03, FR-AI-05) and form fields for G-12
(FR-MAC-04): required/validated fields, {#formgroup}, {#formcheckcombo}."""
import os
import random
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from phraseforge.formcheck import field_error, rule_error
from phraseforge.host import ExpansionContext, FormField
from phraseforge.macros import MacroEngine, catalog
from phraseforge.macros import commands_pe
from tests.fakehost import FakeHost

NOW = datetime(2026, 11, 4, 9, 0, 0)


@pytest.fixture
def host():
    return FakeHost()


@pytest.fixture
def eng(host):
    return MacroEngine(host, clock=lambda: NOW, rng=random.Random(1))


def T(eng, s, **ctx):
    return eng.expand_to_text(s, ExpansionContext(**ctx))


def test_new_macros_are_in_the_catalog():
    names = {m.name for m in catalog()}
    for n in ("explode", "numlist", "settemp", "gettemp", "autocase", "lastchars", "textempty", "prefix",
              "postfix", "regexpos", "regexcount", "setlevel", "langdetect", "mousex", "mousey",
              "mouseposition", "sound", "formcheckcombo", "formgroup", "formgroupend"):
        assert n in names, n


# ------------------------------------------------------------------ explode
def test_explode_index(eng):
    assert T(eng, '{#explode "a,b,c" -index 2}') == "b"
    assert T(eng, '{#explode "a,b,c" -index -1}') == "c"
    assert T(eng, '{#explode "a,b,c" -index 9}') == ""
    assert T(eng, '{#explode "a;b" -sep ";" -index 1}') == "a"


def test_explode_join_count_trim(eng):
    assert T(eng, '{#explode "a, b ,c" -trim -join "|"}') == "a|b|c"
    assert T(eng, '{#explode "a,b,c"}') == "a\nb\nc"
    assert T(eng, '{#explode "a,,b" -noempty -count}') == "2"


# ------------------------------------------------------------------ numlist
def test_numlist_styles(eng):
    assert T(eng, '{#numlist "x|y|z" -sep "|"}') == "1. x\n2. y\n3. z"
    assert T(eng, '{#numlist "x|y" -sep "|" -style ALPHA -suffix ") "}') == "A) x\nB) y"
    assert T(eng, '{#numlist "x|y" -sep "|" -style roman -start 4}') == "iv. x\nv. y"
    assert T(eng, '{#numlist "x|y" -sep "|" -style bullet -level 2}') == "  • x\n  • y"
    assert T(eng, '{#numlist "x" -sep "|" -style arabic -start 12}') == "١٢. x"


def test_numlist_bad_style(eng):
    assert "unknown list style" in T(eng, '{#numlist "x" -style weird}')


def test_roman_and_alpha_helpers():
    assert commands_pe._roman(1994) == "mcmxciv"
    assert commands_pe._alpha(27) == "aa"


# ------------------------------------------------------------------ small text helpers
def test_autocase_follows_the_typed_abbreviation(eng):
    assert T(eng, "{#autocase hello world}", typed_abbreviation="HW") == "HELLO WORLD"
    assert T(eng, "{#autocase hello world}", typed_abbreviation="Hw") == "Hello world"
    assert T(eng, "{#autocase hello world}", typed_abbreviation="hw") == "hello world"


def test_lastchars_textempty_prefix_postfix(eng):
    assert T(eng, '{#lastchars "abcdef" -count 3}') == "def"
    assert T(eng, '{#textempty "  "}') == "1" and T(eng, '{#textempty "x"}') == "0"
    assert T(eng, '{#prefix "Dear " "Sam"}') == "Dear Sam"
    assert T(eng, '{#prefix "Dear " ""}') == ""
    assert T(eng, '{#postfix "," "Sam"}') == "Sam,"
    assert T(eng, '{#postfix "," ""}') == ""


def test_regexpos_and_regexcount(eng):
    assert T(eng, '{#regexpos "abc123" "\\d"}') == "4"
    assert T(eng, '{#regexpos "abc" "\\d"}') == "0"
    assert T(eng, '{#regexcount "a1b22c333" "\\d+"}') == "3"
    assert T(eng, '{#regexcount "AaA" "a" -i}') == "3"
    assert "bad pattern" in T(eng, '{#regexcount "x" "("}')


# ------------------------------------------------------------------ temporary variables
def test_temp_vars_survive_between_expansions_but_not_in_the_db(eng, host):
    commands_pe.TEMP_VARS.clear()
    T(eng, "{#settemp ticket 4711}")
    assert T(eng, "{#gettemp ticket}") == "4711"           # a later expansion
    assert T(eng, "{#gettemp missing -default none}") == "none"
    assert not host.vars                                     # never stored as a variable
    commands_pe.TEMP_VARS.clear()


# ------------------------------------------------------------------ setlevel
def test_setlevel_picks_the_language_version_for_insert():
    from phraseforge.db import Store
    from phraseforge.models import Phrase
    s = Store(":memory:")
    pid = s.add_phrase(Phrase("Greeting", "Hello")).id
    s.set_phrase_version(pid, "de", "Hallo")
    e = MacroEngine(FakeHost(), store=s)
    assert e.expand_to_text('{#insert "Greeting"}') == "Hello"
    assert e.expand_to_text('{#setlevel de}{#insert "Greeting"}') == "Hallo"
    assert e.expand_to_text('{#setlevel de}{#setlevel default}{#insert "Greeting"}') == "Hello"
    assert e.expand_to_text('{#setlevel fr}{#insert "Greeting"}') == "Hello"   # no such version


# ------------------------------------------------------------------ langdetect
@pytest.mark.parametrize("text,code", [
    ("مرحبا بك في البرنامج", "ar"),
    ("The quick fox and the dog are in the garden", "en"),
    ("Der Hund und die Katze sind nicht im Haus", "de"),
    ("Le chat est dans la maison avec les enfants", "fr"),
    ("El perro y la casa de los niños", "es"),
    ("Привет, как дела?", "ru"),
    ("שלום עולם", "he"),
    ("这是一个测试", "zh"),
    ("これはテストです", "ja"),
    ("안녕하세요", "ko"),
])
def test_langdetect(eng, text, code):
    assert T(eng, f'{{#langdetect "{text}"}}') == code


def test_langdetect_no_letters(eng):
    assert T(eng, '{#langdetect "123 !!"}') == ""


# ------------------------------------------------------------------ mouse / sound
def test_mouse_position(eng, monkeypatch):
    monkeypatch.setattr(commands_pe, "cursor_pos", lambda: (120, 45))
    assert T(eng, "{#mousex}/{#mousey}") == "120/45"
    assert T(eng, '{#mouseposition -sep ";"}') == "120;45"
    monkeypatch.setattr(commands_pe, "cursor_pos", lambda: None)
    assert T(eng, "{#mousex}") == ""


def test_sound_outputs_nothing(eng, monkeypatch):
    import sys
    calls = []
    if sys.platform == "win32":
        import winsound
        monkeypatch.setattr(winsound, "MessageBeep", lambda t: calls.append(t))
    assert T(eng, "a{#sound beep}b") == "ab"
    if sys.platform == "win32":
        assert calls == [commands_pe.SOUNDS["beep"]]
        assert "needs a .wav" in T(eng, '{#sound "x.mp3"}')


# ------------------------------------------------------------------ form validation rules
def test_rule_error():
    assert rule_error("a@b.co", "email") == ""
    assert rule_error("nope", "email")
    assert rule_error("", "email") == ""                     # empty passes; -required decides
    assert rule_error("12", "numbers") == "" and rule_error("x", "numbers")
    assert rule_error("AB-1", r"regex:[A-Z]{2}-\d") == ""
    assert rule_error("ab-1", r"regex:[A-Z]{2}-\d")
    assert rule_error("x", "regex:(") .startswith("a valid pattern")
    assert rule_error("anything at all", "anything") == ""
    assert rule_error("x", "nosuchrule") == ""


def test_rule_filepath_and_folder(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    assert rule_error(str(f), "filepath") == "" and rule_error(str(tmp_path), "filepath")
    assert rule_error(str(tmp_path), "folder") == "" and rule_error(str(f), "folder")


def test_field_error_required():
    f = FormField("edit", "name", label="Name", required=True)
    assert field_error(f, "") == "Name: required"
    assert field_error(f, "Sam") == ""
    assert field_error(FormField("checkcombo", "c", required=True), []) == "c: required"
    assert field_error(FormField("edit", "m", label="Mail", validate="email"), "x") == \
        "Mail: please enter an e-mail address"


# ------------------------------------------------------------------ forms in the engine
def test_form_fields_carry_required_validate_and_group(eng, host):
    T(eng, '{#form}{#formedit a -required}{#formgroup g -label "More"}{#formedit b -validate email}'
           '{#formgroupend}{#formedit c}{#endform}')
    fields = host.called("show_form")[0][1]
    by = {f.name: f for f in fields}
    assert by["a"].required and by["b"].validate == "email"
    assert by["b"].group == "g" and by["c"].group == "" and by["a"].group == ""
    assert [f.kind for f in fields] == ["edit", "group", "edit", "groupend", "edit"]


def test_closed_group_outputs_nothing(eng, host):
    host.queue("show_form", {"g": False, "b": "inside", "c": "outside"})
    out = T(eng, '{#form}{#formgroup g -label "More"}{#formedit b}{#formgroupend}{#formedit c}{#endform}'
                 '[{#formvalue b}][{#formvalue c}][{#formvalue g}]')
    assert out == "[][outside][]"


def test_open_group_outputs_its_fields(eng, host):
    host.queue("show_form", {"g": True, "b": "inside"})
    out = T(eng, '{#form}{#formgroup g -on yes}{#formedit b}{#formgroupend}{#endform}'
                 '[{#formvalue b}][{#formvalue g}]')
    assert out == "[inside][yes]"


def test_group_starts_closed_with_unchecked_and_fixed_never_hides(eng, host):
    T(eng, '{#form}{#formgroup g -unchecked}{#formgroupend}{#formgroup h -fixed}{#formedit x}'
           '{#formgroupend}{#endform}')
    fields = {f.name: f for f in host.called("show_form")[0][1]}
    assert fields["g"].default is False
    assert fields["h"].checkable is False
    host.queue("show_form", {"h": False, "x": "kept"})
    assert T(eng, '{#form}{#formgroup h -fixed}{#formedit x}{#formgroupend}{#endform}{#formvalue x}') == "kept"


def test_checkcombo_in_form_and_alone(eng, host):
    host.queue("show_form", {"c": ["a", "c"]})
    assert T(eng, '{#form}{#formcheckcombo c -options "a,b,c"}{#endform}{#formvalue c}') == "a, c"
    host.queue("show_form", {"c": ["b"]})
    assert T(eng, '{#formcheckcombo c -options "a|b" -sep "|" -join " + "}') == "b"
    T(eng, '{#formcheckcombo d -options "x,y,z" -checked "x,z"}')
    assert host.called("show_form")[-1][1][0].default == ["x", "z"]


# ------------------------------------------------------------------ the form dialog
@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _ok(dlg):
    from PySide6.QtWidgets import QDialogButtonBox
    return dlg.buttons.button(QDialogButtonBox.Ok)


def test_dialog_ok_disabled_until_valid(app):
    from phraseforge.ui.dialogs import FormDialog
    dlg = FormDialog("t", [FormField("edit", "name", label="Name", required=True),
                           FormField("edit", "mail", label="Mail", validate="email")])
    try:
        assert not _ok(dlg).isEnabled() and dlg.error.text() == "Name: required"
        dlg.widgets["name"].setText("Sam")
        assert _ok(dlg).isEnabled() and not dlg.error.isVisibleTo(dlg)
        dlg.widgets["mail"].setText("bad")
        assert not _ok(dlg).isEnabled() and "e-mail" in dlg.error.text()
        dlg.accept()                                  # Enter must not slip past the check
        assert dlg.result() != dlg.DialogCode.Accepted
        dlg.widgets["mail"].setText("sam@example.com")
        assert _ok(dlg).isEnabled()
    finally:
        dlg.deleteLater()


def test_dialog_group_hides_fields_and_skips_their_checks(app):
    from phraseforge.ui.dialogs import FormDialog
    fields = [FormField("group", "g", label="Details", default=True),
              FormField("edit", "x", required=True, group="g"),
              FormField("groupend", "e")]
    dlg = FormDialog("t", fields)
    try:
        box = dlg.widgets["g"]
        assert box.isCheckable() and box.isChecked()
        assert not _ok(dlg).isEnabled()
        box.setChecked(False)
        assert _ok(dlg).isEnabled()                   # hidden required field no longer blocks
        assert dlg.values()["g"] is False
    finally:
        dlg.deleteLater()


def test_dialog_checkcombo(app):
    from phraseforge.ui.dialogs import CheckCombo, FormDialog
    dlg = FormDialog("t", [FormField("checkcombo", "c", options=["a", "b", "c"], default=["b"], required=True)])
    try:
        w = dlg.widgets["c"]
        assert isinstance(w, CheckCombo)
        assert dlg.values()["c"] == ["b"] and w.lineEdit().text() == "b"
        w._toggle(w.model().index(0, 0))
        assert dlg.values()["c"] == ["a", "b"] and w.lineEdit().text() == "a, b"
        w.set_checked([])
        assert not _ok(dlg).isEnabled()
    finally:
        dlg.deleteLater()
