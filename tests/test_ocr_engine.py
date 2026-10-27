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


def _text_png(text: str, px: int = 28) -> bytes:
    from PySide6.QtCore import QBuffer, QIODevice, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    img = QImage(900, 120, QImage.Format_ARGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    f = QFont("Arial")
    f.setPixelSize(px)
    p.setFont(f)
    p.setPen(QColor("black"))
    p.drawText(img.rect(), Qt.AlignCenter, text)
    p.end()
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


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
    assert "hello" in text.lower() and "2026" in text


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
    from PySide6.QtCore import QBuffer, QIODevice, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    img = QImage(900, 200, QImage.Format_ARGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    f = QFont("Arial")
    f.setPixelSize(28)
    p.setFont(f)
    p.setPen(QColor("black"))
    p.drawText(20, 50, "Alpha Bravo Charlie")
    p.drawText(20, 140, "Delta Echo Foxtrot")
    p.end()
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    eng = ocr.WindowsOCR()
    lang = "English" if "English" in eng.languages() else ""
    assert "Echo" in eng.ocr_at(bytes(buf.data()), 150, 130, "line", lang)
    assert eng.ocr_at(bytes(buf.data()), 150, 130, "forward", lang).startswith("Echo")


def test_auto_scale_enlarges_only_small_text(monkeypatch):
    calls = []

    def fake_once(self, m, engine, png, scale):
        calls.append(scale)
        h = {1: 9 if png == b"small" else 30, 2: 18, 3: 27}[scale]
        return [ocr.Line([ocr.Word("w", 0, 0, 10, h)], "word" * scale)]

    monkeypatch.setattr(ocr.WindowsOCR, "_recognize_once", fake_once)
    monkeypatch.setattr(ocr.WindowsOCR, "_modules", staticmethod(lambda: {}))
    monkeypatch.setattr(ocr.WindowsOCR, "_engine", lambda self, m, lang: object())
    eng = ocr.WindowsOCR()
    eng.recognize(b"large")
    assert calls == [1]                       # 30 px text: read once, not enlarged
    calls.clear()
    eng.recognize(b"small")
    assert calls == [1, 3]                    # 9 px text: read again at 3x
    calls.clear()
    ocr.WindowsOCR(scale=2).recognize(b"large")
    assert calls == [2]                       # a fixed scale from Settings is used as is
