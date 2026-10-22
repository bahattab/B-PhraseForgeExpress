"""Shared pytest hooks."""
import gc
import sys


def pytest_sessionfinish(session, exitstatus):
    """Close Qt windows left open by tests before Python shuts down.

    Otherwise widgets and the QApplication are destroyed in an arbitrary order
    at interpreter exit, which can crash after every test has passed.
    """
    if "PySide6.QtWidgets" not in sys.modules:
        return
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    for w in QApplication.topLevelWidgets():
        w.close()
        w.deleteLater()
    app.processEvents()
    gc.collect()
    app.processEvents()
