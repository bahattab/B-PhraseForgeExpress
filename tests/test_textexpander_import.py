import plistlib

from phraseforge.db import Store
from phraseforge.importers.textexpander import convert, import_csv, import_textexpander_file


def test_date_run_merges_into_one_format():
    assert convert("%Y-%m-%d").content == '{#date -format "yyyy-MM-dd"}'


def test_date_math_offset():
    assert convert("%@+1D%A").content == '{#date -format "dddd" -offset +1d}'


def test_clipboard_cursor_key_snippet():
    c = convert("Hi %clipboard%|%key:tab%%snippet:sig%").content  # %clipboard has no closing %
    assert c == 'Hi {#clipboard}{#cursor}{#keys tab}{#insert "sig"}'


def test_fills_and_optional_part():
    c = convert("Dear %filltext:name=Name:default=Bob%,%fillpart:name=PS:default=no%P.S.%fillpartend%").content
    assert '{#ask "te_name" -prompt "Name" -default "Bob"}' in c
    assert '{#askcheck "te_ps" -prompt "PS"}{#if {#var "te_ps"} == "1"}P.S.{#endif}' in c


def test_popup_options_default_first():
    c = convert("%fillpopup:name=Size:default=M:S:L%").content
    assert c == '{#askchoice "te_size" -prompt "Size" -options "M|S|L"}'


def test_literal_braces_and_percent_escaped():
    assert convert("{x} 100%%").content == "{{x} 100%"


def test_unknown_key_reported():
    conv = convert("%key:weird%")
    assert conv.unknown == ["key:weird"]


def test_import_csv(tmp_path):
    p = tmp_path / "Mail.csv"
    p.write_text('sig;,"Best regards,\nMe",Signature\ndt;,%Y,\n', encoding="utf-8")
    s = Store(":memory:")
    rep = import_csv(s, p)
    assert rep.imported == 2
    ph = s.phrases(rep.folder_id)
    assert {x.description for x in ph} == {"Signature", "dt;"}
    assert s.folders()[0].name == "Mail"


def test_import_textexpander_plist(tmp_path):
    p = tmp_path / "group.textexpander"
    with open(p, "wb") as fh:
        plistlib.dump({"groupInfo": {"groupName": "Support"},
                       "snippetsTE2": [{"abbreviation": "ty;", "plainText": "Thanks %clipboard",
                                        "label": "Thanks", "snippetType": 0}]}, fh)
    s = Store(":memory:")
    rep = import_textexpander_file(s, p)
    assert rep.imported == 1
    ph = s.phrases(rep.folder_id)[0]
    assert ph.triggers[0].value == "ty;"
    assert s.folders()[0].name == "Support"


def test_import_macos_text_replacements_plist(tmp_path):
    import plistlib

    from phraseforge.db import Store
    from phraseforge.importers.textexpander import import_any
    path = tmp_path / "Text Substitutions.plist"
    path.write_bytes(plistlib.dumps([
        {"phrase": "On my way!", "shortcut": "omw"},
        {"phrase": "Line one\nLine two", "shortcut": "ll"},
        {"phrase": "", "shortcut": "empty"},
        "not a dict",
    ]))
    store = Store(":memory:")
    try:
        rep = import_any(store, path)
        assert (rep.imported, rep.skipped) == (2, 2)
        ps = {p.description: p for p in store.phrases(rep.folder_id)}
        assert ps["On my way!"].content == "On my way!" and ps["On my way!"].triggers[0].value == "omw"
        assert ps["Line one"].content == "Line one\nLine two" and "macos" in ps["Line one"].tags
        assert store.get_folder(rep.folder_id).name == "Text Substitutions"
    finally:
        store.close()
