"""Small UI helpers for Backup & Sync (used by Settings and by the app's timers)."""
from __future__ import annotations

import threading
from typing import Any, Callable

from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QMessageBox, QProgressDialog, QWidget


def run_with_wait(parent: QWidget | None, text: str, fn: Callable[[], Any]) -> tuple[bool, Any]:
    """Run fn on a worker thread while a modal 'please wait' box keeps the UI alive.
    Returns (True, result) or (False, error message)."""
    box: dict = {}

    def work():
        try:
            box["value"] = fn()
        except Exception as e:  # reported to the user by the caller
            box["error"] = str(e) or e.__class__.__name__

    th = threading.Thread(target=work, daemon=True)
    dlg = QProgressDialog(text, "", 0, 0, parent)
    dlg.setWindowTitle("PhraseForge")
    dlg.setCancelButton(None)
    dlg.setWindowModality(Qt.WindowModal)
    dlg.setMinimumDuration(300)
    th.start()
    loop = QEventLoop()
    timer = QTimer()
    timer.timeout.connect(lambda: (not th.is_alive()) and loop.quit())
    timer.start(100)
    loop.exec()
    timer.stop()
    dlg.close()
    return ("error" not in box), box.get("value", box.get("error"))


def merge_message(res) -> str:
    """'Merged the changes from PC-2: 2 added, 1 changed. 1 phrase was edited on both PCs ...'"""
    if res.action != "merged":
        return res.message
    s = res.summary or {}
    parts = [f"{s[k]} {label}" for k, label in (("added", "added"), ("changed", "changed"), ("removed", "removed"))
             if s.get(k)]
    text = res.message + (": " + ", ".join(parts) if parts else "") + "."
    if s.get("conflicts"):
        text += (f" {s['conflicts']} phrase(s) were edited on both PCs: the newer edit was kept and the "
                 "other one is in the phrase's history.")
    return text


def handle_sync_result(parent: QWidget | None, cs, res, quiet: bool = False) -> None:
    """Apply a pull, or ask the user how to settle a conflict. Must run on the UI thread."""
    if res.action in ("pulled", "merged"):
        cs.apply_pull(res.pulled_file, res.remote_rev)
        if not quiet:
            QMessageBox.information(parent, "Backup & Sync", merge_message(res))
    elif res.action == "conflict":
        box = QMessageBox(parent)
        box.setWindowTitle("Backup & Sync")
        box.setIcon(QMessageBox.Question)
        box.setText(res.message + ".\nWhich phrases do you want to keep?")
        box.setInformativeText("A backup of this PC's phrases was saved to the cloud first, "
                               "so nothing is lost either way.")
        local = box.addButton("Keep this PC's phrases", QMessageBox.AcceptRole)
        remote = box.addButton("Use the cloud copy", QMessageBox.DestructiveRole)
        box.addButton("Decide later", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() in (local, remote):
            keep = "local" if box.clickedButton() is local else "remote"
            ok, r2 = run_with_wait(parent, "Synchronizing...", lambda: cs.resolve(keep))
            if ok and r2.action == "pulled":
                cs.apply_pull(r2.pulled_file, r2.remote_rev)
            elif not ok:
                QMessageBox.warning(parent, "Backup & Sync", str(r2))
    elif not quiet:
        QMessageBox.information(parent, "Backup & Sync", res.message)
