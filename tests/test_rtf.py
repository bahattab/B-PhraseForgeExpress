"""HTML -> RTF for the clipboard (PhraseExpress output formats RTF & HTML / RTF only / HTML only)."""
from phraseforge.platform.output import OutputExecutor
from phraseforge.host import HtmlAction
from phraseforge.rtf import escape, html_to_rtf


def test_escape_unicode_and_specials():
    assert escape("a{b}\\") == "a\\{b\\}\\\\"
    assert escape("س") == "\\u1587?"
    assert escape("😀") == "\\u-10179?\\u-8704?"


def test_basic_formatting():
    rtf = html_to_rtf("<p>Hello <b>bold</b> <i>it</i><br>next</p><p>two</p>")
    assert rtf.startswith("{\\rtf1") and rtf.endswith("}")
    assert "\\b bold\\b0" in rtf and "\\i it\\i0" in rtf and "\\line next" in rtf
    assert rtf.count("\\par\n") == 1          # two paragraphs
    assert "<" not in rtf


def test_arabic_paragraph_is_right_to_left():
    rtf = html_to_rtf("<p>مرحبا بكم</p><p>Hello</p>")
    first, second = rtf.split("\\par\n")
    assert "\\rtlpar\\qr" in first and "\\ltrpar\\ql" in second
    assert "\\u1605?" in first                # م


def test_lists_and_style_ignored():
    rtf = html_to_rtf("<style>p{color:red}</style><ul><li>one</li><li>two</li></ul>")
    assert "color" not in rtf and rtf.count("\\bullet") == 2


def test_executor_passes_selected_formats():
    from tests.test_output_services import FakeSI

    calls = []

    class CB:
        def save_all(self): return None
        def restore(self, s): pass
        def set_html(self, h, p, formats="html"): calls.append(formats)

    for setting, want in (({"output.rich_formats": "rtf"}, "rtf"), ({}, "html")):
        calls.clear()
        ex = OutputExecutor(lambda k, d="", st=setting: st.get(k, d))
        ex.sendinput, ex.clipboard = FakeSI([]), CB()
        ex.execute([HtmlAction(html="<b>x</b>", plain="x")])
        assert calls == [want]


@__import__("pytest").mark.skipif(__import__("sys").platform != "win32", reason="Windows clipboard")
def test_windows_clipboard_gets_rtf_and_html():
    from phraseforge.platform import clipboard as cb
    from phraseforge.platform._win32 import user32
    snap = cb.save_all()
    try:
        cb.set_html("<b>مرحبا</b>", "مرحبا", "rtf_html")
        assert user32.IsClipboardFormatAvailable(cb.rtf_format_id())
        assert cb.get_html() == "<b>مرحبا</b>" and cb.get_text() == "مرحبا"
        with cb._Open():
            raw = cb._get(cb.rtf_format_id())
        assert raw.startswith(b"{\\rtf1") and b"\\u1605?" in raw
        cb.set_html("<i>x</i>", "x", "rtf")
        assert not user32.IsClipboardFormatAvailable(cb.html_format_id())
    finally:
        cb.restore(snap)
