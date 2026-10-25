"""`PhraseForge.exe --self-test`: check that a packaged build is complete.

Imports every PhraseForge module, opens a throwaway database and loads the
bundled icon fonts, then exits 0 (all good) or 1. The report is written to
selftest.txt in the data folder, because the windowed EXE has no console.
Used by CI after PyInstaller and after a silent install of Setup.exe.
"""
from __future__ import annotations

import importlib
import pkgutil
import tempfile
import traceback
from pathlib import Path

import phraseforge
from phraseforge import paths

# Optional parts that a full Windows build must still contain.
EXTRA_MODULES = ("httpx", "openpyxl", "qtawesome", "googleapiclient.discovery",
                 "google_auth_oauthlib.flow", "google.auth.transport.requests")


def run() -> int:
    lines: list[str] = [f"PhraseForge {phraseforge.__version__} self-test"]
    failed = False

    def check(name: str, fn) -> None:
        nonlocal failed
        try:
            fn()
            lines.append(f"ok    {name}")
        except Exception:
            failed = True
            lines.append(f"FAIL  {name}\n{traceback.format_exc()}")

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(["phraseforge", "--self-test"])  # noqa: F841

    for mod in pkgutil.walk_packages(phraseforge.__path__, "phraseforge."):
        check(f"import {mod.name}", lambda m=mod.name: importlib.import_module(m))
    for name in EXTRA_MODULES:
        check(f"import {name}", lambda m=name: importlib.import_module(m))

    def database() -> None:
        from phraseforge.db import Store
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "selftest.db")
            store.set_setting("selftest.key", "1")
            assert store.setting("selftest.key") == "1"
            store.close()
    check("database", database)

    def icons() -> None:
        from phraseforge.ui.icons import app_icon
        assert not app_icon().isNull()
        import qtawesome as qta
        assert not qta.icon("mdi6.folder").isNull()
    check("icons", icons)

    def readme() -> None:
        from phraseforge.ui.about_dialog import PROJECT_README
        assert PROJECT_README.is_file(), PROJECT_README
    check("README bundled", readme)

    lines.append("RESULT: " + ("FAIL" if failed else "PASS"))
    (paths.data_dir() / "selftest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if failed else 0
