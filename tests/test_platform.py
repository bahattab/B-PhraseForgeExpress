import sys
import threading
import time

import pytest

from phraseforge.host import CursorAction, HtmlAction, ImageAction, KeyAction, SleepAction, TextAction
from phraseforge.models import OutputMode
from phraseforge.platform import keys as K
from phraseforge.platform.output import cursor_left_count, should_paste

win = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


# ---------------------------------------------------------------- pure helpers
def test_cursor_left_count():
    acts = [TextAction("Dear "), CursorAction(), TextAction(",\r\nBye")]
    assert cursor_left_count(acts) == 5          # ",", newline, "B", "y", "e"
    assert cursor_left_count([TextAction("abc")]) is None
    assert cursor_left_count([TextAction("a"), CursorAction(), TextAction("bc")], " ") == 3
    assert cursor_left_count([CursorAction(), HtmlAction("<b>x</b>", "xy"), KeyAction("tab")]) == 2


def test_should_paste():
    assert should_paste([TextAction("short")], OutputMode.AUTO, 40) is False
    assert should_paste([TextAction("x" * 41)], OutputMode.AUTO, 40) is True
    assert should_paste([TextAction("x")], OutputMode.PASTE, 40) is True
    assert should_paste([TextAction("x" * 100)], OutputMode.TYPE, 40) is False
    assert should_paste([HtmlAction("<b>a</b>", "a")], OutputMode.TYPE, 40) is True
    assert should_paste([ImageAction("a.png")], OutputMode.AUTO, 40) is True


def test_key_names():
    assert K.key_name_to_vk("F5") == 0x74
    assert K.key_name_to_vk("a") == 0x41
    assert K.key_name_to_vk("PgDn") == 0x22
    assert K.vk_to_name(0x25) == "left"
    with pytest.raises(ValueError):
        K.key_name_to_vk("nosuchkey")


@win
def test_cf_html_offsets():
    from phraseforge.platform.clipboard import build_cf_html, parse_cf_html
    frag = "<b>مرحبا</b> & bye"
    data = build_cf_html(frag)
    head = data[:200].decode("ascii", errors="ignore")
    vals = dict(l.split(":", 1) for l in head.split("\r\n") if ":" in l and l.split(":")[0] in
                ("StartHTML", "EndHTML", "StartFragment", "EndFragment"))
    assert data[int(vals["StartFragment"]):int(vals["EndFragment"])].decode("utf-8") == frag
    assert int(vals["EndHTML"]) == len(data)
    assert data[int(vals["StartHTML"]):].startswith(b"<html>")
    assert parse_cf_html(data) == frag


@win
def test_utf16_units_surrogates():
    from phraseforge.platform.sendinput import parse_chord, utf16_units
    assert utf16_units("a") == [0x61]
    assert utf16_units("😀") == [0xD83D, 0xDE00]
    mods, vk = parse_chord("ctrl+shift+left")
    assert mods == [0x11, 0x10] and vk == 0x25
    assert parse_chord("enter") == ([], 0x0D)
    assert parse_chord("ctrl++") == ([0x11], 0xBB)


# ---------------------------------------------------------------- real clipboard (safe: restores contents)
@win
def test_clipboard_roundtrip_and_restore():
    from phraseforge.platform import clipboard as cb
    snap = cb.save_all()
    try:
        cb.set_text("PhraseForge test ✓ مرحبا")
        assert cb.get_text() == "PhraseForge test ✓ مرحبا"
        assert cb.is_own_change()
        cb.set_html("<i>hi</i>", "hi")
        assert cb.get_text() == "hi"
        assert cb.get_html() == "<i>hi</i>"
        inner = cb.save_all()
        cb.set_text("other")
        cb.restore(inner)
        assert cb.get_text() == "hi"
    finally:
        cb.restore(snap)


@win
def test_clipboard_watcher_skips_own_changes():
    from phraseforge.platform import clipboard as cb
    seen = []
    snap = cb.save_all()
    w = cb.ClipboardWatcher(seen.append)
    w.start()
    try:
        cb.set_text("own write")
        time.sleep(0.3)
        assert seen == []
    finally:
        w.stop()
        cb.restore(snap)


@win
def test_foreground_app_and_executor_with_fakes():
    from phraseforge.platform.output import OutputExecutor
    from phraseforge.platform.windows import foreground_app
    exe, title = foreground_app()
    assert isinstance(exe, str) and isinstance(title, str)

    calls = []

    class FakeSI:
        def release_modifiers(self): calls.append(("release",))
        def backspace(self, n): calls.append(("bs", n))
        def type_text(self, t): calls.append(("type", t))
        def send_keys(self, k, repeat=1): calls.append(("keys", k, repeat))
        def press_left(self, n): calls.append(("left", n))
        def mouse_move(self, x, y): calls.append(("move", x, y))
        def mouse_click(self, x, y, button="left", double=False): calls.append(("click", x, y, button, double))

    class FakeCB:
        def save_all(self): calls.append(("save",)); return ["snap"]
        def restore(self, s): calls.append(("restore", s))
        def set_text(self, t): calls.append(("clip", t))
        def set_html(self, h, p, formats="html"): calls.append(("html", h, p))
        def set_image(self, p): calls.append(("img", p))

    busy = []
    ex = OutputExecutor(lambda k, d="": {"output.paste_threshold": "10"}.get(k, d), busy.append)
    ex.sendinput, ex.clipboard = FakeSI(), FakeCB()
    ex.execute([TextAction("Hi "), CursorAction(), TextAction("there"), KeyAction("tab"), SleepAction(1)],
               erase_chars=3, trailing_delimiter=" ")
    assert ("bs", 3) in calls
    assert ("type", "Hi there") in calls and calls[-1] == ("left", 6)
    assert ("keys", "tab", 1) in calls and busy == [True, False]

    calls.clear()
    ex.execute([TextAction("x" * 20)], mode=OutputMode.AUTO)
    assert ("clip", "x" * 20) in calls and ("keys", "ctrl+v", 1) in calls and calls[-1] == ("restore", ["snap"])
