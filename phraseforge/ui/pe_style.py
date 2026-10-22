"""Light Office-2016-like look used by every PhraseForge window.

Matches the reference screenshots in reference/phraseexpress: light grey ribbon
and panels, white input fields, bold field captions (objectName "FieldCaption"),
Segoe UI 9pt, blue selection, active ribbon tab bold with a blue underline.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

ACCENT = "#2b579a"      # Office blue (ribbon underline, selection border)
SELECT_BG = "#cce4f7"   # selected tree row / hovered menu item
PANEL = "#f3f3f3"       # ribbon, panels
BORDER = "#c8c8c8"
TEXT = "#262626"
CAPTION = "#666666"

QSS = f"""
* {{ font-family: "Segoe UI"; font-size: 9pt; color: {TEXT}; }}
QMainWindow, QDialog {{ background: {PANEL}; }}

/* ---------------- ribbon ---------------- */
#Ribbon, #RibbonTabRow, #RibbonBody, #RibbonTabPage {{ background: {PANEL}; }}
#RibbonBody {{ border-bottom: 1px solid {BORDER}; }}
#RibbonFileButton, #RibbonTabButton, #RibbonContextTab {{
  border: none; padding: 5px 10px 4px 10px; font-size: 10.5pt; background: transparent; }}
#RibbonFileButton::menu-indicator {{ image: none; width: 0; }}
#RibbonTabButton:hover, #RibbonFileButton:hover, #RibbonContextTab:hover {{ color: {ACCENT}; }}
#RibbonTabButton:checked, #RibbonContextTab:checked {{
  font-weight: 600; border-bottom: 2px solid {ACCENT}; }}
#RibbonContextTab {{ color: {ACCENT}; }}
#RibbonGroupCaption {{ color: {CAPTION}; font-size: 8pt; padding-bottom: 2px; }}
#RibbonSeparator {{ color: #dadada; margin: 4px 2px 6px 2px; }}
#RibbonLarge, #RibbonSmall {{ border: 1px solid transparent; border-radius: 2px; padding: 1px 3px; }}
#RibbonLarge:hover, #RibbonSmall:hover {{ background: #e1e1e1; border-color: #c5c5c5; }}
#RibbonLarge:pressed, #RibbonSmall:pressed, #RibbonLarge:checked, #RibbonSmall:checked {{
  background: #cde6f7; border-color: #92c0e0; }}
#RibbonLarge:disabled, #RibbonSmall:disabled {{ color: #a0a0a0; }}
#RibbonLarge::menu-button, #RibbonSmall::menu-button {{ border: none; width: 11px; background: transparent; }}
#RibbonLarge::menu-button:hover, #RibbonSmall::menu-button:hover {{ background: #d5d5d5; }}
#RibbonLarge::menu-arrow, #RibbonSmall::menu-arrow, #RibbonLarge::menu-indicator, #RibbonSmall::menu-indicator {{
  width: 7px; height: 7px; }}
#RibbonLarge[popupMode="1"] {{ padding-right: 11px; }}
#RibbonSmall[popupMode="1"] {{ padding-right: 11px; }}

/* ---------------- quick toolbar / status ---------------- */
#QuickToolbar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}
QStatusBar {{ background: {PANEL}; border-top: 1px solid {BORDER}; }}
QStatusBar QLabel {{ padding: 0 6px; }}

/* ---------------- tree / lists ---------------- */
QTreeView, QTreeWidget, QListView, QListWidget, QTableView, QTableWidget {{
  background: {PANEL}; border: none; outline: 0; }}
QTreeView::item, QListView::item {{ padding: 2px 1px; }}
QTreeView::item:selected, QListView::item:selected, QTableView::item:selected {{
  background: {SELECT_BG}; color: {TEXT}; border: 1px dotted #7a9cc4; }}
QTreeView::item:hover, QListView::item:hover {{ background: #e5f1fb; }}
QHeaderView::section {{ background: {PANEL}; border: none; border-bottom: 1px solid {BORDER};
  padding: 3px 6px; font-weight: 600; }}
#PanelHeader {{ font-weight: 600; padding: 6px 6px 4px 6px; }}

/* ---------------- editor fields ---------------- */
#FieldCaption {{ font-weight: 600; padding-top: 6px; }}
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit, QComboBox {{
  background: white; border: 1px solid #b9b9b9; border-radius: 0; padding: 2px 3px;
  selection-background-color: #3399ff; selection-color: white; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus {{
  border-color: {ACCENT}; }}
#ContentEditor {{ border: none; }}
QComboBox QAbstractItemView {{ background: white; selection-background-color: #0078d7;
  selection-color: white; border: 1px solid #7a7a7a; }}
QComboBox::drop-down {{ border: none; width: 16px; }}
QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit, QDateTimeEdit {{ padding-right: 16px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
  subcontrol-origin: border; width: 15px; border-left: 1px solid #d0d0d0; background: #f7f7f7; }}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: #e5f1fb; }}

/* ---------------- buttons ---------------- */
QPushButton {{ background: #e1e1e1; border: 1px solid #adadad; padding: 3px 14px; min-width: 64px; }}
QPushButton:hover {{ background: #e5f1fb; border-color: #0078d7; }}
QPushButton:pressed {{ background: #cce4f7; border-color: #005499; }}
QPushButton:default {{ border: 1px solid #0078d7; }}
QPushButton:disabled {{ color: #a0a0a0; background: #f0f0f0; border-color: #d0d0d0; }}
QPushButton:checked {{ background: #cce4f7; border-color: #0078d7; }}
#ModifierButton {{ min-width: 36px; padding: 3px 8px; }}

/* ---------------- groups / menus ---------------- */
QGroupBox {{ border: 1px solid #dcdcdc; margin-top: 10px; padding: 8px 6px 6px 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 6px; padding: 0 3px; font-weight: 600; }}
QMenu {{ background: white; border: 1px solid #c6c6c6; padding: 2px; }}
QMenu::item {{ padding: 4px 26px 4px 28px; }}
QMenu::item:selected {{ background: {SELECT_BG}; }}
QMenu::item:disabled {{ color: #a0a0a0; }}
QMenu::separator {{ height: 1px; background: #e2e2e2; margin: 3px 4px; }}
QMenu::icon {{ padding-left: 6px; }}
QToolTip {{ background: white; border: 1px solid #767676; padding: 2px 4px; }}
QTabWidget::pane {{ border: 1px solid #d9d9d9; background: white; }}
QTabBar::tab {{ padding: 4px 10px; background: {PANEL}; border: 1px solid #d9d9d9; border-bottom: none; }}
QTabBar::tab:selected {{ background: white; }}
QSplitter::handle {{ background: #e1e1e1; }}
QScrollBar:vertical {{ width: 14px; background: {PANEL}; }}
QScrollBar:horizontal {{ height: 14px; background: {PANEL}; }}
#Hyperlink {{ color: #0066cc; text-decoration: underline; }}
#SettingsTree {{ background: white; border: 1px solid #c8c8c8; }}
#SettingsPage {{ background: {PANEL}; }}
"""


def _arrow_images() -> str:
    """QSS rules for combo/spin arrows. A style sheet that restyles drop-down
    buttons drops Fusion's arrows, so we draw our own once to PNG files."""
    try:
        import qtawesome as qta
        from phraseforge import paths
        d = paths.data_dir() / "ui"
        d.mkdir(exist_ok=True)
        files = {}
        for name, glyph, color in (("down", "mdi6.chevron-down", "#444444"), ("up", "mdi6.chevron-up", "#444444"),
                                   ("down_dis", "mdi6.chevron-down", "#a0a0a0")):
            f = d / f"arrow_{name}.png"
            if not f.exists():
                qta.icon(glyph, color=color).pixmap(12, 12).save(str(f))
            files[name] = f.as_posix()
    except Exception:
        return ""
    return f"""
QComboBox::down-arrow {{ image: url("{files['down']}"); width: 10px; height: 10px; }}
QComboBox::down-arrow:disabled {{ image: url("{files['down_dis']}"); }}
QAbstractSpinBox::up-arrow {{ image: url("{files['up']}"); width: 9px; height: 9px; }}
QAbstractSpinBox::down-arrow {{ image: url("{files['down']}"); width: 9px; height: 9px; }}
"""


def apply(app: QApplication) -> None:
    from PySide6.QtCore import QLocale
    # Western digits in number/date fields even on an Arabic Windows locale;
    # text itself (Arabic phrases, RTL) is unaffected.
    QLocale.setDefault(QLocale(QLocale.English, QLocale.UnitedStates))
    app.setStyle("Fusion")
    pal = app.palette()
    pal.setColor(QPalette.Window, QColor(PANEL))
    pal.setColor(QPalette.Base, QColor("white"))
    pal.setColor(QPalette.Highlight, QColor("#0078d7"))
    pal.setColor(QPalette.HighlightedText, QColor("white"))
    pal.setColor(QPalette.Link, QColor("#0066cc"))
    app.setPalette(pal)
    f = QFont("Segoe UI", 9)
    app.setFont(f)
    app.setStyleSheet(QSS + _arrow_images())


def caption(text: str):
    """Bold field caption label like PhraseExpress's "Description" / "Trigger"."""
    from PySide6.QtWidgets import QLabel
    lab = QLabel(text)
    lab.setObjectName("FieldCaption")
    return lab
