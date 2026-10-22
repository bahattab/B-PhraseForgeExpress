"""Macro menus and dialogs: every menu item yields macro text the engine accepts."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMenu

from phraseforge.macros import MacroEngine
from phraseforge.ui import macro_ui
from phraseforge.ui.macro_dialog_kit import MacroDialog, add_caption, q
from phraseforge.ui.macro_specs import SPECS
from tests.fakehost import FakeHost


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


SAMPLE = {
    "text": "Hello world", "header": "Name", "label": "Customer", "path": r"C:\temp\a.txt",
    "file": r"C:\temp\a.xlsx", "search": "x", "xpath": "./a", "query": "SELECT 1", "var": "PATH",
    "items": "a\nb", "male": "He", "female": "She", "neutral": "It", "title": "T", "url": "example.com",
    "name": "v1", "content": "c", "expr": "1+2", "regex": r"\d+", "source": "s", "sub": "l",
    "contents": "a", "cond": "a", "then": "yes", "else": "no", "elements": "x\ny", "lang": "ar-SA",
    "code": "65", "attr": "email", "values": "1\n2", "descriptions": "one\ntwo", "to": "a@b.c",
}


def _texts(menu: QMenu) -> list[str]:
    out = []
    for a in menu.actions():
        if a.isSeparator():
            out.append("-")
        elif a.menu():
            out.append(a.text() + " >")
        else:
            out.append(a.text())
    return out


def test_menu_items_match_reference(app):
    menus = macro_ui.macro_menus(None, lambda t: None)
    assert list(menus) == ["Date/Time", "User input", "External data", "Output", "Automation", "Programming",
                           "Text operations", "Clipboard"]
    assert _texts(menus["Date/Time"]) == ["Date/Time", "Date Calculation", "Time Calculation"]
    assert _texts(menus["User input"]) == ["Manual text input", "-", "Form input", "Form >", "-", "WYSIWYG form >",
                                           "-", "Document Generator", "File selection dialog", "File save dialog"]
    assert _texts(menus["Automation"]) == ["Create email", "Open web page", "-", "Run program", "Open file",
                                           "Open folder", "-", "Set application focus", "Macro loop"]
    assert _texts(menus["Programming"]) == ["Insert phrase", "Check text/value", "If-Then-Else", "Calculation",
                                            "Set phrase content", "Wait x milliseconds", "-", "Set variable",
                                            "Output variable"]
    assert _texts(menus["Clipboard"]) == ["Clipboard paste/copy", "-", "Insert text from clipboard",
                                          "Put text into clipboard"]
    tx = _texts(menus["Text operations"])
    assert tx[:3] == ["Text length", "Substring", "Extract substring with RegEx"] and len(tx) == 19
    out = _texts(menus["Output"])
    assert out[0] == "Keypress >" and out[-1] == "Set language" and len(out) == 12
    ext = _texts(menus["External data"])
    assert ext[0] == "Outlook email >" and ext[-1] == "ActiveDirectory value >"
    shortcut = next(a for a in menus["Date/Time"].actions() if a.text() == "Date/Time").shortcut().toString()
    assert shortcut == "Ctrl+D"


@pytest.mark.parametrize("kind", macro_ui.all_menu_kinds())
def test_every_dialog_builds_runnable_macro(app, kind):
    s = SPECS[kind]
    if s.direct:
        text = s.build({})
    else:
        d = MacroDialog(s)
        d.set_values({k: v for k, v in SAMPLE.items() if k in d.setters})
        text = d.build_text()
        d.close()
    assert text.startswith("{#")
    host = FakeHost()
    # parse + evaluate without raising (commands needing files/network may render "[name: error]")
    MacroEngine(host).expand_to_text(text)


def test_direct_and_submenu_inserts(app):
    got = []
    menus = macro_ui.macro_menus(None, got.append)
    kp = next(a.menu() for a in menus["Output"].actions() if a.menu())
    next(a for a in kp.actions() if a.text() == "Enter").trigger()
    outlook = next(a.menu() for a in menus["External data"].actions() if a.menu())
    next(a for a in outlook.actions() if a.text() == "Subject").trigger()
    form = next(a.menu() for a in menus["User input"].actions() if a.text() == "Form")
    next(a for a in form.actions() if a.text() == "Separator").trigger()
    assert got == ["{#key enter}", "{#outlook subject}", "{#formseparator}"]


def test_quote_keeps_nested_macros_and_paths():
    assert q('say "hi"') == '"say \\"hi\\""'
    assert q("{#date -format \"yyyy\"} x") == '"{#date -format "yyyy"} x"'
    assert q("C:\\temp\\") == '"C:\\temp\\."'
    assert q("a{b") == '"a{{b"'
    assert add_caption('{#date -format "x"}', "Today") == '{#date -format "x" -caption "Today"}'
    assert add_caption("{#if a}x{#endif}", "N") == "{#if a}x{#endif}"


def test_process_output_wraps(app):
    d = MacroDialog(SPECS["date_time"])
    d.set_values({"format": "yyyy"})
    d.process = ("upper", "")
    assert d.build_text() == '{#upper "{#date -format "yyyy"}"}'
    d.process = ("set", "stamp")
    assert d.build_text().startswith('{#set "stamp" "{#date')
    host = FakeHost()
    assert MacroEngine(host).expand_to_text('{#upper "{#date -format "yyyy"}"}').isdigit()


def test_display_names():
    assert macro_ui.display_name('{#date -format "dd"}') == "Date/Time"
    assert macro_ui.display_name("{#cursor}") == "Set cursor position"
    assert macro_ui.display_name("{#formseparator}") == "Separator"
    assert macro_ui.display_name('{#date -caption "Today"}') == "Today"
    assert macro_ui.display_name("{#key enter}") == "Key: enter"
    assert macro_ui.display_name("{#endif}") == "End if"
    assert macro_ui.display_name('{#calc 1+2}') == "Calculation"
    assert macro_ui.display_name('{#xls "a.xlsx" -cell B2}') == "MS Excel cells"


def test_edit_macro_prefills(app, monkeypatch):
    seen = {}

    def fake_exec(self):
        seen.update(self.values())
        self.result_text = self.build_text()
        return 1
    monkeypatch.setattr(MacroDialog, "exec", fake_exec)
    out = macro_ui.edit_macro('{#date -format "dd.MM" -offset "+2d -3h" -weekday "fri:1" -round 15}')
    assert seen["format"] == "dd.MM" and seen["shift_date"] == 2 and seen["shift_time"] == -3
    assert seen["shift_weekday"] == "fri" and seen["round"] is True
    assert out == '{#date -format "dd.MM" -offset "+2d -3h" -weekday "fri:1" -round "15"}'
    out = macro_ui.edit_macro('{#calc 2*3 -decimals 1 -caption "Total"}')
    assert out == '{#calc "2*3" -decimals "1" -caption "Total"}'


def test_edit_unknown_uses_raw_editor(app, monkeypatch):
    monkeypatch.setattr(macro_ui, "raw_edit", lambda token, parent=None: token + "!")
    assert macro_ui.edit_macro("{#loopindex}") == "{#loopindex}!"


def test_ribbon_group(app):
    from phraseforge.ui.ribbon import Ribbon
    rb = Ribbon()
    g = rb.add_tab("content", "Phrase content").add_group("Macros")
    got = []
    macro_ui.build_macro_group(g, got.append)
    texts = []
    for i in range(g.row.count()):
        col = g.row.itemAt(i).widget()
        texts.append([b.text() for b in col.buttons])
    assert texts == [["Date/Time", "User input", "External data"], ["Output", "Automation", "Programming"],
                     ["Text operations", "Clipboard", "Screen OCR"]]
