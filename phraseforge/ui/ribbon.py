"""Office-style ribbon bar (what PhraseExpress uses), built from plain Qt widgets.

Layout, top to bottom:
  tab row:  [File] [Tab] [Tab] ... [contextual tabs]  [search box]   ...  [right widget]
  body:     groups of large buttons (icon over text) and small buttons
            (icon + text, stacked 3 high), each group captioned at the bottom.

Usage:
    rb = Ribbon()
    rb.set_file_menu(menu)                      # "File" opens this menu
    tab = rb.add_tab("phrases", "Phrases")
    g = tab.add_group("Insert")
    g.add_large("New\\nFolder", "new_folder", on_click)
    g.add_large("New\\nPhrase", "new_phrase", on_click, menu=some_menu)  # split button
    col = g.add_column()                        # 3 small buttons stacked
    col.add_small("Up", "up", on_click)
    rb.set_contextual(tab_key, visible=True)    # e.g. "Phrase content" while editing
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMenu, QSizePolicy, QStackedWidget, QToolButton,
    QVBoxLayout, QWidget,
)

from phraseforge.ui.iconset import icon

LARGE = QSize(32, 32)
SMALL = QSize(16, 16)


class RibbonButton(QToolButton):
    """Large (icon above text) or small (icon beside text) ribbon button."""

    def __init__(self, text: str, icon_name: str = "", large: bool = False,
                 on_click: Callable | None = None, menu: QMenu | None = None,
                 split: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("RibbonLarge" if large else "RibbonSmall")
        self.setText(text)
        if icon_name:
            self.setIcon(icon(icon_name))
        self.setIconSize(LARGE if large else SMALL)
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon if large else Qt.ToolButtonTextBesideIcon)
        self.setAutoRaise(True)
        if large:
            self.setMinimumWidth(44)
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        if menu is not None:
            self.setMenu(menu)
            # split: click runs the action, arrow opens menu; otherwise the whole button opens it
            self.setPopupMode(QToolButton.MenuButtonPopup if (split and on_click) else QToolButton.InstantPopup)
        if on_click:
            self.clicked.connect(lambda _=False: on_click())


class RibbonColumn(QWidget):
    """Vertical stack of up to three small buttons/widgets."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(1)
        self._lay.addStretch(1)
        self.buttons: list[QWidget] = []

    def add_small(self, text: str, icon_name: str = "", on_click: Callable | None = None,
                  menu: QMenu | None = None, split: bool = True) -> RibbonButton:
        b = RibbonButton(text, icon_name, False, on_click, menu, split, self)
        return self.add_widget(b)

    def add_widget(self, w: QWidget):
        self._lay.insertWidget(self._lay.count() - 1, w)
        self.buttons.append(w)
        return w


class RibbonGroup(QFrame):
    def __init__(self, caption: str, parent=None):
        super().__init__(parent)
        self.setObjectName("RibbonGroup")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 2, 4, 0)
        outer.setSpacing(0)
        self.row = QHBoxLayout()
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(2)
        outer.addLayout(self.row, 1)
        self.caption = QLabel(caption)
        self.caption.setObjectName("RibbonGroupCaption")
        self.caption.setAlignment(Qt.AlignHCenter)
        outer.addWidget(self.caption)
        self.buttons: dict[str, QWidget] = {}

    def add_large(self, text: str, icon_name: str = "", on_click: Callable | None = None,
                  menu: QMenu | None = None, split: bool = True, key: str | None = None) -> RibbonButton:
        b = RibbonButton(text, icon_name, True, on_click, menu, split, self)
        self.row.addWidget(b)
        self.buttons[key or text.replace("\n", " ")] = b
        return b

    def add_column(self) -> RibbonColumn:
        c = RibbonColumn(self)
        self.row.addWidget(c)
        return c

    def add_widget(self, w: QWidget) -> QWidget:
        self.row.addWidget(w)
        return w


class RibbonTab(QWidget):
    def __init__(self, key: str, title: str, parent=None):
        super().__init__(parent)
        self.key, self.title = key, title
        self.setObjectName("RibbonTabPage")
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(4, 2, 4, 2)
        self._lay.setSpacing(0)
        self._lay.addStretch(1)
        self.groups: dict[str, RibbonGroup] = {}

    def add_group(self, caption: str) -> RibbonGroup:
        if self.groups:
            sep = QFrame(self)
            sep.setObjectName("RibbonSeparator")
            sep.setFrameShape(QFrame.VLine)
            self._lay.insertWidget(self._lay.count() - 1, sep)
        g = RibbonGroup(caption, self)
        self._lay.insertWidget(self._lay.count() - 1, g)
        self.groups[caption] = g
        return g


class Ribbon(QWidget):
    tab_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Ribbon")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.tab_row = QWidget(self)
        self.tab_row.setObjectName("RibbonTabRow")
        tr = QHBoxLayout(self.tab_row)
        tr.setContentsMargins(6, 2, 6, 0)
        tr.setSpacing(2)
        self.file_button = QToolButton(self.tab_row)
        self.file_button.setObjectName("RibbonFileButton")
        self.file_button.setText("File")
        self.file_button.setPopupMode(QToolButton.InstantPopup)
        tr.addWidget(self.file_button)
        self._tab_buttons_lay = QHBoxLayout()
        self._tab_buttons_lay.setSpacing(2)
        tr.addLayout(self._tab_buttons_lay)
        self._center_lay = QHBoxLayout()        # search box sits right after the tabs
        tr.addLayout(self._center_lay)
        tr.addStretch(1)
        self._right_lay = QHBoxLayout()
        tr.addLayout(self._right_lay)
        self.collapse_button = QToolButton(self.tab_row)
        self.collapse_button.setObjectName("RibbonCollapse")
        self.collapse_button.setIcon(icon("collapse"))
        self.collapse_button.setAutoRaise(True)
        self.collapse_button.setToolTip("Collapse the ribbon (Ctrl+F1)")
        self.collapse_button.clicked.connect(self.toggle_collapsed)
        tr.addWidget(self.collapse_button)
        lay.addWidget(self.tab_row)

        self.stack = QStackedWidget(self)
        self.stack.setObjectName("RibbonBody")
        self.stack.setFixedHeight(96)
        lay.addWidget(self.stack)

        self.tabs: dict[str, RibbonTab] = {}
        self._tab_buttons: dict[str, QToolButton] = {}
        self.current = ""

    # -------------------------------------------------- building
    def set_file_menu(self, menu: QMenu) -> None:
        self.file_button.setMenu(menu)

    def add_tab(self, key: str, title: str, contextual: bool = False) -> RibbonTab:
        tab = RibbonTab(key, title)
        self.tabs[key] = tab
        self.stack.addWidget(tab)
        b = QToolButton(self.tab_row)
        b.setObjectName("RibbonContextTab" if contextual else "RibbonTabButton")
        b.setText(title)
        b.setCheckable(True)
        b.setAutoRaise(True)
        b.clicked.connect(lambda _=False, k=key: self.select(k))
        self._tab_buttons_lay.addWidget(b)
        self._tab_buttons[key] = b
        if contextual:
            b.setVisible(False)
        if not self.current:
            self.select(key)
        return tab

    def set_center_widget(self, w: QWidget) -> None:
        self._center_lay.addWidget(w)

    def set_right_widget(self, w: QWidget) -> None:
        self._right_lay.addWidget(w)

    # -------------------------------------------------- state
    def select(self, key: str) -> None:
        if key not in self.tabs:
            return
        self.current = key
        self.stack.setCurrentWidget(self.tabs[key])
        for k, b in self._tab_buttons.items():
            b.setChecked(k == key)
        if self.stack.isHidden():          # clicking a tab while collapsed shows the body
            self.stack.show()
        self.tab_changed.emit(key)

    def set_contextual(self, key: str, visible: bool, activate: bool = False) -> None:
        b = self._tab_buttons.get(key)
        if not b:
            return
        b.setVisible(visible)
        if visible and activate:
            self.select(key)
        elif not visible and self.current == key:
            first = next(iter(k for k, bb in self._tab_buttons.items() if bb.isVisible()), None)
            if first:
                self.select(first)

    def toggle_collapsed(self) -> None:
        self.stack.setVisible(self.stack.isHidden())
        self.collapse_button.setIcon(icon("collapse" if self.stack.isVisible() else "expand"))

    def button(self, tab: str, group: str, key: str) -> QWidget | None:
        t = self.tabs.get(tab)
        g = t.groups.get(group) if t else None
        return g.buttons.get(key) if g else None


def menu_with(parent: QWidget, items: list) -> QMenu:
    """Build a QMenu from [(text, icon_name, callback_or_submenu_list) | None(separator)]."""
    m = QMenu(parent)
    for it in items:
        if it is None:
            m.addSeparator()
            continue
        text, icon_name, target = (list(it) + [None, None])[:3]
        if isinstance(target, list):
            sub = menu_with(m, target)
            sub.setTitle(text)
            if icon_name:
                sub.setIcon(icon(icon_name))
            m.addMenu(sub)
        else:
            a = QAction(icon(icon_name) if icon_name else icon(""), text, m)
            if callable(target):
                a.triggered.connect(lambda _=False, f=target: f())
            elif target is None:
                a.setEnabled(True)
            m.addAction(a)
    return m
