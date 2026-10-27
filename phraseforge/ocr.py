"""Screen and image OCR, built into PhraseForge.

Text recognition runs inside PhraseForge through the OCR engine that ships with
Windows 10/11 (Windows.Media.Ocr, called in-process through the official WinRT
Python bindings). No other program is started. The Capture2Text-style options
(language, quick languages, re-capture, line breaks, replace rules, log file)
are implemented on top of it in this module and in app.py.

Languages: Windows recognises a language when its OCR component is installed
(Settings > Time & language > Language & region > add the language). English is
present on every English Windows; Arabic needs the Arabic language added.
"""
from __future__ import annotations

import asyncio
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path


class OCRError(RuntimeError):
    pass


# Capture2Text-style language names <-> BCP-47 primary tags used by Windows OCR.
LANGUAGE_TAGS = {
    "Arabic": "ar", "English": "en", "French": "fr", "German": "de", "Spanish": "es",
    "Italian": "it", "Portuguese": "pt", "Russian": "ru", "Turkish": "tr", "Dutch": "nl",
    "Polish": "pl", "Swedish": "sv", "Danish": "da", "Norwegian": "nb", "Finnish": "fi",
    "Czech": "cs", "Greek": "el", "Hungarian": "hu", "Romanian": "ro", "Serbian": "sr",
    "Croatian": "hr", "Slovak": "sk", "Slovenian": "sl", "Bulgarian": "bg", "Ukrainian": "uk",
    "Chinese (Simplified)": "zh-Hans", "Chinese (Traditional)": "zh-Hant", "Japanese": "ja",
    "Korean": "ko", "Hindi": "hi", "Hebrew": "he", "Persian": "fa", "Urdu": "ur",
    "Indonesian": "id", "Malay": "ms", "Vietnamese": "vi", "Thai": "th",
}
_TAG_NAMES = {v.lower(): k for k, v in LANGUAGE_TAGS.items()}

MISSING_LANGUAGE_HELP = (
    "Windows has no OCR for {name}. Add it once: Windows Settings > Time & language > "
    "Language & region > Add a language > {name} (keep \"Optical character recognition\" "
    "ticked), then try again.")
MISSING_LANGUAGE_HELP_AR = (
    "لا يوجد في ويندوز تعرّف ضوئي للغة {name}. أضفها مرة واحدة: إعدادات ويندوز > الوقت واللغة > "
    "اللغة والمنطقة > إضافة لغة > {name} (مع إبقاء خيار \"التعرّف الضوئي على الحروف\" محددًا)، ثم أعد المحاولة.")
_AR_NAMES = {"Arabic": "العربية", "English": "الإنجليزية", "French": "الفرنسية", "German": "الألمانية",
             "Spanish": "الإسبانية", "Russian": "الروسية", "Turkish": "التركية", "Persian": "الفارسية",
             "Urdu": "الأردية", "Chinese (Simplified)": "الصينية المبسطة", "Japanese": "اليابانية"}


def _missing(name: str) -> str:
    try:
        from phraseforge.ui import i18n
        if i18n.language() == "ar":
            return MISSING_LANGUAGE_HELP_AR.format(name=_AR_NAMES.get(name, name))
    except Exception:
        pass
    return MISSING_LANGUAGE_HELP.format(name=name)


def language_tag(name: str) -> str:
    """'Arabic' -> 'ar'; 'ar-SA' and 'ar' are returned as they are."""
    n = (name or "").strip()
    if not n:
        return ""
    for k, v in LANGUAGE_TAGS.items():
        if k.lower() == n.lower():
            return v
    return n


def language_name(tag: str) -> str:
    """'ar-SA' -> 'Arabic', 'zh-Hans-CN' -> 'Chinese (Simplified)'; unknown tags are returned as is."""
    t = (tag or "").strip()
    low = t.lower()
    for key in sorted(_TAG_NAMES, key=len, reverse=True):     # longest first: zh-hans before zh
        if low == key or low.startswith(key + "-"):
            return _TAG_NAMES[key]
    return t


def _tag_matches(installed: str, wanted: str) -> bool:
    a, b = installed.lower(), wanted.lower()
    return a == b or a.startswith(b + "-") or b.startswith(a + "-")


@dataclass
class Word:
    text: str
    x: float
    y: float
    w: float
    h: float


@dataclass
class Line:
    words: list[Word] = field(default_factory=list)
    text: str = ""

    @property
    def top(self) -> float:
        return min((w.y for w in self.words), default=0)

    @property
    def bottom(self) -> float:
        return max((w.y + w.h for w in self.words), default=0)

    @property
    def left(self) -> float:
        return min((w.x for w in self.words), default=0)

    @property
    def right(self) -> float:
        return max((w.x + w.w for w in self.words), default=0)

    @property
    def rtl(self) -> bool:
        return is_rtl(self.text)


def is_rtl(text: str) -> bool:
    """True when the text is mostly Arabic/Hebrew/Persian letters."""
    rtl = sum(1 for c in text if "֐" <= c <= "ࣿ" or "יִ" <= c <= "ﻼ")
    ltr = sum(1 for c in text if c.isalpha() and c.isascii())
    return rtl > ltr


def filter_chars(text: str, whitelist: str = "", blacklist: str = "") -> str:
    """Capture2Text-style character filters: keep only whitelisted characters (when a
    whitelist is set; spaces and line breaks always stay) and drop blacklisted ones."""
    if whitelist:
        keep = set(whitelist) | {" ", "\n", "\t"}
        text = "".join(c for c in text if c in keep)
    if blacklist:
        drop = set(blacklist) - {"\n"}
        text = "".join(c for c in text if c not in drop)
    return text


def _join(lines: list[Line], keep_line_breaks: bool) -> str:
    parts = [l.text.strip() for l in lines if l.text and l.text.strip()]
    return ("\n" if keep_line_breaks else " ").join(parts)


def pick_line(lines: list[Line], x: float, y: float) -> Line | None:
    """The text line under (or nearest to) the point: Capture2Text's "Text Line Capture"."""
    best, best_d = None, None
    for line in lines:
        if not line.words:
            continue
        dy = 0 if line.top <= y <= line.bottom else min(abs(y - line.top), abs(y - line.bottom))
        dx = 0 if line.left <= x <= line.right else min(abs(x - line.left), abs(x - line.right))
        d = (dy * 4 + dx, dy)
        if best_d is None or d < best_d:
            best, best_d = line, d
    if best is None:
        return None
    h = max(1.0, best.bottom - best.top)
    return best if best_d[1] <= h * 1.5 else None


def pick_forward(lines: list[Line], x: float, y: float) -> str:
    """From the word under the point to the end of its line, in reading direction
    (rightwards for English, leftwards for Arabic): "Forward Text Line Capture"."""
    line = pick_line(lines, x, y)
    if line is None:
        return ""
    if line.rtl:
        words = sorted(line.words, key=lambda w: w.x, reverse=True)      # right to left
        start = next((i for i, w in enumerate(words) if w.x <= x), len(words))
    else:
        words = sorted(line.words, key=lambda w: w.x)
        start = next((i for i, w in enumerate(words) if w.x + w.w >= x), len(words))
    return " ".join(w.text for w in words[start:])


def pick_bubble(lines: list[Line], x: float, y: float) -> list[Line]:
    """The block of text around the point (a speech bubble or paragraph): the line
    under the point plus neighbouring lines that are close to it and overlap it."""
    first = pick_line(lines, x, y)
    if first is None:
        return []
    block = [first]
    heights = sorted(max(1.0, l.bottom - l.top) for l in lines if l.words)
    gap = 1.2 * heights[len(heights) // 2]
    changed = True
    while changed:
        changed = False
        top, bottom = min(l.top for l in block), max(l.bottom for l in block)
        left, right = min(l.left for l in block), max(l.right for l in block)
        for line in lines:
            if line in block or not line.words:
                continue
            near = (0 <= top - line.bottom <= gap) or (0 <= line.top - bottom <= gap)
            overlap = min(right, line.right) - max(left, line.left) > 0
            if near and overlap:
                block.append(line)
                changed = True
    return sorted(block, key=lambda l: l.top)


def _prepare_png(png: bytes, max_dim: int = 0, scale: int = 0) -> tuple[bytes, float, int, float]:
    """Make small captures easier to read: enlarge text that is only a few pixels high
    (Capture2Text's scale factor; scale=0 picks it from the image height) and add a white
    margin. Returns (png, scale, pad, shrink); word boxes map back to the original image
    as original = (prepared / shrink - pad) / scale."""
    try:
        from PySide6.QtCore import QBuffer, QIODevice, Qt
        from PySide6.QtGui import QColor, QImage, QPainter
    except ImportError:
        return png, 1.0, 0, 1.0
    img = QImage.fromData(png)
    if img.isNull():
        raise OCRError("The image could not be read.")
    w, h = img.width(), img.height()
    if not scale:
        scale = 3 if h < 40 else 2 if h < 200 else 1
    scale = max(1, min(4, int(scale)))
    pad = 20
    if max_dim:
        while scale > 1 and max(w, h) * scale + 2 * pad > max_dim:
            scale -= 1
    if scale > 1:
        img = img.scaled(w * scale, h * scale, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    out = QImage(img.width() + 2 * pad, img.height() + 2 * pad, QImage.Format_ARGB32)
    out.fill(QColor("white"))
    p = QPainter(out)
    p.drawImage(pad, pad, img)
    p.end()
    shrink = 1.0
    if max_dim and max(out.width(), out.height()) > max_dim:
        before = out.width()
        out = out.scaled(max_dim, max_dim, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        shrink = out.width() / before
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    out.save(buf, "PNG")
    return bytes(buf.data()), float(scale), pad, shrink


class WindowsOCR:
    """OCR engine built into Windows, used in-process (no external program).

    scale: 0 = automatic, 1-4 = enlarge the capture that many times before reading.
    whitelist / blacklist: characters to keep only / to remove from the result."""

    _lock = threading.Lock()

    def __init__(self, scale: int = 0, whitelist: str = "", blacklist: str = ""):
        self.scale, self.whitelist, self.blacklist = scale, whitelist, blacklist

    @staticmethod
    def _modules():
        if os.name != "nt":
            raise OCRError("Screen OCR needs Windows 10 or 11.")
        try:
            from winrt.windows.globalization import Language
            from winrt.windows.graphics.imaging import (
                BitmapAlphaMode, BitmapDecoder, BitmapPixelFormat, SoftwareBitmap)
            from winrt.windows.media.ocr import OcrEngine
            from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
        except ImportError as e:
            raise OCRError(f"The Windows OCR component is missing from this build ({e}).") from e
        return dict(Language=Language, BitmapAlphaMode=BitmapAlphaMode, BitmapDecoder=BitmapDecoder,
                    BitmapPixelFormat=BitmapPixelFormat, SoftwareBitmap=SoftwareBitmap, OcrEngine=OcrEngine,
                    DataWriter=DataWriter, InMemoryRandomAccessStream=InMemoryRandomAccessStream)

    def available(self) -> bool:
        try:
            self._modules()
            return True
        except OCRError:
            return False

    def installed_tags(self) -> list[str]:
        m = self._modules()
        return [lang.language_tag for lang in m["OcrEngine"].available_recognizer_languages]

    def languages(self) -> list[str]:
        """Installed OCR languages as names ('Arabic', 'English', ...)."""
        out: list[str] = []
        for tag in self.installed_tags():
            name = language_name(tag)
            if name not in out:
                out.append(name)
        return out

    def _engine(self, m, language: str):
        if not (language or "").strip():
            engine = m["OcrEngine"].try_create_from_user_profile_languages()
            if engine is None:
                raise OCRError("Windows has no OCR language installed.")
            return engine
        wanted = language_tag(language)
        tags = self.installed_tags()
        tag = next((t for t in tags if t.lower() == wanted.lower()), None) or \
            next((t for t in tags if _tag_matches(t, wanted)), None)
        if tag is None:
            raise OCRError(_missing(language_name(wanted) or language))
        engine = m["OcrEngine"].try_create_from_language(m["Language"](tag))
        if engine is None:
            raise OCRError(_missing(language_name(tag)))
        return engine

    def recognize(self, png: bytes, language: str = "English") -> list[Line]:
        """Lines with their words and word boxes, in the coordinates of the given image.

        Automatic scale: read the capture as it is first; only when the recognised text
        is small (under 20 pixels high) read it again enlarged 2x or 3x. Enlarging text
        that is already large makes Windows OCR worse, so it is never done blindly."""
        if not png:
            raise OCRError("Nothing was captured.")
        m = self._modules()
        engine = self._engine(m, language)
        if self.scale:
            return self._recognize_once(m, engine, png, self.scale)
        lines = self._recognize_once(m, engine, png, 1)
        heights = sorted(w.h for l in lines for w in l.words if w.h > 0)
        median = heights[len(heights) // 2] if heights else 0
        if not lines or median < 20:
            bigger = self._recognize_once(m, engine, png, 3 if 0 < median < 10 else 2)
            if sum(len(l.text) for l in bigger) >= sum(len(l.text) for l in lines):
                return bigger
        return lines

    def _recognize_once(self, m, engine, png: bytes, scale: int) -> list[Line]:
        data, scale, pad, shrink = _prepare_png(png, int(m["OcrEngine"].max_image_dimension or 0), scale)

        async def run():
            stream = m["InMemoryRandomAccessStream"]()
            writer = m["DataWriter"](stream)
            writer.write_bytes(data)
            await writer.store_async()
            await writer.flush_async()
            writer.detach_stream()
            stream.seek(0)
            decoder = await m["BitmapDecoder"].create_async(stream)
            bitmap = await decoder.get_software_bitmap_async()
            if bitmap.bitmap_pixel_format != m["BitmapPixelFormat"].BGRA8:
                bitmap = m["SoftwareBitmap"].convert(bitmap, m["BitmapPixelFormat"].BGRA8,
                                                     m["BitmapAlphaMode"].PREMULTIPLIED)
            result = await engine.recognize_async(bitmap)
            out = []
            for line in result.lines:
                words = []
                for word in line.words:
                    r = word.bounding_rect
                    words.append(Word(word.text,
                                      (r.x / shrink - pad) / scale, (r.y / shrink - pad) / scale,
                                      r.width / shrink / scale, r.height / shrink / scale))
                out.append(Line(words, line.text))
            return out

        with self._lock:
            try:
                return asyncio.run(run())
            except OCRError:
                raise
            except Exception as e:  # WinRT errors arrive as OSError with an HRESULT
                raise OCRError(f"Windows OCR failed: {e}") from e

    def finish(self, text: str) -> str:
        return filter_chars(text, self.whitelist, self.blacklist).strip()

    def ocr_png(self, png: bytes, language: str = "English", keep_line_breaks: bool = True) -> str:
        return self.finish(_join(self.recognize(png, language), keep_line_breaks))

    def ocr_at(self, png: bytes, x: float, y: float, mode: str = "line", language: str = "English",
               keep_line_breaks: bool = True) -> str:
        """Text at a point of the image: mode "line" (the line under the point), "forward"
        (from the point to the end of the line) or "bubble" (the block around the point)."""
        lines = self.recognize(png, language)
        if mode == "forward":
            return self.finish(pick_forward(lines, x, y))
        if mode == "bubble":
            return self.finish(_join(pick_bubble(lines, x, y), keep_line_breaks))
        line = pick_line(lines, x, y)
        return self.finish(line.text if line else "")

    def ocr_image(self, path: str, language: str = "English", keep_line_breaks: bool = True) -> str:
        if not Path(path).is_file():
            raise OCRError(f"Image not found: {path}")
        return self.ocr_png(Path(path).read_bytes(), language, keep_line_breaks)


def engine() -> WindowsOCR:
    return WindowsOCR()


# ---- post-processing (modelled on Capture2Text's Settings > Replace and Output > Logging pages)

def parse_replace_rules(text: str) -> list[tuple[str | None, str, str]]:
    """Rules, one per line: ``regex => replacement``.

    A line ``[Arabic]`` starts a section whose rules apply only when OCR ran in that
    language; rules before any section apply to every language. Blank lines and lines
    starting with ``#`` are ignored. Bad regexes are skipped.
    """
    import re
    rules: list[tuple[str | None, str, str]] = []
    lang: str | None = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            lang = line[1:-1].strip() or None
            continue
        if "=>" not in raw:
            continue
        find, _, repl = raw.partition("=>")
        find, repl = find.strip(), repl.strip()
        if not find:
            continue
        try:
            re.compile(find)
        except re.error:
            continue
        rules.append((lang, find, repl.replace("\\n", "\n").replace("\\t", "\t")))
    return rules


def apply_replacements(text: str, rules, language: str = "") -> str:
    import re
    for lang, find, repl in rules:
        if lang is None or lang.lower() == (language or "").lower():
            text = re.sub(find, repl, text)
    return text


def format_log_entry(text: str, fmt: str = "${capture}${linebreak}", when=None) -> str:
    from datetime import datetime
    when = when or datetime.now()
    return ((fmt or "${capture}${linebreak}")
            .replace("${capture}", text)
            .replace("${linebreak}", "\n")
            .replace("${tab}", "\t")
            .replace("${timestamp}", when.strftime("%Y-%m-%d %H:%M:%S")))


def quick_languages(value: str) -> list[str]:
    """Up to three quick-access languages from 'Arabic, English, ...'."""
    out = []
    for part in (value or "").replace(";", ",").split(","):
        p = part.strip()
        if p and p not in out:
            out.append(p)
    return out[:3]
