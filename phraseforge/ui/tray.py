"""System tray icon and its menu."""
from __future__ import annotations

from PySide6.QtCore import QMetaMethod, Signal
from PySide6.QtGui import QAction, QFont, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from phraseforge.ui.i18n import tr
from phraseforge.ui.iconset import icon
from phraseforge.ui.icons import app_icon


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
        m.addSeparator()
        m.addAction(icon("search"), tr("Phrase menu"), self.show_popup.emit)
        m.addAction(icon("clipboard_cache"), tr("Clipboard history"), self.clipboard_history.emit)
        m.addAction(icon("m_ocr"), tr("OCR to clipboard"), self.ocr_to_clipboard.emit)
        m.addAction(icon("file_search"), tr("Search files"), self.file_search.emit)
        m.addSeparator()
        self.onenote_send_action = m.addAction(icon("on_send"), tr("Send clipboard to OneNote"),
                                               self.onenote_send_clipboard.emit)
        self.onenote_clip_action = m.addAction(icon("on_clip"), tr("Screen clip to OneNote"),
                                               self.onenote_clip.emit)
        m.addSeparator()
        self.stats_action = m.addAction(icon("statistics"), tr("Statistics"), self.show_statistics.emit)
        m.addAction(icon("settings"), tr("Settings"), self.settings.emit)
        m.addAction(icon("about"), tr("About PhraseForge"), self._about)
        m.addSeparator()
        self.pause_action = QAction(tr("Pause"), m, checkable=True)
        self.pause_action.toggled.connect(self._on_pause)
        m.addAction(self.pause_action)
        m.addSeparator()
        m.addAction(icon("exit"), tr("Quit"), self.quit.emit)
        m.aboutToShow.connect(self._before_show)
        self.setContextMenu(m)
        self.activated.connect(self._on_activated)

    def _before_show(self) -> None:
        connected = self.isSignalConnected(QMetaMethod.fromSignal(self.show_statistics))
        self.stats_action.setVisible(connected)
        # OneNote items appear once the app has wired them
        for act, sig in ((self.onenote_send_action, self.onenote_send_clipboard),
                         (self.onenote_clip_action, self.onenote_clip)):
            act.setVisible(self.isSignalConnected(QMetaMethod.fromSignal(sig)))

    def _about(self) -> None:
        from phraseforge.ui.about_dialog import AboutDialog
        AboutDialog().exec()

    def _on_pause(self, paused: bool) -> None:
        self.setIcon(app_icon(paused=True) if paused else self._icon)
        self.setToolTip("PhraseForge (paused)" if paused else "PhraseForge")
        self.toggle_pause.emit(paused)

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.DoubleClick, QSystemTrayIcon.Trigger):
            self.open_main.emit()

    def notify(self, title: str, text: str, ms: int = 4000) -> None:
        self.showMessage(title, text, QSystemTrayIcon.Information, ms)
