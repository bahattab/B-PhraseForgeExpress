"""Win32 clipboard: text, HTML (CF_HTML), images, save/restore, change watcher."""
from __future__ import annotations

import ctypes
import logging
import threading
import time
from pathlib import Path
from typing import Callable

from ctypes import wintypes as wt

from phraseforge.platform._win32 import (
    HWND_MESSAGE, WM_CLIPBOARDUPDATE, WM_QUIT, WNDCLASSW, WNDPROC, kernel32, user32,
)

log = logging.getLogger(__name__)

CF_TEXT, CF_BITMAP, CF_METAFILEPICT, CF_OEMTEXT, CF_DIB = 1, 2, 3, 7, 8
CF_PALETTE, CF_UNICODETEXT, CF_ENHMETAFILE, CF_HDROP, CF_LOCALE, CF_DIBV5 = 9, 13, 14, 15, 16, 17
CF_OWNERDISPLAY, CF_DSPBITMAP, CF_DSPMETAFILEPICT, CF_DSPENHMETAFILE = 0x80, 0x82, 0x83, 0x8E
GMEM_MOVEABLE = 0x0002
_GDI_FORMATS = {CF_BITMAP, CF_METAFILEPICT, CF_PALETTE, CF_ENHMETAFILE, CF_OWNERDISPLAY,
                CF_DSPBITMAP, CF_DSPMETAFILEPICT, CF_DSPENHMETAFILE}
# Formats Windows synthesizes from others; restoring them is redundant.
_SYNTHESIZED = {CF_TEXT, CF_OEMTEXT, CF_LOCALE, CF_DIBV5}

# Sequence numbers produced by our own writes; watchers skip these.
_own_sequences: set[int] = set()
_own_lock = threading.Lock()
_last_snapshot: list[tuple[int, bytes]] | None = None


class ClipboardError(RuntimeError):
    pass


class _Open:
    def __init__(self, retries: int = 20, delay: float = 0.02):
        self.retries, self.delay = retries, delay

    def __enter__(self):
        for _ in range(self.retries):
            if user32.OpenClipboard(None):
                return self
            time.sleep(self.delay)
        raise ClipboardError("could not open clipboard (in use by another app)")

    def __exit__(self, *exc):
        user32.CloseClipboard()


def _mark_own() -> None:
    with _own_lock:
        _own_sequences.add(user32.GetClipboardSequenceNumber())
        if len(_own_sequences) > 64:
            _own_sequences.clear()
            _own_sequences.add(user32.GetClipboardSequenceNumber())


def is_own_change(seq: int | None = None) -> bool:
    seq = user32.GetClipboardSequenceNumber() if seq is None else seq
    with _own_lock:
        return seq in _own_sequences


def _put(fmt: int, data: bytes) -> None:
    h = kernel32.GlobalAlloc(GMEM_MOVEABLE, max(1, len(data)))
    if not h:
        raise ClipboardError("GlobalAlloc failed")
    p = kernel32.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    kernel32.GlobalUnlock(h)
    if not user32.SetClipboardData(fmt, h):
        kernel32.GlobalFree(h)
        raise ClipboardError(f"SetClipboardData({fmt}) failed")


def _get(fmt: int) -> bytes | None:
    h = user32.GetClipboardData(fmt)
    if not h:
        return None
    size = kernel32.GlobalSize(h)
    p = kernel32.GlobalLock(h)
    if not p:
        return None
    try:
        return ctypes.string_at(p, size)
    finally:
        kernel32.GlobalUnlock(h)


def _utf16z(text: str) -> bytes:
    return text.encode("utf-16-le") + b"\x00\x00"


def get_text() -> str:
    with _Open():
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return ""
        raw = _get(CF_UNICODETEXT)
    if not raw:
        return ""
    text = raw.decode("utf-16-le", errors="replace")
    return text.split("\x00", 1)[0]


def set_text(text: str) -> None:
    with _Open():
        user32.EmptyClipboard()
        _put(CF_UNICODETEXT, _utf16z(text))
    _mark_own()


def html_format_id() -> int:
    return user32.RegisterClipboardFormatW("HTML Format")


def build_cf_html(fragment: str, source_url: str = "") -> bytes:
    """Build the CF_HTML payload with correct byte offsets (UTF-8).
    https://learn.microsoft.com/windows/win32/dataxchg/html-clipboard-format"""
    pre = "<html><body>\r\n<!--StartFragment-->"
    post = "<!--EndFragment-->\r\n</body></html>"
    header_tpl = ("Version:0.9\r\nStartHTML:{0:010d}\r\nEndHTML:{1:010d}\r\n"
                  "StartFragment:{2:010d}\r\nEndFragment:{3:010d}\r\n")
    if source_url:
        header_tpl += "SourceURL:" + source_url + "\r\n"
    header_len = len(header_tpl.format(0, 0, 0, 0).encode("utf-8"))
    frag_b = fragment.encode("utf-8")
    start_html = header_len
    start_frag = start_html + len(pre.encode("utf-8"))
    end_frag = start_frag + len(frag_b)
    end_html = end_frag + len(post.encode("utf-8"))
    header = header_tpl.format(start_html, end_html, start_frag, end_frag)
    return header.encode("utf-8") + pre.encode("utf-8") + frag_b + post.encode("utf-8")


def parse_cf_html(data: bytes) -> str:
    """Return the fragment from a CF_HTML payload."""
    head = data[:400].decode("utf-8", errors="replace")
    vals = {}
    for line in head.split("\r\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            vals[k] = v
    try:
        s, e = int(vals["StartFragment"]), int(vals["EndFragment"])
        return data[s:e].decode("utf-8", errors="replace")
    except (KeyError, ValueError):
        return data.decode("utf-8", errors="replace")


def rtf_format_id() -> int:
    return user32.RegisterClipboardFormatW("Rich Text Format")


def set_html(html: str, plain: str, formats: str = "html") -> None:
    """Put formatted text on the clipboard. formats: "html", "rtf" or "rtf_html"
    (PhraseExpress's "HTML only" / "RTF only" / "RTF & HTML"). Plain text is always added."""
    with _Open():
        user32.EmptyClipboard()
        if formats in ("html", "rtf_html", "auto"):
            _put(html_format_id(), build_cf_html(html) + b"\x00")
        if formats in ("rtf", "rtf_html", "auto"):
            from phraseforge.rtf import html_to_rtf
            _put(rtf_format_id(), html_to_rtf(html).encode("ascii", errors="replace") + b"\x00")
        _put(CF_UNICODETEXT, _utf16z(plain))
    _mark_own()


def get_html() -> str:
    fmt = html_format_id()
    with _Open():
        if not user32.IsClipboardFormatAvailable(fmt):
            return ""
        raw = _get(fmt)
    return parse_cf_html(raw.rstrip(b"\x00")) if raw else ""


def set_image(path: str) -> None:
    """Put an image on the clipboard. BMP -> CF_DIB; PNG -> 'PNG' format plus
    CF_DIB when the file can be converted with GDI+ (best effort)."""
    p = Path(path)
    data = p.read_bytes()
    ext = p.suffix.lower()
    dib = None
    png = None
    if ext == ".bmp" and data[:2] == b"BM":
        dib = data[14:]
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        png = data
        dib = _gdiplus_to_dib(str(p))
    else:
        dib = _gdiplus_to_dib(str(p))
        if dib is None:
            raise ClipboardError(f"unsupported image format: {path}")
    with _Open():
        user32.EmptyClipboard()
        if png:
            _put(user32.RegisterClipboardFormatW("PNG"), png)
        if dib:
            _put(CF_DIB, dib)
    _mark_own()


def _gdiplus_to_dib(path: str) -> bytes | None:
    """Decode any GDI+-supported image into a 32-bit top-down DIB."""
    try:
        gdip = ctypes.WinDLL("gdiplus")

        class StartupInput(ctypes.Structure):
            _fields_ = [("GdiplusVersion", ctypes.c_uint32), ("DebugEventCallback", ctypes.c_void_p),
                        ("SuppressBackgroundThread", wt.BOOL), ("SuppressExternalCodecs", wt.BOOL)]

        token = ctypes.c_size_t()
        si = StartupInput(1, None, False, False)
        if gdip.GdiplusStartup(ctypes.byref(token), ctypes.byref(si), None) != 0:
            return None
        try:
            img = ctypes.c_void_p()
            if gdip.GdipCreateBitmapFromFile(ctypes.c_wchar_p(path), ctypes.byref(img)) != 0:
                return None
            w, h = ctypes.c_uint(), ctypes.c_uint()
            gdip.GdipGetImageWidth(img, ctypes.byref(w))
            gdip.GdipGetImageHeight(img, ctypes.byref(h))

            class Rect(ctypes.Structure):
                _fields_ = [("X", ctypes.c_int), ("Y", ctypes.c_int), ("Width", ctypes.c_int), ("Height", ctypes.c_int)]

            class BitmapData(ctypes.Structure):
                _fields_ = [("Width", ctypes.c_uint), ("Height", ctypes.c_uint), ("Stride", ctypes.c_int),
                            ("PixelFormat", ctypes.c_int), ("Scan0", ctypes.c_void_p), ("Reserved", ctypes.c_size_t)]

            PixelFormat32bppARGB = 0x26200A
            rect = Rect(0, 0, w.value, h.value)
            bd = BitmapData()
            if gdip.GdipBitmapLockBits(img, ctypes.byref(rect), 1, PixelFormat32bppARGB, ctypes.byref(bd)) != 0:
                gdip.GdipDisposeImage(img)
                return None
            rows = [ctypes.string_at(bd.Scan0 + y * bd.Stride, w.value * 4) for y in range(h.value)]
            gdip.GdipBitmapUnlockBits(img, ctypes.byref(bd))
            gdip.GdipDisposeImage(img)
        finally:
            gdip.GdiplusShutdown(token)
        import struct
        header = struct.pack("<IiiHHIIiiII", 40, w.value, -h.value, 1, 32, 0, w.value * h.value * 4, 0, 0, 0, 0)
        return header + b"".join(rows)
    except Exception:
        log.exception("GDI+ image decode failed")
        return None


def save_all() -> list[tuple[int, bytes]]:
    """Snapshot every memory-based clipboard format. Also kept as the default for restore()."""
    global _last_snapshot
    snap: list[tuple[int, bytes]] = []
    try:
        with _Open():
            fmt = 0
            while True:
                fmt = user32.EnumClipboardFormats(fmt)
                if not fmt:
                    break
                if fmt in _GDI_FORMATS or fmt in _SYNTHESIZED:
                    continue
                try:
                    data = _get(fmt)
                except Exception:
                    data = None
                if data is not None:
                    snap.append((fmt, data))
    except ClipboardError:
        log.warning("clipboard busy; snapshot skipped")
    _last_snapshot = snap
    return snap


def restore(snapshot: list[tuple[int, bytes]] | None = None) -> None:
    snap = _last_snapshot if snapshot is None else snapshot
    if snap is None:
        return
    with _Open():
        user32.EmptyClipboard()
        for fmt, data in snap:
            try:
                _put(fmt, data)
            except ClipboardError:
                pass
    _mark_own()


def sequence_number() -> int:
    return user32.GetClipboardSequenceNumber()


class ClipboardWatcher:
    """Calls on_change(text) on a background thread whenever another program
    changes the clipboard text. Our own writes (set_text, set_html, restore...)
    are skipped."""

    _class_lock = threading.Lock()
    _class_registered = False
    _CLASS_NAME = "PhraseForgeClipboardWatcher"
    _instances: dict[int, "ClipboardWatcher"] = {}

    def __init__(self, on_change: Callable[[str], None], debounce_s: float = 0.05):
        self.on_change = on_change
        self.debounce_s = debounce_s
        self._thread: threading.Thread | None = None
        self._tid = 0
        self._hwnd = None
        self._ready = threading.Event()
        self._last_text = ""
        self._last_time = 0.0

    @classmethod
    def _wndproc_impl(cls, hwnd, msg, wparam, lparam):
        if msg == WM_CLIPBOARDUPDATE:
            inst = cls._instances.get(hwnd)
            if inst:
                inst._handle_update()
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="pf-clipboard-watch", daemon=True)
        self._thread.start()
        self._ready.wait(5)

    def stop(self) -> None:
        if self._thread and self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._thread.join(3)
        self._thread = None

    def _run(self) -> None:
        cls = type(self)
        hinst = kernel32.GetModuleHandleW(None)
        with cls._class_lock:
            if not cls._class_registered:
                cls._wndproc = WNDPROC(cls._wndproc_impl)
                wc = WNDCLASSW()
                wc.lpfnWndProc = cls._wndproc
                wc.hInstance = hinst
                wc.lpszClassName = cls._CLASS_NAME
                if not user32.RegisterClassW(ctypes.byref(wc)):
                    log.error("RegisterClassW failed: %s", ctypes.get_last_error())
                cls._class_registered = True
        self._tid = kernel32.GetCurrentThreadId()
        self._hwnd = user32.CreateWindowExW(0, cls._CLASS_NAME, "pf-clip", 0, 0, 0, 0, 0,
                                            HWND_MESSAGE, None, hinst, None)
        if not self._hwnd:
            log.error("CreateWindowExW failed: %s", ctypes.get_last_error())
            self._ready.set()
            return
        cls._instances[self._hwnd] = self
        user32.AddClipboardFormatListener(self._hwnd)
        self._ready.set()
        msg = wt.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.RemoveClipboardFormatListener(self._hwnd)
            cls._instances.pop(self._hwnd, None)
            user32.DestroyWindow(self._hwnd)
            self._hwnd = None

    def _handle_update(self) -> None:
        seq = sequence_number()
        if is_own_change(seq):
            return
        time.sleep(self.debounce_s)   # let the owner finish writing all formats
        if is_own_change():
            return
        try:
            text = get_text()
        except ClipboardError:
            return
        now = time.monotonic()
        # apps often fire several updates for one copy; report each text once
        if text and not (text == self._last_text and now - self._last_time < 1.0):
            self._last_text, self._last_time = text, now
            try:
                self.on_change(text)
            except Exception:
                log.exception("clipboard on_change failed")
