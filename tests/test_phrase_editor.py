import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from phraseforge.db import Store
from phraseforge.models import AutotextMode, Folder, Phrase, Trigger, TriggerKind


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    from phraseforge.ui import pe_style
    pe_style.apply(a)
    return a


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


CONTENTS = [
    "plain text only",
    'Hi {#date -format "yyyy-MM-dd"}!\n{#cursor}{#separator}',
    '{#if {#var "x"} == "a"}yes{#else}no{#endif}',
    "literal {{braces} and {#upper {#clipboard}} end",
    'quote "}" inside {#input "a } b" -default "{x}"} done',
    "multi\nline\n\nwith {#key enter} keys",
    "unterminated {#date",
]


@pytest.mark.parametrize("text", CONTENTS)
def test_chip_roundtrip_keeps_exact_text(app, text):
    from phraseforge.ui.phrase_editor import ChipTextEdit, OBJ
    ed = ChipTextEdit()
    ed.set_content(text)
    assert ed.content() == text
    if "{#date -format" in text:
        assert OBJ in ed.toPlainText()          # shown as a chip


def test_split_tokens_nesting(app):
    from phraseforge.ui.phrase_editor import split_tokens
    parts = split_tokens("a{#upper {#clipboard}}b{{c")
    assert parts == [(False, "a"), (True, "{#upper {#clipboard}}"), (False, "b{{c")]


def test_load_save_roundtrip(app, store):
    from phraseforge.ui.phrase_editor import PhraseEditor
    p = store.add_phrase(Phrase("Sig", "Best {#date}", triggers=[Trigger(TriggerKind.AUTOTEXT, "sig#")]))
    ed = PhraseEditor(store)
    ed.load(p.id)
    assert ed.description.text() == "Sig"
    assert ed.content_edit.content() == "Best {#date}"
    ed.description.setText("Signature"); ed._mark_dirty()
    from PySide6.QtGui import QTextCursor
    ed.content_edit.moveCursor(QTextCursor.End)
    ed.insert_macro("{#cursor}")
    assert ed.save()
    got = store.get_phrase(p.id)
    assert got.description == "Signature"
    assert got.content == "Best {#date}{#cursor}"
    assert [t.value for t in got.triggers] == ["sig#"]


def test_all_trigger_types_roundtrip(app, store):
    from phraseforge.ui.phrase_editor import PhraseEditor
    from phraseforge.ui.trigger_editor import TYPES, default_row
    values = {"autotext": "ab#", "smartcomplete": "", "regex_autotext": r"\bfoo(\d+)", "hotkey": "ctrl+alt+k",
              "window": "notepad.exe", "time": "08:30", "clipboard": "copied", "regex_clipboard": r"^\d{5}$"}
    p = store.add_phrase(Phrase("T", "x"))
    ed = PhraseEditor(store)
    ed.load(p.id)
    rows = []
    for key, _ in TYPES:
        r = default_row(key)
        r["value"] = values[key]
        if key == "autotext":
            r.update(exec="confirm", case_sensitive=True, word_pos="end")
        if key == "window":
            r["window_scope"] = "program"
        rows.append(r)
    ed.triggers.set_rows(rows)
    ed._mark_dirty()
    assert ed.save()
    got = store.get_phrase(p.id)
    kinds = [TriggerKind(t.kind) for t in got.triggers]
    assert kinds == [TriggerKind.AUTOTEXT, TriggerKind.REGEX, TriggerKind.HOTKEY, TriggerKind.APP_FOCUS,
                     TriggerKind.TIME, TriggerKind.CLIPBOARD, TriggerKind.CLIPBOARD_REGEX]
    at = got.triggers[0]
    assert at.mode == AutotextMode.CONFIRM and at.case_sensitive and not at.word_start_only
    # reload: UI rows (incl. SmartComplete + extras) come back in order
    ed2 = PhraseEditor(store)
    ed2.load(p.id)
    back = ed2.triggers.get_rows()
    assert [r["type"] for r in back] == [k for k, _ in TYPES]
    assert [r["value"] for r in back] == [values[k] for k, _ in TYPES]
    assert back[0]["word_pos"] == "end" and back[0]["exec"] == "confirm"
    assert back[4]["window_scope"] == "program"


def test_rows_fallback_when_db_changed(app, store):
    """If triggers changed elsewhere (import, other editor), DB wins over stale UI extras."""
    from phraseforge.ui.phrase_editor import PhraseEditor
    p = store.add_phrase(Phrase("T", "x", triggers=[Trigger(TriggerKind.AUTOTEXT, "one")]))
    ed = PhraseEditor(store); ed.load(p.id)
    ed.triggers.rows[0].set_row({"type": "autotext", "value": "one", "word_pos": "entire"}); ed._mark_dirty()
    ed.save()
    p2 = store.get_phrase(p.id); p2.triggers = [Trigger(TriggerKind.HOTKEY, "ctrl+q")]
    store.update_phrase(p2)
    ed.load(p.id)
    rows = ed.triggers.get_rows()
    assert [(r["type"], r["value"]) for r in rows] == [("hotkey", "ctrl+q")]


def test_formatting_makes_phrase_html(app, store):
    from phraseforge.ui.content_tab import build_content_tab
    from phraseforge.ui.phrase_editor import PhraseEditor
    from phraseforge.ui.ribbon import Ribbon
    p = store.add_phrase(Phrase("F", "hello {#date} world"))
    rb = Ribbon(); rb.add_tab("phrases", "Phrases")
    ed = PhraseEditor(store)
    tab = build_content_tab(rb, ed)
    assert "content" in rb.tabs and tab.title == "Phrase content"
    assert {"Clipboard", "Font", "Paragraph", "Insert", "Macros"} <= set(tab.groups)
    ed.load(p.id)
    ed.content_edit.selectAll()
    tab.controller.b_bold.setChecked(True)
    tab.controller._toggle_bold()
    ed.save()
    got = store.get_phrase(p.id)
    assert got.content_format == "html"
    assert "{#date}" in got.content and "font-weight" in got.content
    ed.load(p.id)                                   # html reloads with chips
    assert "{#date}" in ed.content_edit.content()


def test_folder_and_special_editors(app, store):
    from phraseforge.ui.phrase_editor import FolderEditor, SpecialFolderEditor
    from phraseforge.ui.trigger_editor import default_row
    f = store.add_folder(Folder("Work"))
    fe = FolderEditor(store); fe.load(f.id)
    fe.description.setText("Office"); fe.notes.setPlainText("note!")
    fe.triggers.set_rows([dict(default_row("hotkey"), value="ctrl+shift+w")]); fe._mark_dirty()
    assert fe.save()
    assert store.get_folder(f.id).name == "Office"
    fe2 = FolderEditor(store); fe2.load(f.id)
    assert fe2.notes.toPlainText() == "note!"
    assert set(fe2.triggers.get_rows()[0]["value"].split("+")) == {"ctrl", "shift", "w"}

    cc = SpecialFolderEditor(store, "clipboard_cache")
    assert cc.triggers.get_rows()[0]["value"] == "ctrl+alt+v"
    cc.max_items.setValue(33)
    cc.triggers.rows[0].hotkey.set_value("ctrl+shift+v")
    assert store.setting("clipboard_history.max") == "33"
    assert set(store.setting("clipboard_history.hotkey").split("+")) == {"ctrl", "shift", "v"}
    lu = SpecialFolderEditor(store, "last_used")
    lu.clear_on_exit.setChecked(True)
    assert store.setting("special.last_used.clear_on_exit") == "1"


def test_copy_keeps_macro_text(app):
    from phraseforge.ui.phrase_editor import ChipTextEdit
    ed = ChipTextEdit()
    ed.set_content("a {#date} b")
    ed.selectAll()
    md = ed.createMimeDataFromSelection()
    assert md.text() == "a {#date} b"


def test_view_options_and_status(app, store):
    from phraseforge.ui.phrase_editor import PhraseEditor
    p = store.add_phrase(Phrase("S", "one two {#date}"))
    ed = PhraseEditor(store)
    seen = []
    ed.status_changed.connect(seen.append)
    ed.load(p.id)
    assert seen and seen[-1]["words"] == 2 and seen[-1]["chars"] == len("one two {#date}")
    ed.set_view_options(word_wrap=False, show_special=True, show_macro_params=True, rulers=True)
    assert ed.content_edit.show_macro_params and not ed.ruler.isHidden()
    assert ed.content_edit.content() == "one two {#date}"
