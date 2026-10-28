"""Small helpers for AI actions in the UI ("Enhance prompt")."""
from __future__ import annotations

import threading

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from phraseforge.ui.i18n import tr


def run_busy(fn):
    """Run fn on a background thread while the window stays responsive; return its result
    or raise its error."""
    box: dict = {}

    def run():
        try:
            box["value"] = fn()
        except Exception as e:      # noqa: BLE001 - re-raised below
            box["error"] = e
    t = threading.Thread(target=run, daemon=True)
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        t.start()
        while t.is_alive():
            QApplication.processEvents()
            t.join(0.05)
    finally:
        QApplication.restoreOverrideCursor()
    if "error" in box:
        raise box["error"]
    return box.get("value")


def enhance(store, text: str, parent=None, quiet: bool = False, complete_fn=None) -> str | None:
    """Improved version of `text`, or None (an error is shown unless quiet)."""
    from phraseforge import ai
    settings = dict(store.settings())
    try:
        return run_busy(lambda: ai.enhance_prompt(settings, text, complete_fn=complete_fn))
    except Exception as e:      # noqa: BLE001 - shown to the user
        if not quiet:
            QMessageBox.warning(parent, tr("Enhance prompt"),
                                tr("The prompt could not be enhanced.") + f"\n\n{e}")
        return None
