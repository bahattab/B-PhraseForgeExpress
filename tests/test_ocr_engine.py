"""Built-in OCR (Windows.Media.Ocr in-process): language mapping everywhere,
real recognition on Windows."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from phraseforge import ocr  # noqa: E402


def test_language_names_and_tags():
    assert ocr.language_tag("Arabic") == "ar"
    assert ocr.language_tag("english") == "en"
    assert ocr.language_tag("ar-SA") == "ar-SA"
    assert ocr.language_name("ar-SA") == "Arabic"
    assert ocr.language_name("en-US") == "English"
    assert ocr.language_name("zh-Hans-CN") == "Chinese (Simplified)"
    assert ocr.language_name("xx-YY") == "xx-YY"


def test_tag_matching():
    assert ocr._tag_matches("ar-SA", "ar")
    assert ocr._tag_matches("en-US", "en-US")
    assert not ocr._tag_matches("en-US", "ar")


def test_no_external_program_is_started():
    import inspect
    src = inspect.getsource(ocr)
    assert "subprocess" not in src and "Capture2Text_CLI" not in src


_RENDER = r"""
import sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
out, w, h = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
img = QImage(w, h, QImage.Format_ARGB32)
img.fill(QColor("white"))
p = QPainter(img)
p.setRenderHint(QPainter.TextAntialiasing, True)
p.setPen(QColor("black"))
for i in range(4, len(sys.argv), 4):
    text, x, y, px = sys.argv[i], int(sys.argv[i + 1]), int(sys.argv[i + 2]), int(sys.argv[i + 3])
    f = QFont("Arial")
    f.setPixelSize(px)
    p.setFont(f)
    p.drawText(x, y, text)
p.end()
img.save(out, "PNG")
"""


def _render(w: int, h: int, items, native: bool = True) -> bytes:
    """PNG with text items (text, x, baseline_y, px). On Windows the text is drawn in a
    separate Python process with Qt's normal Windows platform, the way real screen text
    looks; the test process itself runs Qt offscreen."""
    import subprocess
    import sys
    import tempfile
    args = [str(v) for item in items for v in item]
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "t.png")
        if native and os.name == "nt":
            env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
            subprocess.run([sys.executable, "-c", _RENDER, out, str(w), str(h), *args],
                           check=True, env=env, timeout=60)
        else:
            from PySide6.QtWidgets import QApplication
            QApplication.instance() or QApplication([])
            ns = {"__name__": "render"}
            old = sys.argv
            sys.argv = ["render", out, str(w), str(h), *args]
            try:
                exec(_RENDER, ns)
            finally:
                sys.argv = old
        with open(out, "rb") as fh:
            return fh.read()


def _text_png(text: str, px: int = 28, native: bool = True) -> bytes:
    return _render(900, 120, [(text, 20, 70, px)], native)


def test_prepare_png_enlarges_small_captures():
    from PySide6.QtGui import QImage
    small = _text_png("Hi", 12)
    out = QImage.fromData(ocr._prepare_png(small)[0])
    assert out.height() > 120


def test_missing_language_message():
    eng = ocr.WindowsOCR()
    eng.installed_tags = lambda: ["en-US"]

    class M:
        class OcrEngine:
            @staticmethod
            def try_create_from_language(lang):
                return object()
        Language = staticmethod(lambda t: t)
    with pytest.raises(ocr.OCRError, match="Arabic"):
        eng._engine({"OcrEngine": M.OcrEngine, "Language": M.Language}, "Arabic")
    assert eng._engine({"OcrEngine": M.OcrEngine, "Language": M.Language}, "English") is not None


windows_ocr = pytest.mark.skipif(not ocr.WindowsOCR().available(), reason="needs Windows OCR")


@windows_ocr
def test_windows_lists_languages():
    langs = ocr.WindowsOCR().languages()
    assert langs, "Windows reported no OCR languages"


@windows_ocr
def test_windows_recognises_rendered_text():
    eng = ocr.WindowsOCR()
    lang = "English" if "English" in eng.languages() else ""
    text = eng.ocr_png(_text_png("Hello PhraseForge 2026"), language=lang)
    if not ("Hello" in text and "2026" in text):
        diag = {f"{'native' if n else 'offscreen'} {px}px scale {sc}":
                ocr.WindowsOCR(scale=sc).ocr_png(_text_png("Hello PhraseForge 2026", px, n), lang)
                for n in (True, False) for px in (14, 28) for sc in (1, 2)}
        raise AssertionError(f"got {text!r}; diagnostics: {diag}")


@windows_ocr
def test_windows_ocr_image_file(tmp_path):
    f = tmp_path / "t.png"
    f.write_bytes(_text_png("Invoice 4521"))
    eng = ocr.WindowsOCR()
    lang = "English" if "English" in eng.languages() else ""
    assert "4521" in eng.ocr_image(str(f), language=lang)


# ---- Text Line / Forward / Bubble capture (pure geometry, no Windows needed)
def _line(text, y, x0=0, word_w=60, gap=10, h=20, rtl=False):
    words, x = [], x0
    parts = text.split()
    if rtl:                      # Arabic: first word on the right
        parts = list(reversed(parts))
    for t in parts:
        words.append(ocr.Word(t, x, y, word_w, h))
        x += word_w + gap
    return ocr.Line(words, text)


def test_pick_line_under_pointer():
    lines = [_line("first line here", 0), _line("second line here", 40), _line("third", 80)]
    assert ocr.pick_line(lines, 50, 45).text == "second line here"
    assert ocr.pick_line(lines, 500, 5).text == "first line here"      # right of the line, same row
    assert ocr.pick_line(lines, 10, 400) is None                        # far below every line


def test_pick_forward_english_and_arabic():
    lines = [_line("one two three four", 0)]
    assert ocr.pick_forward(lines, 75, 10) == "two three four"         # pointer on "two"
    ar = [_line("واحد اثنان ثلاثة اربعة", 0, rtl=True)]
    # words laid out right to left: واحد is rightmost (x=210), اثنان at x=140
    assert ocr.pick_forward(ar, 150, 10) == "اثنان ثلاثة اربعة"


def test_pick_bubble_groups_nearby_lines():
    bubble = [_line("Hello there", 100, x0=100), _line("my friend", 125, x0=110)]
    other = [_line("far away text", 400, x0=100), _line("side text", 100, x0=600)]
    block = ocr.pick_bubble(bubble + other, 120, 110)
    assert [l.text for l in block] == ["Hello there", "my friend"]


def test_character_filters():
    assert ocr.filter_chars("Tel: 050-123 4567", whitelist="0123456789") == " 050123 4567"
    assert ocr.filter_chars("a|b|c", blacklist="|") == "abc"
    assert ocr.is_rtl("مرحبا بالعالم world") and not ocr.is_rtl("hello there مرحبا world")


def test_textline_hotkeys_map_to_commands():
    from phraseforge.triggers.manager import COMMAND_HOTKEY_SETTINGS as M
    assert (M["ocr.textline_hotkey"], M["ocr.forward_hotkey"], M["ocr.bubble_hotkey"]) == \
        ("ocr:textline", "ocr:forward", "ocr:bubble")


@windows_ocr
def test_windows_text_line_under_point():
    png = _render(900, 200, [("Alpha Bravo Charlie", 20, 50, 28), ("Delta Echo Foxtrot", 20, 140, 28)])
    eng = ocr.WindowsOCR()
    lang = "English" if "English" in eng.languages() else ""
    line = eng.ocr_at(png, 150, 130, "line", lang)
    assert "echo" in line.lower() and "alpha" not in line.lower(), line
    assert eng.ocr_at(png, 150, 130, "forward", lang).lower().startswith("echo")


# ---- automatic language (Settings > Screen OCR > OCR language "Auto")
def test_auto_language_helpers():
    assert ocr.is_auto("Auto") and ocr.is_auto(" auto ") and ocr.is_auto("تلقائي")
    assert not ocr.is_auto("English") and not ocr.is_auto("")
    assert ocr.script_of("Arabic") == "arabic" and ocr.script_of("ar-SA") == "arabic"
    assert ocr.script_of("English") == "latin" and ocr.script_of("French") == "latin"
    assert ocr.script_of("Russian") == "cyrillic"
    assert ocr.detect_order(["English", "Arabic", "French", "Russian"]) == \
        ["Arabic", "Russian", "English", "French"]
    assert ocr.script_letters("مرحبا world", "arabic") == (5, 10)


def test_choose_detected():
    # Arabic text: the Arabic recogniser returns Arabic letters, keep it
    assert ocr.choose_detected([("Arabic", "مرحبا بالعالم"), ("English", "pal-JI ~IWI")]) == 0
    # English text: the Arabic recogniser finds hardly any Arabic, fall back to English
    assert ocr.choose_detected([("Arabic", "Hello world ه"), ("English", "Hello world")]) == 1
    assert ocr.choose_detected([("Arabic", ""), ("English", "Invoice 4521")]) == 1
    # only Arabic installed: still the Arabic reading
    assert ocr.choose_detected([("Arabic", "Hello")]) == 0
    assert ocr.choose_detected([]) == -1


def test_auto_reads_each_language_until_one_fits(monkeypatch):
    """Arabic is tried first; an Arabic reading stops the search, otherwise English is used."""
    eng = ocr.WindowsOCR()
    calls = []
    readings = {"Arabic": "مرحبا بالعالم", "English": "pal-JI"}
    monkeypatch.setattr(eng, "languages", lambda: ["English", "Arabic"])
    monkeypatch.setattr(eng, "_engine", lambda m, lang: lang)
    monkeypatch.setattr(eng, "_recognize_with",
                        lambda m, e, png: calls.append(e) or [ocr.Line([], readings[e])])
    assert [l.text for l in eng._recognize_auto({}, b"png")] == ["مرحبا بالعالم"]
    assert calls == ["Arabic"] and eng.last_language == "Arabic"
    calls.clear()
    readings.update(Arabic="Hello ه", English="Hello")
    assert [l.text for l in eng._recognize_auto({}, b"png")] == ["Hello"]
    assert calls == ["Arabic", "English"] and eng.last_language == "English"


def test_ocr_language_defaults_to_auto(tmp_path):
    from phraseforge.db import Store
    s = Store(tmp_path / "a.db")
    assert s.setting("ocr.language") == "Auto"
    s.set_setting("ocr.language", "English")          # old default saved by an older version
    s.set_setting("ocr.auto_migrated", "")
    s.close()
    s = Store(tmp_path / "a.db")
    assert s.setting("ocr.language") == "Auto"
    s.set_setting("ocr.language", "English")          # chosen after the switch: kept
    s.close()
    s = Store(tmp_path / "a.db")
    assert s.setting("ocr.language") == "English"
    s.close()


@windows_ocr
def test_windows_auto_language():
    eng = ocr.WindowsOCR()
    text = eng.ocr_png(_text_png("Hello PhraseForge 2026"), language="Auto")
    assert "Hello" in text and "2026" in text, (text, eng.last_language)
    if "Arabic" in eng.languages():
        ar = eng.ocr_png(_text_png("مرحبا بالعالم"), language="Auto")
        assert eng.last_language == "Arabic" and "مرحبا" in ar, (ar, eng.last_language)
        en = eng.ocr_png(_text_png("Hello PhraseForge 2026"), language="Auto")
        assert "Hello" in en, (en, eng.last_language)
