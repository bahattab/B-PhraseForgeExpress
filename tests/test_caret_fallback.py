"""Caret fallback for programs without a Win32 caret (G-07)."""
import sys

import pytest

from phraseforge.platform import caret


@pytest.mark.parametrize("rects,expect", [
    ([(100, 200, 1, 18)], (100, 218)),
    ([(100.4, 200.6, 0, 17.6)], (100, 219)),           # UIA answers doubles; 0-wide carets are fine
    ([(0, 0, 1, 18), (50, 60, 2, 10)], (50, 70)),       # (0, 0) means "unknown"
    ([(10, 10, 1, 0)], None),                           # no height
    ([(10, 10, 5000, 20)], None),                       # the whole control, not a caret
    ([("x", 1, 2, 3)], None),
    ([], None),
    (None, None),
])
def test_pick_point(rects, expect):
    assert caret.pick_point(rects) == expect


def test_flat_rects():
    assert caret.flat_rects([1, 2, 3, 4, 5, 6, 7, 8, 9]) == [(1, 2, 3, 4), (5, 6, 7, 8)]
    assert caret.flat_rects(None) == []


def test_off_windows_nothing_runs():
    if sys.platform == "win32":
        pytest.skip("Windows has the real layers")
    assert caret.msaa_caret(123) is None
    assert caret.uia_caret() is None


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 layers")
def test_layers_in_order(monkeypatch):
    from phraseforge.platform import windows
    seen = []
    monkeypatch.setattr(windows, "_win32_caret", lambda: seen.append("win32"))
    monkeypatch.setattr(caret, "msaa_caret", lambda hwnd: seen.append("msaa"))
    monkeypatch.setattr(caret, "uia_caret", lambda: seen.append("uia") or (5, 6))
    assert windows.caret_position() == (5, 6)
    assert seen == ["win32", "msaa", "uia"]


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 layers")
def test_real_layers_never_raise():
    from phraseforge.platform import windows
    pos = windows.caret_position()          # CI has no focused text field: None or a point, no error
    assert pos is None or (isinstance(pos, tuple) and len(pos) == 2)
