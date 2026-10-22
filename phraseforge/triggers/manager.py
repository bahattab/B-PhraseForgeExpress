"""TriggerManager: turns keyboard, clipboard, clock and focus events into
ExpansionRequests / commands.

Callbacks (on_expand, on_command) run on a dedicated dispatch thread, never
inside the keyboard hook, so they may block (e.g. while output is typed).
The app must marshal to the Qt thread itself if it touches widgets.

Commands passed to on_command (the app handles each one):
  "popup", "ocr", "clipboard_history", "new_phrase", "edit_last_phrase",
  "open_settings", "clear_clipboard_cache", "pause"      global command hotkeys
  "confirm:<phrase_id>:<erase_chars>"        autotext in "after manual confirmation" mode
  "folder_popup:<folder_id|last_used|clipboard_cache>:<erase_chars>"
                                             a folder's own autotext/hotkey: erase the typed
                                             abbreviation, then show that folder's popup
  "smartcomplete:<phrase_id>:<typed_len>"    show the SmartComplete tip for this phrase
  "autocomplete:<word>:<typed_len>"          show the tip with a word completion
  "suggest_hide"                             hide the tip
  "autocorrect:<erase_chars>:<replacement>"  erase N chars left of the caret, type replacement
                                             (capitalization fixes, accepted word completions)
  "undo_expansion:<phrase_id>:<typed>"       Backspace right after an expansion: remove the
                                             inserted text and type <typed> back
  "sound:unwanted_detected"                  with undo_expansion
  "sound:unwanted_skipped"                   a trigger skipped by "Pause for a short time"
  "sound:spelling_added"                     AutoComplete learned a corrected word
Accepting a SmartComplete tip (Tab/Enter, or accept_suggestion()) sends an
ExpansionRequest that erases the typed characters.
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
from phraseforge.models import Trigger, TriggerKind
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
    "hotkey.popup_search": "popup_search",
    "onenote.send_hotkey": "onenote_send_clipboard",
    "onenote.clip_hotkey": "onenote_clip",
    "stickynotes.hotkey": "open_sticky_notes",
}

NAV_KEYS = {0x21: "pgup", 0x22: "pgdn", 0x23: "end", 0x24: "home", 0x25: "left", 0x26: "up",
            0x27: "right", 0x28: "down", 0x2E: "delete", 0x2D: "insert", 0x1B: "escape"}
IGNORED_VKS = {0x14, 0x90, 0x91}  # caps / num / scroll lock
VK_PACKET = 0xE7
VK_CAPITAL = 0x14
VK_TAB, VK_RETURN, VK_ESCAPE = 0x09, 0x0D, 0x1B
UNDO_WINDOW_S = 10.0
MACRO_TOKEN = re.compile(r"\{#[^{}]*\}")
HTML_TAG = re.compile(r"<[^>]+>")


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


def window_trigger_hit(t: Trigger, exe: str, title: str) -> bool:
    """Window trigger: "program" scope matches the exe name, otherwise the title contains the text.
    The value may list several entries separated by commas."""
    values = [v.strip().lower() for v in t.value.split(",") if v.strip()]
    if not values:
        return False
    scope = t.window_scope or ("program" if all(v.endswith(".exe") for v in values) else "any")
    exe, title = (exe or "").lower(), (title or "").lower()
    if scope == "program":
        names = {exe, exe[:-4] if exe.endswith(".exe") else exe}
        return any(v in names or v.removesuffix(".exe") in names for v in values)
    return any(v in title for v in values)


def smart_target(t: Trigger, phrase) -> str:
    """Text a SmartComplete trigger completes: its value, else the start of the phrase content."""
    if t.value.strip():
        return t.value
    text = phrase.content if phrase else ""
    if phrase is not None and phrase.content_format == "html":
        text = HTML_TAG.sub("", text)
    text = MACRO_TOKEN.sub("", text).strip()
    return text.split("\n", 1)[0][:60]


def _parse_programs(text: str) -> set[str]:
    return {p.strip().lower() for p in re.split(r"[,;\n]+", text or "") if p.strip()}


class TriggerManager:
    def __init__(self, store, on_expand: Callable[[ExpansionRequest], None],
                 on_command: Callable[[str], None], *, learner=None, word_learner=None,
                 hook_factory=None, watcher_factory=None, foreground_app=None,
                 foreground_hwnd=None, vk_from_char=None, poll_interval_s: float = 0.5,
                 clock: Callable[[], float] = time.monotonic, timer_factory=None):
        self.store = store
        self.on_expand = on_expand
        self.on_command = on_command
        self.learner = learner
        if word_learner is None:
            from phraseforge.learning import WordLearner
            word_learner = WordLearner(store)
        self.words = word_learner
        self._hook_factory = hook_factory
        self._watcher_factory = watcher_factory
        self._foreground_app = foreground_app
        self._foreground_hwnd = foreground_hwnd
        self.poll_interval_s = poll_interval_s
        self._clock = clock
        self._timer_factory = timer_factory or threading.Timer

        self.matcher = AutotextMatcher()
        self.hotkeys = HotkeyMatcher(vk_from_char)
        self._clip_triggers: list[Trigger] = []
        self._time_triggers: list[tuple[Trigger, str, int]] = []
        self._focus_triggers: list[Trigger] = []
        self._smart: list[tuple[Trigger, str]] = []
        self._autotext_enabled = True
        self._opt: dict = {}

        self._paused = False
        self._pause_count = 0
        self._pause_until = 0.0
        self._suspend = 0
        self._suspend_lock = threading.Lock()
        self._hook = None
        self._watcher = None
        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._last_hwnd = None
        self._last_focus = ("", "")
        self._focus_state: dict = {}
        self._time_state: dict[int, object] = {}

        self._pending: dict | None = None      # "pause"/"continue" execution in progress
        self._pending_seq = 0
        self._suggest: dict | None = None      # visible SmartComplete / AutoComplete tip
        self._last_exp: dict | None = None     # for Backspace-undo
        self._recent = ""                      # recent typed text for auto-correction

    # ------------------------------------------------------------ state
    @property
    def paused(self) -> bool:
        return self._paused

    @paused.setter
    def paused(self, value: bool) -> None:
        self._paused = bool(value)
        self._reset_typing()

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

    def pause_for(self, repetitions: int = 1, seconds: float = 10.0) -> None:
        """Hotkey "Pause for a short time": skip the next `repetitions` triggers, or all
        triggers for `seconds` - the pause ends at whichever comes first."""
        self._pause_count = max(0, int(repetitions))
        self._pause_until = self._clock() + max(0.0, float(seconds))

    def pause_from_settings(self) -> tuple[int, float]:
        """The "pause" hotkey: Settings > Hotkeys repetitions / seconds. Returns (reps, secs)."""
        try:
            reps = int(self.store.setting("pause.repetitions", "1") or 1)
            secs = float(self.store.setting("pause.seconds", "10") or 10)
        except ValueError:
            reps, secs = 1, 10.0
        self.pause_for(reps, secs)
        return reps, secs

    def _pause_skips(self) -> bool:
        if self._pause_count <= 0 or self._clock() >= self._pause_until:
            self._pause_count = 0
            return False
        self._pause_count -= 1
        self._emit(self.on_command, "sound:unwanted_skipped")
        return True

    # ------------------------------------------------------------ lifecycle
    def reload(self) -> None:
        st = self.store
        s = st.setting
        self._autotext_enabled = s("autotext.enabled", "1") == "1"
        try:
            pause_ms = int(s("autotext.pause_ms", "700") or 700)
        except ValueError:
            pause_ms = 700
        try:
            min_chars = int(s("smartcomplete.min_chars", "3") or 3)
        except ValueError:
            min_chars = 3
        self._opt = {
            "disable_capslock": s("features.disable_capslock", "0") == "1",
            "capitalize": s("autocorrect.capitalize_sentences", "0") == "1",
            "two_caps": s("autocorrect.two_initial_capitals", "0") == "1",
            "undo": s("features.detect_unwanted_replacements", "0") == "1",
            "pause_s": max(50, pause_ms) / 1000.0,
            "min_chars": max(1, min_chars),
            "restrict": s("app.restrict_enabled", "0") == "1",
            "programs": _parse_programs(s("app.restrict_programs", "")),
        }
        self.matcher.set_route_enter_tab(s("autotext.route_enter_tab", "0") == "1")
        lead = s("autotext.leading_delimiters", "")
        self.matcher.set_leading(lead or None)
        self.matcher.set_delimiters(s("autotext.delimiters", " \t\n.,;:!?)]}'\""))
        self.matcher.load(st.triggers(TriggerKind.AUTOTEXT, owners="all") + st.triggers(TriggerKind.REGEX))
        self.hotkeys.clear()
        for key, cmd in COMMAND_HOTKEY_SETTINGS.items():
            self.hotkeys.register(s(key, ""), ("cmd", cmd))
        for t in st.triggers(TriggerKind.HOTKEY, owners="all"):
            if t.phrase_id is not None:
                self.hotkeys.register(t.value, ("phrase", t.phrase_id))
            elif t.folder_id is not None:
                self.hotkeys.register(t.value, ("folder", t.folder_id))
            elif t.special:
                self.hotkeys.register(t.value, ("folder", t.special))
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
        smart = []
        for t in st.triggers(TriggerKind.SMARTCOMPLETE):
            target = smart_target(t, st.get_phrase(t.phrase_id))
            if len(target) > self._opt["min_chars"]:
                smart.append((t, target))
        self._smart = smart
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
        try:
            self.words.save()
        except Exception:
            pass

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

    def _restricted(self, exe: str) -> bool:
        """Expert Options: "Execute only in specific programs"."""
        if not self._opt.get("restrict") or not self._opt.get("programs"):
            return False
        e = (exe or "").lower()
        return e not in self._opt["programs"] and e.removesuffix(".exe") not in self._opt["programs"]

    def _reset_typing(self) -> None:
        self.matcher.reset()
        self.words.reset()
        self._recent = ""
        self._pending = None
        self._last_exp = None
        self._hide_suggestion()

    # ------------------------------------------------------------ keyboard
    def _on_key(self, ev) -> bool:
        """Runs on the hook thread: must return quickly. True = swallow the key."""
        if ev.vk == VK_CAPITAL and self._opt.get("disable_capslock"):
            return True                                   # Caps Lock disabled (down and up)
        if not ev.down:
            return self.hotkeys.on_key_up(ev.vk)
        if not self._active():
            return False
        hwnd = self._fg_hwnd()
        if hwnd != self._last_hwnd:
            self._last_hwnd = hwnd
            self._reset_typing()
            if self.learner:
                self.learner.feed_key("focus")
        plain = not (ev.modifiers & {"ctrl", "alt", "win"}) or getattr(ev, "altgr", False)

        # a visible SmartComplete / AutoComplete tip: Tab/Enter accept, Esc dismisses
        if self._suggest is not None and plain:
            if ev.vk in (VK_TAB, VK_RETURN):
                self.accept_suggestion()
                return True
            if ev.vk == VK_ESCAPE:
                self._hide_suggestion()
                return False

        # Backspace right after an expansion: undo it (Settings > Features)
        last, self._last_exp = self._last_exp, None
        if (last is not None and ev.vk == K.VK_BACK and plain and self._opt.get("undo")
                and self._clock() - last["time"] <= UNDO_WINDOW_S):
            self._emit(self.on_command, f"undo_expansion:{last['pid']}:{last['typed']}")
            self._emit(self.on_command, "sound:unwanted_detected")
            self._hide_suggestion()
            return True

        payload = self.hotkeys.on_key_down(ev.vk, ev.modifiers)
        if payload is not None:
            return self._on_hotkey(ev, payload)

        char, key = self._classify(ev)
        if char is None and key is None:
            return False

        # "pause"/"continue" execution modes waiting on the next key
        pending, self._pending = self._pending, None
        if pending is not None and pending["mode"] == "continue" and char is not None \
                and self._clock() <= pending["deadline"]:
            m: Match = pending["match"]
            trail = "" if m.trigger.remove_trailing else m.trailing_delimiter
            self._fire(m, erase=typed_len(m), trailing=trail + char, exe=pending["exe"], title=pending["title"])
            return True

        if self.learner:
            (self.learner.feed_char(char) if char is not None else self.learner.feed_key(key))
        if char is not None:
            if self.words.feed_char(char) and self.words.last_was_correction:
                self._emit(self.on_command, "sound:spelling_added")
        else:
            self.words.feed_key(key)
            if key != "backspace":
                self._recent = ""

        if self._autotext_enabled:
            m = self.matcher.feed(char, key)
            if m is not None:
                self._hide_suggestion()
                return self._handle_match(m)
        if char is None:
            if key == "backspace":
                self._recent = self._recent[:-1]
            self._update_suggestion()
            return False

        swallow = self._autocorrect(char)
        self._update_suggestion()
        return swallow

    def _on_hotkey(self, ev, payload) -> bool:
        kind, value = payload
        if kind == "cmd":
            self._emit(self.on_command, value)
            return True
        exe, title = self._fg()
        if self._restricted(exe):
            self.hotkeys.on_key_up(ev.vk)
            return False
        if kind == "folder":
            self._emit(self.on_command, f"folder_popup:{value}:0")
            return True
        if self.store.phrase_allowed_in_app(value, exe):
            if self._pause_skips():
                self.hotkeys.on_key_up(ev.vk)
                return False
            self._emit(self.on_expand, self._request(value, exe=exe, title=title))
            return True
        self.hotkeys.on_key_up(ev.vk)  # not ours after all: let the release through
        return False

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

    # ------------------------------------------------------------ matches
    def _handle_match(self, m: Match) -> bool:
        t = m.trigger
        exe, title = self._fg()
        if self._restricted(exe):
            return False
        if t.phrase_id is None:                           # a folder's own trigger
            owner = t.folder_id if t.folder_id is not None else t.special
            self._emit(self.on_command, f"folder_popup:{owner}:{m.erase_chars}")
            return True
        pid = t.phrase_id
        if not self.store.phrase_allowed_in_app(pid, exe):
            return False
        if self._pause_skips():
            return False
        mode = t.eff_exec() if TriggerKind(t.kind) in (TriggerKind.AUTOTEXT, TriggerKind.REGEX) else "immediate"
        if mode == "confirm" and TriggerKind(t.kind) == TriggerKind.AUTOTEXT:
            self._emit(self.on_command, f"confirm:{pid}:{typed_len(m)}")
            return False      # let the key through; erase count includes it
        if mode in ("pause", "continue"):
            self._pending_seq += 1
            self._pending = {"mode": mode, "match": m, "exe": exe, "title": title, "seq": self._pending_seq,
                             "deadline": self._clock() + self._opt.get("pause_s", 0.7)}
            if mode == "pause":
                timer = self._timer_factory(self._opt.get("pause_s", 0.7), self._fire_pending,
                                            args=(self._pending_seq,))
                timer.daemon = True
                timer.start()
            return False      # the completing key is typed normally; erase typed_len later
        trail = "" if t.remove_trailing else m.trailing_delimiter
        self._fire(m, erase=m.erase_chars, trailing=trail, exe=exe, title=title)
        return True

    def _fire(self, m: Match, erase: int, trailing: str, exe: str, title: str) -> None:
        pid = m.trigger.phrase_id
        self._emit(self.on_expand, self._request(pid, erase, trailing, m.typed, m.groups, exe, title))
        self._recent = ""
        self.words.reset()
        if self._opt.get("undo"):
            self._last_exp = {"pid": pid, "typed": m.typed + m.trailing_delimiter, "time": self._clock()}

    def _fire_pending(self, seq: int) -> None:
        """Timer for the "when pausing after autotext input" mode: no key came in time."""
        p = self._pending
        if p is None or p["seq"] != seq or p["mode"] != "pause" or not self._active():
            return
        self._pending = None
        m: Match = p["match"]
        trail = "" if m.trigger.remove_trailing else m.trailing_delimiter
        self._fire(m, erase=typed_len(m), trailing=trail, exe=p["exe"], title=p["title"])

    # ------------------------------------------------------------ auto-correction
    def _sentence_start(self) -> bool:
        r = self._recent
        if not r:
            return False
        if r.endswith("\n"):
            return True
        stripped = r.rstrip(" ")
        return len(stripped) < len(r) and stripped[-1:] in (".", "!", "?")

    def _autocorrect(self, char: str) -> bool:
        """Capitalize sentence starts and fix TWo INitial CApitals. True = key swallowed."""
        if self._opt.get("capitalize") and char.isalpha() and char.islower() and char.upper() != char \
                and self._sentence_start():
            up = char.upper()
            self._recent += up
            self._emit(self.on_command, f"autocorrect:0:{up}")
            return True
        if self._opt.get("two_caps") and not (char.isalnum() or char in "'’-_"):
            word = re.search(r"[\w'’-]*$", self._recent).group(0)
            if (len(word) >= 3 and word[0].isupper() and word[1].isupper()
                    and any(c.islower() for c in word[2:]) and not any(c.isupper() for c in word[2:])):
                fixed = word[0] + word[1].lower() + word[2:]
                self._recent = self._recent[:-len(word)] + fixed + char
                self._emit(self.on_command, f"autocorrect:{len(word)}:{fixed}{char}")
                return True
        self._recent = (self._recent + char)[-64:]
        return False

    # ------------------------------------------------------------ suggestions (tip)
    def _best_smart(self) -> tuple[Trigger, int] | None:
        buf = self.matcher.buffer
        n = self._opt.get("min_chars", 3)
        best = None
        for t, target in self._smart:
            limit = min(len(target) - 1, len(buf))
            for k in range(limit, n - 1, -1):
                tail, head = buf[-k:], target[:k]
                same = tail == head if t.case_sensitive else tail.casefold() == head.casefold()
                if same and (len(buf) == k or not buf[-k - 1].isalnum()):
                    if best is None or k > best[1]:
                        best = (t, k)
                    break
        return best

    def _update_suggestion(self) -> None:
        new = None
        smart = self._best_smart()
        if smart is not None:
            t, k = smart
            new = {"kind": "smart", "pid": t.phrase_id, "len": k}
        else:
            word = self.words.current
            if len(word) >= self._opt.get("min_chars", 3):
                completion = self.words.suggest(word, self._opt.get("min_chars", 3))
                if completion:
                    new = {"kind": "word", "word": completion, "len": len(word)}
        if new == self._suggest:
            return
        if new is None:
            self._hide_suggestion()
            return
        self._suggest = new
        if new["kind"] == "smart":
            self._emit(self.on_command, f"smartcomplete:{new['pid']}:{new['len']}")
        else:
            self._emit(self.on_command, f"autocomplete:{new['word']}:{new['len']}")

    def _hide_suggestion(self) -> None:
        if self._suggest is not None:
            self._suggest = None
            self._emit(self.on_command, "suggest_hide")

    def clear_suggestion(self) -> None:
        """The tip was closed by the user (app side)."""
        self._hide_suggestion()

    def accept_suggestion(self) -> bool:
        """Tab/Enter on a visible tip, or a click on it (app side)."""
        s = self._suggest
        if s is None:
            return False
        self._hide_suggestion()
        exe, title = self._fg()
        if s["kind"] == "smart":
            self._emit(self.on_expand, self._request(s["pid"], erase=s["len"], exe=exe, title=title))
        else:
            self._emit(self.on_command, f"autocorrect:{s['len']}:{s['word']}")
        self.matcher.reset()
        self.words.reset()
        self._recent = ""
        return True

    # ------------------------------------------------------------ clipboard
    def _on_clipboard(self, text: str) -> None:
        if not self._active() or not self._clip_triggers:
            return
        exe, title = self._fg()
        if self._restricted(exe):
            return
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
        """Fire Window triggers when a matching window comes to the front (testable).
        Each trigger fires once per time its window gets focus."""
        cur = ((exe or "").lower(), title or "")
        if cur == self._last_focus:
            return []
        self._last_focus = cur
        fired = []
        for t in self._focus_triggers:
            key = t.id if t.id is not None else id(t)
            hit = window_trigger_hit(t, exe, title)
            if hit and not self._focus_state.get(key):
                fired.append(t.phrase_id)
            self._focus_state[key] = hit
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
                        if not self._restricted(exe):
                            self._emit(self.on_expand, self._request(pid, exe=exe, title=title))
            except Exception:
                log.exception("trigger poll failed")
