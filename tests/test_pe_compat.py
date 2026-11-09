"""FR-MAC-01: PhraseExpress macro syntax translator. A hand-written corpus (no PhraseExpress
phrase content copied) translates with no parser problems and expands to golden output."""
import random
from datetime import datetime

import pytest

from phraseforge.host import ExpansionContext
from phraseforge.macros import MacroEngine
from phraseforge.macros.parser import parse
from phraseforge.macros.pe_compat import delphi_format, translate
from tests.fakehost import FakeHost

NOW = datetime(2026, 11, 9, 14, 5, 7)     # Monday


@pytest.fixture(scope="module")
def eng():
    h = FakeHost()
    h.clipboard = "clip"
    return MacroEngine(h, clock=lambda: NOW, rng=random.Random(1))


def T(eng, s):
    return eng.expand_to_text(s, ExpansionContext())


# (PhraseExpress text, translated text, expanded output)
CORPUS: list[tuple[str, str, str]] = []

# -- renamed text macros, in several spellings and with nested text
for pe, pf, fn in [("uppercase", "upper", str.upper), ("lowercase", "lower", str.lower),
                   ("uppercasefirst", "ucfirst", lambda s: s[:1].upper() + s[1:]),
                   ("lowercasefirst", "lcfirst", lambda s: s[:1].lower() + s[1:])]:
    for spelled in (pe, pe.upper(), pe.capitalize()):
        for word in ("hello world", "Mixed Case", "abc", "ARABIC عربي", "x", "two words here", "Ünïcode"):
            CORPUS.append((f'{{#{spelled} "{word}"}}', f'{{#{pf} "{word}"}}', fn(word)))

# -- Delphi date formats
for fmt, pf, out in [
    ("dd.mm.yyyy", "dd.MM.yyyy", "09.11.2026"), ("d/m/yy", "d/M/yy", "9/11/26"),
    ("yyyy-mm-dd", "yyyy-MM-dd", "2026-11-09"), ("hh:nn", "HH:mm", "14:05"), ("hh:nn:ss", "HH:mm:ss", "14:05:07"),
    ("h:nn am/pm", "h:mm tt", "2:05 PM"), ("hh:mm", "HH:mm", "14:05"), ("dddd", "dddd", "Monday"),
    ("ddd d mmm", "ddd d MMM", "Mon 9 Nov"), ("mmmm yyyy", "MMMM yyyy", "November 2026"),
    ("dd.mm.yyyy hh:nn", "dd.MM.yyyy HH:mm", "09.11.2026 14:05"), ("'Week of' d mmmm", "'Week of' d MMMM", "Week of 9 November"),
("yyyymmdd", "yyyyMMdd", "20261109"), ("nn", "mm", "05"),
]:
    for macro in ("date", "DATE", "Date"):
        CORPUS.append((f'{{#{macro} -f "{fmt}"}}', f'{{#date -format "{pf}"}}', out))
    CORPUS.append((f'Today: {{#date -f "{fmt}"}}.', f'Today: {{#date -format "{pf}"}}.', f"Today: {out}."))

# -- key blocks
for pe, pf in [("{#CTRL a}", "ctrl+a"), ("{#CTRL {#SHIFT a}}", "ctrl+shift+a"), ("{#ALT {#F4}}", "alt+f4"),
               ("{#CTRL {#ENTER}}", "ctrl+enter"), ("{#SHIFT {#TAB}}", "shift+tab"), ("{#WIN r}", "win+r"),
               ("{#CTRL {#ALT {#DEL}}}", "ctrl+alt+delete"), ("{#CTRL {#HOME}}", "ctrl+home"),
               ("{#shift {#end}}", "shift+end"), ("{#Ctrl v}", "ctrl+v"), ("{#CTRL {#SHIFT {#LEFT}}}", "ctrl+shift+left"),
               ("{#ALT {#TAB}}", "alt+tab"), ("{#CTRL {#BKSP}}", "ctrl+backspace"), ("{#CONTROL c}", "ctrl+c")]:
    CORPUS.append((pe, "{#key " + pf + "}", "<" + pf + ">"))
    CORPUS.append(("x" + pe + "y", "x{#key " + pf + "}y", "x<" + pf + ">y"))

# -- named keys with -count
for k in ("ENTER", "TAB", "BKSP", "DEL", "LEFT", "RIGHT", "UP", "DOWN"):
    for n in (1, 2, 5):
        low = k.lower()
        name = {"bksp": "backspace", "del": "delete"}.get(low, low)
        CORPUS.append((f"{{#{k} -count {n}}}", f"{{#{low} -repeat {n}}}", ("<" + name + ">") * n))

# -- conditions
for v, yes in (("clip", "same"), ("other", "different")):
    CORPUS.append((f'{{#cond {{#clipboard}} == {v}}}same{{#elsecond}}different{{#endcond}}',
                   f'{{#if {{#clipboard}} == {v}}}same{{#else}}different{{#endif}}', yes))

# -- PhraseForge already understands these: nothing changes
for same, out in [("{#upper abc}", "ABC"), ('{#date -format "yyyy"}', "2026"), ("plain text", "plain text"),
                  ("{#key ctrl+c}", "<ctrl+c>"), ("{{not a macro}", "{not a macro}"), ("{#clipboard}", "clip"),
                  ('{#replace "a-b" "-" "+"}', "a+b"), ("{#length hello}", "5")]:
    CORPUS.append((same, same, out))

# -- unsupported macros are kept, visibly
for name in ("flushclipboardcache", "qstext", "outputall", "nosuchmacro", "WEIRD"):
    src = f"before {{#{name} x y}} after"
    CORPUS.append((src, f'before {{#pe_unsupported "{{{{#{name} x y}}"}} after',
                   f"before [PhraseExpress macro not supported: {{#{name} x y}}] after"))


def test_corpus_is_big_enough():
    assert len(CORPUS) >= 200


@pytest.mark.parametrize("pe,pf,out", CORPUS)
def test_corpus(eng, pe, pf, out):
    got, _ = translate(pe)
    assert got == pf
    parse(got)                                   # no parser error
    shown = T(eng, got)
    shown = shown.replace("⟨", "⟨").replace("⟩", "⟩")
    assert _keys_as_markers(eng, got) == out


def _keys_as_markers(eng, text):
    from phraseforge.macros.engine import actions_to_text
    acts = eng.expand(text, ExpansionContext())
    return actions_to_text(acts, keys_as_markers=True).replace("[", "⟨", 0)


def test_warnings_name_what_happened():
    _, w = translate("{#UPPERCASE x}{#nosuch}")
    assert any("became {#upper}" in x for x in w) and any("{#nosuch} is not supported" in x for x in w)
    _, w = translate("{#upper x}")
    assert w == []


def test_unclosed_macro_is_left_alone():
    text, w = translate("a {#upper b")
    assert text == "a {#upper b" and w


def test_delphi_long_and_short_dates_warn():
    fmt, w = delphi_format("ddddd")
    assert fmt == "dd/MM/yyyy" and w
    fmt, w = delphi_format("dddddd")
    assert fmt == "dddd, d MMMM yyyy" and w


def test_import_translates(tmp_path):
    from phraseforge.db import Store
    from phraseforge.importers.phraseexpress import import_csv
    f = tmp_path / "pe.csv"
    f.write_text('description,content,autotext\nGreet,"{#UPPERCASE hi} {#CTRL v} {#zzz}",gr\n', encoding="utf-8")
    s = Store(":memory:")
    try:
        rep = import_csv(s, f)
        p = s.phrases()[0]
        assert p.content == '{#upper hi} {#key ctrl+v} {#pe_unsupported "{{#zzz}"}'
        assert any("zzz" in n for n in rep.notes)
    finally:
        s.close()
