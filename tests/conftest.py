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
    # Qt flushes its clipboard data to Windows at exit; leave nothing behind.
    try:
        app.clipboard().clear()
    except Exception:
        pass
    for w in QApplication.topLevelWidgets():
        w.close()
        w.deleteLater()
    app.processEvents()
    gc.collect()
    app.processEvents()


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _two_column_default(request, monkeypatch):
    """Most UI tests were written for the two-column tree; the app itself opens in three
    columns (main_window.DEFAULT_LAYOUT). Tests marked real_layout_default keep it."""
    if request.node.get_closest_marker("real_layout_default"):
        return
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from phraseforge.ui import main_window
    monkeypatch.setattr(main_window, "DEFAULT_LAYOUT", "two")


def pytest_configure(config):
    config.addinivalue_line("markers", "real_layout_default: use the app's own default layout")
