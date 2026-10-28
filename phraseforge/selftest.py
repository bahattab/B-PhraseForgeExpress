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
                 "google_auth_oauthlib.flow", "google.auth.transport.requests",
                 "winrt.windows.media.ocr", "winrt.windows.graphics.imaging",
                 "winrt.windows.storage.streams", "winrt.windows.globalization",
                 "comtypes.client", "pyodbc", "win32com.client")


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

    def guide() -> None:
        from phraseforge.ui.help_viewer import guide_path
        p = guide_path("ar")
        assert p.name == "USER_GUIDE.ar.md" and p.is_file(), p
    check("Arabic user guide bundled", guide)

    def ocr_engine() -> None:
        from PySide6.QtCore import QBuffer, QIODevice, Qt
        from PySide6.QtGui import QColor, QFont, QImage, QPainter
        from phraseforge.ocr import WindowsOCR
        langs = WindowsOCR().languages()
        lines.append(f"      OCR languages: {', '.join(langs) or '(none)'}")
        lang = "English" if "English" in langs else ""
        for px in (14, 28):                       # small screen text and large text
            img = QImage(700, 3 * px, QImage.Format_ARGB32)
            img.fill(QColor("white"))
            p = QPainter(img)
            f = QFont("Arial")
            f.setPixelSize(px)
            p.setFont(f)
            p.setPen(QColor("black"))
            p.drawText(img.rect(), Qt.AlignVCenter | Qt.AlignLeft, "  Hello PhraseForge 2026")
            p.end()
            buf = QBuffer()
            buf.open(QIODevice.WriteOnly)
            img.save(buf, "PNG")
            for scale in (0, 1, 2, 3):
                got = WindowsOCR(scale=scale).ocr_png(bytes(buf.data()), lang)
                lines.append(f"      OCR {px}px text, scale {scale or 'auto'}: {got!r}")
            auto = WindowsOCR()
            got = auto.ocr_png(bytes(buf.data()), "Auto")
            lines.append(f"      OCR {px}px text, language Auto -> {auto.last_language}: {got!r}")
            assert "2026" in got, got
    check("built-in OCR engine", ocr_engine)

    def com_wrappers() -> None:
        # OneNote is reached through comtypes, which writes wrapper modules for a
        # COM type library at run time; prove that works inside the packaged EXE.
        import comtypes.client
        mod = comtypes.client.GetModule("stdole2.tlb")
        assert hasattr(mod, "IFontDisp"), mod
    check("COM type library wrappers (OneNote)", com_wrappers)

    def screen_ocr() -> None:
        # The Screen OCR path on the real desktop: draw text in a window, capture that
        # area the way the region selector reports it, then read it.
        import time
        from PySide6.QtCore import QPoint, QRect, Qt
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QLabel
        from phraseforge.app import _grab_screen_png
        from phraseforge.ocr import WindowsOCR
        from phraseforge.ui.region_select import logical_to_physical
        w = QLabel("  Screen capture 2026  ")
        w.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        w.setStyleSheet("background:white;color:black")
        f = QFont("Arial")
        f.setPixelSize(32)
        w.setFont(f)
        w.adjustSize()
        w.move(120, 120)
        w.show()
        try:
            for _ in range(10):
                app.processEvents()
                time.sleep(0.05)
            screen = w.screen()
            top_left = w.mapToGlobal(QPoint(0, 0)) - screen.geometry().topLeft()
            rect = logical_to_physical(screen, QRect(top_left, w.size()))
            png = _grab_screen_png(rect)
            assert png, f"nothing captured at {rect}"
            from PySide6.QtGui import QImage
            img = QImage.fromData(png)
            colours = {img.pixel(x, y) for x in range(0, img.width(), 7) for y in range(0, img.height(), 7)}
            if len(colours) < 2:
                lines.append(f"      screen capture is blank here (no desktop session?) {rect}")
                return
            langs = WindowsOCR().languages()
            got = WindowsOCR().ocr_png(png, "English" if "English" in langs else "")
            lines.append(f"      screen OCR {rect}: {got!r}")
            assert "2026" in got or "capture" in got.lower(), got
        finally:
            w.close()
    check("screen capture + OCR", screen_ocr)

    def main_window_views() -> None:
        # The View tab's editor options and layout buttons, on the real phrase editor.
        from phraseforge.db import Store
        from phraseforge.models import Phrase
        from phraseforge.ui.main_window import MainWindow
        from phraseforge.ui.phrase_editor import PhraseEditor
        from phraseforge.ui.tree_panel import ROLE_KIND
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d) / "views.db")
            p = store.add_phrase(Phrase("Self-test", "a\tb {#date}"))
            w = MainWindow(store)
            try:
                w.select_phrase(p.id)
                ed = w.editor
                assert isinstance(ed, PhraseEditor), f"phrase editor not created: {type(ed).__name__}"
                for cb in w.view_options.values():
                    cb.setChecked(not cb.isChecked())
                ce = ed.content_edit
                assert ed.view == {"word_wrap": False, "show_special": True,
                                   "show_macro_params": True, "rulers": True}, ed.view
                assert ce.lineWrapMode() == ce.LineWrapMode.NoWrap and not ed.ruler.isHidden()
                w.set_columns(3, save=False)
                w.btn_flat.click()
                kinds = {w.phrase_list.list.topLevelItem(i).data(0, ROLE_KIND)
                         for i in range(w.phrase_list.list.topLevelItemCount())}
                assert w.panel.flat and kinds == {"phrase"}, kinds
                w.btn_fit.click()
            finally:
                w.close()
                store.close()
    check("main window view options", main_window_views)

    def google_signin() -> None:
        # The Google sign-in libraries load, and the settings page opens the setup dialog.
        from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: F401
        from phraseforge.cloud.gdrive import builtin_client_file, client_config
        from phraseforge.ui.settings_dialog import GoogleClientDialog
        GoogleClientDialog().deleteLater()
        if builtin_client_file().is_file():
            assert client_config() is not None, "the built-in Google client file is invalid"
        lines.append("      built-in Google client: " + ("yes" if builtin_client_file().is_file() else "no"))
    check("Google sign-in", google_signin)

    lines.append("RESULT: " + ("FAIL" if failed else "PASS"))
    (paths.data_dir() / "selftest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if failed else 0
