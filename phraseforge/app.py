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
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication

from phraseforge import paths
from phraseforge.db import Store
from phraseforge.host import (
    Cancelled, ExpansionContext, ExpansionRequest, FormField, TextAction,
)
from phraseforge.models import OutputMode
from phraseforge.ocr import Capture2TextOCR, OCRError

log = logging.getLogger("phraseforge")
user32 = ctypes.windll.user32 if sys.platform == "win32" else None


# ------------------------------------------------------------------ focus helpers
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


def _grab_screen_png(rect) -> bytes | None:
    """Screenshot of a region given in physical pixels (from ui.region_select), main thread."""
    if not rect:
        return None
    x1, y1, x2, y2 = rect
    from PySide6.QtGui import QGuiApplication
    for screen in QGuiApplication.screens():
        g, dpr = screen.geometry(), screen.devicePixelRatio()
        px, py = int(g.x() * dpr), int(g.y() * dpr)            # screen origin in physical pixels
        pw, ph = int(g.width() * dpr), int(g.height() * dpr)
        if px <= x1 < px + pw and py <= y1 < py + ph:
            shot = screen.grabWindow(0)                         # whole screen, physical resolution
            return _png_bytes(shot.copy(x1 - px, y1 - py, x2 - x1, y2 - y1).toImage())
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
        from phraseforge.platform import clipboard
        clipboard.set_text(text)

    def clipboard_history(self, index):
        return self.store.clipboard_at(index)

    # phrases + variables
    def phrase_content(self, description_or_id):
        p = None
        if str(description_or_id).isdigit():
            p = self.store.get_phrase(int(description_or_id))
        p = p or self.store.find_phrase(str(description_or_id))
        return (p.content, p.content_format) if p else None

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

    def _ocr(self) -> Capture2TextOCR:
        return Capture2TextOCR(self.store.setting("ocr.cli_path"))

    def _keep_breaks(self, keep_line_breaks) -> bool:
        if keep_line_breaks is None:   # Settings > Screen OCR > Keep line breaks
            return self.store.setting("ocr.keep_line_breaks", "1") != "0"
        return bool(keep_line_breaks)

    def ocr_region(self, language="", keep_line_breaks=None):
        rect = self.select_screen_region()
        if not rect:
            raise Cancelled()
        lang = language or self.store.setting("ocr.language", "English")
        return self._ocr().ocr_rect(*rect, language=lang, keep_line_breaks=self._keep_breaks(keep_line_breaks))

    def onenote_page_text(self, ref, include_title=False, include_ocr=False):
        """{#onenote} macro: text of a OneNote page (worker thread, own COM apartment)."""
        return self.app._onenote().page_text(ref, include_title=include_title, include_ocr=include_ocr)

    def ocr_image(self, path, language=""):
        lang = language or self.store.setting("ocr.language", "English")
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
    def __init__(self, qapp: QApplication, store: Store):
        super().__init__()
        self.qapp = qapp
        self.store = store
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
        self._build_local_backups()
        self._build_file_index()
        # the executor tells the trigger layer while it types, so our own output is ignored
        self.output = OutputExecutor(store.setting, busy_callback=self.triggers.set_busy)
        threading.Thread(target=self._worker, name="expansion", daemon=True).start()

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
        reg("ocr", lambda arg, hwnd: self._jobs.put(("ocr", None, hwnd)))
        reg("new_phrase", lambda arg, hwnd: post(self._new_phrase_with_selection))
        reg("edit_last_phrase", lambda arg, hwnd: post(self._edit_last_phrase))
        reg("open_settings", lambda arg, hwnd: post(self.show_settings))
        reg("clear_clipboard_cache", lambda arg, hwnd: self.store.clear_clipboard(keep_pinned=True))
        reg("pause", lambda arg, hwnd: post(self._pause_cmd))
        reg("sound", lambda arg, hwnd: self._play(arg))   # "sound:<event>" from other layers
        reg("popup_search", lambda arg, hwnd: post(lambda: self._show_popup(hwnd, search=True)))
        # trigger-layer events (triggers/manager.py)
        reg("folder_popup", lambda arg, hwnd: self._folder_popup_cmd(arg, hwnd))  # "<folder|last_used|clipboard_cache>:<erase>"
        reg("smartcomplete", lambda arg, hwnd: post(lambda: self._show_tip_phrase(arg)))   # "<pid>:<len>"
        reg("autocomplete", lambda arg, hwnd: post(lambda: self._show_tip_word(arg)))      # "<word>:<len>"
        reg("suggest_hide", lambda arg, hwnd: post(self._hide_tip))
        reg("autocorrect", lambda arg, hwnd: self._jobs.put(("replace", arg, hwnd)))       # "<erase>:<text>"
        reg("undo_expansion", lambda arg, hwnd: self._jobs.put(("undo", arg, hwnd)))       # "<pid>:<typed>"
        # Microsoft OneNote (Settings > OneNote hotkeys, tray menu)
        reg("onenote_send_clipboard", lambda arg, hwnd: self._jobs.put(("call", self._onenote_send_clipboard, hwnd)))
        reg("onenote_clip", lambda arg, hwnd: self._jobs.put(("call", self._onenote_clip, hwnd)))
        reg("quick_note", lambda arg, hwnd: post(self._show_quick_note))   # like ONENOTEM "New Quick Note"
        # Microsoft Sticky Notes
        reg("open_sticky_notes", lambda arg, hwnd: self._open_sticky_notes())
        # Search files (Listary-style launcher, phraseforge/filesearch.py)
        reg("file_search", lambda arg, hwnd: post(lambda: self._show_file_search(hwnd)))

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
                lambda text: self._jobs.put(("call", lambda: self._onenote_send_note(text), 0)))
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
        """Screen clipping: PhraseForge's region selector (or OneNote's own clipping tool),
        then add the image to OneNote and/or OCR it to the clipboard (Settings > OneNote)."""
        st = self.store.setting
        action = st("onenote.clip_action", "image")
        if st("onenote.clip_tool", "phraseforge") == "onenote":
            png = self._clip_with_onenote_tool()
        else:
            rect = self.host.select_screen_region()
            png = self.host._ui(lambda: _grab_screen_png(rect)) if rect else None
        if not png:
            return
        if action in ("ocr", "both"):
            import tempfile
            fd, tmp = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            try:
                with open(tmp, "wb") as fh:
                    fh.write(png)
                text = self.host.ocr_image(tmp)
            finally:
                os.unlink(tmp)
            if text:
                self.host.set_clipboard(text)
                self.poster.posted.emit(lambda: self.tray.notify("Clip text copied", text[:100]))
        if action in ("image", "both"):
            ref = st("onenote.default_target", "")
            self._onenote().send(image_png=png, target=ref, title="Screen clipping")
            self.poster.posted.emit(lambda: self.tray.notify("Clip sent to OneNote", ref or "Quick Notes"))

    def _clip_with_onenote_tool(self, timeout_s: float = 60):
        """Start OneNote's screen clipping tool and wait for the clip to land on the clipboard."""
        import subprocess
        import time
        from phraseforge.onenote import capture_exe
        from phraseforge.platform import clipboard
        exe = capture_exe()
        if not exe:
            self.poster.posted.emit(lambda: self.tray.notify("OneNote", "onenotecapture.exe was not found."))
            return None
        before = clipboard.sequence_number()
        subprocess.Popen([exe])
        end = time.time() + timeout_s
        while time.time() < end:
            time.sleep(0.3)
            if clipboard.sequence_number() != before:
                time.sleep(0.3)
                return self.host._ui(_clipboard_png)
        return None

    def _open_sticky_notes(self):
        try:
            from phraseforge import stickynotes
            stickynotes.open_app()
        except Exception as e:
            self.poster.posted.emit(lambda e=e: self.tray.notify("Sticky Notes", f"Could not open Sticky Notes: {e}"))

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
        self.tray.clipboard_history.connect(lambda: self.on_command("clipboard_history"))
        self.tray.toggle_pause.connect(self.set_paused)
        self.tray.settings.connect(self.show_settings)
        if hasattr(self.tray, "show_statistics"):
            self.tray.show_statistics.connect(self.show_statistics)
        for sig in ("onenote_send_clipboard", "onenote_clip", "open_sticky_notes", "file_search", "quick_note"):   # OneNote / Sticky Notes items
            if hasattr(self.tray, sig):
                getattr(self.tray, sig).connect(lambda _=None, c=sig: self.on_command(c))
        self.tray.quit.connect(self.quit)
        self.tray.show()

    def _build_triggers(self):
        from phraseforge.clipboard_history import ClipboardHistory
        from phraseforge.learning import Learner
        from phraseforge.platform.windows import focused_is_password
        from phraseforge.triggers.manager import TriggerManager
        self.learner = Learner(self.store, password_check=focused_is_password)
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
        self.triggers.start()
        self.clip_history.start()
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

    def _cloud_tick(self, force_sync: bool = False):
        from datetime import datetime, timedelta
        st = self.store
        if st.setting("sync.provider", "off") == "off" or not self._cloud_busy.acquire(blocking=False):
            return

        def due(key: str, minutes: float) -> bool:
            last = st.setting(key, "")
            try:
                return not last or datetime.now() - datetime.fromisoformat(last) >= timedelta(minutes=minutes)
            except ValueError:
                return True
        do_sync = st.setting("sync.auto", "1") == "1" and (
            force_sync or due("sync.last_time", float(st.setting("sync.interval_min", "15") or 15)))
        do_backup = st.setting("backup.cloud_auto", "1") == "1" and due(
            "backup.cloud_last", 60 * float(st.setting("backup.cloud_interval_hours", "24") or 24))
        if not (do_sync or do_backup):
            self._cloud_busy.release()
            return

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
                    if res.action in ("pulled", "conflict"):
                        def on_ui(cs=cs, res=res):
                            from phraseforge.ui.cloud_ui import handle_sync_result
                            handle_sync_result(self.main_window, cs, res, quiet=True)
                            if res.action == "pulled":
                                self.tray.notify("PhraseForge", "Phrases updated from the cloud.")
                        self.poster.posted.emit(on_ui)
            except Exception as e:
                log.warning("cloud sync failed: %s", e)
                self.poster.posted.emit(lambda e=e: self.tray.notify("Backup & Sync failed", str(e)))
            finally:
                self._cloud_busy.release()
        threading.Thread(target=work, name="cloud-sync", daemon=True).start()

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

    def _on_store_change(self, kind, _id):
        if kind in ("phrase", "folder", "setting"):
            self.poster.posted.emit(self.triggers.reload)

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
        p = self.store.add_phrase(Phrase(desc, text))
        self.show_main()
        self.main_window.select_phrase(p.id)

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

    # ---------------------------------------------------------- worker thread
    def _worker(self):
        while True:
            kind, payload, hwnd = self._jobs.get()
            self._busy.set()
            try:
                if kind == "expand":
                    self._expand(payload, hwnd)
                elif kind == "ocr":
                    self._ocr_to_clipboard()
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
        ctx = req.context
        ctx.phrase_id, ctx.phrase_description = p.id, p.description
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

    def _ocr_to_clipboard(self):
        text = self.host.ocr_region()
        if text:
            self.host.set_clipboard(text)
            preview = text if len(text) < 120 else text[:117] + "..."
            self.poster.posted.emit(lambda: self.tray.notify("OCR copied to clipboard", preview))
        else:
            self.poster.posted.emit(lambda: self.tray.notify("OCR", "No text recognised"))

    # ---------------------------------------------------------- main-thread UI
    def _caret_or_cursor(self):
        from PySide6.QtGui import QCursor
        try:
            from phraseforge.platform import windows
            pos = windows.caret_position()
            if pos:
                return pos
        except Exception:
            pass
        c = QCursor.pos()
        return c.x(), c.y()

    def _show_popup(self, hwnd, folder=None, search: bool = False):
        from phraseforge.ui.popup import PhrasePopup
        if self.popup is None:
            self.popup = PhrasePopup(self.store)
            self.popup.phrase_chosen.connect(
                lambda pid: self._jobs.put(("expand", ExpansionRequest(
                    phrase_id=pid, context=ExpansionContext(app_exe=self._popup_app)), self._popup_hwnd)))
            if hasattr(self.popup, "clipboard_chosen"):
                self.popup.clipboard_chosen.connect(
                    lambda text: self._jobs.put(("text", text, self._popup_hwnd)))
            if hasattr(self.popup, "new_phrase_requested"):
                self.popup.new_phrase_requested.connect(self._new_phrase_from_popup)
        try:
            from phraseforge.platform import windows
            self._popup_app = windows.foreground_app()[0]
        except Exception:
            self._popup_app = ""
        self._popup_hwnd = hwnd
        x, y = self._caret_or_cursor()
        kw = {"search": True} if search else {}
        if folder is not None:
            kw["folder"] = folder
        try:
            self.popup.show_at(x, y, self._popup_app, **kw)   # the popup plays its own sound
        except TypeError:          # popup without folder support: open the normal menu
            self.popup.show_at(x, y, self._popup_app, search=search)

    def _new_phrase_from_popup(self):
        """Popup footer "New phrase...": create it in the popup's folder and open the editor."""
        from phraseforge.models import Phrase
        folder_id = getattr(self.popup, "new_phrase_folder_id", None)
        p = self.store.add_phrase(Phrase("New phrase", "", folder_id=folder_id))
        self.show_main()
        if hasattr(self.main_window, "select_phrase"):
            self.main_window.select_phrase(p.id)

    def show_statistics(self):
        from phraseforge.ui.stats_window import StatsWindow
        StatsWindow(self.store).exec()

    # ---- Search files (Listary-style launcher)
    def _build_file_index(self):
        from phraseforge import filesearch
        s = self.store.setting
        roots = filesearch.parse_roots(s("filesearch.roots", "")) or None
        self.file_index = filesearch.FileIndex(roots, include_hidden=s("filesearch.include_hidden", "0") == "1",
                                               history_file=paths.data_dir() / "filesearch_history.json")
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

    def _show_file_search(self, hwnd):
        from phraseforge.ui.file_search import FileSearchWindow
        if self.file_index is None:
            self._build_file_index()
        if self.file_window is None:
            from phraseforge import filesearch
            kw = filesearch.parse_web_keywords(self.store.setting("filesearch.web_keywords", "")
                                               or filesearch.DEFAULT_WEB_KEYWORDS)
            self.file_window = FileSearchWindow(self.file_index, web_keywords=kw)
            self.file_window.insert_path.connect(lambda path: self._jobs.put(("text", path, self._file_hwnd)))
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

    def show_main(self):
        from phraseforge.ui.main_window import MainWindow
        if self.main_window is None:
            self.main_window = MainWindow(self.store, on_test_phrase=self.test_phrase)
        self.main_window.show()
        self.main_window.raise_()
        self.main_window.activateWindow()

    def show_settings(self):
        from phraseforge.ui.settings_dialog import SettingsDialog
        SettingsDialog(self.store).exec()
        try:
            from phraseforge import autostart
            autostart.set_enabled(self.store.setting("app.start_with_windows", "0") == "1")
        except Exception:
            log.exception("autostart update failed")
        from phraseforge.ui.theme import apply_theme
        apply_theme(self.qapp, self.store.setting("ui.theme", "system"))
        self._apply_service_settings()
        self.triggers.reload()

    def set_paused(self, paused: bool):
        self.triggers.paused = bool(paused)

    def quit(self):
        try:
            self.triggers.stop()
            self.clip_history.stop()
            self._cloud_push_on_exit()
        finally:
            self.tray.hide()
            self.qapp.quit()


def main(argv: list[str] | None = None) -> int:
    if "--self-test" in (argv if argv is not None else sys.argv):
        from phraseforge.selftest import run
        return run()
    logging.basicConfig(filename=str(paths.data_dir() / "phraseforge.log"), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sys.excepthook = lambda *a: log.error("".join(traceback.format_exception(*a)))
    # Qt 6 sets per-monitor DPI awareness itself; setting it here first made Qt warn.
    qapp = QApplication(argv if argv is not None else sys.argv)
    qapp.setApplicationName("PhraseForge")
    qapp.setQuitOnLastWindowClosed(False)
    store = Store(paths.db_path())
    configure_logging(store)          # diagnostic mode from the start
    from phraseforge.ui.theme import apply_theme
    apply_theme(qapp, store.setting("ui.theme", "system"))
    app = PhraseForgeApp(qapp, store)
    if store.setting("app.first_run_done", "0") != "1":
        from phraseforge.ui.wizard import FirstRunWizard
        FirstRunWizard(store).exec()
    if "--minimized" not in (argv or sys.argv):
        app.show_main()
    return qapp.exec()
