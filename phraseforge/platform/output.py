"""Perform macro-engine Actions in the focused application.

Settings honoured (Settings > Expert Options > Text Insertion / Delays / Phrase Formatting):
- output.paste_long + output.paste_threshold: AUTO mode pastes text longer than N chars
- output.key_method: vk_packet | unicode | scancode (how key-by-key typing is sent)
- output.per_app_method + output.app_methods (JSON {exe: "type"|"paste"}): programs that
  need a specific method
- output.format: auto | plain | rich | html; format.html_output: auto | inline | css
- output.restore_clipboard, delay.paste, delay.clipboard_restore, delay.keypress
"""
from __future__ import annotations

import html as _html
import json
import logging
import re
import threading
import time
from typing import Callable, Iterable

from phraseforge.host import (
    CursorAction, HtmlAction, ImageAction, KeyAction, MouseAction, SleepAction, TextAction,
)
from phraseforge.models import OutputMode

log = logging.getLogger(__name__)

PASTE_SETTLE_S = 0.08     # default time for the target app to read the clipboard after Ctrl+V
RESTORE_DELAY_S = 0.25

# Programs known to need one method. Users can override with setting output.app_methods.
DEFAULT_APP_METHODS = {
    "mstsc.exe": "type", "vmconnect.exe": "type", "putty.exe": "paste", "kitty.exe": "paste",
    "windowsterminal.exe": "paste", "cmd.exe": "paste", "powershell.exe": "paste", "pwsh.exe": "paste",
    "conhost.exe": "paste", "mintty.exe": "paste", "teamviewer.exe": "type", "anydesk.exe": "type",
}


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


def should_paste(actions: Iterable, mode: OutputMode, threshold: int, paste_long: bool = True) -> bool:
    actions = list(actions)
    if mode == OutputMode.PASTE:
        return True
    if any(isinstance(a, (HtmlAction, ImageAction)) for a in actions):
        return True   # rich content can only be pasted (even in TYPE mode)
    if mode == OutputMode.TYPE or not paste_long:
        return False
    total = sum(visible_length(a) for a in actions)
    return total > threshold


def text_to_html(text: str) -> str:
    return _html.escape(normalize_newlines(text)).replace("\n", "<br>")


def html_for_output(html: str, style: str) -> str:
    """format.html_output: "inline" drops <style> blocks (Qt puts the formats on the
    elements themselves), "css"/"auto" keep the document as produced."""
    if style == "inline":
        return re.sub(r"(?is)<style[^>]*>.*?</style>", "", html)
    return html


def apply_format(actions: list, fmt: str, html_style: str = "auto") -> list:
    """output.format: auto (as stored), plain (drop formatting), rich (paste as rich
    text), html (insert the HTML source as text)."""
    out = []
    for a in actions:
        if isinstance(a, HtmlAction):
            if fmt == "plain":
                out.append(TextAction(a.plain))
            elif fmt == "html":
                out.append(TextAction(html_for_output(a.html, html_style)))
            else:
                out.append(HtmlAction(html=html_for_output(a.html, html_style), plain=a.plain))
        elif isinstance(a, TextAction) and fmt == "rich" and a.text:
            out.append(HtmlAction(html=text_to_html(a.text), plain=a.text))
        else:
            out.append(a)
    return out


def app_methods(setting: Callable[[str, str], str]) -> dict[str, str]:
    m = dict(DEFAULT_APP_METHODS)
    try:
        user = json.loads(setting("output.app_methods", "") or "{}")
        if isinstance(user, dict):
            m.update({str(k).lower(): str(v) for k, v in user.items() if v in ("type", "paste", "auto")})
    except ValueError:
        pass
    return m


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

    # ------------------------------------------------------------ settings
    def _int(self, key: str, default: int) -> int:
        try:
            return int(float(self.setting(key, str(default)) or default))
        except (TypeError, ValueError):
            return default

    def _threshold(self) -> int:
        return self._int("output.paste_threshold", 40)

    def resolve_mode(self, mode: OutputMode, app_exe: str = "") -> OutputMode:
        """Per-program method (Settings > Text Insertion) overrides AUTO."""
        mode = OutputMode(mode)
        if mode == OutputMode.AUTO and app_exe and self.setting("output.per_app_method", "1") == "1":
            m = app_methods(self.setting).get(app_exe.lower())
            if m in ("type", "paste"):
                return OutputMode(m)
        return mode

    # ------------------------------------------------------------ run
    def execute(self, actions: list, erase_chars: int = 0, trailing_delimiter: str = "",
                mode: OutputMode = OutputMode.AUTO, app_exe: str = "", key_delay_ms: int | None = None) -> None:
        with self._lock:
            if self.busy_callback:
                self.busy_callback(True)
            try:
                actions = apply_format(list(actions), self.setting("output.format", "auto") or "auto",
                                       self.setting("format.html_output", "auto") or "auto")
                self._execute(actions, erase_chars, trailing_delimiter, self.resolve_mode(mode, app_exe),
                              key_delay_ms)
            finally:
                if self.busy_callback:
                    self.busy_callback(False)

    def _type(self, text: str, char_delay: int) -> None:
        method = self.setting("output.key_method", "vk_packet") or "vk_packet"
        if method in ("vk_packet", "unicode") and not char_delay:
            self.sendinput.type_text(text)
        else:
            self.sendinput.type_text(text, method=method, char_delay_ms=char_delay)

    def _keys(self, keys: str, repeat: int, delay: int) -> None:
        if delay:
            self.sendinput.send_keys(keys, repeat, delay_ms=delay)
        else:
            self.sendinput.send_keys(keys, repeat)

    def _execute(self, actions: list, erase_chars: int, trailing_delimiter: str, mode: OutputMode,
                 key_delay_ms: int | None) -> None:
        si, cb = self.sendinput, self.clipboard
        paste_settle = max(20, self._int("delay.paste", int(PASTE_SETTLE_S * 1000))) / 1000
        restore_delay = max(50, self._int("delay.clipboard_restore", int(RESTORE_DELAY_S * 1000))) / 1000
        key_delay = key_delay_ms if key_delay_ms is not None else self._int("delay.keypress", 0)
        char_delay = key_delay_ms or 0      # {#pastemethod -delay N} slows typing too
        si.release_modifiers()
        if erase_chars > 0:
            si.backspace(erase_chars)
        paste = should_paste(actions, mode, self._threshold(), self.setting("output.paste_long", "1") != "0")
        restore = self.setting("output.restore_clipboard", "1") == "1"
        snapshot = cb.save_all() if (paste and restore) else None
        used_clipboard = False
        left = cursor_left_count(actions, trailing_delimiter)

        pending_text: list[str] = []

        def paste_now():
            si.send_keys("ctrl+v")
            time.sleep(paste_settle)

        def flush_text():
            nonlocal used_clipboard
            if not pending_text:
                return
            text = "".join(pending_text)
            pending_text.clear()
            if paste:
                cb.set_text(text)
                paste_now()
                used_clipboard = True
            else:
                self._type(text, char_delay)

        for a in actions:
            if isinstance(a, TextAction):
                pending_text.append(normalize_newlines(a.text))
                continue
            if isinstance(a, CursorAction):
                continue          # position applied at the end via Left presses
            flush_text()
            if isinstance(a, HtmlAction):
                cb.set_html(a.html, a.plain)
                paste_now()
                used_clipboard = True
            elif isinstance(a, ImageAction):
                cb.set_image(a.path)
                paste_now()
                used_clipboard = True
            elif isinstance(a, KeyAction):
                self._keys(a.keys, a.repeat, key_delay)
            elif isinstance(a, SleepAction):
                time.sleep(max(0, a.ms) / 1000)
            elif isinstance(a, MouseAction):
                if a.kind == "move" and a.x is not None and a.y is not None:
                    si.mouse_move(a.x, a.y)
                elif a.kind in ("click", "rclick", "dblclick"):
                    si.mouse_click(a.x, a.y, button="right" if a.kind == "rclick" else "left",
                                   double=a.kind == "dblclick")
            else:
                log.warning("unknown action %r", a)
        flush_text()
        if trailing_delimiter:
            si.type_text(trailing_delimiter)
        if left:
            si.press_left(left)
        if snapshot is not None and used_clipboard:
            time.sleep(restore_delay)
            try:
                cb.restore(snapshot)
            except Exception:
                log.exception("clipboard restore failed")
