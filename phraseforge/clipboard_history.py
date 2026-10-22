"""Records clipboard text changes into the store's clipboard history."""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

MAX_ENTRY_CHARS = 100_000


class ClipboardHistory:
    """start()/stop(). Set `paused = True` to stop recording temporarily.
    Uses setting "clipboard_history.enabled" (default "1")."""

    def __init__(self, store, watcher_factory=None, foreground_app=None):
        self.store = store
        self.paused = False
        self._watcher_factory = watcher_factory
        self._foreground_app = foreground_app
        self._watcher = None

    def start(self) -> None:
        if self._watcher_factory is None:
            from phraseforge.platform.clipboard import ClipboardWatcher
            self._watcher_factory = ClipboardWatcher
        self._watcher = self._watcher_factory(self.on_clipboard_text)
        self._watcher.start()

    def stop(self) -> None:
        if self._watcher:
            self._watcher.stop()
            self._watcher = None

    def _fg_exe(self) -> str:
        if self._foreground_app is None:
            from phraseforge.platform.windows import foreground_app
            self._foreground_app = foreground_app
        try:
            return self._foreground_app()[0]
        except Exception:
            return ""

    def enabled(self) -> bool:
        """Settings > Features > Clipboard Cache (features.clipboard_cache) and the
        older clipboard_history.enabled switch; read live, so changes apply at once."""
        s = self.store.setting
        return s("features.clipboard_cache", "1") == "1" and s("clipboard_history.enabled", "1") == "1"

    def on_clipboard_text(self, text: str) -> None:
        if self.paused or not self.enabled():
            return
        if not text or not text.strip() or len(text) > MAX_ENTRY_CHARS:
            return
        exe = self._fg_exe()
        if exe and exe in self.store.excluded_apps():
            return
        try:
            self.store.add_clipboard(text, source_app=exe)
        except Exception:
            log.exception("could not store clipboard entry")
            return
        from phraseforge import sounds
        sounds.play(self.store.setting, "clipboard_cache")
