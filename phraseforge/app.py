"""Application wiring: tray, triggers, macro engine, output, OCR and windows.

Threads:
- The keyboard hook / clipboard / timer threads (triggers.TriggerManager) call
  back into us; we hand work to a single expansion worker thread.
- The worker runs the macro engine. Anything that shows UI goes through
  QtHost._ui(), which runs the call on the Qt main thread and waits.
"""
from __future__ import annotations

import ctypes
import logging
import os
import queue
import sys
import threading
import time
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication

from phraseforge import paths, policy
from phraseforge.policy import PolicyError
from phraseforge.db import Store
from phraseforge.host import (
    Cancelled, ExpansionContext, ExpansionRequest, FormField, TextAction,
)
from phraseforge.models import OutputMode
from phraseforge.ocr import OCRError, WindowsOCR

log = logging.getLogger("phraseforge")
AFTER_CHANGE_SYNC_MS = 60_000      # Auto sync: wait this long after the last phrase change
user32 = ctypes.windll.user32 if sys.platform == "win32" else None


# ------------------------------------------------------------------ focus helpers
def _bring_to_front(w) -> None:
    """Raise one of our windows above other programs. A window opened from the tray
    menu otherwise often appears behind the active program, because Windows only lets
    the foreground program take the focus."""
    w.show()
    w.raise_()
    w.activateWindow()
    if user32:
        try:
            _restore_focus(int(w.winId()), force=True, settle_ms=0)
        except Exception:
            log.debug("bring to front failed", exc_info=True)


def _exec_in_front(dlg):
    """dlg.exec(), with the dialog brought in front of other programs once it is shown."""
    from PySide6.QtCore import QTimer
    QTimer.singleShot(0, lambda: _bring_to_front(dlg))
    return dlg.exec()


def _foreground_hwnd() -> int:
    return user32.GetForegroundWindow() if user32 else 0


def _restore_focus(hwnd: int, force: bool = True, settle_ms: int = 50) -> None:
    """Bring the original target window back after one of our dialogs.
    force: share input state with the foreground thread so Windows allows the switch
    (Settings > Text Insertion "Force focus change"). settle_ms: Settings > Delays
    "Program focus change delay", waited after the switch."""
    import time
    if not user32 or not hwnd or user32.GetForegroundWindow() == hwnd:
        return
    if force:
        kernel32 = ctypes.windll.kernel32
        fg = user32.GetForegroundWindow()
        cur = kernel32.GetCurrentThreadId()
        fg_thread = user32.GetWindowThreadProcessId(fg, None)
        user32.AttachThreadInput(cur, fg_thread, True)
        user32.SetForegroundWindow(hwnd)
        user32.AttachThreadInput(cur, fg_thread, False)
    else:
        user32.SetForegroundWindow(hwnd)
    for _ in range(20):
        if user32.GetForegroundWindow() == hwnd:
            break
        time.sleep(0.025)
    time.sleep(max(0, settle_ms) / 1000)


def _is_own_window(hwnd: int) -> bool:
    if not user32 or not hwnd:
        return False
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value == os.getpid()


def uppercase_wanted(typed: str, enabled: bool, n: int) -> bool:
    """Settings > Text Insertion "Output in UPPERCASE if N chars of Autotext is entered
    in uppercase": the first N letters of what was typed are capitals."""
    letters = [c for c in typed or "" if c.isalpha()]
    return enabled and n > 0 and len(letters) >= n and all(c.isupper() for c in letters[:n])


def configure_logging(store: Store) -> None:
    """Settings > Features > Diagnostic mode: DEBUG level + diagnostic.log."""
    root = logging.getLogger()
    diag = store.setting("app.diagnostic_mode", "0") == "1"
    root.setLevel(logging.DEBUG if diag else logging.INFO)
    have = [h for h in root.handlers if getattr(h, "_pf_diag", False)]
    if diag and not have:
        h = logging.FileHandler(str(paths.data_dir() / "diagnostic.log"), encoding="utf-8")
        h.setLevel(logging.DEBUG)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s"))
        h._pf_diag = True
        root.addHandler(h)
    elif not diag:
        for h in have:
            root.removeHandler(h)
            h.close()


def _mime_or_png(data: bytes) -> str:
    from phraseforge import ai
    try:
        return ai.image_mime(data)
    except ai.AIError:
        return "image/png"


def _png_bytes(image) -> bytes | None:
    from PySide6.QtCore import QBuffer, QIODevice
    if image is None or image.isNull():
        return None
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    image.save(buf, "PNG")
    return bytes(buf.data())


def _clipboard_png() -> bytes | None:
    """Image on the clipboard as PNG bytes (main thread)."""
    return _png_bytes(QApplication.clipboard().image())


def _screen_physical(screen) -> tuple[int, int, int, int]:
    """(x, y, width, height) of a screen in physical pixels. Qt keeps each screen's
    origin unscaled and scales only sizes and offsets inside it (as in
    ui.region_select.logical_to_physical, which produces the capture rectangles)."""
    g, dpr = screen.geometry(), screen.devicePixelRatio()
    return g.x(), g.y(), int(round(g.width() * dpr)), int(round(g.height() * dpr))


def _grab_screen_png(rect) -> bytes | None:
    """Screenshot of a region given in physical pixels (from ui.region_select), main thread."""
    if not rect:
        return None
    x1, y1, x2, y2 = rect
    from PySide6.QtGui import QGuiApplication
    QGuiApplication.processEvents()   # finish hiding the selection overlay first
    for screen in QGuiApplication.screens():
        px, py, pw, ph = _screen_physical(screen)
        if px <= x1 < px + pw and py <= y1 < py + ph:
            shot = screen.grabWindow(0)                         # whole screen, physical resolution
            return _png_bytes(shot.copy(x1 - px, y1 - py, x2 - x1, y2 - y1).toImage())
    return None


def _cursor_physical() -> tuple[int, int]:
    """Mouse position in physical pixels (the coordinates _grab_screen_png uses)."""
    if os.name == "nt":
        from phraseforge.platform import windows
        return windows.mouse_position()
    from PySide6.QtGui import QCursor, QGuiApplication
    pos = QCursor.pos()
    screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
    g, dpr = screen.geometry(), screen.devicePixelRatio()
    return int(g.x() + (pos.x() - g.x()) * dpr), int(g.y() + (pos.y() - g.y()) * dpr)


def _area_around(x: int, y: int, mode: str):
    """Screen area (physical pixels) to read around the pointer: a wide band for a text
    line, a box for a bubble; clipped to the screen under the pointer."""
    from PySide6.QtGui import QGuiApplication
    for screen in QGuiApplication.screens():
        dpr = screen.devicePixelRatio()
        sx, sy, sw, sh = _screen_physical(screen)
        if sx <= x < sx + sw and sy <= y < sy + sh:
            if mode == "bubble":
                half_w, half_h = int(450 * dpr), int(300 * dpr)
            else:
                half_w, half_h = int(900 * dpr), int(60 * dpr)
            return (max(sx, x - half_w), max(sy, y - half_h),
                    min(sx + sw, x + half_w), min(sy + sh, y + half_h))
    return None


# ------------------------------------------------------------------ main-thread invoker
class _Invoker(QObject):
    call = Signal(object)

    def __init__(self):
        super().__init__()
        self.call.connect(self._run, Qt.ConnectionType.BlockingQueuedConnection)

    @Slot(object)
    def _run(self, job):
        fn, box = job
        try:
            box["value"] = fn()
        except BaseException as e:  # forwarded to the waiting thread
            box["error"] = e


class _Poster(QObject):
    """Fire-and-forget calls onto the main thread."""
    posted = Signal(object)

    def __init__(self):
        super().__init__()
        self.posted.connect(lambda fn: fn(), Qt.ConnectionType.QueuedConnection)


# ------------------------------------------------------------------ host services
class QtHost:
    """HostServices implementation backed by Qt dialogs and the platform layer."""

    def __init__(self, app: "PhraseForgeApp"):
        self.app = app
        self.store = app.store
        self._invoker = _Invoker()
        self._invoker.moveToThread(QApplication.instance().thread())

    def _ui(self, fn: Callable[[], Any]) -> Any:
        if threading.current_thread() is threading.main_thread():
            return fn()
        box: dict = {}
        self._invoker.call.emit((fn, box))
        if "error" in box:
            raise box["error"]
        return box.get("value")

    # user interaction
    def ask_input(self, prompt, default="", multiline=False):
        from phraseforge.ui import dialogs
        return self._ui(lambda: dialogs.ask_input(prompt, default, multiline))

    def show_form(self, title, fields: list[FormField]):
        from phraseforge.ui import dialogs
        return self._ui(lambda: dialogs.show_form(title, fields))

    def choose(self, prompt, options, multi=False):
        from phraseforge.ui import dialogs
        return self._ui(lambda: dialogs.choose(prompt, options, multi))

    def pick_date(self, prompt, default_iso):
        from phraseforge.ui import dialogs
        return self._ui(lambda: dialogs.pick_date(prompt, default_iso))

    def message(self, text, title=""):
        from phraseforge.ui import dialogs
        return self._ui(lambda: dialogs.message(text, title))

    def select_screen_region(self):
        from phraseforge.ui.region_select import select_region
        return self._ui(select_region)

    # clipboard
    def get_clipboard(self):
        from phraseforge.platform import clipboard
        return clipboard.get_text() or ""

    def set_clipboard(self, text):
        """Put text on the clipboard from the UI thread. Its hidden owner window gets Windows
        messages there; a worker thread's owner window never processes any."""
        from phraseforge.platform import clipboard
        self._ui(lambda: clipboard.set_text(text))

    def copy_checked(self, text: str, tries: int = 3) -> bool:
        """set_clipboard, then read it back; retries a few times (another program may hold
        or replace the clipboard). True when the clipboard holds the text."""
        import time
        for i in range(tries):
            try:
                self.set_clipboard(text)
                got = self._ui(self.get_clipboard)
            except Exception as e:
                log.warning("clipboard copy failed (try %d): %s", i + 1, e)
                got = None
            if got is not None and got.replace("\r\n", "\n") == text.replace("\r\n", "\n"):
                return True
            time.sleep(0.15)
        return False

    def clipboard_history(self, index):
        return self.store.clipboard_at(index)

    # phrases + variables
    def phrase_content(self, description_or_id):
        p = None
        if str(description_or_id).isdigit():
            p = self.store.get_phrase(int(description_or_id))
        p = p or self.store.find_phrase(str(description_or_id))
        return self.store.phrase_text(p, self.store.setting("phrase.active_language", "")) if p else None

    def get_var(self, name, scope="global"):
        return self.store.get_var(name, scope)

    def set_var(self, name, value, scope="global"):
        self.store.set_var(name, value, scope)

    # OS
    def run_program(self, cmd, args="", wait=False, workdir=""):
        from phraseforge.platform import windows
        return windows.run_program(cmd, args, wait, workdir)

    def open_target(self, target):
        from phraseforge.platform import windows
        windows.open_target(target)

    def wait_for_window(self, title_substring, timeout_s):
        from phraseforge.platform import windows
        return windows.wait_for_window(title_substring, timeout_s)

    def focused_app(self):
        from phraseforge.platform import windows
        return windows.foreground_app()

    # integrations
    def http_request(self, method, url, headers=None, body=None, timeout_s=30):
        from phraseforge import net
        return net.http_request(method, url, headers, body, timeout_s)

    def ai_complete(self, prompt, provider="", model="", system=""):
        from phraseforge import ai
        # {#translate} builds its own exact prompt; the user's custom instructions
        # (Settings > AI > Custom instructions) apply to {#ai} only.
        translating = (system or "").startswith("You are a translator.")
        return ai.complete(self.store.settings(), prompt, provider, model, system, raw_system=translating)

    def ai_vision(self, prompt, images, provider="", model="", system=""):
        from phraseforge import ai
        return ai.complete(self.store.settings(), prompt, provider, model, system, images=images)

    def ai_image(self, prompt, provider="", model="", size="1024x1024"):
        """{#aiimage}: make the picture and save it where ImageAction can paste it from."""
        import hashlib
        from phraseforge import ai, paths
        data = ai.generate_image(self.store.settings(), prompt, provider, model, size)
        folder = paths.data_dir() / "ai-images"
        folder.mkdir(parents=True, exist_ok=True)
        ext = {"image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}.get(_mime_or_png(data), ".png")
        out = folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{hashlib.sha1(data).hexdigest()[:8]}{ext}"
        out.write_bytes(data)
        return str(out)

    def clipboard_image(self):
        """PNG bytes of the image on the clipboard, or None."""
        def grab():
            from PySide6.QtGui import QGuiApplication
            return _png_bytes(QGuiApplication.clipboard().image())
        return self._ui(grab)

    def capture_region(self):
        """Let the user draw a screen area; PNG bytes of it (None if cancelled)."""
        rect = self.select_screen_region()
        if not rect:
            return None
        time.sleep(0.15)   # let the selection overlay disappear before the screenshot
        return self._ui(lambda: _grab_screen_png(rect))

    def _ocr(self) -> WindowsOCR:
        s = self.store.setting
        try:
            scale = int(s("ocr.scale", "0") or 0)
        except ValueError:
            scale = 0
        return WindowsOCR(scale=scale, whitelist=s("ocr.whitelist", ""), blacklist=s("ocr.blacklist", ""))

    def ocr_at_cursor(self, mode: str = "line", language: str = "") -> str:
        """Capture2Text's Text Line / Forward Text Line / Bubble capture: read the text
        under the mouse pointer without drawing a box."""
        from phraseforge.ocr import apply_replacements, parse_replace_rules
        x, y = _cursor_physical()
        rect = self._ui(lambda: _area_around(x, y, mode))
        if not rect:
            raise OCRError("The mouse pointer is outside the screens.")
        png = self._ui(lambda: _grab_screen_png(rect))
        if not png:
            raise OCRError("The area could not be captured.")
        lang = language or self.store.setting("ocr.language", "Auto")
        engine = self._ocr()
        text = engine.ocr_at(png, x - rect[0], y - rect[1], mode=mode, language=lang,
                             keep_line_breaks=self._keep_breaks(None))
        rules = parse_replace_rules(self.store.setting("ocr.replace_rules", ""))
        return apply_replacements(text, rules, engine.last_language or lang) if rules else text

    def _keep_breaks(self, keep_line_breaks) -> bool:
        if keep_line_breaks is None:   # Settings > Screen OCR > Keep line breaks
            return self.store.setting("ocr.keep_line_breaks", "1") != "0"
        return bool(keep_line_breaks)

    def ocr_region(self, language="", keep_line_breaks=None, rect=None):
        """OCR a screen area. rect=None asks the user to draw one; the area is kept
        for "Re-capture last" (like Capture2Text). Settings > Screen OCR > Replace
        rules are applied to the result."""
        from phraseforge.ocr import apply_replacements, parse_replace_rules
        if rect is None:
            rect = self.select_screen_region()
            log.info("OCR: area %s", rect)
            if not rect:
                raise Cancelled()
        self.last_ocr_rect = tuple(rect)
        lang = language or self.store.setting("ocr.language", "Auto")
        import time
        time.sleep(0.15)   # let the selection overlay disappear before the screenshot
        png = self._ui(lambda: _grab_screen_png(rect))
        log.info("OCR: captured %d bytes", len(png or b""))
        if not png:
            raise OCRError("The selected area could not be captured.")
        if self.store.setting("ocr.engine", "windows") == "mistral":
            # Settings > Screen OCR > engine "Mistral OCR (cloud)": the capture is uploaded
            from phraseforge import mistral_ocr
            try:
                text = mistral_ocr.ocr_png_text(self.store.setting("ai.mistral_key", ""), png)
            except mistral_ocr.MistralOCRError as e:
                raise OCRError(str(e)) from e
            used = language or ""
        else:
            engine = self._ocr()
            text = engine.ocr_png(png, language=lang, keep_line_breaks=self._keep_breaks(keep_line_breaks))
            used = engine.last_language or lang       # with "Auto", rules for the detected language apply
        log.info("OCR: engine %s, language %s, %d characters read",
                 self.store.setting("ocr.engine", "windows"), used, len(text or ""))
        rules = parse_replace_rules(self.store.setting("ocr.replace_rules", ""))
        return apply_replacements(text, rules, used) if rules else text

    def onenote_page_text(self, ref, include_title=False, include_ocr=False):
        """{#onenote} macro: text of a OneNote page (worker thread, own COM apartment)."""
        return self.app._onenote().page_text(ref, include_title=include_title, include_ocr=include_ocr)

    def ocr_image(self, path, language=""):
        lang = language or self.store.setting("ocr.language", "Auto")
        return self._ocr().ocr_image(path, language=lang, keep_line_breaks=self._keep_breaks(None))

    def setting(self, key, default=""):
        return self.store.setting(key, default)

    # ---- extra services used by the PhraseExpress-style macros
    def notify(self, title, text, on_click=""):
        self.app.poster.posted.emit(lambda: self.app.tray.notify(title or "PhraseForge", text))

    def ask_buttons(self, text, title, buttons):
        from PySide6.QtWidgets import QMessageBox
        def run():
            box = QMessageBox()
            box.setWindowTitle(title or "PhraseForge")
            box.setText(text)
            btns = [box.addButton(b, QMessageBox.ActionRole) for b in buttons] or [box.addButton(QMessageBox.Ok)]
            box.setWindowFlag(Qt.WindowStaysOnTopHint, True)
            box.exec()
            clicked = box.clickedButton()
            return buttons[btns.index(clicked)] if clicked in btns and buttons else ""
        return self._ui(run)

    def pick_file(self, title, directory="", filename="", ext="", save=False):
        from PySide6.QtWidgets import QFileDialog
        import os
        start = os.path.join(directory or "", filename or "")
        filt = f"*.{ext.lstrip('.')}" if ext else "All files (*)"
        def run():
            fn = QFileDialog.getSaveFileName if save else QFileDialog.getOpenFileName
            path, _ = fn(None, title or ("Save file" if save else "Select file"), start, filt)
            return path or ""
        return self._ui(run)

    def set_clipboard_files(self, paths):
        from PySide6.QtCore import QMimeData, QUrl
        def run():
            md = QMimeData()
            md.setUrls([QUrl.fromLocalFile(p) for p in paths])
            QApplication.clipboard().setMimeData(md)
        self._ui(run)

    def focus_window(self, process="", title="", state=""):
        """Bring the first window matching process exe and/or title text to front."""
        if not user32:
            return False
        from ctypes import wintypes
        import os
        found = []
        proc_l, title_l = (process or "").lower(), (title or "").lower()

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum(h, _):
            if not user32.IsWindowVisible(h):
                return True
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(h, buf, 512)
            if title_l and title_l not in buf.value.lower():
                return True
            if proc_l:
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
                k32 = ctypes.windll.kernel32
                hp = k32.OpenProcess(0x1000, False, pid.value)
                name = ""
                if hp:
                    nb = ctypes.create_unicode_buffer(520); n = wintypes.DWORD(520)
                    if k32.QueryFullProcessImageNameW(hp, 0, nb, ctypes.byref(n)):
                        name = os.path.basename(nb.value).lower()
                    k32.CloseHandle(hp)
                if proc_l not in (name, name.rsplit(".", 1)[0]):
                    return True
            found.append(h)
            return False
        user32.EnumWindows(enum, 0)
        if not found:
            return False
        h = found[0]
        user32.ShowWindow(h, {"maximized": 3, "minimized": 6}.get((state or "").lower(), 9))
        _restore_focus(h)
        return True

    def set_keyboard_layout(self, language):
        """Switch the focused window's input language, e.g. 'en-US', 'ar-SA' or a hex KLID."""
        if not user32:
            return False
        lang = (language or "").strip()
        klid = lang if len(lang) == 8 and all(c in "0123456789abcdefABCDEF" for c in lang) else None
        if not klid:
            from ctypes import wintypes
            lcid = ctypes.windll.kernel32.LocaleNameToLCID(lang, 0)
            if not lcid:
                return False
            klid = f"{lcid:08x}"
        hkl = user32.LoadKeyboardLayoutW(klid, 1)
        if not hkl:
            return False
        user32.PostMessageW(user32.GetForegroundWindow(), 0x0050, 0, hkl)  # WM_INPUTLANGCHANGEREQUEST
        return True


# ------------------------------------------------------------------ application
class PhraseForgeApp(QObject):
    def _count_ai_usage(self, provider, model, inp, out, images=0):
        from phraseforge import ai
        with ai.USAGE_LOCK:
            self.store.set_setting("ai.usage", ai.add_usage(self.store.setting("ai.usage", ""), provider, model,
                                                            inp, out, images), notify=False)

    def __init__(self, qapp: QApplication, store: Store, options=None):
        super().__init__()
        from phraseforge import cli
        self.options = options if options is not None else cli.Options()   # command-line switches
        self.qapp = qapp
        self.store = store
        from phraseforge.plugins import manager as plugin_manager
        plugin_manager.set_current(plugin_manager.PluginManager(store))   # {#<plugin>.<macro>}
        from phraseforge import ai as _ai
        _ai.USAGE_HOOK = self._count_ai_usage                                # Settings > AI > Usage
        self.host = QtHost(self)
        self.poster = _Poster()
        self._jobs: queue.Queue = queue.Queue()
        self._last_expansion: tuple[int, int] | None = None   # (phrase id, chars inserted)
        self._busy = threading.Event()
        self.main_window = None
        self.popup = None
        self.clip_window = None
        self.file_window = None
        self.quick_note = None
        self.sticky = None          # ui.sticky_notes.StickyNotesManager, created on first use
        self.file_index = None

        from phraseforge.macros import MacroEngine
        from phraseforge.platform.output import OutputExecutor
        self.engine = MacroEngine(self.host, store)
        try:  # new Settings keys + real phrases/variables in macro dialog pickers
            from phraseforge.ui.settings_schema import ensure_defaults
            ensure_defaults(store)
            from phraseforge.ui import macro_ui
            macro_ui.set_context(store, store.settings())
        except Exception:
            log.exception("UI context setup failed")

        self._apply_service_settings()
        self._build_commands()
        self._build_tray()
        self._build_triggers()
        self._build_cloud()
        self._build_shared()
        self._build_dynamic()
        self._build_local_backups()
        self._build_file_index()
        self._build_update_check()
        # the executor tells the trigger layer while it types, so our own output is ignored
        self.output = OutputExecutor(store.setting, busy_callback=self.triggers.set_busy)
        threading.Thread(target=self._worker, name="expansion", daemon=True).start()
        # OneNote actions get their own thread: a OneNote call that waits (for example while
        # OneNote shows a dialog) must not hold up text expansion and OCR.
        self._onenote_jobs: queue.Queue = queue.Queue()
        threading.Thread(target=self._onenote_worker, name="onenote", daemon=True).start()

    # ---------------------------------------------------------- commands
    def _build_commands(self):
        """Command dispatch for hotkeys/trigger-layer events (TriggerManager.on_command).

        Plain commands: "popup", "ocr", ... -> fn(arg="", hwnd)
        Prefixed commands: "confirm:<phrase id>:<erase>" -> registered under "confirm",
        called with the text after the first ':'. Add new ones with register_command().
        """
        self._commands: dict[str, Callable[[str, int], None]] = {}
        post = self.poster.posted.emit
        reg = self.register_command
        reg("confirm", lambda arg, hwnd: self._confirm_cmd(arg, hwnd))
        reg("popup", lambda arg, hwnd: post(lambda: self._show_popup(hwnd)))
        reg("clipboard_history", lambda arg, hwnd: post(lambda: self._show_clipboard(hwnd)))
        # "ocr", "ocr:recapture", "ocr:quick1".."ocr:quick3" (Capture2Text-style hotkeys)
        reg("ocr", lambda arg, hwnd: self._jobs.put(("ocr", arg, hwnd)))
        reg("new_phrase", lambda arg, hwnd: post(self._new_phrase_with_selection))
        reg("edit_last_phrase", lambda arg, hwnd: post(self._edit_last_phrase))
        reg("new_phrase_from_clipboard", lambda arg, hwnd: post(self._new_phrase_from_clipboard))
        reg("toggle_expansion", lambda arg, hwnd: post(self._toggle_expansion))
        reg("open_main", lambda arg, hwnd: post(self.show_main))
        reg("open_settings", lambda arg, hwnd: post(self.show_settings))
        reg("shared_sync", lambda arg, hwnd: post(lambda: self.shared_tick(manual=True)))
        reg("record_macro", lambda arg, hwnd: post(self.record_macro))
        reg("clear_clipboard_cache", lambda arg, hwnd: self.store.clear_clipboard(keep_pinned=True))
        reg("pause", lambda arg, hwnd: post(self._pause_cmd))
        reg("elevated", lambda arg, hwnd: post(lambda: self._elevated_notice(arg)))
        reg("sound", lambda arg, hwnd: self._play(arg))   # "sound:<event>" from other layers
        reg("popup_search", lambda arg, hwnd: post(lambda: self._show_popup(hwnd, search=True)))
        # trigger-layer events (triggers/manager.py)
        reg("folder_popup", lambda arg, hwnd: self._folder_popup_cmd(arg, hwnd))  # "<folder|last_used|clipboard_cache>:<erase>"
        reg("choose", lambda arg, hwnd: self._choice_cmd(arg, hwnd))  # "<id,id,...>:<erase>:<delim>": shared autotext
        reg("smartcomplete", lambda arg, hwnd: post(lambda: self._show_tip_phrase(arg)))   # "<pid>:<len>"
        reg("autocomplete", lambda arg, hwnd: post(lambda: self._show_tip_word(arg)))      # "<word>:<len>"
        reg("suggest_hide", lambda arg, hwnd: post(self._hide_tip))
        reg("autocorrect", lambda arg, hwnd: self._jobs.put(("replace", arg, hwnd)))       # "<erase>:<text>"
        reg("undo_expansion", lambda arg, hwnd: self._jobs.put(("undo", arg, hwnd)))       # "<pid>:<typed>"
        reg("autoskip", lambda arg, hwnd: post(lambda: self._autoskip_notice(arg)))         # "<pid>:<exe>"
        # Microsoft OneNote (Settings > OneNote hotkeys, tray menu)
        reg("onenote_send_clipboard", lambda arg, hwnd: self._onenote_jobs.put(self._onenote_send_clipboard))
        reg("onenote_clip", lambda arg, hwnd: self._onenote_jobs.put(self._onenote_clip))
        reg("quick_note", lambda arg, hwnd: post(self._show_quick_note))   # like ONENOTEM "New Quick Note"
        # Sticky notes built into PhraseForge (ui/sticky_notes.py)
        reg("open_sticky_notes", lambda arg, hwnd: post(
            lambda: self._open_sticky_notes(int(arg) if arg.isdigit() else None)))
        reg("new_sticky_note", lambda arg, hwnd: post(self._new_sticky_note))
        reg("sync_now", lambda arg, hwnd: post(self.sync_now))
        reg("prompt_tower", lambda arg, hwnd: post(lambda: self.show_prompt_tower(arg)))
        reg("ocr_file", lambda arg, hwnd: post(lambda: self.ocr_file(arg)))
        reg("prompt_optimizer", lambda arg, hwnd: post(self.show_prompt_optimizer))
        reg("boost_selection", lambda arg, hwnd: self._jobs.put(("call", lambda: self._boost_selection(hwnd), hwnd)))
        reg("instant_translate", lambda arg, hwnd: self._jobs.put(("call", lambda: self._instant_translate(hwnd), hwnd)))
        reg("delete_sticky_note", lambda arg, hwnd: post(
            lambda: self.sticky_notes().delete_note(int(arg)) if arg.isdigit() else None))
        # Search files (Listary-style launcher, phraseforge/filesearch.py)
        reg("file_search", lambda arg, hwnd: post(lambda: self._show_file_search(hwnd)))
        reg("next_language", lambda arg, hwnd: post(self._next_language))   # G-17 level hotkey

    def _next_language(self) -> None:
        """Switch the version that autotext and hotkeys insert to the next phrase language."""
        from phraseforge import levels
        new = levels.next_language(self.store.setting("phrase.active_language", ""),
                                   self.store.setting("phrase.languages", "[]"))
        self.store.set_setting("phrase.active_language", new)
        self.tray.notify("PhraseForge", f"Phrase language: {new or 'Default'}")

    def register_command(self, name: str, fn: Callable[[str, int], None]) -> None:
        self._commands[name] = fn

    def _confirm_cmd(self, arg: str, hwnd: int):
        pid, erase = (arg.split(":") + ["0"])[:2]
        self.poster.posted.emit(lambda: self._confirm(int(pid), int(erase or 0), hwnd))

    def _play(self, event: str) -> None:
        from phraseforge import sounds
        sounds.play(self.store.setting, event)

    # ---- Microsoft OneNote (official COM API; runs on the worker thread)
    def _onenote(self):
        from phraseforge.onenote import DEFAULT_EXE, OneNote
        return OneNote(self.store.setting("onenote.exe", DEFAULT_EXE) or DEFAULT_EXE)

    def _onenote_send_clipboard(self):
        """Tray/hotkey: send the clipboard (text, or image if no text) to OneNote."""
        from phraseforge.platform import clipboard
        text = clipboard.get_text() or ""
        image = None if text else self.host._ui(_clipboard_png)
        if not text and not image:
            self.poster.posted.emit(lambda: self.tray.notify("OneNote", "The clipboard is empty."))
            return
        ref = self.store.setting("onenote.default_target", "")
        self._onenote().send(text=text, image_png=image, target=ref,
                             title=text.strip().splitlines()[0][:60] if text.strip() else "Clipboard image")
        self.poster.posted.emit(lambda: self.tray.notify("Sent to OneNote", ref or "Quick Notes"))

    def _show_quick_note(self):
        from phraseforge.ui.quick_note import QuickNoteWindow
        if self.quick_note is None:
            self.quick_note = QuickNoteWindow()
            self.quick_note.send_to_onenote.connect(
                lambda text: self._onenote_jobs.put(lambda: self._onenote_send_note(text)))
            self.quick_note.save_as_phrase.connect(self._quick_note_phrase)
        self.quick_note.show_note()

    def _onenote_send_note(self, text: str):
        ref = self.store.setting("onenote.default_target", "")
        self._onenote().send(text=text, target=ref, title=text.strip().splitlines()[0][:60])
        self.poster.posted.emit(lambda: self.tray.notify("Sent to OneNote", ref or "Quick Notes"))

    def _quick_note_phrase(self, text: str):
        from phraseforge.models import Phrase
        self.store.add_phrase(Phrase(text.strip().splitlines()[0][:60], text))
        self.tray.notify("PhraseForge", "Quick note saved as a phrase")

    def _onenote_clip(self):
        """Screen clipping with PhraseForge's own area selection, then add the image to
        OneNote and/or read its text with the built-in OCR (Settings > OneNote)."""
        st = self.store.setting
        action = st("onenote.clip_action", "image")
        rect = self.host.select_screen_region()
        if rect:
            time.sleep(0.15)   # let the selection overlay disappear before the screenshot
        png = self.host._ui(lambda: _grab_screen_png(rect)) if rect else None
        if not png:
            return
        if action in ("ocr", "both"):
            text = self.host._ocr().ocr_png(png, language=st("ocr.language", "Auto"),
                                            keep_line_breaks=self.host._keep_breaks(None))
            if text:
                self.host.set_clipboard(text)
                self.poster.posted.emit(lambda: self.tray.notify("Clip text copied", text[:100]))
        if action in ("image", "both"):
            ref = st("onenote.default_target", "")
            self._onenote().send(image_png=png, target=ref, title="Screen clipping")
            self.poster.posted.emit(lambda: self.tray.notify("Clip sent to OneNote", ref or "Quick Notes"))

    def sticky_notes(self):
        """The sticky-notes manager (main thread)."""
        if self.sticky is None:
            from phraseforge.ui.sticky_notes import StickyNotesManager
            self.sticky = StickyNotesManager(self.store)
            self.sticky.save_as_phrase.connect(self._sticky_note_phrase)
        return self.sticky

    def _open_sticky_notes(self, note_id=None):
        if note_id is None:
            self.sticky_notes().show_list()
        else:
            self.sticky_notes().open_note(note_id)

    def _new_sticky_note(self):
        self.sticky_notes().new_note()

    def _sticky_note_phrase(self, title: str, text: str):
        from phraseforge.models import Phrase
        if not text.strip():
            return
        self.store.add_phrase(Phrase(title, text, tags=["stickynotes"]))
        self.tray.notify("PhraseForge", "Note saved as a phrase")

    # ---- trigger-layer command handlers
    def _pause_cmd(self):
        """Hotkey "Pause PhraseForge for a short time": skip the next N triggers or S seconds."""
        try:
            n, secs = self.triggers.pause_from_settings()
            self.tray.notify("PhraseForge paused", f"Skipping the next {n} trigger(s) for up to {secs:g} s")
        except AttributeError:          # older trigger manager
            self._pause_briefly()

    def _folder_popup_cmd(self, arg: str, hwnd: int):
        owner, _, erase = arg.rpartition(":")
        if (erase or "0").isdigit() and int(erase or 0):
            self._jobs.put(("replace", f"{erase}:", hwnd))      # remove the typed abbreviation first
        folder = int(owner) if owner.isdigit() else owner
        self.poster.posted.emit(lambda: self._show_popup(hwnd, folder=folder))

    def _choice_cmd(self, arg: str, hwnd: int):
        """Several phrases share the typed autotext: show them in a menu. Unlike a folder popup,
        the abbreviation is erased only once a phrase is chosen, by its own expansion (after its
        folder is unlocked and it is approved): cancelling the menu or the password prompt leaves
        what was typed. The delimiter typed after the abbreviation is typed again after it."""
        ids, _, rest = arg.partition(":")
        erase, _, delim = rest.partition(":")
        pending = (int(erase) if erase.isdigit() else 0, chr(int(delim)) if delim.isdigit() else "")
        self.poster.posted.emit(lambda: self._show_popup(hwnd, folder="choice:" + ids, pending=pending))

    def _popup_phrase_chosen(self, pid: int):
        erase, delim = getattr(self, "_popup_pending", (0, ""))
        self._popup_pending = (0, "")
        self._jobs.put(("expand", ExpansionRequest(
            phrase_id=pid, erase_chars=erase, trailing_delimiter=delim,
            context=ExpansionContext(app_exe=self._popup_app),
            language=getattr(self.popup, "language", "")), self._popup_hwnd))

    def _ensure_tip(self):
        if self.tip is None:
            from phraseforge.ui.smartcomplete_tip import SmartCompleteTip
            self.tip = SmartCompleteTip()
            self.tip.accepted.connect(self.triggers.accept_suggestion)
            self.tip.dismissed.connect(self.triggers.clear_suggestion)
        return self.tip

    def _show_tip_phrase(self, arg: str):
        pid, _, _n = arg.partition(":")
        p = self.store.get_phrase(int(pid)) if pid.isdigit() else None
        if p:
            x, y = self._caret_or_cursor()
            self._ensure_tip().show_for(p.description, x, y, preview=p.content.split("\n", 1)[0][:120])

    def _show_tip_word(self, arg: str):
        word, _, _n = arg.rpartition(":")
        if word:
            x, y = self._caret_or_cursor()
            self._ensure_tip().show_for(word, x, y)

    def _hide_tip(self):
        if self.tip is not None:
            self.tip.hide()

    # ---------------------------------------------------------- settings-driven services
    def _apply_service_settings(self):
        """Proxy (Settings > Network) and diagnostic logging; re-run after Settings closes."""
        try:
            from phraseforge import net
            net.configure(self.store.settings())
        except Exception:
            log.exception("proxy setup failed")
        configure_logging(self.store)

    def _build_local_backups(self):
        """Settings > Phrase File/Database > Backup: a local copy at start and then daily."""
        from PySide6.QtCore import QTimer
        self._backup_timer = QTimer(self)
        self._backup_timer.timeout.connect(self._local_backup_tick)
        self._backup_timer.start(60 * 60 * 1000)
        QTimer.singleShot(5_000, self._local_backup_tick)

    def _local_backup_tick(self):
        def work():
            try:
                from phraseforge.io_formats import auto_backup
                path = auto_backup(self.store)
                if path:
                    log.info("local backup %s", path)
            except Exception:
                log.exception("local backup failed")
        threading.Thread(target=work, name="local-backup", daemon=True).start()

    # ---------------------------------------------------------- setup
    def _build_tray(self):
        from phraseforge.ui.icons import app_icon
        from phraseforge.ui.tray import Tray
        self.qapp.setWindowIcon(app_icon())
        self.tray = Tray(app_icon())
        self.tray.open_main.connect(self.show_main)
        self.tray.show_popup.connect(lambda: self.on_command("popup"))
        self.tray.ocr_to_clipboard.connect(lambda: self.on_command("ocr"))
        self.tray.ocr_languages_provider = self._ocr_language_choices
        self.tray.ocr_language.connect(lambda lang: self.store.set_setting("ocr.language", lang))
        self.tray.clipboard_history.connect(lambda: self.on_command("clipboard_history"))
        self.tray.toggle_pause.connect(self.set_paused)
        self.tray.settings.connect(self.show_settings)
        if hasattr(self.tray, "show_statistics"):
            self.tray.show_statistics.connect(self.show_statistics)
        for sig in ("onenote_send_clipboard", "onenote_clip", "open_sticky_notes", "new_sticky_note",
                    "file_search", "quick_note", "prompt_tower", "prompt_optimizer",
                    "new_phrase_from_clipboard", "edit_last_phrase"):   # OneNote / Sticky Notes items
            if hasattr(self.tray, sig):
                getattr(self.tray, sig).connect(lambda _=None, c=sig: self.on_command(c))
        self.tray.quit.connect(self.quit)
        self._apply_tray_click()
        self.tray.language_provider = lambda: self.store.setting("ui.language", "en")
        self.tray.language.connect(self._set_language)
        self.tray.last_app_provider = lambda: self._last_app
        self.tray.excluded_provider = self.store.excluded_apps
        self.tray.app_enabled.connect(self._set_app_enabled)
        self._last_app = None
        self._start_app_tracker()
        if not self.options.has("hidden"):           # --hidden: no tray icon either
            self.tray.show()

    def _build_triggers(self):
        from phraseforge.clipboard_history import ClipboardHistory
        from phraseforge.learning import Learner
        from phraseforge.platform.windows import focused_is_password
        from phraseforge.triggers.manager import TriggerManager
        self.learner = Learner(self.store, password_check=focused_is_password,
                               on_reminder=self._abbreviation_reminder)
        self.tip = None                     # SmartComplete / autocomplete suggestion, created on demand
        try:
            from phraseforge.learning import WordLearner
            word_learner = WordLearner(self.store, paths.data_dir() / "learned_words.json")
        except Exception:
            log.exception("word learner unavailable")
            word_learner = None
        self.triggers = TriggerManager(self.store, self.on_expand_request, self.on_command,
                                       learner=self.learner, word_learner=word_learner)
        self.clip_history = ClipboardHistory(self.store)
        self.store.on_change(self._on_store_change)
        if os.environ.get("PHRASEFORGE_DEBUG_KEYS"):
            orig = self.triggers._on_key

            def spy(ev):
                r = orig(ev)
                if ev.down:  # debugging only: logs every key, never enable for normal use
                    log.info("key vk=%#x char=%r mods=%s injected=%s swallow=%s active=%s",
                             ev.vk, ev.char, ev.modifiers, ev.injected, r, self.triggers._active())
                return r
            self.triggers._on_key = spy
        if not self.options.has("no-hook"):          # --no-hook: no keyboard watching at all
            self.triggers.start()
        if not self.options.has("no-clipboard"):
            self.clip_history.start()
        if self.store.setting("caret.accessibility", "1") == "1":
            from phraseforge.platform import caret     # first use builds COM wrappers (~1 s): not on a hotkey
            threading.Thread(target=caret.warm_up, name="pf-caret-warmup", daemon=True).start()
        log.info("triggers ready")   # tools/e2e_notepad.py waits for this line

    # ---------------------------------------------------------- cloud backup & sync
    def _build_cloud(self):
        """Sync shortly after start, then on the configured interval; back up on its own interval."""
        from PySide6.QtCore import QTimer
        self._cloud_busy = threading.Lock()
        self._cloud_timer = QTimer(self)
        self._cloud_timer.timeout.connect(self._cloud_tick)
        self._cloud_timer.start(60_000)
        QTimer.singleShot(10_000, lambda: self._cloud_tick(force_sync=True))
        # Sync soon after phrases change, so nobody has to remember Send/Receive. Each new
        # change restarts the wait, so a burst of edits gives one sync.
        self._change_sync_timer = QTimer(self)
        self._change_sync_timer.setSingleShot(True)
        self._change_sync_timer.setInterval(AFTER_CHANGE_SYNC_MS)
        self._change_sync_timer.timeout.connect(self._sync_after_change)

    def _schedule_sync_after_change(self):
        """UI thread: (re)start the short wait before syncing a change."""
        st = self.store
        timer = getattr(self, "_change_sync_timer", None)
        if timer is not None and st.setting("sync.provider", "off") != "off" \
                and st.setting("sync.auto", "1") == "1":
            timer.start()

    def _sync_after_change(self):
        st = self.store
        if st.setting("sync.provider", "off") == "off" or st.setting("sync.auto", "1") != "1":
            return
        if not self._cloud_tick(force_sync=True):
            self._change_sync_timer.start()          # a sync is running: try again after the wait

    # ---------------------------------------------------------- dynamic folders (dynamic.py)
    def _build_dynamic(self):
        """Update dynamic folders whose source changed (files) or whose query is due, every 30 s."""
        from PySide6.QtCore import QTimer
        self._dynamic_busy = threading.Lock()
        self._dynamic_errors: dict[int, str] = {}
        self._library_errors: dict[str, str] = {}
        from phraseforge import libraries
        libraries.manager(self.store)          # mounted phrase libraries: guards and precedence now
        self._dynamic_timer = QTimer(self)
        self._dynamic_timer.timeout.connect(self.dynamic_tick)
        self._dynamic_timer.start(30_000)

    def dynamic_tick(self) -> None:
        if not self._dynamic_busy.acquire(blocking=False):
            return

        def work():
            from phraseforge import dynamic
            try:
                now = dict(dynamic.refresh_due(self.store))
                for fid, err in now.items():
                    if self._dynamic_errors.get(fid) != err:      # say each new problem once
                        name = getattr(self.store.get_folder(fid), "name", str(fid))
                        self.poster.posted.emit(lambda n=name, e=err: self.tray.notify(f"Dynamic folder {n}", e[:240]))
                self._dynamic_errors = now                       # a fixed problem is announced again if it returns
            except Exception:
                log.exception("dynamic folders")
            try:                                                  # phrase libraries whose file changed
                from phraseforge import libraries
                errs = {lib.id: (lib.name, e) for lib, e in libraries.manager(self.store).refresh()}
                for lid, (name, err) in errs.items():
                    if self._library_errors.get(lid) != err:
                        self.poster.posted.emit(lambda n=name, e=err: self.tray.notify(f"Phrase library {n}", e[:240]))
                self._library_errors = {k: v[1] for k, v in errs.items()}
            except Exception:
                log.exception("phrase libraries")
            finally:
                self._dynamic_busy.release()
        threading.Thread(target=work, name="dynamic-folders", daemon=True).start()

    # ---------------------------------------------------------- shared database (shared/)
    def _build_shared(self):
        """Sync the Shared folder with the shared database every shared.interval seconds."""
        from PySide6.QtCore import QTimer
        self._shared_error = ""
        self._shared_next = time.monotonic() + 5
        self._shared_timer = QTimer(self)
        self._shared_timer.timeout.connect(self.shared_tick)
        self._shared_timer.start(15_000)

    def shared_tick(self, manual: bool = False) -> None:
        from phraseforge.shared import service
        if not manual and (not service.enabled(self.store) or time.monotonic() < self._shared_next):
            return
        self._shared_next = time.monotonic() + service.interval_s(self.store)

        def work():
            try:
                res = service.sync(self.store)
                if res is None:
                    return                              # another sync is still running
                if manual or self._shared_error:
                    self.poster.posted.emit(lambda r=res: self.tray.notify("Shared database", r.summary()))
                self._shared_error = ""
            except Exception as e:                      # offline, wrong password ...: say it once
                msg = str(e)
                log.warning("shared database sync failed: %s", msg)
                if manual or msg != self._shared_error:
                    self.poster.posted.emit(lambda m=msg: self.tray.notify("Shared database", m[:240]))
                self._shared_error = msg
        threading.Thread(target=work, name="shared-sync", daemon=True).start()

    # ---------------------------------------------------------- automatic update check
    def _build_update_check(self):
        """Look for a newer release on GitHub shortly after start and then once a day
        (Settings > General > Check for updates automatically)."""
        from PySide6.QtCore import QTimer
        self._update_timer = QTimer(self, interval=60 * 60_000)        # re-checks hourly whether a day passed
        self._update_timer.timeout.connect(self.auto_check_updates)
        self._update_timer.start()
        QTimer.singleShot(30_000, self.auto_check_updates)

    def auto_check_updates(self, latest=None, force: bool = False) -> dict | None:
        """latest: test hook () -> release dict. Returns the newer release it announced."""
        from datetime import datetime
        from phraseforge import __version__, updates
        st = self.store
        if st.setting("updates.auto_check", "1") != "1":
            return None
        if not force and not updates.check_due(st.setting("updates.last_check", "")):
            return None
        box: dict = {}

        def work():
            try:
                box["rel"] = (latest or updates.latest_release)()
            except Exception as e:      # offline, proxy, rate limit: try again tomorrow
                log.info("update check failed: %s", e)
            st.set_setting("updates.last_check", datetime.now().isoformat(timespec="seconds"))
            rel = box.get("rel")
            if rel and updates.is_newer(rel["version"], __version__) and \
                    st.setting("updates.notified_version", "") != rel["version"]:
                st.set_setting("updates.notified_version", rel["version"])
                url = updates.safe_release_url(rel.get("setup_url")) or updates.safe_release_url(rel.get("url")) \
                    or updates.RELEASES_PAGE

                def show(rel=rel, url=url):
                    from PySide6.QtCore import QUrl
                    from PySide6.QtGui import QDesktopServices
                    self.tray.notify(f"PhraseForge {rel['version']} is available",
                                     f"You have {__version__}. Click here to download the new version.",
                                     ms=15000, on_click=lambda: QDesktopServices.openUrl(QUrl(url)))
                self.poster.posted.emit(show)
                box["announced"] = rel
        if latest is not None:
            work()                      # tests: run inline
            return box.get("announced")
        threading.Thread(target=work, name="update-check", daemon=True).start()
        return None

    def sync_now(self):
        """Send/Receive updates (Ctrl+F5): synchronize with the cloud now."""
        if self.store.setting("sync.provider", "off") == "off":
            self.tray.notify("Send/Receive updates",
                             "Choose a cloud service in Settings > Backup & Sync first.")
            self.show_settings()
            return
        if not self._cloud_tick(force_sync=True, manual=True):
            self.tray.notify("Send/Receive updates", "A synchronization is already running.")

    def _cloud_tick(self, force_sync: bool = False, manual: bool = False) -> bool:
        from datetime import datetime, timedelta
        st = self.store
        if st.setting("sync.provider", "off") == "off" or not self._cloud_busy.acquire(blocking=False):
            return False

        def due(key: str, minutes: float) -> bool:
            last = st.setting(key, "")
            try:
                return not last or datetime.now() - datetime.fromisoformat(last) >= timedelta(minutes=minutes)
            except ValueError:
                return True
        do_sync = manual or st.setting("sync.auto", "1") == "1" and (
            force_sync or due("sync.last_time", float(st.setting("sync.interval_min", "7") or 7)))
        do_backup = not manual and st.setting("backup.cloud_auto", "1") == "1" and due(
            "backup.cloud_last", 60 * float(st.setting("backup.cloud_interval_hours", "24") or 24))
        if not (do_sync or do_backup):
            self._cloud_busy.release()
            return True

        def work():
            try:
                from phraseforge.cloud.sync import CloudSync, make_remote
                remote = make_remote(st)
                if remote is None:
                    return
                cs = CloudSync(st, remote)
                if do_backup:
                    cs.backup_now(int(st.setting("backup.cloud_keep", "10") or 10))
                    st.set_setting("backup.cloud_last", datetime.now().isoformat(timespec="seconds"))
                if do_sync:
                    res = cs.sync()
                    if manual and res.action not in ("pulled", "merged", "conflict"):
                        msg = {"pushed": "Your phrases were sent to the cloud."}.get(
                            res.action, "Your phrases are up to date.")
                        self.poster.posted.emit(lambda m=msg: self.tray.notify("Send/Receive updates", m))
                    if res.action in ("pulled", "merged", "conflict"):
                        def on_ui(cs=cs, res=res):
                            from phraseforge.ui.cloud_ui import handle_sync_result, merge_message
                            handle_sync_result(self.main_window, cs, res, quiet=True)
                            if res.action == "pulled":
                                self.tray.notify("PhraseForge", "Phrases updated from the cloud.")
                            elif res.action == "merged":
                                self.tray.notify("PhraseForge", merge_message(res))
                        self.poster.posted.emit(on_ui)
            except Exception as e:
                log.warning("cloud sync failed: %s", e)
                self.poster.posted.emit(lambda e=e: self.tray.notify("Backup & Sync failed", str(e)))
            finally:
                self._cloud_busy.release()
        threading.Thread(target=work, name="cloud-sync", daemon=True).start()
        return True

    def _cloud_push_on_exit(self):
        """Upload local changes before quitting (no pull, no prompts)."""
        st = self.store
        if st.setting("sync.provider", "off") == "off" or st.setting("sync.auto", "1") != "1":
            return
        try:
            from phraseforge.cloud.sync import CloudSync, content_hash, make_remote
            remote = make_remote(st)
            if remote is not None and content_hash(st) != st.setting("sync.last_hash", ""):
                res = CloudSync(st, remote).sync()
                if res.pulled_file:
                    res.pulled_file.unlink(missing_ok=True)   # don't replace data while quitting
        except Exception as e:
            log.warning("sync on exit failed: %s", e)

    def _abbreviation_reminder(self, abbreviation: str, description: str):
        """Hook thread: the user typed out a phrase that has an autotext (TextExpander-style tip)."""
        self.poster.posted.emit(lambda: self.tray.notify(
            "You have an autotext for this", f'Next time type "{abbreviation}" for "{description}".'))

    def _on_store_change(self, kind, _id):
        if kind in ("phrase", "folder") and getattr(self, "learner", None) is not None:
            self.learner.invalidate_phrases()
        if kind in ("phrase", "folder", "setting"):
            self.poster.posted.emit(self.triggers.reload)
        if kind in ("phrase", "folder"):
            self.poster.posted.emit(self._schedule_sync_after_change)
        if kind == "setting" and getattr(self, "tray", None) is not None:
            self.poster.posted.emit(self._apply_tray_click)

    # PhraseExpress tray: 'Enabled in "<program>"' acts on the program used last,
    # so remember the last foreground window that is not ours or the taskbar.
    def _start_app_tracker(self) -> None:
        if sys.platform != "win32":
            return
        from PySide6.QtCore import QTimer
        self._app_timer = QTimer(self)
        self._app_timer.timeout.connect(self._track_foreground_app)
        self._app_timer.start(1000)

    def _track_foreground_app(self, fg=None) -> None:
        try:
            if fg is None:
                from phraseforge.platform.windows import foreground_app
                fg = foreground_app()
            exe, title = fg
        except Exception:
            return
        own = os.path.basename(sys.executable).lower()
        if exe and title and exe != own:
            self._last_app = (exe, title)

    def _set_app_enabled(self, exe: str, on: bool) -> None:
        if not exe:
            return
        apps = set(self.store.excluded_apps())
        if on:
            apps.discard(exe.lower())
        else:
            apps.add(exe.lower())
        self.store.set_excluded_apps(apps)

    def _set_language(self, code: str) -> None:
        mw = getattr(self, "main_window", None)
        if mw is not None and hasattr(mw, "set_language"):
            mw.set_language(code)
            return
        self.store.set_setting("ui.language", code)
        from phraseforge.ui import i18n
        i18n.install(self.qapp, i18n.resolve_language(code))

    def _apply_tray_click(self) -> None:
        on = self.store.setting("tray.left_click_popup", "0") == "1"
        self.tray.left_click = "popup" if on else "main"

    # ---------------------------------------------------------- trigger callbacks (any thread)
    def on_expand_request(self, req: ExpansionRequest):
        log.debug("trigger fired phrase=%s erase=%s", req.phrase_id, req.erase_chars)
        self._jobs.put(("expand", req, _foreground_hwnd()))

    def on_command(self, cmd: str):
        """Any thread. Looks the command up in the dispatch table (see _build_commands)."""
        hwnd = _foreground_hwnd()
        if cmd in self._commands:
            fn, arg = self._commands[cmd], ""
        else:
            name, _, arg = cmd.partition(":")
            fn = self._commands.get(name)
        if fn is None:
            log.warning("unknown command %r", cmd)
            return
        try:
            fn(arg, hwnd)
        except PolicyError as e:            # e.g. "new phrase" while the administrator disabled editing
            log.info("command %r refused by policy: %s", cmd, e)
            try:
                self.tray.notify("PhraseForge", str(e))
            except Exception:
                pass
        except Exception:
            log.exception("command %r failed", cmd)

    def _new_phrase_with_selection(self):
        """Hotkey "Create a new phrase": new phrase pre-filled with the selected text."""
        from phraseforge.models import Phrase
        text = ""
        try:
            from phraseforge.platform import windows
            text = windows.get_selected_text() or ""
        except Exception:
            pass
        desc = (text.strip().splitlines() or ["New phrase"])[0][:60]
        p = self._ask_new_phrase_info(Phrase(desc, text))
        if p is None:
            return None
        self.show_main()
        self.main_window.select_phrase(p.id)
        return p

    def _ask_new_phrase_info(self, phrase):
        """PhraseExpress "Enter additional information for the new phrase..." (Settings >
        Display > Prompt for additional information). Returns the stored phrase, or None
        when the user cancels. With the setting off the phrase is stored as given."""
        if self.store.setting("display.prompt_after_new_phrase", "1") != "1":
            return self.store.add_phrase(phrase)
        from phraseforge.ui.main_dialogs import NewPhraseInfoDialog
        dlg = NewPhraseInfoDialog(self.store, phrase.description, phrase.folder_id)
        dlg.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        if not dlg.exec():
            return None
        return self.store.add_phrase(dlg.phrase(phrase.content))

    def _new_phrase_from_clipboard(self):
        """TextExpander "New Snippet from Clipboard": a new phrase holding the clipboard text."""
        from PySide6.QtWidgets import QApplication

        from phraseforge.models import Phrase
        text = QApplication.clipboard().text() or ""
        desc = (text.strip().splitlines() or ["New phrase"])[0][:60]
        p = self.store.add_phrase(Phrase(desc, text))
        self.show_main()
        self.main_window.select_phrase(p.id)
        return p

    def _toggle_expansion(self):
        """TextExpander "Enable/Disable TextExpander" hotkey: flips the tray's Pause item."""
        act = getattr(self.tray, "pause_action", None)
        paused = not self.triggers.paused
        if act is not None:
            act.setChecked(paused)          # emits toggle_pause -> set_paused
        else:
            self.set_paused(paused)
        self.tray.notify("PhraseForge", "Text expansion paused." if paused else "Text expansion resumed.")

    def _edit_last_phrase(self):
        rows = self.store.conn.execute("SELECT phrase_id FROM usage_log ORDER BY id DESC LIMIT 1").fetchall()
        self.show_main()
        if rows:
            self.main_window.select_phrase(rows[0][0])

    def _pause_briefly(self):
        from PySide6.QtCore import QTimer
        secs = int(self.store.setting("pause.seconds", "10") or 10)
        self.set_paused(True)
        self.tray.notify("PhraseForge paused", f"Text expansion resumes in {secs} seconds.")
        QTimer.singleShot(secs * 1000, lambda: self.set_paused(False))

    # ---------------------------------------------------------- worker threads
    def _onenote_worker(self):
        while True:
            fn = self._onenote_jobs.get()
            try:
                fn()
            except Cancelled:
                pass
            except Exception as e:
                log.exception("OneNote job failed")
                self.poster.posted.emit(lambda e=e: self.tray.notify("OneNote", str(e)))

    def _worker(self):
        while True:
            kind, payload, hwnd = self._jobs.get()
            self._busy.set()
            try:
                if kind == "expand":
                    if not self._target_elevated(hwnd):
                        self._expand(payload, hwnd)
                elif kind == "ocr":
                    self._ocr_to_clipboard(payload or "")
                elif kind == "text":
                    hwnd = self._prepare_target(hwnd)
                    self._with_triggers_paused(lambda: self.output.execute(
                        [TextAction(payload)], app_exe=self._exe_of(hwnd)))
                elif kind == "replace":     # "<erase>:<text>" from autocorrect / folder popup
                    erase, _, text = payload.partition(":")
                    self._with_triggers_paused(lambda: self.output.execute(
                        [TextAction(text)] if text else [], erase_chars=int(erase or 0),
                        app_exe=self._exe_of(hwnd)))
                elif kind == "undo":        # "<pid>:<typed>": user pressed Backspace right after an expansion
                    self._undo_last_expansion(payload, hwnd)
                elif kind == "call":        # any worker-side job, e.g. OneNote actions
                    payload()
            except Cancelled:
                pass
            except Exception as e:
                log.exception("job failed")
                self.poster.posted.emit(lambda e=e: self.tray.notify("PhraseForge error", str(e)))
            finally:
                self._busy.clear()

    # ---------------------------------------------------------- windows that run as administrator
    def _target_elevated(self, hwnd) -> bool:
        """FR-INP-04: Windows blocks the keys we would type into a program that runs as
        administrator, so a half-typed phrase would be left behind. Skip and explain."""
        try:
            from phraseforge.platform import session
            if not hwnd or not session.window_elevated(hwnd):
                return False
            exe = self._exe_of(hwnd) or "?"
        except Exception:
            return False
        log.info("expansion skipped: %s runs as administrator", exe)
        self.poster.posted.emit(lambda: self._elevated_notice(exe))
        return True

    def _autoskip_notice(self, arg: str) -> None:
        """Learned auto-skip turned an autotext off in one program; clicking brings it back."""
        from phraseforge.ui.i18n import tr
        pid_s, _, exe = arg.partition(":")
        if not pid_s.isdigit():
            return
        p = self.store.get_phrase(int(pid_s))
        name = p.description if p is not None else "?"
        restore = lambda: self.triggers.autoskip.restore(int(pid_s), exe)  # noqa: E731
        self.tray.notify(tr("Autotext skipped"),
                         tr('You undid "{name}" several times in {exe}, so its autotext no longer fires there. '
                            "Click here to turn it back on.").replace("{name}", name).replace("{exe}", exe),
                         ms=10000, on_click=restore)

    def _elevated_notice(self, exe: str) -> None:
        """Tray message for an elevated window; clicking it restarts PhraseForge as administrator."""
        from phraseforge.ui.i18n import tr
        text = tr("{exe} runs as administrator, so PhraseForge cannot type into it. "
                  "Click here to restart PhraseForge as administrator (programs your phrases start then "
                  "run as administrator too).").replace("{exe}", exe or "?")
        self.tray.notify(tr("Cannot type into an administrator window"), text, ms=8000,
                         on_click=self._restart_as_admin)

    def _restart_as_admin(self) -> None:
        from phraseforge.platform import session
        if session.running_as_admin():
            return
        if session.restart_as_admin():      # the user agreed in the Windows prompt
            self.quit()

    def _undo_last_expansion(self, payload: str, hwnd: int) -> None:
        """Detect unwanted text replacements: put back what the user typed.

        The trigger layer swallows the Backspace that came right after an expansion (and plays
        the "unwanted detected" sound), so we erase the whole inserted text ourselves."""
        pid, _, typed = payload.partition(":")
        last = self._last_expansion
        if not last or str(last[0]) != pid:
            return
        inserted = last[1]
        self._last_expansion = None
        self._with_triggers_paused(lambda: self.output.execute(
            [TextAction(typed)] if typed else [], erase_chars=inserted,
            app_exe=self._exe_of(hwnd)))

    def _with_triggers_paused(self, fn):
        with self.triggers.suspend():
            fn()

    def _expand(self, req: ExpansionRequest, hwnd: int):
        p = self.store.get_phrase(req.phrase_id)
        if not p:
            return
        if not unlocked_for(self, p, req):
            return
        ctx = req.context
        ctx.phrase_id, ctx.phrase_description = p.id, p.description
        # language version: chosen in the phrase menu, else the active language (Settings)
        lang = getattr(req, "language", "") or self.store.setting("phrase.active_language", "")
        p.content, p.content_format = self.store.phrase_text(p, lang)
        p.content = wrap_in_folder_text(self.store, p)       # folder text before / after (FR-DAT-05)
        ctx.content_format = p.content_format
        if not approved_for(self, p, req):
            return
        if "{#selection" in p.content and not ctx.selected_text:
            from phraseforge.platform import windows
            ctx.selected_text = windows.get_selected_text() or ""
        typed = ctx.typed_abbreviation
        # The engine matches the output's case to the typed abbreviation. Only do
        # that when the user typed a different case than the stored abbreviation.
        if ctx.typed_abbreviation and any(
                t.case_sensitive or t.value == ctx.typed_abbreviation for t in p.autotexts()):
            ctx.typed_abbreviation = ""
        actions = self.engine.expand(p.content, ctx)
        log.debug("expand phrase=%s erase=%s actions=%d", p.id, req.erase_chars, len(actions))
        if p.content_format == "html":
            actions = self._as_html(actions)
        st = self.store.setting
        if uppercase_wanted(typed, st("output.uppercase_if", "0") == "1", int(st("output.uppercase_chars", "2") or 2)):
            actions = [TextAction(a.text.upper()) if isinstance(a, TextAction) else a for a in actions]

        from phraseforge import output_target
        target, opts = output_target.resolve(self.store, p)
        if target == "current":
            hwnd = self._prepare_target(hwnd)
            self._with_triggers_paused(lambda: self.output.execute(
                actions, erase_chars=req.erase_chars, trailing_delimiter=req.trailing_delimiter,
                mode=self._output_mode(p, ctx), app_exe=ctx.app_exe or self._exe_of(hwnd),
                key_delay_ms=getattr(ctx, "key_delay_ms", None) or None))
            # remembered for "detect unwanted text replacements" (undo with Backspace)
            from phraseforge.output_target import plain_text
            self._last_expansion = (p.id, len(plain_text(actions)) + len(req.trailing_delimiter or ""))
        else:
            self._deliver_elsewhere(target, opts, p, actions, req, hwnd)
        self._play("phrase_insertion")
        if st("features.usage_statistics", "1") != "0":   # Settings > Features > Usage statistics
            chars = sum(len(getattr(a, "text", "") or getattr(a, "plain", "")) for a in actions)
            self.store.record_use(p.id, app=ctx.app_exe, chars=max(0, chars - req.erase_chars),
                                  trigger="autotext" if req.erase_chars else "other")

    # ---------------------------------------------------------- output helpers (worker thread)
    def _prepare_target(self, hwnd: int) -> int:
        """Minimize our own window if it is in front (Settings > Text Insertion), then
        bring the target back with the configured focus delay. Returns the target hwnd."""
        st = self.store.setting
        if st("output.minimize_main", "1") == "1" and _is_own_window(hwnd) and self.main_window is not None:
            self.host._ui(self.main_window.showMinimized)
            import time
            time.sleep(0.35)
            hwnd = _foreground_hwnd()
        try:
            delay = int(st("delay.focus", "200") or 200)
        except ValueError:
            delay = 200
        _restore_focus(hwnd, force=st("output.force_focus", "1") == "1", settle_ms=min(delay, 2000))
        return hwnd

    @staticmethod
    def _exe_of(hwnd: int) -> str:
        if not user32 or not hwnd:
            return ""
        try:
            from ctypes import wintypes
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            k32 = ctypes.windll.kernel32
            hp = k32.OpenProcess(0x1000, False, pid.value)
            if not hp:
                return ""
            try:
                buf = ctypes.create_unicode_buffer(520)
                n = wintypes.DWORD(520)
                if k32.QueryFullProcessImageNameW(hp, 0, buf, ctypes.byref(n)):
                    return os.path.basename(buf.value).lower()
            finally:
                k32.CloseHandle(hp)
        except Exception:
            pass
        return ""

    def _erase_typed(self, req: ExpansionRequest, hwnd: int) -> None:
        """Remove the typed abbreviation from the app where it was typed."""
        if req.erase_chars or req.trailing_delimiter:
            hwnd = self._prepare_target(hwnd)
            self._with_triggers_paused(lambda: self.output.execute(
                [], erase_chars=req.erase_chars, trailing_delimiter=req.trailing_delimiter,
                app_exe=self._exe_of(hwnd)))

    def _deliver_elsewhere(self, target: str, opts: dict, p, actions, req: ExpansionRequest, hwnd: int) -> None:
        """Output targets other than the current application."""
        from phraseforge import output_target as ot
        from phraseforge.platform import clipboard
        text, html = ot.plain_text(actions), ot.html_of(actions)
        notify = lambda title, body: self.poster.posted.emit(lambda: self.tray.notify(title, body))  # noqa: E731
        if target == "clipboard":
            self._erase_typed(req, hwnd)
            clipboard.set_html(html, text) if html else clipboard.set_text(text)
            notify("Copied to clipboard", p.description)
        elif target == "textfile":
            self._erase_typed(req, hwnd)
            docs = os.path.join(os.path.expanduser("~"), "Documents")
            path = self.host.pick_file("Save phrase as text file", docs, ot.safe_filename(p.description) + ".txt",
                                       "txt", save=True)
            if path:
                saved = ot.write_text_file(path, text)
                notify("Phrase saved", str(saved))
        elif target == "email":
            self._erase_typed(req, hwnd)
            from phraseforge.macros.commands import mail_url
            st = self.store.setting
            url = mail_url("", {"subject": p.description, "body": text}, st("mail.method", "mailto"),
                           st("mail.utf8", "1") != "0")
            self.host.open_target(url)
        elif target == "onenote":
            self._erase_typed(req, hwnd)
            ref = opts.get("arg", "") or self.store.setting("onenote.default_target", "")
            self._onenote().send(text=text, target=ref, title=p.description)
            notify("Sent to OneNote", ref or "Quick Notes")
        elif target == "program":
            exe = opts.get("output_program", "")
            if not exe or not os.path.isfile(exe):
                exe = self.host.pick_file(f'Program for "{p.description}"', os.environ.get("ProgramFiles", ""),
                                          "", "exe", save=False)
                if not exe:
                    return
                ot.remember_program(self.store, p.id, exe)
            self._erase_typed(req, hwnd)
            name = os.path.basename(exe).lower()
            if not self.host.focus_window(process=name):
                self.host.run_program(exe)
                import time
                for _ in range(40):           # up to ~10 s for the window to appear
                    time.sleep(0.25)
                    if self.host.focus_window(process=name):
                        break
                else:
                    raise RuntimeError(f"{name} did not open a window")
            target_hwnd = _foreground_hwnd()
            self._with_triggers_paused(lambda: self.output.execute(
                ot.only_text(actions), mode=OutputMode(p.output_mode), app_exe=name))
            log.debug("phrase %s inserted into %s (%s)", p.id, name, target_hwnd)

    def _output_mode(self, p, ctx) -> OutputMode:
        """{#pastemethod} in the phrase wins, then the phrase setting, then Settings > Text Insertion."""
        pm = getattr(ctx, "paste_method", "") or ""
        if pm in ("auto", "type", "paste"):
            return OutputMode(pm)
        mode = OutputMode(p.output_mode)
        if mode == OutputMode.AUTO and self.store.setting("output.method", "keys") == "clipboard":
            return OutputMode.PASTE   # "keys" keeps AUTO: type short text, paste long text
        return mode

    @staticmethod
    def _as_html(actions):
        """Turn the text parts of an HTML phrase into a single HtmlAction."""
        from phraseforge.host import HtmlAction
        from PySide6.QtGui import QTextDocument
        out, buf = [], []
        def flush():
            if buf:
                html = "".join(buf)
                doc = QTextDocument()
                doc.setHtml(html)
                out.append(HtmlAction(html=html, plain=doc.toPlainText()))
                buf.clear()
        for a in actions:
            if isinstance(a, TextAction):
                buf.append(a.text)
            else:
                flush()
                out.append(a)
        flush()
        return out

    def _ocr_language_choices(self):
        """Tray "OCR language" menu: the current language plus the quick-access ones."""
        from phraseforge.ocr import quick_languages
        from phraseforge.ocr import AUTO
        current = self.store.setting("ocr.language", AUTO)
        langs = quick_languages(self.store.setting("ocr.quick_languages", ""))
        if current and current not in langs:
            langs.insert(0, current)
        if AUTO not in langs:
            langs.insert(0, AUTO)
        return langs, current

    def _ocr_to_clipboard(self, mode: str = ""):
        """mode: "" draw an area; "recapture" OCR the last area again; "quickN" draw an
        area and use quick-access language N (Settings > Screen OCR)."""
        from phraseforge.ocr import quick_languages
        s = self.store.setting
        language, rect = "", None
        if mode in ("textline", "forward", "bubble"):
            try:
                text = self.host.ocr_at_cursor({"textline": "line"}.get(mode, mode))
            except OCRError as e:
                self.poster.posted.emit(lambda e=e: self.tray.notify("OCR", str(e)))
                return
            self._ocr_deliver(text)
            return
        if mode == "recapture":
            rect = getattr(self.host, "last_ocr_rect", None)
            if not rect:
                self.poster.posted.emit(lambda: self.tray.notify("OCR", "Nothing captured yet"))
                return
        elif mode.startswith("quick"):
            langs = quick_languages(s("ocr.quick_languages", ""))
            i = int(mode[5:] or 1) - 1
            if not 0 <= i < len(langs):
                self.poster.posted.emit(lambda: self.tray.notify("OCR", f"Quick-access language {i + 1} is not set"))
                return
            language = langs[i]
        try:
            text = self.host.ocr_region(language=language, rect=rect)
        except OCRError as e:   # e.g. the OCR language is not installed in Windows
            self.poster.posted.emit(lambda e=e: self.tray.notify("OCR", str(e)))
            return
        self._ocr_deliver(text)

    def _ocr_deliver(self, text: str):
        """Settings > Screen OCR > Output: log file, clipboard, notification."""
        s = self.store.setting
        from phraseforge.ocr import format_log_entry
        if not text:
            log.info("OCR: no text recognised")
            self.poster.posted.emit(lambda: self.tray.notify("OCR", "No text recognised"))
            return
        log_file = s("ocr.log_file", "").strip()
        if log_file:
            try:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(format_log_entry(text, s("ocr.log_format", "${capture}${linebreak}")))
            except OSError:
                log.exception("OCR log file")
        copied = s("ocr.save_to_clipboard", "1") != "0"
        if copied and not self.host.copy_checked(text):
            log.warning("OCR: the text could not be put on the clipboard")
            self.poster.posted.emit(lambda: self.tray.notify(
                "OCR", "The text was read but could not be copied to the clipboard. Another program "
                       "may be holding the clipboard; try again."))
            return
        log.info("OCR: %d characters delivered (clipboard %s, notification %s)", len(text),
                 "on" if copied else "off", "on" if s("ocr.show_popup", "1") != "0" else "off")
        if s("ocr.show_popup", "1") != "0":
            preview = text if len(text) < 120 else text[:117] + "..."
            title = "OCR copied to clipboard" if copied else "OCR"
            self.poster.posted.emit(lambda: self.tray.notify(title, preview))

    # ---------------------------------------------------------- main-thread UI
    def _caret_point(self):
        """The caret in Qt coordinates, or None."""
        try:
            from phraseforge.platform import windows
            from phraseforge.ui.region_select import physical_to_logical
            pos = windows.caret_position(self.store.setting("caret.accessibility", "1") == "1")
            if pos:
                return physical_to_logical(*pos)      # the caret is in physical pixels, Qt is not
        except Exception:
            pass
        return None

    def _caret_or_cursor(self):
        from PySide6.QtGui import QCursor
        pos = self._caret_point()
        if pos:
            return pos
        c = QCursor.pos()
        return c.x(), c.y()

    def _show_popup(self, hwnd, folder=None, search: bool = False, pending: tuple[int, str] = (0, "")):
        """pending: (abbreviation chars to erase, delimiter to re-type) for the phrase chosen
        from a multiple-choice autotext menu; nothing for every other menu."""
        from phraseforge.ui.popup import PhrasePopup
        self._popup_pending = pending
        if self.popup is None:
            self.popup = PhrasePopup(self.store)
            self.popup.phrase_chosen.connect(self._popup_phrase_chosen)
            if hasattr(self.popup, "clipboard_chosen"):
                self.popup.clipboard_chosen.connect(
                    lambda text: self._jobs.put(("text", text, self._popup_hwnd)))
            if hasattr(self.popup, "new_phrase_requested"):
                self.popup.new_phrase_requested.connect(self._new_phrase_from_popup)
                self.popup.sticky_notes_requested.connect(lambda: self._open_sticky_notes())
        try:
            from phraseforge.platform import windows
            self._popup_app = windows.foreground_app()[0]
        except Exception:
            self._popup_app = ""
        self._popup_hwnd = hwnd
        from PySide6.QtGui import QCursor
        caret = self._caret_point()                 # looked up once, handed to the popup
        x, y = caret or (QCursor.pos().x(), QCursor.pos().y())
        kw = {"search": True, "caret": caret} if search else {"caret": caret}
        if folder is not None:
            kw["folder"] = folder
        try:
            self.popup.show_at(x, y, self._popup_app, **kw)   # the popup plays its own sound
        except TypeError:          # popup without folder support: open the normal menu
            self.popup.show_at(x, y, self._popup_app, search=search, caret=caret)

    def _new_phrase_from_popup(self):
        """Popup footer "New phrase...": create it in the popup's folder and open the editor."""
        from phraseforge.models import Phrase
        folder_id = getattr(self.popup, "new_phrase_folder_id", None)
        p = self._ask_new_phrase_info(Phrase("New phrase", "", folder_id=folder_id))
        if p is None:
            return
        self.show_main()
        if hasattr(self.main_window, "select_phrase"):
            self.main_window.select_phrase(p.id)

    def show_statistics(self):
        from phraseforge.ui.stats_window import StatsWindow
        _exec_in_front(StatsWindow(self.store))

    # ---- Search files (Listary-style launcher)
    def _build_file_index(self):
        from phraseforge import filesearch
        s = self.store.setting
        roots = filesearch.parse_roots(s("filesearch.roots", "")) or None
        rules = filesearch.parse_priority_rules(s("filesearch.priorities", filesearch.DEFAULT_PRIORITY_RULES))
        self.file_index = filesearch.FileIndex(roots, include_hidden=s("filesearch.include_hidden", "0") == "1",
                                               history_file=paths.data_dir() / "filesearch_history.json",
                                               priority_rules=rules)
        if s("filesearch.enabled", "1") != "1":
            return
        self.file_index.build_async()
        from PySide6.QtCore import QTimer
        try:
            minutes = max(5, int(s("filesearch.refresh_minutes", "30") or 30))
        except ValueError:
            minutes = 30
        self._file_index_timer = QTimer(interval=minutes * 60_000)
        self._file_index_timer.timeout.connect(lambda: self.file_index.building or self.file_index.build_async())
        self._file_index_timer.start()

    def show_prompt_tower(self, set_name: str = ""):
        """Prompt Tower: build an AI prompt from project files (ui/prompt_tower.py)."""
        from phraseforge.ui.prompt_tower import PromptTowerWindow
        w = getattr(self, "prompt_tower", None)
        if w is None:
            w = self.prompt_tower = PromptTowerWindow(self.store)
            w.save_as_phrase.connect(self._prompt_to_phrase)
        if set_name:
            w.load_set(set_name)
        if w.isMinimized():
            w.showNormal()
        _bring_to_front(w)
        return w

    def _boost_selection(self, hwnd: int, get_selection=None, boost=None) -> str:
        """PromptBoost hotkey (worker thread): the text selected in any program is replaced
        by a detailed, structured prompt. On any error the selection stays as it was."""
        from phraseforge import ai
        if get_selection is None:
            from phraseforge.platform import windows
            get_selection = windows.get_selected_text
        text = (get_selection() or "").strip()
        notify = lambda t, m: self.poster.posted.emit(lambda: self.tray.notify(t, m))   # noqa: E731
        if not text:
            notify("Boost prompt", "Select the prompt text first, then press the hotkey again.")
            return ""
        notify("Boost prompt", "Improving the selected prompt…")
        try:
            out = (boost or (lambda t: ai.boost_prompt(self.store.settings(), t)))(text)
        except Exception as e:      # noqa: BLE001 - shown to the user, selection unchanged
            notify("Boost prompt", f"The prompt was not changed: {e}")
            return ""
        hwnd = self._prepare_target(hwnd)
        self._with_triggers_paused(lambda: self.output.execute([TextAction(out)], app_exe=self._exe_of(hwnd)))
        return out

    def _instant_translate(self, hwnd: int, get_selection=None, translate_fn=None, target: str = "") -> None:
        """Instant translation hotkey (worker thread): translate the selected text and show it
        in the translation window next to the caret (instant_translate.py)."""
        from phraseforge import instant_translate as it
        if get_selection is None:
            from phraseforge.platform import windows
            get_selection = windows.get_selected_text
        text = (get_selection() or "").strip()
        post = lambda fn: self.poster.posted.emit(fn)   # noqa: E731
        if not text:
            post(lambda: self.tray.notify("Instant translation", "Select some text first, then press the hotkey."))
            return
        if not target:                    # a new selection (not a retranslation): its window is the target
            self._translate_hwnd = hwnd
        self._translate_req = rid = getattr(self, "_translate_req", 0) + 1
        cut = it.was_cut(text)
        settings = self.store.settings()

        def busy():
            b = self._bubble()
            b.back_language = settings.get("translate.instant_back") or "English"
            b.show_busy(text, *self._caret_or_cursor(), request=rid)
        post(busy)
        try:
            out, lang = it.translate(settings, text, target, translate_fn)
        except Exception as e:     # noqa: BLE001 - shown in the window
            msg = f"Could not translate: {e}"
            post(lambda: self._bubble().show_error(msg, request=rid))
            return
        post(lambda: self._bubble().show_result(text, out, lang, request=rid, cut=cut))

    def _bubble(self):
        b = getattr(self, "_translate_bubble", None)
        if b is None:
            from phraseforge.ui.translate_bubble import TranslateBubble
            b = self._translate_bubble = TranslateBubble()
            b.replace_requested.connect(self._replace_with_translation)
            b.retranslate.connect(lambda text, lang: self._jobs.put(
                ("call", lambda: self._instant_translate(self._translate_hwnd, lambda: text, None, lang),
                 self._translate_hwnd)))
            b.speak_requested.connect(self._speak_translation)
        return b

    def _replace_with_translation(self, text: str) -> None:
        hwnd = getattr(self, "_translate_hwnd", 0)
        try:
            if hwnd and user32 and not user32.IsWindow(hwnd):   # the program was closed meanwhile
                self.tray.notify("Instant translation", "That window is gone: use Copy instead.")
                return
        except (AttributeError, OSError):                       # not Windows
            pass

        def run():
            if self._target_elevated(hwnd):
                return
            target = self._prepare_target(hwnd)
            if user32 and (not hwnd or not user32.IsWindow(hwnd) or user32.GetForegroundWindow() != hwnd):
                # the window was closed or did not come back: typing now would go into whatever
                # program is in front (R155)
                self.poster.posted.emit(lambda: self.tray.notify(
                    "Instant translation", "The original window is gone or could not be brought back; "
                    "nothing was typed. Use Copy instead."))
                return
            self._with_triggers_paused(lambda: self.output.execute([TextAction(text)], app_exe=self._exe_of(target)))
        self._jobs.put(("call", run, hwnd))

    def _speak_translation(self, text: str) -> None:
        import threading
        from phraseforge.macros import commands_pe

        def run():
            com = None
            try:
                import pythoncom  # type: ignore
                pythoncom.CoInitialize()          # a new thread needs COM before SAPI
                com = pythoncom
            except Exception:      # noqa: BLE001 - not Windows
                pass
            try:
                commands_pe.SPEAKER(text, wait=True)   # this thread lives until the voice is done
            except Exception:      # noqa: BLE001 - no SAPI voice on this PC
                self.poster.posted.emit(lambda: self.tray.notify("Instant translation", "No Windows voice is available."))
            finally:
                if com is not None:
                    com.CoUninitialize()
        threading.Thread(target=run, daemon=True, name="translate-speak").start()

    def ocr_file(self, path: str = "", post=None, open_result: bool = True):
        """Tools > OCR PDF / image (Mistral OCR): Markdown and images are saved in a folder named
        after the file, then the Markdown opens. Runs the upload on a background thread."""
        from phraseforge import mistral_ocr
        if not path:
            from PySide6.QtWidgets import QFileDialog
            path, _ = QFileDialog.getOpenFileName(None, "OCR a PDF or image", "",
                                                  mistral_ocr.FILE_FILTER)
            if not path:
                return None
        key = self.store.setting("ai.mistral_key", "").strip()
        # With a Mistral key the file goes to Mistral OCR (cloud); without one it is read on this
        # PC: the PDF's own text, or Windows OCR for scans and images.
        title = "Mistral OCR" if key else "OCR"
        self.tray.notify(title, f"Reading {os.path.basename(path)}…")
        box: dict = {}

        def work():
            try:
                if key:
                    md, pages = mistral_ocr.ocr_file(key, path, post=post)
                else:
                    from phraseforge import local_ocr_file
                    lang = self.store.setting("ocr.language", "Auto")
                    engine = self.host._ocr()
                    md, pages = local_ocr_file.ocr_file(
                        path, lambda png: engine.ocr_png(png, language=lang, keep_line_breaks=True))
                box["md"] = md
                log.info("OCR file: %d page(s) from %s saved to %s", len(pages), os.path.basename(path), md)

                def done(md=md, n=len(pages)):
                    self.tray.notify(title, f"{n} page(s) saved to {md.parent.name}.")
                    if open_result:
                        from PySide6.QtCore import QUrl
                        from PySide6.QtGui import QDesktopServices
                        QDesktopServices.openUrl(QUrl.fromLocalFile(str(md)))
                self.poster.posted.emit(done)
            except Exception as e:      # noqa: BLE001 - shown to the user
                log.warning("%s failed: %s", title, e)
                self.poster.posted.emit(lambda e=e: self.tray.notify(f"{title} failed", str(e)))
        t = threading.Thread(target=work, name="ocr-file", daemon=True)
        t.start()
        if post is not None:          # tests: wait for the result
            t.join(30)
            return box.get("md")
        return None

    def show_prompt_optimizer(self):
        """Prompt Optimizer: chat that turns an idea into a precise prompt (ui/prompt_optimizer.py)."""
        from phraseforge.ui.prompt_optimizer import PromptOptimizerWindow
        w = getattr(self, "prompt_optimizer", None)
        if w is None:
            w = self.prompt_optimizer = PromptOptimizerWindow(self.store)
            w.save_as_phrase.connect(self._prompt_to_phrase)
            w.to_prompt_tower.connect(lambda text: self.show_prompt_tower().prefix.setPlainText(text))
        if w.isMinimized():
            w.showNormal()
        _bring_to_front(w)
        return w

    def _prompt_to_phrase(self, description: str, text: str):
        from phraseforge.models import Phrase
        p = self.store.add_phrase(Phrase(description[:80], text, tags=["prompttower"]))
        self.tray.notify("Prompt Tower", f'Saved as the phrase "{p.description}".')

    def _show_file_search(self, hwnd):
        from phraseforge.ui.file_search import FileSearchWindow
        if self.file_index is None:
            self._build_file_index()
        if self.file_window is None:
            from phraseforge import filesearch
            kw = filesearch.parse_web_keywords(self.store.setting("filesearch.web_keywords", "")
                                               or filesearch.DEFAULT_WEB_KEYWORDS)
            self.file_window = FileSearchWindow(
                self.file_index, web_keywords=kw,
                filters=filesearch.parse_filters(self.store.setting("filesearch.filters", "")),
                custom_actions=filesearch.parse_custom_actions(self.store.setting("filesearch.actions", "")),
                custom_commands=filesearch.parse_custom_commands(
                    self.store.setting("filesearch.commands", filesearch.DEFAULT_CUSTOM_COMMANDS)),
                favorites=filesearch.parse_roots(self.store.setting("filesearch.favorites", "")))
            self.file_window.insert_path.connect(lambda path: self._jobs.put(("text", path, self._file_hwnd)))
            self.file_window.open_settings.connect(self.show_settings)
        elif self.file_window.isVisible() and self.store.setting("filesearch.press_again", "hide") == "hide":
            self.file_window.hide()            # Listary: "When pressing again: Hide"
            return
        self._file_hwnd = hwnd
        if not len(self.file_index) and not self.file_index.building:
            self.file_index.build_async()
        self.file_window.show_centered()

    def _show_clipboard(self, hwnd):
        from phraseforge.ui.clipboard_window import ClipboardWindow
        if self.clip_window is None:
            self.clip_window = ClipboardWindow(self.store)
            self.clip_window.entry_chosen.connect(
                lambda text: self._jobs.put(("text", text, self._clip_hwnd)))
        self._clip_hwnd = hwnd
        x, y = self._caret_or_cursor()
        self.clip_window.show_at(x, y)

    def _confirm(self, phrase_id, erase, hwnd):
        from phraseforge.ui import dialogs
        p = self.store.get_phrase(phrase_id)
        if p and dialogs.confirm_expand(p.description):
            self._jobs.put(("expand", ExpansionRequest(phrase_id=phrase_id, erase_chars=erase), hwnd))

    def test_phrase(self, phrase_id: int):
        """'Test' button in the editor: expand into the previously focused app."""
        self._jobs.put(("expand", ExpansionRequest(phrase_id=phrase_id), _foreground_hwnd()))

    # ---------------------------------------------------------- macro recorder (recorder.py)
    def record_macro(self):
        """Start recording, or stop when a recording runs. The result becomes a new phrase."""
        ctl = getattr(self, "_recording", None)
        if ctl is not None and ctl.active:
            ctl.finish()
            return
        from phraseforge.ui.recording_bar import RecordingController
        try:
            from phraseforge.platform.windows import focused_is_password
        except Exception:
            focused_is_password = None

        def skip_key() -> bool:
            """Keys not to record: a password field, or any PhraseForge window (its folder
            password prompt, the editor), whose text is not something to replay (R50)."""
            try:
                if user32 and _is_own_window(user32.GetForegroundWindow()):
                    return True
            except Exception:
                pass
            return bool(focused_is_password and focused_is_password())
        self._recording = RecordingController(self.store, self._recorded, post=self.poster.posted.emit,
                                              triggers=self.triggers, password_check=skip_key)
        self._recording.start()

    def _recorded(self, text: str):
        if not text.strip():
            self.tray.notify("PhraseForge", "Nothing was recorded.")
            return
        from datetime import datetime
        from phraseforge.models import Phrase
        p = self.store.add_phrase(Phrase("Recorded macro " + datetime.now().strftime("%Y-%m-%d %H:%M"), text))
        self.show_main()
        self.main_window.refresh_tree()
        self.main_window.select_phrase(p.id)

    def show_main(self):
        from phraseforge.ui.main_window import MainWindow
        if self.main_window is None:
            self.main_window = MainWindow(self.store, on_test_phrase=self.test_phrase,
                                          on_command=self.on_command, tray=getattr(self, "tray", None))
        if self.main_window.isMinimized():
            self.main_window.showNormal()
        _bring_to_front(self.main_window)

    def show_settings(self):
        from phraseforge.ui.policy_ui import settings_allowed
        if not settings_allowed():
            return
        from phraseforge.ui.settings_dialog import SettingsDialog
        _exec_in_front(SettingsDialog(self.store))
        try:
            from phraseforge import autostart
            if not paths.is_portable():            # portable: never touch the registry
                autostart.set_enabled(self.store.setting("app.start_with_windows", "0") == "1")
        except Exception:
            log.exception("autostart update failed")
        from phraseforge.ui.theme import apply_theme
        from phraseforge.ui import i18n
        apply_theme(self.qapp, self.store.setting("ui.theme", "system"),
                    i18n.resolve_language(self.store.setting("ui.language", "auto")))
        self._apply_service_settings()
        self.triggers.reload()

    def set_paused(self, paused: bool):
        self.triggers.paused = bool(paused)

    def quit(self):
        try:
            if self.sticky is not None:
                self.sticky.flush()      # save notes typed in the last half second
            self.triggers.stop()
            self.clip_history.stop()
            from phraseforge.plugins import manager as plugin_manager
            if plugin_manager.current() is not None:
                plugin_manager.current().stop_all()
            self._cloud_push_on_exit()
        finally:
            self.tray.hide()
            self.qapp.quit()


def wrap_in_folder_text(store, p) -> str:
    """The phrase's content with its folders' text before and after it (macros included). In a
    formatted phrase the folder text is plain text: it is escaped and its line breaks kept."""
    before, after = store.folder_wrap(p.folder_id)
    if not (before or after):
        return p.content
    if p.content_format == "html":
        import html as _html

        def esc(t: str) -> str:
            return _html.escape(t, quote=False).replace("\n", "<br>")
        before, after = esc(before), esc(after)
    return before + p.content + after


# ---------------------------------------------------------- protection (security.py)
# Module functions (not methods) so tests can drive _expand with a stand-in app.
def _skipped_phrase(app, p, why: str) -> None:
    from phraseforge.ui.i18n import tr
    log.warning("phrase %s not run: %s", p.id, why)   # no phrase names in the log (R73)
    text = tr('"{name}" was skipped: it is not approved on this PC and was started automatically.')
    app.poster.posted.emit(lambda: app.tray.notify(tr("Phrase not run"), text.format(name=p.description)))


def unlocked_for(app, p, req: ExpansionRequest) -> bool:
    """A phrase in a password folder needs the password first (once per session).
    Nothing has been typed or erased yet, so a refused unlock leaves the abbreviation."""
    from phraseforge.security import LOCKS
    while (locked := LOCKS.locked_folder(app.store, p.folder_id)) is not None:
        if req.automatic:
            log.info("phrase %s not run: folder %s is locked", p.id, locked.id)
            return False
        from phraseforge.ui.dialogs import ask_folder_password
        if not app.host._ui(lambda f=locked: ask_folder_password(app.store, f)):
            return False
    return True


def approved_for(app, p, req: ExpansionRequest) -> bool:
    """Imported or synced phrases that use privileged macros need the user's OK.
    Sets req.context.allow_privileged for the engine's run-time check."""
    origin = app.store.quarantine_origin(p.id)
    if not origin:
        return True
    from phraseforge import output_target
    from phraseforge.security import scan_privileged
    reasons = scan_privileged(p.content)
    target = output_target.resolve(app.store, p)[0]
    if target == "program":
        reasons.append("start a program (output target)")
    elif target in ("email", "onenote"):
        reasons.append(f"send its text by {'e-mail' if target == 'email' else 'OneNote'} (output target)")
    req.context.allow_privileged = False
    if not reasons:
        return True                       # nothing privileged to block; the engine still guards
    if req.automatic:
        _skipped_phrase(app, p, f"unapproved {origin} phrase wants to: {', '.join(reasons)}")
        return False
    from phraseforge.ui import dialogs
    answer = app.host._ui(lambda: dialogs.approve_phrase(p.description, origin, reasons))
    if answer == dialogs.ALLOW_ALWAYS:
        app.store.release_quarantine(p.id)
        if hasattr(app.store, "release_folder_chain"):
            app.store.release_folder_chain(p.id)
    if answer in (dialogs.ALLOW_ONCE, dialogs.ALLOW_ALWAYS):
        req.context.allow_privileged = True
        return True
    return False


def quiet_http_loggers() -> None:
    """HTTP libraries log every request URL at INFO (and headers at DEBUG). URLs can hold the
    text sent for translation or a token in a {#http} query string, so keep them out of the log."""
    for name in ("httpx", "httpcore", "urllib3", "googleapiclient", "google_auth_oauthlib", "oauthlib"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _plugin_entry_ok(path: str) -> str:
    """"" when `path` is the entry script of a plugin the administrator allows, else why not.
    Without this check PhraseForge.exe ran any Python file, also on a PC whose policy allows
    no plugins (security R106)."""
    from pathlib import Path
    from phraseforge import policy
    from phraseforge.plugins import manifest as pman
    if not os.environ.get("PHRASEFORGE_PLUGIN_API"):
        return "--run-plugin is only used by PhraseForge itself"
    p = Path(path).resolve()
    try:
        m = pman.parse((p.parent / "plugin.toml").read_text(encoding="utf-8-sig"))
    except Exception as e:                  # noqa: BLE001 - no or bad manifest: not a plugin
        return f"not a plugin: {e}"
    if m.id != p.parent.name or (p.parent / m.entry).resolve() != p:
        return "not the entry script of an installed plugin"
    pol = policy.current()
    allowed = pol.plugins_allowed
    if allowed is None:
        ok = not (pol.settings_locked or pol.editing_disabled)
    else:
        ok = "*" in allowed or m.id in allowed
    return "" if ok else "your administrator does not allow this plugin"


def _run_plugin(path: str) -> int:
    """The frozen EXE runs a Python plugin's entry script (plugins/host.py starts it this way)."""
    import runpy
    from pathlib import Path
    why = _plugin_entry_ok(path)
    if why:
        print(f"PhraseForge: {why}", file=sys.stderr)
        return 2
    import tempfile
    sys.dont_write_bytecode = True
    given = os.environ.get("PHRASEFORGE_PYCACHE", "")       # made by PhraseForge itself (Medium integrity)
    sys.pycache_prefix = given if given and os.path.isdir(given) else tempfile.mkdtemp(prefix="pf-pycache-")
    sys.argv = [path]
    sys.path[:] = [str(Path(path).parent)] + [p for p in sys.path if p]
    runpy.run_path(path, run_name="__main__")
    return 0


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv)
    if len(raw) >= 3 and raw[1] == "--run-plugin":          # never mixed with the app start-up
        return _run_plugin(raw[2])
    from phraseforge import cli
    argv = cli.link_only(raw)                               # a link: nothing else (R81)
    argv = paths.apply_command_line(argv)                   # --portable, --home
    try:
        options = cli.parse(argv[1:])
    except cli.UsageError as e:
        print(f"PhraseForge: {e}", file=sys.stderr)
        return 2
    if options.has("self-test"):
        from phraseforge.selftest import run
        return run()
    if options.has("register-url") or options.has("unregister-url"):
        try:
            (cli.register_url_protocol if options.has("register-url") else cli.unregister_url_protocol)()
        except Exception as e:
            print(f"PhraseForge: {e}", file=sys.stderr)
            return 1
        return 0
    cli.configure_logging(options, str(paths.data_dir() / "phraseforge.log"))
    if options.has("readonly"):           # like the administrator's editing_disabled, for this run
        import dataclasses
        policy.set_current(dataclasses.replace(policy.current(), editing_disabled=True))
    quiet_http_loggers()
    sys.excepthook = lambda *a: log.error("".join(traceback.format_exception(*a)))
    # Qt 6 sets per-monitor DPI awareness itself; setting it here first made Qt warn.
    qapp = QApplication(argv)
    qapp.setApplicationName("PhraseForge")
    qapp.setQuitOnLastWindowClosed(False)
    from phraseforge.single_instance import SingleInstance, instance_name
    argv_list = list(argv)
    if "--after-exit" in argv_list:       # "restart as administrator": let the old copy close first
        i = argv_list.index("--after-exit")
        pid = argv_list[i + 1] if i + 1 < len(argv_list) else ""
        del argv_list[i:i + 2]
        if pid.isdigit():
            from phraseforge.platform.session import wait_for_exit
            wait_for_exit(int(pid))
    instance = SingleInstance(instance_name(str(paths.data_dir().resolve())))
    if not instance.acquire():
        handover = cli.forwarded(options)
        log.info("PhraseForge is already running; handing over %s", handover)
        instance.forward(handover)
        return 0
    if options.has("shutdown"):           # nothing is running: nothing to shut down
        instance.release()
        return 0
    from phraseforge import vault
    try:
        store = Store(paths.db_path())
    except vault.NeedPassphrase:          # encrypted with "ask for the passphrase at every start"
        from phraseforge.ui.encryption_dialog import ask_passphrase
        store = ask_passphrase(str(paths.db_path()))
        if store is None:
            instance.release()
            return 1
    except vault.VaultError as e:         # encrypted for another Windows account, or damaged
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "PhraseForge", f"{e}\n\n{paths.db_path()}")
        instance.release()
        return 1
    configure_logging(store)
    try:
        store.purge_trash()               # trash entries older than trash.days (default 30)
    except Exception as e:
        log.warning("could not empty old trash entries: %s", e)          # diagnostic mode from the start
    from phraseforge.ui.theme import apply_theme
    from phraseforge.ui import i18n
    apply_theme(qapp, store.setting("ui.theme", "system"), i18n.resolve_language(store.setting("ui.language", "auto")))
    app = PhraseForgeApp(qapp, store, options)
    # a failed save of the encrypted phrase file is shown, not only logged (R75)
    store.on_flush_error = lambda err: app.poster.posted.emit(lambda: app.tray.notify(
        i18n.tr("Phrases not saved"), i18n.tr("The encrypted phrase file could not be saved: {err}").format(err=err)))
    if store.vault_warning:               # a plain or older copy was put back in place (R70)
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(None, "PhraseForge", i18n.tr(store.vault_warning))

    def _unhandled(*exc):
        # An error in a menu or button handler used to be written only to the log, so the
        # click looked as if it did nothing; show it too.
        if isinstance(exc[1], PolicyError):          # refused by the administrator's policy
            from phraseforge.ui.policy_ui import show_policy_error
            show_policy_error(None, exc[1])
            return
        log.error("".join(traceback.format_exception(*exc)))
        try:
            app.tray.notify("PhraseForge error", f"{exc[0].__name__}: {exc[1]}"[:200])
        except Exception:
            pass
    sys.excepthook = _unhandled
    try:   # sticky notes that were open last time come back where they were
        if store.sticky_notes():
            app.sticky_notes().restore()
    except Exception:
        log.exception("restoring sticky notes")
    if store.setting("app.first_run_done", "0") != "1" and not policy.current().editing_disabled:
        from phraseforge.ui.wizard import FirstRunWizard
        FirstRunWizard(store).exec()
    # a second launch (e.g. the Start-menu shortcut) brings this window to the front
    def _from_later_launch(args):
        try:
            later = cli.parse(list(args))
        except cli.UsageError as e:
            app.tray.notify("PhraseForge", str(e))
            return
        if later.actions:
            from phraseforge.platform import session
            if session.running_as_admin() and (later.imports or later.opens or later.execs or later.url_execs):
                # any program of this user can start PhraseForge with switches: an elevated copy
                # does not import, mount or run phrases for it (security R82)
                app.tray.notify("PhraseForge", "PhraseForge runs as administrator: --import, --open, "
                                "--exec and links are not accepted from other programs.")
                return
            for problem in cli.run_actions(app, later):
                app.tray.notify("PhraseForge", problem)
        elif not (later.has("minimized") or later.has("hidden")):
            app.show_main()
    instance.message.connect(_from_later_launch)
    if not (options.has("minimized") or options.has("hidden")) and not options.actions:
        app.show_main()
    if options.actions:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: [app.tray.notify("PhraseForge", m) for m in cli.run_actions(app, options)])
    try:
        return qapp.exec()
    finally:
        try:
            store.flush()                 # an encrypted phrase file: save the last second's changes
        except Exception as e:
            log.error("could not save the encrypted phrase file: %s", e)
            try:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.critical(None, "PhraseForge", i18n.tr(
                    "The encrypted phrase file could not be saved: {err}").format(err=e))
            except Exception:
                pass
        instance.release()
