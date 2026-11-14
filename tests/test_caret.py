"""Caret position in more programs (PRD FR-INP-05, G-07): Win32 caret, then MSAA, then UI
Automation, on a worker thread with a time limit; physical pixels mapped to Qt coordinates."""
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from phraseforge.platform import caret
from phraseforge.platform.caret import first_caret, plausible, rect_from_uia


# ---------------------------------------------------------------- pure helpers
def test_rect_from_uia_start_and_end():
    assert rect_from_uia((100.0, 200.0, 8.0, 18.0)) == (100, 200, 101, 218)
    # two lines: the caret after the last character is at the end of the last rectangle
    assert rect_from_uia((10, 20, 50, 18, 10, 40, 30, 18), at_end=True) == (40, 40, 41, 58)
    assert rect_from_uia(()) is None and rect_from_uia(None) is None
    assert rect_from_uia((1, 2, 3, 0)) is None                      # no height


def test_plausible_rejects_empty_origin_and_far_away():
    win = (100, 100, 900, 700)
    assert plausible((300, 300, 301, 320), win)
    assert not plausible(None, win)
    assert not plausible((0, 0, 1, 20), win)
    assert not plausible((300, 300, 301, 300), win)                 # zero height
    assert not plausible((2000, 300, 2001, 320), win)
    assert plausible((60, 300, 61, 320), win)                       # within the slack
    assert plausible((5, 5, 6, 20), None)


def test_first_caret_takes_the_first_good_answer():
    calls = []

    def src(name, value):
        def fn():
            calls.append(name)
            if value == "boom":
                raise OSError("no")
            return value
        return name, fn

    win = (0, 0, 1000, 1000)
    rect, name = first_caret([src("win32", None), src("msaa", "boom"), src("uia", (5, 5, 6, 25)),
                              src("never", (1, 1, 2, 2))], win)
    assert (rect, name) == ((5, 5, 6, 25), "uia") and calls == ["win32", "msaa", "uia"]
    assert first_caret([src("win32", (0, 0, 1, 1))], win) == (None, "")


def test_physical_to_logical_scales_inside_each_screen():
    from phraseforge.ui.region_select import physical_to_logical

    class Geo:
        def __init__(self, x, y, w, h):
            self._v = (x, y, w, h)

        def x(self): return self._v[0]
        def y(self): return self._v[1]
        def width(self): return self._v[2]
        def height(self): return self._v[3]

    class Scr:
        def __init__(self, geo, dpr):
            self._g, self._d = geo, dpr

        def geometry(self): return self._g
        def devicePixelRatio(self): return self._d

    # primary 1920x1080 at 150 % (physical 2880x1620), second screen to its right at 100 %
    screens = [Scr(Geo(0, 0, 1920, 1080), 1.5), Scr(Geo(2880, 0, 1920, 1080), 1.0)]
    assert physical_to_logical(1500, 900, screens) == (1000, 600)
    assert physical_to_logical(3000, 100, screens) == (3000, 100)
    assert physical_to_logical(-50, -50, screens) == (-50, -50)     # on no screen: unchanged


# ---------------------------------------------------------------- the worker never blocks the caller
def test_worker_times_out_and_does_not_queue_behind_a_hung_lookup():
    w = caret._Worker()
    w._com = object()                      # no COM needed for this test
    release = threading.Event()
    t = time.monotonic()
    assert w.call(lambda com: release.wait(5) and (1, 2, 3, 4), 0.1) is None
    assert time.monotonic() - t < 1.0
    t = time.monotonic()
    assert w.call(lambda com: (9, 9, 9, 9), 1.0) is None            # still busy: answer at once
    assert time.monotonic() - t < 0.2
    release.set()
    time.sleep(0.2)
    assert w.call(lambda com: (5, 6, 7, 8), 1.0) == (5, 6, 7, 8)


def test_worker_survives_a_failing_lookup():
    w = caret._Worker()
    w._com = object()
    assert w.call(lambda com: 1 / 0, 1.0) is None
    assert w.call(lambda com: "ok", 1.0) == "ok"


# ---------------------------------------------------------------- a real WPF text box (Windows)
FIXTURE = Path(__file__).parent / "fixtures" / "wpf_textbox.ps1"


@pytest.fixture
def wpf_window():
    if os.name != "nt":
        pytest.skip("Windows only")
    from phraseforge.platform import windows
    caret.warm_up()                        # COM set-up first, so the window keeps the focus meanwhile
    p = subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(FIXTURE), "20"])
    try:
        for _ in range(80):
            time.sleep(0.25)
            if windows.foreground_app()[1] == "PF caret test":
                break
        else:
            pytest.skip("the test window did not come to the front (no interactive desktop?)")
        time.sleep(0.7)
        yield caret._window_rect(caret._foreground())
    finally:
        p.kill()


def _near(a, b, px=12):
    return abs(a[0] - b[0]) <= px and abs(a[1] - b[1]) <= px


def test_caret_in_a_wpf_text_box(wpf_window):
    # caret_rect gives MSAA and UI Automation TIMEOUT_S (0.25 s) together, on purpose: the popup
    # must not wait, it falls back to the mouse. On a busy CI runner WPF's first answers can take
    # longer than that, which made this test fail now and then. What it checks is that the caret
    # is found, so it asks again for up to 5 s.
    rect, source = caret.caret_rect()
    deadline = time.monotonic() + 5
    while not rect and time.monotonic() < deadline:
        time.sleep(0.2)
        rect, source = caret.caret_rect()
    assert rect and source, "no caret found"
    l, t, r, b = rect
    wl, wt, wr, wb = wpf_window
    assert wl <= l <= wr and wt <= t <= wb and b > t
    # the accessibility routes agree with each other (within a few pixels)
    from phraseforge.platform import windows
    w = caret._get_worker()
    uia = w.call(lambda com: com.uia_caret(), 5)
    msaa = w.call(lambda com: com.msaa(), 5)
    if windows.foreground_app()[1] != "PF caret test":
        pytest.skip("the test window lost the focus during the test")
    found = [x for x in (uia, msaa) if x]
    assert found, "neither MSAA nor UI Automation answered"
    for x in found:
        assert _near(x, rect), (x, rect, source)


def test_one_wait_for_the_whole_chain(monkeypatch):
    """Review of #60: MSAA and UIA waited 250 ms each (and the menu looked twice): ~1 s per open."""
    import time
    from phraseforge.platform import caret as C
    monkeypatch.setattr(C, "_Com", lambda: object())
    w = C._Worker()
    w.call(lambda com: None, 1)                  # let the worker start
    slow = lambda com: (time.sleep(0.24), None)[1]
    srcs = C.com_sources(w, msaa=slow, uia=slow)
    t = time.monotonic()
    C.first_caret(srcs, (0, 0, 1000, 800))
    assert time.monotonic() - t < C.TIMEOUT_S + 0.1


def test_a_stuck_worker_is_replaced(monkeypatch):
    """Review of #60: one program that never answers COM turned the lookup off until restart."""
    import threading
    from phraseforge.platform import caret as C
    monkeypatch.setattr(C, "STUCK_S", 0.3)
    monkeypatch.setattr(C, "_worker", None)
    monkeypatch.setattr(C, "_Com", lambda: object())       # no real COM on this test machine
    ev = threading.Event()
    w1 = C._get_worker()
    assert w1.call(lambda com: ev.wait(), 0.05) is None          # hangs
    assert C._get_worker() is w1                                 # not yet given up
    import time
    time.sleep(0.4)
    w2 = C._get_worker()
    assert w2 is not w1 and w2.call(lambda com: (1, 1, 2, 9), 1) == (1, 1, 2, 9)
    ev.set()
