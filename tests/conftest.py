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


@pytest.fixture(autouse=True)
def _relock_folders():
    """Folders unlocked in one test must not stay unlocked in the next (security.LOCKS
    is process-wide, and in-memory stores reuse folder ids)."""
    from phraseforge.security import LOCKS
    LOCKS.clear()
    yield
    LOCKS.clear()


@pytest.fixture(autouse=True)
def _destroy_leftover_widgets():
    """Delete top-level widgets a test left behind.

    Without this, hundreds of windows from earlier test files stay alive, and the
    next app.setPalette() (theme switch) re-polishes all of them: the full suite
    then stalls in test_ui.py::test_theme_icons_tray.

    Only windows created during this test are deleted (module-scoped fixtures keep
    theirs), and never one that still owns a running QThread: Qt aborts the whole
    process when a running thread is destroyed."""
    before = _top_level_ids()
    yield
    if before is None:
        return
    from PySide6.QtCore import QCoreApplication, QEvent, QThread
    from PySide6.QtWidgets import QApplication
    deleted = False
    for w in QApplication.topLevelWidgets():
        if _cpp_id(w) in before:
            continue
        if any(t.isRunning() for t in w.findChildren(QThread)):
            w.hide()
            continue
        w.hide()
        w.deleteLater()
        deleted = True
    if deleted:
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _cpp_id(obj) -> int:
    import shiboken6
    return shiboken6.getCppPointer(obj)[0]


def _top_level_ids():
    """C++ addresses of the current top-level widgets, or None without a QApplication."""
    if "PySide6.QtWidgets" not in sys.modules:
        return None
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        return None
    return {_cpp_id(w) for w in QApplication.topLevelWidgets()}


def pytest_configure(config):
    config.addinivalue_line("markers", "real_layout_default: use the app's own default layout")
