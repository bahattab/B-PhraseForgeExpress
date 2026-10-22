"""Engine commands added for PhraseExpress-equivalent macros."""
import csv
from datetime import datetime

import pytest

from phraseforge.db import Store
from phraseforge.host import Cancelled, KeyAction
from phraseforge.macros import MacroEngine
from phraseforge.models import Folder, Phrase, Trigger, TriggerKind
from tests.fakehost import FakeHost

NOW = datetime(2026, 10, 21, 14, 7, 30)   # a Wednesday


def run(text, host=None, store=None):
    host = host or FakeHost()
    return MacroEngine(host, store, clock=lambda: NOW).expand_to_text(text)


def acts(text, host=None):
    return MacroEngine(host or FakeHost(), clock=lambda: NOW).expand(text)


@pytest.mark.parametrize("macro,out", [
    ('{#strpos "hello world" "o"}', "5"), ('{#lastpos "hello world" "o"}', "8"),
    ('{#strpos "abc" "z"}', "0"), (r'{#strpos "a1b22" "\d+" -regex}', "2"),
    ('{#sentence "hi. how are you? fine"}', "Hi. How are you? Fine"),
    ('{#ucfirst "abc"}', "Abc"), ('{#lcfirst "ABC"}', "aBC"),
    ('{#ucwords "a big cat"}', "A Big Cat"), ('{#lcwords "A Big Cat"}', "a big cat"),
    ('{#ltrim "  x  "}', "x  "), ('{#rtrim "  x  "}', "  x"), ("{#ascii 65}", "A"), ("{#ascii 0x41}", "A"),
])
def test_text_ops(macro, out):
    assert run(macro) == out


def test_date_round_and_weekday():
    assert run('{#date -format "HH:mm" -round 15}') == "14:00"
    assert run('{#date -format "HH:mm" -round 15 -roundup}') == "14:15"
    assert run('{#date -format "yyyy-MM-dd" -weekday "mon:1"}') == "2026-10-26"
    assert run('{#date -format "yyyy-MM-dd" -weekday "wed:2"}') == "2026-11-04"


def test_datecalc_units():
    assert run('{#datecalc 2020-03-15 -diff 2026-03-14 -unit years}') == "5"
    assert run('{#datecalc 2026-01-31 -diff 2026-03-31 -unit months}') == "2"
    assert run('{#datecalc 2026-01-01 -diff 2026-01-02 -unit hours}') == "24"


def test_timecalc_duration_and_round():
    assert run('{#timecalc 09:00 -diff 17:30 -unit custom -format "H:mm"}') == "8:30"
    assert run('{#timecalc 09:00 -diff 09:07 -round 15 -unit minutes}') == "0"
    assert run('{#timecalc 09:00 -diff 09:07 -round 15 -roundup -unit minutes}') == "15"
    assert run('{#timecalc 10:00 -offset +20min -round 30 -format "HH:mm"}') == "10:30"


def test_calc_formatting():
    assert run("{#calc 1234567.891 -decimals 2 -thousands , }") == "1,234,567.89"
    assert run('{#calc 1234.5 -decimals 2 -decsep "," -thousands "."}') == "1.234,50"
    assert run("{#calc 7 -zeros 3}") == "007"


def test_input_syntax_validation():
    h = FakeHost().queue("ask_input", "abc", "42")
    assert run('{#input "Age" -syntax number}', h) == "42"
    assert len(h.called("ask_input")) == 2


def test_gender_asks_once_and_uses_var():
    h = FakeHost().queue("choose", ["Female"])
    assert run('{#gender -male He -female She -neutral It} {#gender -male his -female her -neutral its}', h) == "She her"
    assert len(h.called("choose")) == 1
    assert run('{#set gender m}{#gender -male He -female She}') == "He"


def test_message_buttons_insert_phrase():
    h = FakeHost().queue("choose", ["Yes"])
    h.phrases["accept"] = ("accepted!", "text")   # FakeHost keys are lower-case
    assert run('{#message "Proceed?" -buttons yesno -onyes "Accept"}', h) == "accepted!"


def test_notify_falls_back_to_message():
    h = FakeHost()
    run('{#notify "T" "Body"}', h)
    assert h.called("message") == [("Body", "T")]


def test_outputfile_and_document(tmp_path):
    p = tmp_path / "out.txt"
    run(f'{{#outputfile "{p}" "hello"}}')
    run(f'{{#outputfile "{p}" " world" -append}}')
    assert p.read_text() == "hello world"
    assert run(f'{{#document "{p}"}}') == "hello world"


def test_document_docx(tmp_path):
    import zipfile
    p = tmp_path / "a.docx"
    xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
           '<w:p><w:r><w:t>Line one</w:t></w:r></w:p><w:p><w:r><w:t>Line two</w:t></w:r></w:p></w:body></w:document>')
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", xml)
    assert run(f'{{#document "{p}"}}') == "Line one\nLine two"


def test_csv_range(tmp_path):
    p = tmp_path / "d.csv"
    with open(p, "w", newline="") as fh:
        csv.writer(fh).writerows([["a", "b", "c"], ["1", "2", "3"]])
    assert run(f'{{#csv "{p}" -fromrow 2 -fromcol 2}}') == "2"
    assert run(f'{{#csv "{p}" -fromrow 1 -torow 2 -fromcol 1 -tocol 2 -colsep ";" -rowsep "|"}}') == "a;b|1;2"


def test_xls_range_and_find(tmp_path):
    import openpyxl
    p = tmp_path / "d.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Name", "Age"])
    ws.append(["Ann", 31])
    wb.save(p)
    assert run(f'{{#xls "{p}" -sheet 1 -fromrow 1 -torow 2 -fromcol 1 -tocol 2 -colsep "," -rowsep "/"}}') == "Name,Age/Ann,31"
    assert run(f'{{#xlsfindcol "{p}" "age"}}') == "2"
    assert run(f'{{#xlsfindcol "{p}" "age" -letter}}') == "B"
    assert run(f'{{#xlsfindrow "{p}" "Ann"}}') == "2"
    assert run(f'{{#xlsfindrow "{p}" "zzz"}}') == "0"


def test_dbquery_sqlite(tmp_path):
    import sqlite3
    p = tmp_path / "x.db"
    con = sqlite3.connect(p)
    con.execute("create table t(a)")
    con.executemany("insert into t values (?)", [("x",), ("y",)])
    con.commit()
    con.close()
    assert run(f'{{#dbquery "select a from t" -engine sqlite -database "{p}" -rowsep ","}}') == "x,y"


def test_pastemethod_sets_context():
    eng = MacroEngine(FakeHost(), clock=lambda: NOW)
    from phraseforge.host import ExpansionContext
    ctx = ExpansionContext()
    eng.expand("{#pastemethod type -delay 20}hi", ctx)
    assert ctx.paste_method == "type" and ctx.key_delay_ms == 20


def test_pastefile_uses_host(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("x")
    h = FakeHost()
    h.set_clipboard_files = lambda paths: h.calls.append(("files", tuple(paths)))
    a = acts(f'{{#pastefile "{p}"}}', h)
    assert ("files", (str(p),)) in h.calls and isinstance(a[0], KeyAction)


def test_fileselect_fallback_and_host():
    h = FakeHost().queue("ask_input", r"C:\x.txt")
    assert run('{#fileselect -title "Pick"}', h) == r"C:\x.txt"
    h2 = FakeHost()
    h2.pick_file = lambda title, d, f, e, save: "C:\\out.txt" if save else ""
    assert run("{#filesave}", h2) == "C:\\out.txt"
    with pytest.raises(Cancelled):
        MacroEngine(h2).expand("{#fileselect}")


def test_focus_and_web_and_setlanguage():
    h = FakeHost()
    h.focus_window = lambda p, t, s: h.calls.append(("focus", (p, t, s))) or True
    run('{#focus -process notepad.exe -state max}', h)
    assert ("focus", ("notepad.exe", "", "max")) in h.calls
    run('{#web example.com}', h)
    assert h.called("open_target")[-1] == ("https://example.com",)
    run('{#web "x.org" -browser edge}', h)
    assert h.called("run_program")[-1][0] == "msedge.exe"
    assert run('{#setlanguage "ar-SA"}', FakeHost()).startswith("[setlanguage:")


@pytest.fixture
def store():
    s = Store(":memory:")
    f = s.add_folder(Folder("Letters"))
    s.add_phrase(Phrase("Intro", "Dear {#var who}", folder_id=f.id))
    s.add_phrase(Phrase("Outro", "Regards", folder_id=f.id,
                        triggers=[Trigger(TriggerKind.AUTOTEXT, "rg#")]))
    yield s
    s.close()


def test_insert_by_autotext_folder_pick(store):
    assert run('{#insert -autotext "rg#"}', store=store) == "Regards"
    assert run('{#insert -folder "Letters" -pick 2}', store=store) == "Regards"
    h = FakeHost().queue("choose", ["Outro"])
    assert run('{#insert -folder "Letters"}', h, store) == "Regards"
    out = run('{#insert -folder "Letters" -pick random -same}|{#insert -folder "Letters" -pick random -same}',
              store=store)
    a, b = out.split("|")
    assert a == b


def test_setphrase_and_docgen(store):
    run('{#setphrase "New one" "body" -folder "Letters"}', store=store)
    assert store.find_phrase("New one").content == "body"
    run('{#setphrase "" "changed" -target "New one"}', store=store)
    assert store.find_phrase("New one").content == "changed"
    h = FakeHost().queue("choose", ["Intro", "Outro"])
    assert run('{#set who Bob}{#docgen -folder "Letters" -sep " / "}', h, store) == "Dear Bob / Regards"


def test_form_extras(store):
    h = FakeHost().queue("show_form", {"items__0": True, "items__2": True})
    assert run('{#formenum items -options "a|b|c"}', h) == "a and c"
    h = FakeHost().queue("show_form", {"items__0": True, "items__1": True, "items__2": True})
    assert run('{#form}{#formenum items -options "a|b|c" -delim "; " -last " & "}{#endform}{#formvalue items}', h) == "a; b & c"
    h = FakeHost().queue("show_form", {"p": "Outro"})
    assert run('{#formphrases p -folder "Letters"}', h, store) == "Regards"
    h = FakeHost()
    run("{#form}{#formseparator}{#formslider n -min 1 -max 5}{#endform}", h)
    kinds = [f.kind for f in h.called("show_form")[0][1]]
    assert kinds == ["label", "number"]


def test_formdate_shift():
    h = FakeHost()
    run('{#formdate d -shift +3d}', h)
    field = h.called("show_form")[0][1][0]
    assert field.default == "2026-10-24"


def test_outlook_and_ad_degrade_gracefully():
    assert isinstance(run("{#outlook subject}"), str)
    assert isinstance(run("{#ad email}"), str)
    assert run("{#outlook nonsense}").startswith("[outlook:")
