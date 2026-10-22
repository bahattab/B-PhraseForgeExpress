"""Perform macro-engine Actions in the focused application."""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Iterable

from phraseforge.host import (
    CursorAction, HtmlAction, ImageAction, KeyAction, MouseAction, SleepAction, TextAction,
)
from phraseforge.models import OutputMode

log = logging.getLogger(__name__)

PASTE_SETTLE_S = 0.08     # time for the target app to read the clipboard after Ctrl+V
RESTORE_DELAY_S = 0.25


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def visible_length(action) -> int:
    """Caret movements needed to cross the text an action produces."""
    if isinstance(action, TextAction):
        return len(normalize_newlines(action.text))
    if isinstance(action, HtmlAction):
        return len(normalize_newlines(action.plain))
    return 0


def cursor_left_count(actions: Iterable, trailing_delimiter: str = "") -> int | None:
    """Number of Left presses to put the caret at the last {#cursor} marker,
    or None when there is no marker. Newlines count as one position;
    characters outside the BMP count as one (Left moves per character)."""
    actions = list(actions)
    idx = None
    for i, a in enumerate(actions):
        if isinstance(a, CursorAction):
            idx = i
    if idx is None:
        return None
    n = sum(visible_length(a) for a in actions[idx + 1:])
    return n + len(normalize_newlines(trailing_delimiter))


def should_paste(actions: Iterable, mode: OutputMode, threshold: int) -> bool:
    actions = list(actions)
    if mode == OutputMode.PASTE:
        return True
    if any(isinstance(a, (HtmlAction, ImageAction)) for a in actions):
        return True   # rich content can only be pasted (even in TYPE mode)
    if mode == OutputMode.TYPE:
        return False
    total = sum(visible_length(a) for a in actions)
    return total > threshold


class OutputExecutor:
    """Executes actions; one expansion at a time. busy_callback(True/False)
    lets the trigger layer suspend itself while output runs."""

    def __init__(self, settings_getter: Callable[[str, str], str],
                 busy_callback: Callable[[bool], None] | None = None):
        self.setting = settings_getter
        self.busy_callback = busy_callback
        self._lock = threading.Lock()
        # injectable for tests
        from phraseforge.platform import clipboard, sendinput
        self.clipboard = clipboard
        self.sendinput = sendinput

    def _threshold(self) -> int:
        try:
            return int(self.setting("output.paste_threshold", "40") or 40)
        except ValueError:
            return 40

    def execute(self, actions: list, erase_chars: int = 0, trailing_delimiter: str = "",
                mode: OutputMode = OutputMode.AUTO) -> None:
        with self._lock:
            if self.busy_callback:
                self.busy_callback(True)
            try:
                self._execute(list(actions), erase_chars, trailing_delimiter, OutputMode(mode))
            finally:
                if self.busy_callback:
                    self.busy_callback(False)

    def _execute(self, actions: list, erase_chars: int, trailing_delimiter: str, mode: OutputMode) -> None:
        si, cb = self.sendinput, self.clipboard
        si.release_modifiers()
        if erase_chars > 0:
            si.backspace(erase_chars)
        paste = should_paste(actions, mode, self._threshold())
        restore = self.setting("output.restore_clipboard", "1") == "1"
        snapshot = cb.save_all() if (paste and restore) else None
        used_clipboard = False
        left = cursor_left_count(actions, trailing_delimiter)

        pending_text: list[str] = []

        def flush_text():
            nonlocal used_clipboard
            if not pending_text:
                return
            text = "".join(pending_text)
            pending_text.clear()
            if paste:
                cb.set_text(text)
                si.send_keys("ctrl+v")
                time.sleep(PASTE_SETTLE_S)
                used_clipboard = True
            else:
                si.type_text(text)

        for a in actions:
            if isinstance(a, TextAction):
                pending_text.append(normalize_newlines(a.text))
                continue
            if isinstance(a, CursorAction):
                continue          # position applied at the end via Left presses
            flush_text()
            if isinstance(a, HtmlAction):
                cb.set_html(a.html, a.plain)
                si.send_keys("ctrl+v")
                time.sleep(PASTE_SETTLE_S)
                used_clipboard = True
            elif isinstance(a, ImageAction):
                cb.set_image(a.path)
                si.send_keys("ctrl+v")
                time.sleep(PASTE_SETTLE_S)
                used_clipboard = True
            elif isinstance(a, KeyAction):
                si.send_keys(a.keys, a.repeat)
            elif isinstance(a, SleepAction):
                time.sleep(max(0, a.ms) / 1000)
            elif isinstance(a, MouseAction):
                if a.kind == "move" and a.x is not None and a.y is not None:
                    si.mouse_move(a.x, a.y)
                elif a.kind in ("click", "rclick", "dblclick"):
                    si.mouse_click(a.x, a.y, button="right" if a.kind == "rclick" else "left",
                                   double=a.kind == "dblclick")
            elif isinstance(a, CursorAction):
                pass
            else:
                log.warning("unknown action %r", a)
        flush_text()
        if trailing_delimiter:
            si.type_text(trailing_delimiter)
        if left:
            si.press_left(left)
        if snapshot is not None and used_clipboard:
            time.sleep(RESTORE_DELAY_S)
            try:
                cb.restore(snapshot)
            except Exception:
                log.exception("clipboard restore failed")
