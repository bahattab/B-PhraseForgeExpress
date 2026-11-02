"""Visual audit fixes (0.6.0): contrast, primary buttons, menu buttons, icon palette, Arabic headers."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QHeaderView, QPushButton, QToolButton

from phraseforge.db import Store
from phraseforge.ui import iconset, pe_style


def _lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    pe_style.apply(a)
    return a


def test_colours_meet_wcag():
    assert contrast(pe_style.FIELD_BORDER, "#ffffff") >= 3.0          # WCAG 1.4.11
    assert contrast(pe_style.PLACEHOLDER, "#ffffff") >= 4.5           # WCAG 1.4.3
    assert contrast("#ffffff", pe_style.ACCENT) >= 4.5                # primary button text
    assert "#b9b9b9" not in pe_style.QSS


def test_placeholder_colour_is_in_the_palette(app):
    from PySide6.QtGui import QPalette
    assert app.palette().color(QPalette.PlaceholderText).name() == pe_style.PLACEHOLDER


def test_ok_button_of_a_button_box_becomes_primary(app):
    d = QDialog()
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, d)
    d.show()
    app.processEvents()
    assert bb.button(QDialogButtonBox.Ok).property("primary") is True
    assert bb.button(QDialogButtonBox.Cancel).property("primary") is not True
    d.close()


def test_primary_and_menu_button_helpers(app):
    b = pe_style.primary(QPushButton("Send"))
    assert b.property("primary") is True
    t = pe_style.menu_button(QToolButton())
    assert t.objectName() == "MenuButton"


def test_icon_palette_is_calm():
    assert iconset.tone("import", iconset.GREEN) == iconset.BLUE
    assert iconset.tone("two_columns", iconset.PURPLE) == iconset.BLUE
    assert iconset.tone("new_folder", iconset.YELLOW) == iconset.YELLOW
    assert iconset.tone("delete", iconset.RED) == iconset.RED
    assert iconset.tone("program_restrictions", iconset.RED) == iconset.BLUE
    assert iconset.tone("warning", iconset.ORANGE) == iconset.ORANGE
    used = {iconset.tone(k, c) for k, (_, c) in iconset.ICONS.items()}
    assert used <= {iconset.BLUE, iconset.GREY, iconset.YELLOW, iconset.RED, iconset.ORANGE}


def test_phrase_list_has_no_forced_horizontal_scroll(app):
    from phraseforge.ui.main_window import MainWindow
    s = Store(":memory:")
    w = MainWindow(s)
    hdr = w.phrase_list.list.header()
    assert hdr.sectionResizeMode(0) == QHeaderView.Stretch
    assert not hdr.stretchLastSection()
    w.close()
    s.close()


def test_arabic_texts_for_list_headers_and_breadcrumb():
    from phraseforge.ui.i18n import AR
    for key in ("Description", "Autotext", "Hotkey", "Phrases", 'Files and Folders ("Default")',
                'Folders and phrases ("Default")'):
        assert AR.get(key), key
