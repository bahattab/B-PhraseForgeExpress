"""Where the text caret is, in more programs (PRD FR-INP-05, G-07).

Chain, first answer wins:
  1. win32: GetGUIThreadInfo, the classic Win32 caret (Notepad, most dialogs, Qt).
  2. msaa:  AccessibleObjectFromWindow(OBJID_CARET), which Chrome, Edge, Electron apps
            (VS Code, Teams) and Office provide for screen magnifiers.
  3. uia:   UI Automation, TextPattern2.GetCaretRange (or the selection of TextPattern),
            for WPF, UWP / WinUI and modern Office.
When none answers, callers fall back to the mouse (Settings > Popup menu > position).

MSAA and UIA ask the target program over COM, which can take long when it is busy. They run
on one worker thread and the caller waits at most TIMEOUT_S; a hung window is not asked at all.
All rectangles are physical screen pixels (left, top, right, bottom).
"""
from __future__ import annotations

import logging
import os
import queue
import threading
from typing import Callable

log = logging.getLogger(__name__)

TIMEOUT_S = 0.25
OBJID_CARET = 0xFFFFFFF8
CHILDID_SELF = 0
UIA_TextPatternId, UIA_TextPattern2Id = 10014, 10024
TextUnit_Character = 0
TextPatternRangeEndpoint_Start = 0

Rect = tuple[int, int, int, int]


# ---------------------------------------------------------------- pure helpers (tested anywhere)
def rect_from_uia(values, at_end: bool = False) -> Rect | None:
    """UIA GetBoundingRectangles() gives (left, top, width, height) per line. The caret is at
    the start of the first rectangle, or at the end of the last one when the range was
    widened backwards (caret after the last character)."""
    vals = [float(v) for v in (values or ())]
    if len(vals) < 4:
        return None
    l, t, w, h = vals[-4:] if at_end else vals[:4]
    if h <= 0:
        return None
    x = l + w if at_end else l
    return int(round(x)), int(round(t)), int(round(x)) + 1, int(round(t + h))


def plausible(rect: Rect | None, window: Rect | None, slack: int = 80) -> bool:
    """Reject empty rectangles, (0,0) and rectangles far outside the foreground window."""
    if not rect:
        return False
    l, t, r, b = rect
    if b <= t or (l == 0 and t == 0):
        return False
    if window:
        wl, wt, wr, wb = window
        if l < wl - slack or l > wr + slack or t < wt - slack or b > wb + slack:
            return False
    return True


def first_caret(sources: list[tuple[str, Callable[[], Rect | None]]], window: Rect | None):
    """(rect, source name) from the first source that gives a plausible rectangle."""
    for name, fn in sources:
        try:
            rect = fn()
        except Exception:
            log.debug("caret source %s failed", name, exc_info=True)
            continue
        if plausible(rect, window):
            return rect, name
    return None, ""


# ---------------------------------------------------------------- Windows sources
def _foreground():
    from phraseforge.platform._win32 import user32
    return user32.GetForegroundWindow()


def _window_rect(hwnd) -> Rect | None:
    import ctypes
    from ctypes import wintypes as wt
    from phraseforge.platform._win32 import user32
    r = wt.RECT()
    if not hwnd or not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return r.left, r.top, r.right, r.bottom


def win32_caret() -> Rect | None:
    import ctypes
    from ctypes import wintypes as wt
    from phraseforge.platform._win32 import GUITHREADINFO, user32
    hwnd = _foreground()
    if not hwnd:
        return None
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(GUITHREADINFO)
    if not user32.GetGUIThreadInfo(user32.GetWindowThreadProcessId(hwnd, None), ctypes.byref(info)):
        return None
    if not info.hwndCaret:
        return None
    tl = wt.POINT(info.rcCaret.left, info.rcCaret.top)
    br = wt.POINT(info.rcCaret.right, info.rcCaret.bottom)
    if not (user32.ClientToScreen(info.hwndCaret, ctypes.byref(tl))
            and user32.ClientToScreen(info.hwndCaret, ctypes.byref(br))):
        return None
    return tl.x, tl.y, max(br.x, tl.x + 1), br.y


def _focus_hwnd():
    import ctypes
    from phraseforge.platform._win32 import GUITHREADINFO, user32
    hwnd = _foreground()
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(GUITHREADINFO)
    if hwnd and user32.GetGUIThreadInfo(user32.GetWindowThreadProcessId(hwnd, None), ctypes.byref(info)):
        return info.hwndFocus or hwnd
    return hwnd


class _Com:
    """COM objects of the worker thread (created there, used only there)."""

    def __init__(self):
        import comtypes
        import comtypes.client as cc
        try:
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        except OSError:            # importing comtypes already initialised COM on this thread
            pass
        cc.GetModule("oleacc.dll")
        cc.GetModule("UIAutomationCore.dll")
        from comtypes.gen import Accessibility, UIAutomationClient as U
        self.A, self.U = Accessibility, U
        self.uia = cc.CreateObject(U.CUIAutomation, interface=U.IUIAutomation)
        try:                       # Windows 8+: never wait long on a busy program
            u2 = self.uia.QueryInterface(U.IUIAutomation2)
            u2.ConnectionTimeout = 300
            u2.TransactionTimeout = 300
        except Exception:
            pass
        import ctypes
        self.oleacc = ctypes.oledll.oleacc

    def msaa(self) -> Rect | None:
        import ctypes
        hwnd = _focus_hwnd()
        if not hwnd:
            return None
        ptr = ctypes.POINTER(self.A.IAccessible)()
        self.oleacc.AccessibleObjectFromWindow(hwnd, OBJID_CARET, ctypes.byref(self.A.IAccessible._iid_),
                                               ctypes.byref(ptr))
        if not ptr:
            return None
        loc = ptr.accLocation(CHILDID_SELF)
        l, t, w, h = (int(v) for v in loc)
        if h <= 0:
            return None
        return l, t, l + max(1, w), t + h

    def uia_caret(self) -> Rect | None:
        U = self.U
        el = self.uia.GetFocusedElement()
        if not el:
            return None
        rng = None
        pat = el.GetCurrentPattern(UIA_TextPattern2Id)
        if pat:
            got = pat.QueryInterface(U.IUIAutomationTextPattern2).GetCaretRange()
            rng = got[-1] if isinstance(got, tuple) else got
        if not rng:
            pat = el.GetCurrentPattern(UIA_TextPatternId)
            if not pat:
                return None
            sel = pat.QueryInterface(U.IUIAutomationTextPattern).GetSelection()
            if not sel or not sel.Length:
                return None
            rng = sel.GetElement(0)
        rect = rect_from_uia(rng.GetBoundingRectangles())
        if rect:
            return rect
        wide = rng.Clone()                              # an empty range has no rectangle: widen it
        wide.ExpandToEnclosingUnit(TextUnit_Character)
        rect = rect_from_uia(wide.GetBoundingRectangles())
        if rect:
            return rect
        back = rng.Clone()                              # caret after the last character
        back.MoveEndpointByUnit(TextPatternRangeEndpoint_Start, TextUnit_Character, -1)
        return rect_from_uia(back.GetBoundingRectangles(), at_end=True)


class _Worker:
    """One thread for the COM lookups; a call that is still running blocks no one."""

    def __init__(self):
        self._jobs: queue.Queue = queue.Queue()
        self._busy = threading.Lock()
        self._com = None
        self._com_failed = False
        threading.Thread(target=self._run, name="pf-caret", daemon=True).start()

    def _run(self):
        while True:
            fn, box, done = self._jobs.get()
            try:
                if self._com is None and not self._com_failed:
                    try:
                        self._com = _Com()
                    except Exception:
                        self._com_failed = True
                        log.info("accessibility caret lookup unavailable", exc_info=True)
                box.append(fn(self._com) if self._com is not None else None)
            except Exception:
                log.debug("caret lookup failed", exc_info=True)
                box.append(None)
            finally:
                done.set()
                self._busy.release()

    def call(self, fn, timeout: float):
        if not self._busy.acquire(blocking=False):
            return None                     # the previous lookup still hangs on a busy program
        box: list = []
        done = threading.Event()
        self._jobs.put((fn, box, done))
        done.wait(timeout)
        return box[0] if box else None


_worker: _Worker | None = None
_worker_lock = threading.Lock()


def _get_worker() -> _Worker:
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = _Worker()
        return _worker


def warm_up() -> None:
    """Create the COM objects early (the first use generates wrappers, about a second)."""
    if os.name == "nt":
        _get_worker().call(lambda com: None, 5.0)


def _own_window(hwnd) -> bool:
    import ctypes
    from ctypes import wintypes as wt
    from phraseforge.platform._win32 import user32
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value == os.getpid()


def caret_rect(use_accessibility: bool = True) -> tuple[Rect | None, str]:
    """(rect, source) of the caret in the foreground window, or (None, "")."""
    if os.name != "nt":
        return None, ""
    from phraseforge.platform._win32 import user32
    hwnd = _foreground()
    if not hwnd:
        return None, ""
    window = _window_rect(hwnd)
    sources = [("win32", win32_caret)]
    # never ask our own windows over COM (this thread would have to answer itself) or a hung one
    if use_accessibility and not _own_window(hwnd) and not user32.IsHungAppWindow(hwnd):
        w = _get_worker()
        sources += [("msaa", lambda: w.call(lambda com: com.msaa(), TIMEOUT_S)),
                    ("uia", lambda: w.call(lambda com: com.uia_caret(), TIMEOUT_S))]
    return first_caret(sources, window)


def caret_point(use_accessibility: bool = True) -> tuple[int, int] | None:
    """Physical screen point just below the caret (where a menu or tip should open)."""
    rect, _src = caret_rect(use_accessibility)
    return (rect[0], rect[3]) if rect else None
