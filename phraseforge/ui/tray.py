"""System tray icon and its menu."""
from __future__ import annotations

from PySide6.QtCore import QMetaMethod, Qt, Signal
from PySide6.QtGui import QAction, QFont, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from phraseforge.ui.i18n import tr
from phraseforge.ui.iconset import icon
from phraseforge.ui.icons import app_icon


LANGUAGES = (("en", "Default (English)"), ("ar", "العربية (Arabic)"))


class Tray(QSystemTrayIcon):
    open_main = Signal()
    show_popup = Signal()
    ocr_to_clipboard = Signal()
    clipboard_history = Signal()
    toggle_pause = Signal(bool)
    settings = Signal()
    quit = Signal()
    show_statistics = Signal()      # shown in the menu only when something is connected
    onenote_send_clipboard = Signal()   # "Send clipboard to OneNote"
    onenote_clip = Signal()             # "Screen clip to OneNote"
    file_search = Signal()              # "Search files"
    prompt_tower = Signal()             # "Prompt Tower" (AI prompts from project files)
    prompt_optimizer = Signal()         # "Prompt Optimizer" (chat that improves a prompt)
    ocr_language = Signal(str)          # picked in "OCR language" (like Capture2Text's tray menu)
    quick_note = Signal()               # "New quick note" (like ONENOTEM)
    new_sticky_note = Signal()          # "New sticky note" (built-in sticky notes)
    open_sticky_notes = Signal()        # "Sticky notes" list
    new_phrase_from_clipboard = Signal()   # TextExpander "New Snippet from Clipboard"
    edit_last_phrase = Signal()            # TextExpander "Edit Last Expanded Snippet"
    app_enabled = Signal(str, bool)        # PhraseExpress 'Enabled in "<program>"' (exe, on)
    language = Signal(str)                 # PhraseExpress "Language selection"

    def __init__(self, icon_: QIcon | None = None, parent=None):
        super().__init__(icon_ or app_icon(), parent)
        self._icon = icon_ or app_icon()
        self.setToolTip("PhraseForge")
        m = QMenu()
        self._menu = m
        a = m.addAction(icon("phrase"), tr("Open PhraseForge"), self.open_main.emit)
        f = QFont(a.font())
        f.setBold(True)
        a.setFont(f)
        m.addAction(icon("new_phrase"), tr("New phrase from clipboard"), self.new_phrase_from_clipboard.emit)
        m.addAction(icon("pencil"), tr("Edit last used phrase"), self.edit_last_phrase.emit)
        m.addSeparator()
        m.addAction(icon("search"), tr("Phrase menu"), self.show_popup.emit)
        m.addAction(icon("clipboard_cache"), tr("Clipboard history"), self.clipboard_history.emit)
        m.addAction(icon("m_ocr"), tr("OCR to clipboard"), self.ocr_to_clipboard.emit)
        # filled before showing from ocr_languages_provider() -> (languages, current)
        self.ocr_languages_provider = None
        self.ocr_lang_menu = m.addMenu(icon("languages"), tr("OCR language"))
        self.ocr_lang_menu.menuAction().setVisible(False)
        m.addAction(icon("file_search"), tr("Search files"), self.file_search.emit)
        m.addAction(icon("m_ai"), tr("Prompt Tower"), self.prompt_tower.emit)
        m.addAction(icon("m_ai"), tr("Prompt Optimizer"), self.prompt_optimizer.emit)
        m.addSeparator()
        self.onenote_send_action = m.addAction(icon("on_send"), tr("Send clipboard to OneNote"),
                                               self.onenote_send_clipboard.emit)
        self.onenote_clip_action = m.addAction(icon("on_clip"), tr("Screen clip to OneNote"),
                                               self.onenote_clip.emit)
        self.quick_note_action = m.addAction(icon("sticky_notes"), tr("New quick note"), self.quick_note.emit)
        self.new_sticky_action = m.addAction(icon("sticky_notes"), tr("New sticky note"), self.new_sticky_note.emit)
        self.sticky_list_action = m.addAction(icon("sticky_notes"), tr("Sticky notes"), self.open_sticky_notes.emit)
        m.addSeparator()
        self.stats_action = m.addAction(icon("statistics"), tr("Statistics"), self.show_statistics.emit)
        m.addAction(icon("settings"), tr("Settings"), self.settings.emit)
        m.addAction(icon("about"), tr("About PhraseForge"), self._about)
        m.addSeparator()
        # PhraseExpress tray menu (observed): Language selection, Enabled in "<last program>"
        self.language_provider = None          # () -> current language code
        self.language_menu = m.addMenu(icon("languages"), tr("Language selection"))
        for code, text in LANGUAGES:
            a = self.language_menu.addAction(text)
            a.setCheckable(True)
            a.setData(code)
            a.triggered.connect(lambda _=False, c=code: self.language.emit(c))
        self.last_app_provider = None          # () -> (exe, label) of the last program used, or None
        self.excluded_provider = None          # () -> set of excluded exe names
        self._app_exe = ""
        self.app_toggle_action = QAction("", m, checkable=True)
        self.app_toggle_action.triggered.connect(lambda on: self.app_enabled.emit(self._app_exe, on))
        self.app_toggle_action.setVisible(False)
        m.addAction(self.app_toggle_action)
        m.addSeparator()
        self.pause_action = QAction(tr("Pause"), m, checkable=True)
        self.pause_action.toggled.connect(self._on_pause)
        m.addAction(self.pause_action)
        m.addSeparator()
        m.addAction(icon("exit"), tr("Quit"), self.quit.emit)
        m.aboutToShow.connect(self._before_show)
        self.setContextMenu(m)
        self.activated.connect(self._on_activated)

    def _fill_ocr_languages(self) -> None:
        menu = self.ocr_lang_menu
        menu.clear()
        langs, current = self.ocr_languages_provider() if self.ocr_languages_provider else ([], "")
        menu.menuAction().setVisible(bool(langs))
        for lang in langs:
            a = menu.addAction(lang)
            a.setCheckable(True)
            a.setChecked(lang == current)
            a.triggered.connect(lambda _=False, l=lang: self.ocr_language.emit(l))

    def _before_show(self) -> None:
        self._fill_ocr_languages()
        self._fill_app_toggle()
        cur = self.language_provider() if self.language_provider else "en"
        for a in self.language_menu.actions():
            a.setChecked(a.data() == cur)
        connected = self.isSignalConnected(QMetaMethod.fromSignal(self.show_statistics))
        self.stats_action.setVisible(connected)
        # OneNote items appear once the app has wired them
        for act, sig in ((self.onenote_send_action, self.onenote_send_clipboard),
                         (self.onenote_clip_action, self.onenote_clip)):
            act.setVisible(self.isSignalConnected(QMetaMethod.fromSignal(sig)))

    def _fill_app_toggle(self) -> None:
        last = self.last_app_provider() if self.last_app_provider else None
        act = self.app_toggle_action
        if not last or not last[0]:
            self._app_exe = ""
            act.setVisible(False)
            return
        exe, label = last
        self._app_exe = exe
        label = (label or exe).strip()
        if len(label) > 40:
            label = label[:39] + "\u2026"
        act.setText(tr("Enabled in") + f' "{label}"')
        excluded = self.excluded_provider() if self.excluded_provider else set()
        act.setChecked(exe not in excluded)
        act.setVisible(True)

    def _about(self) -> None:
        from phraseforge.ui.about_dialog import AboutDialog
        AboutDialog().exec()

    def _on_pause(self, paused: bool) -> None:
        self.setIcon(app_icon(paused=True) if paused else self._icon)
        self.setToolTip("PhraseForge (paused)" if paused else "PhraseForge")
        self.toggle_pause.emit(paused)

    # What a plain left click does: "main" (open the main window) or "popup"
    # (open the phrase menu, as PhraseExpress does). Set from tray.left_click.
    left_click = "main"

    def handle_click(self, reason, modifiers=None) -> str:
        """Act on a tray click and return what was done (for tests).

        PhraseExpress (published docs): Ctrl+click disables it for a while,
        Alt+click opens the settings, double-click opens the main window and a
        left click opens the phrase menu.
        """
        if modifiers is None:
            modifiers = QApplication.keyboardModifiers()
        if reason == QSystemTrayIcon.DoubleClick:
            self.open_main.emit()
            return "main"
        if reason != QSystemTrayIcon.Trigger:
            return ""
        if modifiers & Qt.ControlModifier:
            self.pause_action.toggle()
            return "pause"
        if modifiers & Qt.AltModifier:
            self.settings.emit()
            return "settings"
        if self.left_click == "popup":
            self.show_popup.emit()
            return "popup"
        self.open_main.emit()
        return "main"

    def _on_activated(self, reason) -> None:
        self.handle_click(reason)

    def notify(self, title: str, text: str, ms: int = 4000, on_click=None) -> None:
        """Balloon message; on_click runs when the user clicks it (e.g. open a download page)."""
        self._on_message_click = on_click
        if not getattr(self, "_click_hooked", False):
            self.messageClicked.connect(lambda: (getattr(self, "_on_message_click", None) or (lambda: None))())
            self._click_hooked = True
        self.showMessage(title, text, QSystemTrayIcon.Information, ms)
