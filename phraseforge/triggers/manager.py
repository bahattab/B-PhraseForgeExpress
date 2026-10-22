"""TriggerManager: turns keyboard, clipboard, clock and focus events into
ExpansionRequests / commands.

Callbacks (on_expand, on_command) run on a dedicated dispatch thread, never
inside the keyboard hook, so they may block (e.g. while output is typed).
The app must marshal to the Qt thread itself if it touches widgets.

Commands passed to on_command:
  "popup", "ocr", "clipboard_history"            global command hotkeys
  "confirm:<phrase_id>:<erase_chars>"             CONFIRM-mode autotext hit
"""
from __future__ import annotations

import contextlib
import logging
import queue
import re
import threading
import time
from datetime import datetime
from typing import Callable

from phraseforge.host import ExpansionContext, ExpansionRequest
from phraseforge.models import AutotextMode, Trigger, TriggerKind
from phraseforge.platform import keys as K
from phraseforge.triggers.autotext import AutotextMatcher, Match, typed_len
from phraseforge.triggers.hotkeys import HotkeyMatcher

log = logging.getLogger(__name__)

COMMAND_HOTKEY_SETTINGS = {
    "popup.hotkey": "popup",
    "ocr.hotkey": "ocr",
    "clipboard_history.hotkey": "clipboard_history",
    # Settings > Hotkeys page
    "hotkey.new_phrase": "new_phrase",
    "hotkey.edit_last_phrase": "edit_last_phrase",
    "hotkey.open_settings": "open_settings",
    "hotkey.clear_clipboard_cache": "clear_clipboard_cache",
    "hotkey.pause": "pause",
}

NAV_KEYS = {0x21: "pgup", 0x22: "pgdn", 0x23: "end", 0x24: "home", 0x25: "left", 0x26: "up",
            0x27: "right", 0x28: "down", 0x2E: "delete", 0x2D: "insert", 0x1B: "escape"}
IGNORED_VKS = {0x14, 0x90, 0x91}  # caps / num / scroll lock
VK_PACKET = 0xE7


def parse_time_trigger(value: str) -> tuple[str, int]:
    """'08:30' -> ('daily', 510); 'every:15' -> ('every', 15). Raises ValueError."""
    v = value.strip().lower()
    if v.startswith("every:"):
        n = int(v.split(":", 1)[1])
        if n <= 0:
            raise ValueError("interval must be positive")
        return "every", n
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", v)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError(f"bad time trigger {value!r}")
    return "daily", int(m.group(1)) * 60 + int(m.group(2))


def clipboard_trigger_hit(t: Trigger, text: str) -> tuple[bool, tuple[str, ...]]:
    kind = TriggerKind(t.kind)
    if kind == TriggerKind.CLIPBOARD:
        a, b = text.strip(), t.value.strip()
        return (a == b if t.case_sensitive else a.casefold() == b.casefold()), ()
    if kind == TriggerKind.CLIPBOARD_REGEX:
        try:
            m = re.search(t.value, text, 0 if t.case_sensitive else re.IGNORECASE)
        except re.error:
            return False, ()
        return (m is not None), (tuple(g or "" for g in m.groups()) if m else ())
    return False, ()


class TriggerManager:
    def __init__(self, store, on_expand: Callable[[ExpansionRequest], None],
                 on_command: Callable[[str], None], *, learner=None,
                 hook_factory=None, watcher_factory=None, foreground_app=None,
                 foreground_hwnd=None, vk_from_char=None, poll_interval_s: float = 0.5):
        self.store = store
        self.on_expand = on_expand
        self.on_command = on_command
        self.learner = learner
        self._hook_factory = hook_factory
        self._watcher_factory = watcher_factory
        self._foreground_app = foreground_app
        self._foreground_hwnd = foreground_hwnd
        self.poll_interval_s = poll_interval_s

        self.matcher = AutotextMatcher()
        self.hotkeys = HotkeyMatcher(vk_from_char)
        self._clip_triggers: list[Trigger] = []
        self._time_triggers: list[tuple[Trigger, str, int]] = []
        self._focus_triggers: list[Trigger] = []
        self._autotext_enabled = True

        self._paused = False
        self._suspend = 0
        self._suspend_lock = threading.Lock()
        self._hook = None
        self._watcher = None
        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._last_hwnd = None
        self._last_focus_exe = ""
        self._time_state: dict[int, object] = {}

    # ------------------------------------------------------------ state
    @property
    def paused(self) -> bool:
        return self._paused

    @paused.setter
    def paused(self, value: bool) -> None:
        self._paused = bool(value)
        self.matcher.reset()

    @property
    def suspended(self) -> bool:
        return self._suspend > 0

    def set_busy(self, busy: bool) -> None:
        """Pass as OutputExecutor(busy_callback=...): ignore input while we type."""
        with self._suspend_lock:
            self._suspend = max(0, self._suspend + (1 if busy else -1))
        if not busy:
            self.matcher.reset()

    @contextlib.contextmanager
    def suspend(self):
        self.set_busy(True)
        try:
            yield
        finally:
            self.set_busy(False)

    def _active(self) -> bool:
        return not self._paused and self._suspend == 0

    # ------------------------------------------------------------ lifecycle
    def reload(self) -> None:
        st = self.store
        self._autotext_enabled = st.setting("autotext.enabled", "1") == "1"
        self.matcher.set_delimiters(st.setting("autotext.delimiters", " \t\n.,;:!?)]}'\""))
        self.matcher.load(st.triggers(TriggerKind.AUTOTEXT) + st.triggers(TriggerKind.REGEX))
        self.hotkeys.clear()
        for key, cmd in COMMAND_HOTKEY_SETTINGS.items():
            self.hotkeys.register(st.setting(key, ""), ("cmd", cmd))
        for t in st.triggers(TriggerKind.HOTKEY):
            self.hotkeys.register(t.value, ("phrase", t.phrase_id))
        self._clip_triggers = st.triggers(TriggerKind.CLIPBOARD) + st.triggers(TriggerKind.CLIPBOARD_REGEX)
        tt = []
        for t in st.triggers(TriggerKind.TIME):
            try:
                kind, n = parse_time_trigger(t.value)
                tt.append((t, kind, n))
            except ValueError:
                log.warning("ignoring bad time trigger %r", t.value)
        self._time_triggers = tt
        self._focus_triggers = st.triggers(TriggerKind.APP_FOCUS)
        if self.hotkeys.errors:
            log.warning("hotkey errors: %s", self.hotkeys.errors)

    def start(self) -> None:
        self._stop.clear()
        self.reload()
        if self._hook_factory is None:
            from phraseforge.platform.keyboard_hook import KeyboardHook
            self._hook_factory = KeyboardHook
        if self._watcher_factory is None:
            from phraseforge.platform.clipboard import ClipboardWatcher
            self._watcher_factory = ClipboardWatcher
        self._hook = self._hook_factory(self._on_key)
        self._hook.start()
        self._watcher = self._watcher_factory(self._on_clipboard)
        self._watcher.start()
        for target, name in ((self._dispatch_loop, "pf-trigger-dispatch"), (self._poll_loop, "pf-trigger-poll")):
            th = threading.Thread(target=target, name=name, daemon=True)
            th.start()
            self._threads.append(th)

    def stop(self) -> None:
        self._stop.set()
        self._queue.put(None)
        for obj in (self._hook, self._watcher):
            if obj:
                try:
                    obj.stop()
                except Exception:
                    log.exception("stop failed")
        for th in self._threads:
            th.join(2)
        self._threads.clear()

    # ------------------------------------------------------------ helpers
    def _fg(self) -> tuple[str, str]:
        if self._foreground_app is None:
            from phraseforge.platform.windows import foreground_app
            self._foreground_app = foreground_app
        try:
            return self._foreground_app()
        except Exception:
            return "", ""

    def _fg_hwnd(self):
        if self._foreground_hwnd is None:
            from phraseforge.platform._win32 import user32
            self._foreground_hwnd = user32.GetForegroundWindow
        try:
            return self._foreground_hwnd()
        except Exception:
            return None

    def _emit(self, fn, arg) -> None:
        self._queue.put((fn, arg))

    def _dispatch_loop(self) -> None:
        while not self._stop.is_set():
            item = self._queue.get()
            if item is None:
                break
            fn, arg = item
            try:
                fn(arg)
            except Exception:
                log.exception("trigger callback failed")

    def _request(self, phrase_id: int, erase: int = 0, trailing: str = "", typed: str = "",
                 groups: tuple[str, ...] = (), exe: str = "", title: str = "") -> ExpansionRequest:
        return ExpansionRequest(
            phrase_id=phrase_id, erase_chars=erase, trailing_delimiter=trailing,
            context=ExpansionContext(phrase_id=phrase_id, typed_abbreviation=typed, app_exe=exe,
                                     window_title=title, regex_groups=groups))

    # ------------------------------------------------------------ keyboard
    def _on_key(self, ev) -> bool:
        """Runs on the hook thread: must return quickly."""
        if not ev.down:
            return self.hotkeys.on_key_up(ev.vk)
        if not self._active():
            return False
        hwnd = self._fg_hwnd()
        if hwnd != self._last_hwnd:
            self._last_hwnd = hwnd
            self.matcher.reset()
            if self.learner:
                self.learner.feed_key("focus")

        payload = self.hotkeys.on_key_down(ev.vk, ev.modifiers)
        if payload is not None:
            kind, value = payload
            if kind == "cmd":
                self._emit(self.on_command, value)
                return True
            exe, title = self._fg()
            if self.store.phrase_allowed_in_app(value, exe):
                self._emit(self.on_expand, self._request(value, exe=exe, title=title))
                return True
            self.hotkeys.on_key_up(ev.vk)  # not ours after all: let the release through
            return False

        char, key = self._classify(ev)
        if char is None and key is None:
            return False
        if self.learner:
            if char is not None:
                self.learner.feed_char(char)
            else:
                self.learner.feed_key(key)
        if not self._autotext_enabled:
            return False
        m = self.matcher.feed(char, key)
        if m is None:
            return False
        return self._handle_match(m)

    @staticmethod
    def _classify(ev) -> tuple[str | None, str | None]:
        if ev.vk in K.MODIFIER_VKS or ev.vk in IGNORED_VKS:
            return None, None
        if ev.vk == VK_PACKET:
            # Unicode packets injected by other software (Windows 11 autocorrect,
            # text suggestions) are not user typing: ignore without resetting.
            # A non-injected packet (some IMEs) carries its char in the scan code.
            if ev.injected:
                return None, None
            return (chr(ev.scan), None) if ev.scan else (None, None)
        mods = ev.modifiers
        if ("win" in mods) or (("ctrl" in mods or "alt" in mods) and not ev.altgr):
            return None, "ctrl"
        if ev.vk == K.VK_BACK:
            return None, "backspace"
        if ev.vk in NAV_KEYS:
            return None, NAV_KEYS[ev.vk]
        if ev.char:
            return ev.char, None
        return None, "f-key"

    def _handle_match(self, m: Match) -> bool:
        exe, title = self._fg()
        pid = m.trigger.phrase_id
        if not self.store.phrase_allowed_in_app(pid, exe):
            return False
        if AutotextMode(m.trigger.mode) == AutotextMode.CONFIRM and TriggerKind(m.trigger.kind) == TriggerKind.AUTOTEXT:
            self._emit(self.on_command, f"confirm:{pid}:{typed_len(m)}")
            return False      # let the key through; erase count includes it
        self._emit(self.on_expand, self._request(pid, m.erase_chars, m.trailing_delimiter, m.typed,
                                                 m.groups, exe, title))
        return True

    # ------------------------------------------------------------ clipboard
    def _on_clipboard(self, text: str) -> None:
        if not self._active() or not self._clip_triggers:
            return
        exe, title = self._fg()
        for t in self._clip_triggers:
            hit, groups = clipboard_trigger_hit(t, text)
            if hit and self.store.phrase_allowed_in_app(t.phrase_id, exe):
                req = self._request(t.phrase_id, groups=groups, exe=exe, title=title)
                req.context.selected_text = text
                self._emit(self.on_expand, req)
                break

    # ------------------------------------------------------------ time + focus
    def check_time(self, now: datetime) -> list[int]:
        """Fire due time triggers; returns phrase ids fired (testable)."""
        fired = []
        minute_of_day = now.hour * 60 + now.minute
        for t, kind, n in self._time_triggers:
            key = t.id if t.id is not None else id(t)
            if kind == "daily":
                if minute_of_day == n and self._time_state.get(key) != now.date():
                    self._time_state[key] = now.date()
                    fired.append(t.phrase_id)
            else:
                last = self._time_state.get(key)
                if last is None:
                    self._time_state[key] = now
                elif (now - last).total_seconds() >= n * 60:
                    self._time_state[key] = now
                    fired.append(t.phrase_id)
        return fired

    def check_focus(self, exe: str, title: str) -> list[int]:
        """Fire APP_FOCUS triggers when the foreground exe changes (testable)."""
        exe = (exe or "").lower()
        if exe == self._last_focus_exe:
            return []
        self._last_focus_exe = exe
        fired = []
        for t in self._focus_triggers:
            targets = {a.strip().lower() for a in t.value.split(",") if a.strip()}
            if exe in targets:
                fired.append(t.phrase_id)
        return fired

    def _poll_loop(self) -> None:
        while not self._stop.wait(self.poll_interval_s):
            if not self._active():
                continue
            try:
                exe, title = self._fg()
                for pid in self.check_time(datetime.now()):
                    if self.store.phrase_allowed_in_app(pid, exe):
                        self._emit(self.on_expand, self._request(pid, exe=exe, title=title))
                if self._focus_triggers:
                    for pid in self.check_focus(exe, title):
                        self._emit(self.on_expand, self._request(pid, exe=exe, title=title))
            except Exception:
                log.exception("trigger poll failed")
