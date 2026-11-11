"""Caret position for programs without a Win32 caret (PRD G-07, FR-INP-05).

GetGUIThreadInfo (windows.caret_position) only knows the classic Win32 caret. Browsers,
Electron programs, modern Office and UWP apps draw their own, so for them PhraseForge asks:

1. MSAA: the window's caret object (OBJID_CARET). Chrome, Edge, Firefox and many others
   expose it.
2. UI Automation: the focused element's text pattern, caret range first (TextPattern2),
   else the selection; its bounding rectangle.

Every step is best effort: any error means "no answer" and the caller falls back to the
mouse position. The questions are cross-process COM calls that a hung program never answers,
so they run on one worker thread of their own (its own COM apartment) and lookup() waits at
most TIMEOUT_S; while an earlier question is still stuck, lookup() answers None at once.
Nothing here runs off Windows.
"""
from __future__ import annotations

import logging
import queue
import sys
import threading

log = logging.getLogger(__name__)

OBJID_CARET = -8
CHILDID_SELF = 0
UIA_TEXT_PATTERN = 10014
UIA_TEXT_PATTERN2 = 10024
TEXT_UNIT_CHARACTER = 0
TIMEOUT_S = 0.25
MAX_SIDE = 2000          # a "caret" larger than this is the whole control, not a caret


def pick_point(rects) -> tuple[int, int] | None:
    """(left, bottom) of the first usable (left, top, width, height) rectangle, else None.
    A caret is often 0 or 1 pixel wide; a zero-height or giant one is not a caret."""
    for r in rects or ():
        try:
            left, top, width, height = (int(round(float(v))) for v in r)
        except (TypeError, ValueError):
            continue
        if height <= 0 or width < 0 or height > MAX_SIDE or width > MAX_SIDE:
            continue
        if left == 0 and top == 0:
            continue
        return left, top + height
    return None


def flat_rects(values) -> list[tuple[float, float, float, float]]:
    """UI Automation's GetBoundingRectangles answer: one flat list l, t, w, h, l, t, w, h, ..."""
    v = list(values or ())
    return [tuple(v[i:i + 4]) for i in range(0, len(v) - len(v) % 4, 4)]


def msaa_caret(hwnd: int) -> tuple[int, int] | None:
    if sys.platform != "win32" or not hwnd:
        return None
    try:
        import ctypes
        import comtypes.client
        from comtypes.automation import VARIANT
        oleacc = ctypes.oledll.oleacc
        mod = comtypes.client.GetModule("oleacc.dll")
        acc = ctypes.POINTER(mod.IAccessible)()
        oleacc.AccessibleObjectFromWindow(hwnd, OBJID_CARET, ctypes.byref(mod.IAccessible._iid_),
                                          ctypes.byref(acc))
        if not acc:
            return None
        # the four [out] numbers come back as a tuple (comtypes)
        return pick_point([tuple(acc.accLocation(VARIANT(CHILDID_SELF)))])
    except Exception:            # noqa: BLE001 - no caret object, no oleacc, a hung program
        log.debug("MSAA caret not available", exc_info=True)
        return None


_UIA = None


def _automation():
    global _UIA
    if _UIA is None:
        import comtypes.client
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as uia
        _UIA = (uia, comtypes.client.CreateObject(uia.CUIAutomation, interface=uia.IUIAutomation))
    return _UIA


def uia_caret() -> tuple[int, int] | None:
    if sys.platform != "win32":
        return None
    try:
        uia, auto = _automation()
        el = auto.GetFocusedElement()
        if not el:
            return None
        rng = None
        try:
            p2 = el.GetCurrentPattern(UIA_TEXT_PATTERN2)
            if p2:
                active, rng = p2.QueryInterface(uia.IUIAutomationTextPattern2).GetCaretRange()
        except Exception:        # noqa: BLE001 - TextPattern2 is Windows 8+ and not everywhere
            rng = None
        if rng is None:
            p = el.GetCurrentPattern(UIA_TEXT_PATTERN)
            if not p:
                return None
            sel = p.QueryInterface(uia.IUIAutomationTextPattern).GetSelection()
            if not sel or sel.Length < 1:
                return None
            rng = sel.GetElement(0)
        point = pick_point(flat_rects(rng.GetBoundingRectangles()))
        if point is None:        # an empty range has no rectangle: measure the next character
            rng = rng.Clone()
            rng.ExpandToEnclosingUnit(TEXT_UNIT_CHARACTER)
            point = pick_point(flat_rects(rng.GetBoundingRectangles()))
        return point
    except Exception:            # noqa: BLE001 - no UI Automation, element gone, hung program
        log.debug("UI Automation caret not available", exc_info=True)
        return None


_jobs: "queue.Queue" = queue.Queue()
_worker: threading.Thread | None = None
_busy = threading.Event()


def _serve() -> None:
    try:
        import comtypes
        comtypes.CoInitialize()
    except Exception:            # noqa: BLE001
        log.debug("COM could not start on the caret thread", exc_info=True)
    while True:
        hwnd, box, done = _jobs.get()
        try:
            box.append(msaa_caret(hwnd) or uia_caret())
        except Exception:        # noqa: BLE001
            box.append(None)
        finally:
            _busy.clear()
            done.set()


def lookup(hwnd: int, timeout: float = TIMEOUT_S) -> tuple[int, int] | None:
    """MSAA then UI Automation, asked on the caret thread; None after `timeout` seconds."""
    global _worker
    if sys.platform != "win32" or _busy.is_set():
        return None
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_serve, name="caret-com", daemon=True)
        _worker.start()
    box: list = []
    done = threading.Event()
    _busy.set()
    _jobs.put((hwnd, box, done))
    if not done.wait(timeout):
        return None              # still asking a hung program: the next lookup returns None until it ends
    return box[0] if box else None
