"""Full Arabic interface: automatic translation, right-to-left layout, popup painting."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QGroupBox, QLabel, QLineEdit, QMenu, QPushButton,
    QVBoxLayout,
)

from phraseforge.ui import i18n


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    i18n.install(app, "en")


def _dialog():
    d = QDialog()
    d.setWindowTitle("Settings")
    lay = QVBoxLayout(d)
    g = QGroupBox("Appearance")
    lay.addWidget(g)
    lay.addWidget(QLabel("Description:"))
    lay.addWidget(QPushButton("&Cancel"))
    lay.addWidget(QCheckBox("Enabled"))
    e = QLineEdit()
    e.setPlaceholderText("Search")
    lay.addWidget(e)
    data = QComboBox()
    data.addItem("Default", "default")
    lay.addWidget(data)
    plain = QComboBox()
    plain.addItems(["Default"])          # program reads currentText(): must stay English
    lay.addWidget(plain)
    user = QLabel("Settings")
    user.setProperty("pf_user", True)    # user data looks like UI text but is not
    lay.addWidget(user)
    return d, g, e, data, plain, user


def test_lookup_variants():
    assert i18n.AR["Exit"]
    i18n.set_language("ar")
    try:
        assert i18n.lookup("&Settings...") == i18n.AR["Settings"] + "..."
        assert i18n.lookup("Description:") == i18n.AR["Description"] + ":"
        assert i18n.lookup("Not a known UI string 123") == "Not a known UI string 123"
    finally:
        i18n.set_language("en")


def test_resolve_language():
    assert i18n.resolve_language("ar") == "ar"
    assert i18n.resolve_language("auto", "ar_SA") == "ar"
    assert i18n.resolve_language("auto", "en_US") == "en"
    assert i18n.is_rtl("ar") and not i18n.is_rtl("en")


def test_dialog_translates_to_arabic_and_back(qapp):
    d, g, e, data, plain, user = _dialog()
    i18n.install(qapp, "ar")
    d.show()
    qapp.processEvents()
    assert qapp.layoutDirection() == Qt.RightToLeft
    assert d.windowTitle() == i18n.AR["Settings"]
    assert g.title() == i18n.AR["Appearance"]
    assert e.placeholderText() == i18n.AR["Search"]
    assert data.itemText(0) == i18n.AR["Default"] and data.currentData() == "default"
    assert plain.itemText(0) == "Default"
    assert user.text() == "Settings"
    i18n.install(qapp, "en")
    assert qapp.layoutDirection() == Qt.LeftToRight
    assert d.windowTitle() == "Settings" and g.title() == "Appearance"
    assert data.itemText(0) == "Default"
    d.close()


def test_menu_actions_translate_on_show(qapp):
    i18n.install(qapp, "ar")
    m = QMenu()
    a = m.addAction("Exit")
    i18n.translate_tree(m)
    assert a.text() == i18n.AR["Exit"]


def test_settings_dialog_in_arabic(qapp, tmp_path):
    from phraseforge.db import Store
    from phraseforge.ui.settings_dialog import SettingsDialog
    s = Store(tmp_path / "t.db")
    try:
        i18n.install(qapp, "ar")
        d = SettingsDialog(s)
        d.show()
        qapp.processEvents()
        top = [d.tree.topLevelItem(i).text(0) for i in range(d.tree.topLevelItemCount())]
        arabic = [t for t in top if any("؀" <= c <= "ۿ" for c in t)]
        assert len(arabic) >= len(top) - 1, top        # the page tree is in Arabic
        d.show_page("display")                         # pages still found by key
        d.close()
    finally:
        s.close()


def test_popup_paints_right_to_left(qapp, tmp_path):
    from PySide6.QtGui import QPixmap
    from phraseforge.db import Store
    from phraseforge.models import Phrase
    from phraseforge.ui.popup import PhrasePopup, has_rtl
    assert has_rtl("مرحبا") and not has_rtl("hello")
    s = Store(tmp_path / "t.db")
    try:
        s.add_phrase(Phrase("تحية الصباح", "صباح الخير"))
        s.add_phrase(Phrase("Hello", "Hello"))
        i18n.install(qapp, "ar")
        pop = PhrasePopup(s)
        pop.resize(320, 240)
        pop.grab()                                     # paints every row through the RTL path
        pm = QPixmap(pop.size())
        pop.render(pm)
        assert not pm.isNull()
    finally:
        s.close()
