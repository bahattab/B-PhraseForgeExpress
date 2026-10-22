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


def _restore_focus(hwnd: int) -> None:
    """Bring the original target window back after one of our dialogs."""
    if not user32 or not hwnd or user32.GetForegroundWindow() == hwnd:
        return
    kernel32 = ctypes.windll.kernel32
    fg = user32.GetForegroundWindow()
    cur = kernel32.GetCurrentThreadId()
    fg_thread = user32.GetWindowThreadProcessId(fg, None)
    user32.AttachThreadInput(cur, fg_thread, True)
    user32.SetForegroundWindow(hwnd)
    user32.AttachThreadInput(cur, fg_thread, False)
    import time
    for _ in range(20):
        if user32.GetForegroundWindow() == hwnd:
            break
        time.sleep(0.025)
    time.sleep(0.05)


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
        return ai.complete(self.store.settings(), prompt, provider, model, system)

    def _ocr(self) -> Capture2TextOCR:
        return Capture2TextOCR(self.store.setting("ocr.cli_path"))

    def ocr_region(self, language="", keep_line_breaks=True):
        rect = self.select_screen_region()
        if not rect:
            raise Cancelled()
        lang = language or self.store.setting("ocr.language", "English")
        return self._ocr().ocr_rect(*rect, language=lang, keep_line_breaks=keep_line_breaks)

    def ocr_image(self, path, language=""):
        lang = language or self.store.setting("ocr.language", "English")
        return self._ocr().ocr_image(path, language=lang)

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
        self._busy = threading.Event()
        self.main_window = None
        self.popup = None
        self.clip_window = None

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

        self._build_tray()
        self._build_triggers()
        self._build_cloud()
        # the executor tells the trigger layer while it types, so our own output is ignored
        self.output = OutputExecutor(store.setting, busy_callback=self.triggers.set_busy)
        threading.Thread(target=self._worker, name="expansion", daemon=True).start()

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
        self.tray.quit.connect(self.quit)
        self.tray.show()

    def _build_triggers(self):
        from phraseforge.clipboard_history import ClipboardHistory
        from phraseforge.learning import Learner
        from phraseforge.platform.windows import focused_is_password
        from phraseforge.triggers.manager import TriggerManager
        self.learner = Learner(self.store, password_check=focused_is_password)
        self.triggers = TriggerManager(self.store, self.on_expand_request, self.on_command,
                                       learner=self.learner)
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
        hwnd = _foreground_hwnd()
        if cmd.startswith("confirm:"):
            _, pid, erase = cmd.split(":")[:3]
            self.poster.posted.emit(lambda: self._confirm(int(pid), int(erase), hwnd))
        elif cmd == "popup":
            self.poster.posted.emit(lambda: self._show_popup(hwnd))
        elif cmd == "clipboard_history":
            self.poster.posted.emit(lambda: self._show_clipboard(hwnd))
        elif cmd == "ocr":
            self._jobs.put(("ocr", None, hwnd))
        elif cmd == "new_phrase":
            self.poster.posted.emit(self._new_phrase_with_selection)
        elif cmd == "edit_last_phrase":
            self.poster.posted.emit(self._edit_last_phrase)
        elif cmd == "open_settings":
            self.poster.posted.emit(self.show_settings)
        elif cmd == "clear_clipboard_cache":
            self.store.clear_clipboard(keep_pinned=True)
        elif cmd == "pause":
            self.poster.posted.emit(self._pause_briefly)

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
                    _restore_focus(hwnd)
                    self._with_triggers_paused(lambda: self.output.execute([TextAction(payload)]))
            except Cancelled:
                pass
            except Exception as e:
                log.exception("job failed")
                self.poster.posted.emit(lambda e=e: self.tray.notify("PhraseForge error", str(e)))
            finally:
                self._busy.clear()

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
        # The engine matches the output's case to the typed abbreviation. Only do
        # that when the user typed a different case than the stored abbreviation.
        if ctx.typed_abbreviation and any(
                t.case_sensitive or t.value == ctx.typed_abbreviation for t in p.autotexts()):
            ctx.typed_abbreviation = ""
        actions = self.engine.expand(p.content, ctx)
        log.debug("expand phrase=%s erase=%s actions=%d", p.id, req.erase_chars, len(actions))
        if p.content_format == "html":
            actions = self._as_html(actions)
        _restore_focus(hwnd)
        self._with_triggers_paused(lambda: self.output.execute(
            actions, erase_chars=req.erase_chars, trailing_delimiter=req.trailing_delimiter,
            mode=self._output_mode(p, ctx)))
        chars = sum(len(getattr(a, "text", "") or getattr(a, "plain", "")) for a in actions)
        self.store.record_use(p.id, app=ctx.app_exe, chars=max(0, chars - req.erase_chars),
                              trigger="autotext" if req.erase_chars else "other")

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

    def _show_popup(self, hwnd):
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
        self.popup.show_at(x, y, self._popup_app)

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
    logging.basicConfig(filename=str(paths.data_dir() / "phraseforge.log"), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sys.excepthook = lambda *a: log.error("".join(traceback.format_exception(*a)))
    # Qt 6 sets per-monitor DPI awareness itself; setting it here first made Qt warn.
    qapp = QApplication(argv if argv is not None else sys.argv)
    qapp.setApplicationName("PhraseForge")
    qapp.setQuitOnLastWindowClosed(False)
    store = Store(paths.db_path())
    from phraseforge.ui.theme import apply_theme
    apply_theme(qapp, store.setting("ui.theme", "system"))
    app = PhraseForgeApp(qapp, store)
    if store.setting("app.first_run_done", "0") != "1":
        from phraseforge.ui.wizard import FirstRunWizard
        FirstRunWizard(store).exec()
    if "--minimized" not in (argv or sys.argv):
        app.show_main()
    return qapp.exec()
