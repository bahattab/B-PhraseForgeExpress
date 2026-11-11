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
