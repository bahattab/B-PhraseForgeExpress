import base64
import json
import random
import sqlite3
from datetime import datetime

import pytest

from phraseforge.host import (
    Cancelled, CursorAction, ExpansionContext, ImageAction, KeyAction, MouseAction, SleepAction, TextAction,
)
from phraseforge.macros import MacroEngine, MacroInfo, apply_case, catalog
from phraseforge.macros.parser import Call, IfBlock, LoopBlock, Text, parse
from tests.fakehost import FakeHost

NOW = datetime(2026, 10, 21, 14, 5, 9)   # Wednesday


@pytest.fixture
def host():
    return FakeHost()


@pytest.fixture
def eng(host):
    return MacroEngine(host, clock=lambda: NOW, rng=random.Random(1))


def T(eng, s, **ctx):
    return eng.expand_to_text(s, ExpansionContext(**ctx))


# ------------------------------------------------------------------ parser
def test_plain_text_and_literal_brace(eng):
    assert T(eng, "a {{#date} b") == "a {#date} b"
    assert T(eng, "no macros") == "no macros"


def test_unknown_and_malformed_kept_literal(eng):
    assert T(eng, "x {#nosuch 1 2} y") == "x {#nosuch 1 2} y"
    assert T(eng, "x {#date") == "x {#date"
    assert T(eng, "{# date}") == "{# date}"
    assert T(eng, 'a {#upper "unterminated}') == 'a {#upper "unterminated}'


def test_parser_options_and_flags():
    nodes = parse('{#cmd a "b c" -opt v -flag -x "1 2"}')
    c = nodes[0]
    assert isinstance(c, Call) and c.name == "cmd"
    assert [t.bare_text or t.parts[0].text for t in c.args] == ["a", "b c"]
    assert c.opts["flag"] is None
    assert c.opts["opt"].bare_text == "v"
    assert c.opts["x"].parts[0].text == "1 2"


def test_negative_number_is_not_option():
    c = parse("{#calc -5 + 2}")[0]
    assert "5" not in c.opts and len(c.args) == 3


def test_escaped_quote_and_nested_in_quotes(eng, host):
    host.clipboard = "CLIP"
    assert T(eng, '{#upper "say \\"hi\\" {#clipboard}"}') == 'SAY "HI" CLIP'


def test_nesting(eng, host):
    host.clipboard = "  hello world "
    assert T(eng, "{#upper {#trim {#clipboard}}}") == "HELLO WORLD"
    assert T(eng, "[{#lower AB{#upper c}D}]") == "[abcd]"


def test_block_structure():
    n = parse("{#if 1}a{#elseif 2}b{#else}c{#endif}")
    assert isinstance(n[0], IfBlock) and len(n[0].branches) == 3
    assert isinstance(parse("{#loop 2}x{#endloop}")[0], LoopBlock)
    assert parse("stray {#endif}")[0] == Text("stray {#endif}")


def test_case_insensitive_names(eng):
    assert T(eng, "{#UPPER abc}") == "ABC"


# ------------------------------------------------------------------ date / time
def test_date_formats(eng):
    assert T(eng, "{#date}") == "2026-10-21"
    assert T(eng, '{#date -format "dd.MM.yyyy"}') == "21.10.2026"
    assert T(eng, '{#date -format "dddd, d MMMM yy"}') == "Wednesday, 21 October 26"
    assert T(eng, '{#time -format "hh:mm:ss tt"}') == "02:05:09 PM"
    assert T(eng, '{#date -format "\'Day\' DDD"}') == "Day 294"
    assert T(eng, '{#date -format "%Y/%m"}') == "2026/10"
    assert T(eng, '{#date -format "dddd MMMM" -lang ar}') == "الأربعاء أكتوبر"


def test_zzz_offset_token(eng):
    out = T(eng, '{#date -format "zzz"}')
    assert len(out) == 6 and out[0] in "+-" and out[3] == ":"


def test_date_offsets(eng):
    assert T(eng, "{#date -offset +3d}") == "2026-10-24"
    assert T(eng, "{#date -offset -1y}") == "2025-10-21"
    assert T(eng, "{#date -offset +1m}") == "2026-11-21"
    assert T(eng, "{#date -offset +2mo}") == "2026-12-21"
    assert T(eng, '{#time -offset +30min}') == "14:35"
    assert T(eng, '{#time -offset "-2h +5min"}') == "12:10"
    assert T(eng, "{#date -offset +3wd}") == "2026-10-26"   # Wed + 3 workdays (Sat/Sun weekend) = Mon


def test_weekend_setting(host):
    host.settings["date.weekend"] = "fri,sat"
    eng = MacroEngine(host, clock=lambda: NOW)
    assert T(eng, "{#date -offset +2wd}") == "2026-10-25"   # Thu, (skip Fri Sat) Sun


def test_month_end_clamp(eng):
    assert T(eng, "{#datecalc 2026-01-31 -offset +1m}") == "2026-02-28"


def test_datecalc_diff(eng):
    assert T(eng, "{#datecalc 2026-10-21 -diff 2026-10-31}") == "10"
    assert T(eng, "{#datecalc 2026-10-21 -diff 2026-10-31 -unit workdays}") == "7"   # Thu 22 .. Fri 30
    assert T(eng, '{#datecalc today -offset +7d -format "d.M."}') == "28.10."


def test_timecalc(eng):
    assert T(eng, "{#timecalc 09:30 -offset +45min}") == "10:15"
    assert T(eng, "{#timecalc 09:30 -diff 17:00}") == "450"
    assert T(eng, "{#timecalc 09:30 -diff 17:00 -unit hours}") == "7.5"


def test_bad_offset_inline_error(eng):
    assert T(eng, "{#date -offset soon}").startswith("[date:")


def test_datepick(eng, host):
    host.queue("pick_date", "2026-12-24")
    assert T(eng, '{#datepick "When" -format "dd/MM"}') == "24/12"


# ------------------------------------------------------------------ numbers
def test_calc(eng):
    assert T(eng, "{#calc 2*(3+4)}") == "14"
    assert T(eng, "{#calc 10/4}") == "2.5"
    assert T(eng, "{#calc 2^10}") == "1024"
    assert T(eng, "{#calc 1/3 -decimals 2}") == "0.33"
    assert T(eng, "{#calc max(1, 5) + sqrt(16)}") == "9"
    assert T(eng, "{#calc __import__('os')}").startswith("[calc:")


def test_random(eng):
    v = int(T(eng, "{#random 5 7}"))
    assert 5 <= v <= 7
    assert T(eng, '{#randomtext "a|b|c"}') in ("a", "b", "c")
    assert T(eng, "{#randomtext x y}") in ("x", "y")


def test_counter_persists(eng, host):
    assert T(eng, "{#counter inv -pad 3}") == "001"
    assert T(eng, "{#counter inv -pad 3}") == "002"
    assert host.vars[("counter", "inv")] == "2"
    assert T(eng, "{#counter other -start 10 -step 5}") == "10"
    assert T(eng, "{#counter other -start 10 -step 5}") == "15"


def test_number_format(eng):
    assert T(eng, "{#number 1234567.891 -decimals 2}") == "1,234,567.89"
    assert T(eng, '{#number 1234.5 -decimals 1 -thousands . -decimal ,}') == "1.234,5"


# ------------------------------------------------------------------ actions
def test_actions_and_merge(eng):
    acts = eng.expand("Hi {#cursor}there{#enter}{#key ctrl+a -repeat 2}{#sleep 100}{#mouse click -x 1 -y 2}x",
                      ExpansionContext())
    assert acts[0] == TextAction("Hi ")
    assert isinstance(acts[1], CursorAction)
    assert acts[2] == TextAction("there")
    assert acts[3] == KeyAction("enter", 1)
    assert acts[4] == KeyAction("ctrl+a", 2)
    assert acts[5] == SleepAction(100)
    assert acts[6] == MouseAction("click", 1, 2)
    assert acts[7] == TextAction("x")


def test_named_keys_and_aliases(eng):
    assert eng.expand("{#tab 3}", None) == [KeyAction("tab", 3)]
    assert eng.expand("{#keys tab}", None) == [KeyAction("tab", 1)]
    assert eng.expand("{#key Control+Shift+PgDn}", None) == [KeyAction("ctrl+shift+pagedown", 1)]
    assert eng.expand("{#f5}{#bksp 2}", None) == [KeyAction("f5", 1), KeyAction("backspace", 2)]
    assert T(eng, "a{#enter}b") == "a<enter>b"


def test_text_newline_tab(eng):
    assert T(eng, "a{#nl 2}b{#tabchar}c") == "a\n\nb\tc"


# ------------------------------------------------------------------ clipboard / context
def test_clipboard_and_history(eng, host):
    host.set_clipboard("old")
    host.set_clipboard("new")
    assert T(eng, "{#clipboard}|{#clipboardhistory 1}|{#insertclipboard}") == "new|old|new"
    T(eng, "{#setclipboard abc}")
    assert host.clipboard == "abc"


def test_selection_group_app(eng):
    ctx = dict(selected_text="SEL", regex_groups=("g1", "g2"), app_exe="word.exe", window_title="Doc")
    assert T(eng, "{#selection} {#group 2} {#group 9} {#appname} {#windowtitle}", **ctx) == "SEL g2  word.exe Doc"
    assert T(eng, "{#appname}") == "notepad.exe"


# ------------------------------------------------------------------ forms / input
def test_input_and_formvalue(eng, host):
    host.queue("ask_input", "Bob")
    assert T(eng, '{#input "Name" -name n} / {#formvalue n}') == "Bob / Bob"
    assert host.called("ask_input")[0][0] == "Name"


def test_input_cancel_propagates(eng, host):
    host.queue("ask_input", Cancelled)
    with pytest.raises(Cancelled):
        eng.expand('{#input "x"}', None)


def test_form_block(eng, host):
    host.queue("show_form", {"name": "Ann", "city": "Riyadh", "vip": True, "when": "2026-11-01"})
    out = T(eng, '{#form -title "Customer"}{#formedit name -label "Name"}{#formcombo city -options "Jeddah,Riyadh"}'
                 '{#formcheckbox vip -on "VIP" -off "regular"}{#formdate when -format "dd.MM"}{#formlabel x}'
                 'ignored text{#endform}{#formvalue name} {#formvalue city} {#formvalue vip} {#formvalue when}')
    assert out == "Ann Riyadh VIP 01.11"
    title, fields = host.called("show_form")[0]
    assert title == "Customer"
    assert [f.kind for f in fields] == ["edit", "combo", "checkbox", "date", "label"]
    assert fields[1].options == ["Jeddah", "Riyadh"] and fields[1].default == "Jeddah"


def test_form_defaults_when_not_answered(eng, host):
    out = T(eng, '{#form}{#formcheckbox c -checked}{#formradio r -options "x,y"}{#endform}[{#formvalue c}{#formvalue r}]')
    assert out == "[1x]"


def test_standalone_field(eng, host):
    host.queue("show_form", {"qty": 3.0})
    assert T(eng, "{#formnumber qty -label Quantity}") == "3"


def test_choose(eng, host):
    host.queue("choose", ["b", "c"])
    assert T(eng, '{#choose "Pick" -options "a,b,c" -multi -name sel}={#formvalue sel}') == "b, c=b, c"
    assert host.called("choose")[0] == ("Pick", ["a", "b", "c"], True)
    assert T(eng, '{#choose "Pick" x y}') == "x"


def test_message(eng, host):
    assert T(eng, '{#message "Hello" -title T}') == ""
    assert ("message", ("Hello", "T")) in host.calls


# ------------------------------------------------------------------ ask-once commands
def test_ask_once(eng, host):
    host.queue("ask_input", "Sam")
    assert T(eng, 'Hi {#ask "te_name" -prompt "Name"}, bye {#ask "te_name" -prompt "Name"}') == "Hi Sam, bye Sam"
    assert len(host.called("ask_input")) == 1
    assert host.called("ask_input")[0][0] == "Name"
    host.queue("ask_input", "Max")
    assert T(eng, '{#ask "te_name"}') == "Max"     # new expansion asks again


def test_ask_default_and_multiline(eng, host):
    assert T(eng, '{#ask "x" -prompt P -default dflt -multiline}') == "dflt"
    assert host.called("ask_input")[0] == ("P", "dflt", True)


def test_askchoice(eng, host):
    assert T(eng, '{#askchoice "s" -prompt Size -options "S|M|L"}{#askchoice "s"}') == "SS"
    assert host.called("choose")[0] == ("Size", ["S", "M", "L"], False)
    host.queue("choose", ["L"])
    assert T(eng, '{#askchoice "s" -options "S|M|L"}') == "L"


def test_askcheck_with_if(eng, host):
    host.queue("show_form", {"te_x": True})
    src = '{#askcheck "te_x" -prompt "Add?"}[{#if {#var "te_x"} == "1"}yes{#else}no{#endif}]'
    assert T(eng, src) == "[yes]"
    host.queue("show_form", {"te_x": False})
    assert T(eng, src) == "[no]"
    assert T(eng, '{#askcheck "c" -checked}{#var c}') == "1"


def test_askdate(eng, host):
    host.queue("pick_date", "2026-12-01")
    assert T(eng, '{#askdate "d" -prompt Due}/{#askdate "d"}') == "2026-12-01/2026-12-01"
    assert len(host.called("pick_date")) == 1


# ------------------------------------------------------------------ conditions
@pytest.mark.parametrize("cond,expected", [
    ('a == a', True), ('a == b', False), ('a != b', True), ('1.0 == 1', True),
    ('10 > 9', True), ('"10" < "9"', False), ('abc < abd', True),
    ('"Hello World" contains world', True), ('abc startswith AB', True), ('abc endswith x', False),
    ('abc =~ "^a.c$"', True), ('abc !~ "z"', True), ('b in "a, b ,c"', True),
    ('empty ""', True), ('notempty x', True), ('not empty x', True),
    ('a == a and b == c', False), ('a == a or b == c', True), ('( a == b or 1 ) and 0', False),
    ('1', True), ('0', False), ('""', False), ('false', False), ('"and" == "and"', True),
])
def test_conditions(eng, cond, expected):
    assert T(eng, "{#if " + cond + "}Y{#else}N{#endif}") == ("Y" if expected else "N")


def test_elseif_and_nested_if(eng, host):
    src = ("{#if {#var x} == 1}one{#elseif {#var x} == 2}two"
           "{#if {#var y} == z}+z{#endif}{#else}other{#endif}")
    assert T(eng, "{#set x 1}" + src) == "one"
    assert T(eng, "{#set x 2}{#set y z}" + src) == "two+z"
    assert T(eng, src) == "other"


def test_if_with_quoted_values_with_spaces(eng, host):
    host.clipboard = "hello there"
    assert T(eng, '{#if {#clipboard} == "hello there"}ok{#endif}') == "ok"


# ------------------------------------------------------------------ loops
def test_loop(eng):
    assert T(eng, "{#loop 3}{#loopindex}{#endloop}") == "123"
    assert T(eng, "{#loop 2 -join ,}{#loopindex -zero}/{#loopcount}{#endloop}") == "0/2,1/2"
    assert T(eng, "{#loop 0}x{#endloop}") == ""
    assert T(eng, "{#loop 2}{#loop 2}{#loopindex}{#endloop}|{#endloop}") == "12|12|"


def test_foreach(eng):
    assert T(eng, '{#foreach "a, b,c"}<{#item}>{#endforeach}') == "<a><b><c>"
    assert T(eng, '{#foreach x y -join " + "}{#upper {#item}}{#endforeach}') == "X + Y"
    assert T(eng, '{#foreach "1;2" -sep ;}{#item}{#endforeach}') == "12"


def test_unclosed_block_runs_to_end(eng):
    assert T(eng, "{#loop 2}ab") == "abab"


# ------------------------------------------------------------------ variables
def test_vars_scopes(eng, host):
    assert T(eng, "{#set a 1}{#var a}") == "1"
    assert T(eng, "{#var a}") == ""            # local does not persist
    T(eng, "{#set g hello world -scope global}")
    assert host.vars[("global", "g")] == "hello world"
    assert T(eng, "{#var g}") == "hello world"   # falls back to global store
    assert T(eng, "{#var missing -default dd}") == "dd"
    assert T(eng, "{#set a 1}{#unset a}[{#var a}]") == "[]"
    T(eng, "{#unset g -scope global}")
    assert host.vars[("global", "g")] == ""


def test_local_overrides_global(eng, host):
    host.vars[("global", "v")] = "G"
    assert T(eng, "{#var v} {#set v L}{#var v} {#var v -scope global}") == "G L G"


# ------------------------------------------------------------------ insert
def test_insert_recursive_and_cycles(eng, host):
    host.phrases = {
        "sig": ("Regards, {#insert \"name\"}", "text"),
        "name": ("{#upper bob}", "text"),
        "loop1": ("A{#insert loop2}", "text"),
        "loop2": ("B{#insert loop1}", "text"),
        "self": ("S{#insert self}", "text"),
        "rich": ("<p>Hi<br>there &amp; you</p>", "html"),
    }
    assert T(eng, '{#insert "Sig"}') == "Regards, BOB"
    assert T(eng, "{#insert loop1}") == "AB"
    assert T(eng, "{#insert self}") == "S"
    assert T(eng, "{#insert rich}") == "Hi\nthere & you"
    assert T(eng, "{#insert nope}").startswith("[insert:")


def test_insert_skips_own_phrase(eng, host):
    host.phrases = {"me": ("x{#insert me}", "text")}
    assert T(eng, "{#insert me}", phrase_description="me") == ""


def test_insert_depth_limit(eng, host):
    host.phrases = {f"p{i}": (f"{i}{{#insert p{i + 1}}}", "text") for i in range(20)}
    assert T(eng, "{#insert p0}") == "0123456789"


def test_insert_from_store():
    from phraseforge.db import Store
    from phraseforge.models import Phrase
    s = Store(":memory:")
    s.add_phrase(Phrase("Greeting", "Hello {#upper x}"))
    e = MacroEngine(FakeHost(), store=s)
    assert e.expand_to_text('{#insert "greeting"}') == "Hello X"


# ------------------------------------------------------------------ text functions
def test_text_functions(eng):
    assert T(eng, "{#title hello WORLD}") == "Hello World"
    assert T(eng, "{#capitalize hello}") == "Hello"
    assert T(eng, '{#replace "a-b-c" - +}') == "a+b+c"
    assert T(eng, '{#replace "A a" a x -i}') == "x x"
    assert T(eng, '{#replace "a b" " " "\\n"}') == "a\nb"
    assert T(eng, '{#regexreplace "2026-10-21" "(\\d+)-(\\d+)-(\\d+)" "\\3.\\2.\\1"}') == "21.10.2026"
    assert T(eng, '{#regexget "Order #123 and #456" "#(\\d+)" -group 1}') == "123"
    assert T(eng, '{#regexget "Order #123 and #456" "#(\\d+)" -group 1 -all -sep "|"}') == "123|456"
    assert T(eng, "{#substr abcdef 2 3}") == "bcd"
    assert T(eng, "{#substr abcdef -2}") == "ef"
    assert T(eng, '{#length "abc d"}') == "5"
    assert T(eng, "{#padleft 7 3 -char 0}") == "007"
    assert T(eng, "{#padright ab 4 -char .}") == "ab.."
    assert T(eng, "{#reverse abc}") == "cba"
    assert T(eng, '{#urlencode "a b&c"}') == "a%20b%26c"
    assert T(eng, "{#urldecode a%20b}") == "a b"
    assert T(eng, '{#htmlencode "<b>&"}') == "&lt;b&gt;&amp;"
    assert T(eng, "{#base64 hi}") == base64.b64encode(b"hi").decode()
    assert T(eng, "{#base64 aGk= -decode}") == "hi"


# ------------------------------------------------------------------ files & data
def test_textfile_and_image(eng, tmp_path):
    f = tmp_path / "t.txt"
    f.write_text("line1\nline2\n", encoding="utf-8")
    assert T(eng, f'{{#textfile "{f}"}}') == "line1\nline2\n"
    assert T(eng, f'{{#textfile "{f}" -line 2}}') == "line2"
    assert T(eng, f'{{#embed "{f}" -line 1}}') == "line1"
    assert T(eng, '{#textfile "C:\\nope\\x.txt"}').startswith("[textfile:")
    img = tmp_path / "i.png"
    img.write_bytes(b"\x89PNG")
    assert eng.expand(f'{{#image "{img}"}}', None) == [ImageAction(str(img))]


def test_xls(eng, tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Prices"
    ws.append(["apple", 1.5])
    ws.append(["pear", 2])
    p = tmp_path / "d.xlsx"
    wb.save(p)
    assert T(eng, f'{{#xls "{p}" -sheet Prices -cell B1}}') == "1.5"
    assert T(eng, f'{{#xlsfind "{p}" PEAR -searchcol A -returncol B}}') == "2"
    assert T(eng, f'{{#xlsfind "{p}" kiwi -default none}}') == "none"


def test_xml(eng, tmp_path):
    x = '<r><item id="1"><n>A</n></item><item id="2"><n>B</n></item></r>'
    assert T(eng, '{#xml "' + x.replace('"', '\\"') + '" -path "./item/n"}') == "A"
    p = tmp_path / "x.xml"
    p.write_text(x, encoding="utf-8")
    assert T(eng, f'{{#xml "{p}" -path "./item" -attr id -all -sep ","}}') == "1,2"


def test_sql(eng, tmp_path):
    p = tmp_path / "d.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE t (a, b)")
    c.executemany("INSERT INTO t VALUES (?, ?)", [(1, "x"), (2, "y")])
    c.commit()
    c.close()
    assert T(eng, f'{{#sql "{p}" "SELECT a, b FROM t ORDER BY a" -sep = -rowsep ";"}}') == "1=x;2=y"
    assert T(eng, f'{{#sql "{p}" "DELETE FROM t"}}').startswith("[sql:")   # read-only


def test_http_and_json(eng, host):
    host.http["https://api.test/x"] = json.dumps({"data": {"items": [{"name": "N1"}]}, "ok": True})
    assert T(eng, '{#json {#http "https://api.test/x"} -path "data.items[0].name"}') == "N1"
    assert T(eng, '{#json {#http "https://api.test/x"} -path ok}') == "true"
    assert T(eng, '{#json {#http "https://api.test/x"} -path "zz" -default -}') == "-"
    T(eng, '{#http "https://api.test/x" -method post -body "b" -header "A: 1; B: 2"}')
    assert host.called("http_request")[-1] == ("POST", "https://api.test/x", {"A": "1", "B": "2"}, "b")


# ------------------------------------------------------------------ system
def test_run_open_mail_waitfor(eng, host):
    host.queue("run_program", 3)
    assert T(eng, '{#run "cmd.exe" -args "/c exit 3" -exitcode}') == "3"
    assert host.called("run_program")[0] == ("cmd.exe", "/c exit 3", True, "")
    T(eng, '{#open "C:\\Temp"}{#url "https://x.y"}')
    T(eng, '{#mail -to a@b.com -subject "Hi there" -body "x&y"}')
    targets = [a[0] for m, a in host.calls if m == "open_target"]
    assert targets[:2] == ["C:\\Temp", "https://x.y"]
    assert targets[2] == "mailto:a@b.com?subject=Hi%20there&body=x%26y"
    host.windows_ok = False
    assert T(eng, '{#waitfor "Notepad" -timeout 1}') == ""
    with pytest.raises(Cancelled):
        eng.expand('{#waitfor "Notepad" -abort}', None)


def test_env_user_uuid(eng, monkeypatch):
    monkeypatch.setenv("PF_TEST", "val")
    assert T(eng, "{#env PF_TEST}") == "val"
    assert T(eng, "{#username}")
    assert len(T(eng, "{#uuid}")) == 36


# ------------------------------------------------------------------ AI / OCR
def test_ai_and_translate(eng, host):
    assert T(eng, '{#ai "hello" -provider anthropic -model m -system s}') == "AI:hello"
    assert host.called("ai_complete")[0] == ("hello", "anthropic", "m", "s")
    T(eng, "{#translate Hello -to Arabic}")
    sys_prompt = host.called("ai_complete")[1][3]
    assert "Arabic" in sys_prompt


def test_ocr(eng, host):
    host.ocr_text = "نص"
    assert T(eng, "{#ocr -lang Arabic -linebreaks}") == "نص"
    assert host.called("ocr_region")[0] == ("Arabic", True)
    host.settings["ocr.language"] = "Russian"
    T(eng, '{#ocrfile "C:\\i.png"}')
    assert host.called("ocr_image")[0] == ("C:\\i.png", "Russian")


# ------------------------------------------------------------------ case matching
def test_apply_case():
    assert apply_case("best regards", "BR") == "BEST REGARDS"
    assert apply_case("best regards", "Br") == "Best regards"
    assert apply_case("best regards", "br") == "best regards"
    assert apply_case("best", "#1") == "best"


def test_engine_case_matching(eng):
    assert T(eng, "best {#cursor}regards", typed_abbreviation="BR#") == "BEST REGARDS"
    assert T(eng, "best regards", typed_abbreviation="Br") == "Best regards"
    assert T(eng, "best", typed_abbreviation="br") == "best"


# ------------------------------------------------------------------ catalog
def test_catalog():
    cat = catalog()
    names = {m.name for m in cat}
    assert all(isinstance(m, MacroInfo) for m in cat)
    for required in ["date", "time", "datecalc", "timecalc", "calc", "random", "counter", "cursor", "clipboard",
                     "clipboardhistory", "selection", "key", "enter", "tab", "sleep", "mouse", "input", "form",
                     "formedit", "formmemo", "formcombo", "formcheckbox", "formradio", "formdate", "formnumber",
                     "formlabel", "formvalue", "choose", "if", "loop", "foreach", "set", "var", "unset", "insert",
                     "upper", "regexget", "textfile", "xls", "xml", "sql", "http", "json", "group", "run", "open",
                     "waitfor", "mail", "image", "appname", "env", "uuid", "ai", "translate", "ocr", "ocrfile",
                     "message", "ask", "askchoice", "askcheck", "askdate"]:
        assert required in names, required
    assert len(names) == len(cat)                 # no duplicates (aliases hidden)
    assert all(m.template.startswith("{#") for m in cat)
