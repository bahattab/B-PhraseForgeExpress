"""Every UI string found by tools/i18n_missing.py has Arabic (G-31): new text needs a translation."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import i18n_missing  # noqa: E402


def test_no_untranslated_ui_strings():
    rows = i18n_missing.missing()
    assert rows == [], "add Arabic to phraseforge/ui/i18n_ar.py for:\n" + "\n".join(
        f"{f}:{line}: {s!r}" for s, f, line in rows)


def test_the_scanner_finds_strings(tmp_path):
    f = tmp_path / "w.py"
    f.write_text('QLabel("Hello there")\nb.setToolTip("Tip text")\nx = "not ui"\n', encoding="utf-8")
    assert [s for s, _ in i18n_missing.strings(f)] == ["Hello there", "Tip text"]


def test_scanner_covers_message_boxes_menus_and_fstrings(tmp_path):
    f = tmp_path / "w.py"
    f.write_text('QMessageBox.warning(self, "Box title", f"Failed: {e}")\n'
                 'menu_with(self, [("Menu entry...", "icon", fn), None])\n'
                 'tray.notify("Notice", f"{n} page(s) saved to {path}.")\n'
                 'QLabel(f"{n} ms")\nQLabel("مرحبا")\n', encoding="utf-8")
    assert [s for s, _ in i18n_missing.strings(f)] == [
        "Box title", "Failed: {}", "Menu entry...", "Notice", "{} page(s) saved to {}.", "{} ms"]


def test_run_time_text_is_translated_from_templates():
    from phraseforge.ui import i18n
    assert i18n.lookup("Exported 12 phrase(s).") == "تم تصدير 12 عبارة."
    assert i18n.lookup('Next time type "sig" for "Best regards".') == \
        "في المرة القادمة اكتب «sig» للحصول على «Best regards»."
    assert i18n.lookup("The download failed: timed out\nline 2") == "فشل التنزيل: timed out\nline 2"
    assert i18n.lookup("Reading report.pdf…") == "جارٍ قراءة report.pdf…"
    assert i18n.lookup("Some text nobody translated 42") == "Some text nobody translated 42"
    assert i18n.lookup("7 ms") == "7 ms"                      # too little fixed text: left alone


def test_templates_keep_their_place_holders():
    """Every template entry has as many {} in Arabic as in English."""
    from phraseforge.ui.i18n import AR
    bad = [k for k, v in AR.items() if "{}" in k and k.count("{}") != v.count("{}")]
    assert bad == []
