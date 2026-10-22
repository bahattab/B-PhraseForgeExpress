"""Phrase popup menu (hotkey / tray), styled like a classic text-expander menu.

Layout of the root menu, top to bottom:
  header band  - our own "PHRASEFORGE" wordmark, search icon, pin icon
                 (turns into a search field in quick-search mode)
  ▲            - scroll arrow, only when the list is longer than the menu
  rows         - folders first (with ›), then phrases; Clipboard Cache and
                 Last Used appear as folders
  ▼
  footer       - "New phrase..."

Clicking a folder opens a cascading sub-menu beside the row (same style, folder
name in the header). Typing a letter, or clicking the search icon, switches the
root menu to quick search across all phrases; matches are highlighted.

Settings read (all optional):
  popup.max_items (30)  popup.show_icons (1)  popup.font_size (9)  popup.width (350)
  popup.position ("caret" | "mouse" | "center")  popup.sort ("description" | "usage")
  popup.search_content (0)  popup.search_match_case (0)  popup.search_subfolders (1)
  popup.show_clipboard_cache (1)  popup.show_last_used (1)
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QLinearGradient, QPainter, QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QStackedWidget, QStyle, QStyledItemDelegate, QToolButton, QVBoxLayout, QWidget,
)

from phraseforge.db import Store
from phraseforge.ui.iconset import icon

ROLE_KIND = Qt.UserRole          # "folder" | "phrase" | "clip" | "special" | "empty"
ROLE_ID = Qt.UserRole + 1        # folder id / phrase id / clipboard entry id / special key
ROLE_RIGHT = Qt.UserRole + 2     # grey secondary text on the right (autotext, path)
ROLE_QUERY = Qt.UserRole + 3     # text to highlight
ROLE_TEXT = Qt.UserRole + 4      # clipboard text

CLIPBOARD = "clipboard"
LAST_USED = "last_used"

ROW_H = 32
HEADER_H = 32
BAND_TOP, BAND_BOTTOM = "#1d5fa8", "#3a8ad6"
SELECT = QColor("#cde3f6")
MATCH = QColor("#1565c0")


def _setting(store: Store, key: str, default: str) -> str:
    try:
        v = store.setting(key, default)
    except Exception:
        return default
    return default if v in (None, "") else v


def _int_setting(store: Store, key: str, default: int) -> int:
    try:
        return int(float(_setting(store, key, str(default))))
    except ValueError:
        return default


def highlight_spans(text: str, query: str, match_case: bool = False) -> list[tuple[str, bool]]:
    """Split text into (segment, is_match) for every occurrence of query."""
    if not query:
        return [(text, False)]
    hay, needle = (text, query) if match_case else (text.lower(), query.lower())
    out, i = [], 0
    while True:
        j = hay.find(needle, i)
        if j < 0:
            break
        if j > i:
            out.append((text[i:j], False))
        out.append((text[j:j + len(query)], True))
        i = j + len(query)
    if i < len(text):
        out.append((text[i:], False))
    return out or [(text, False)]


# ---------------------------------------------------------------- painting
class _RowDelegate(QStyledItemDelegate):
    def __init__(self, panel: "_Panel"):
        super().__init__(panel)
        self.panel = panel

    def sizeHint(self, option, index):  # noqa: N802
        return QSize(option.rect.width(), ROW_H)

    def paint(self, p: QPainter, option, index):
        p.save()
        r = option.rect
        kind = index.data(ROLE_KIND)
        if option.state & QStyle.State_Selected and kind != "empty":
            p.fillRect(r, SELECT)
        x = r.left() + 8
        if self.panel.popup.show_icons and kind in ("folder", "phrase", "special", "clip"):
            name = {"folder": "folder", "phrase": "phrase", "clip": "clipboard_cache"}.get(kind)
            if kind == "special":
                name = "clipboard_cache" if index.data(ROLE_ID) == CLIPBOARD else "last_used"
            icon(name).paint(p, QRect(x, r.top() + (ROW_H - 16) // 2, 16, 16))
            x += 22
        font = QFont(self.panel.font())
        p.setFont(font)
        fm = QFontMetrics(font)
        right_text = index.data(ROLE_RIGHT) or ""
        chevron = kind in ("folder", "special")
        right_w = 18 if chevron else 6
        if right_text:
            right_w += min(fm.horizontalAdvance(right_text) + 12, r.width() // 3)
        avail = r.right() - right_w - x
        text = index.data(Qt.DisplayRole) or ""
        if kind == "empty":
            p.setPen(QColor("#8a8a8a"))
            p.drawText(QRect(x, r.top(), avail, r.height()), Qt.AlignVCenter | Qt.AlignLeft, text)
            p.restore()
            return
        query = index.data(ROLE_QUERY) or ""
        base_y = r.top() + (r.height() + fm.ascent() - fm.descent()) // 2
        cx = x
        bold = QFont(font)
        bold.setBold(True)
        for seg, hit in highlight_spans(text, query, self.panel.popup.match_case):
            f = bold if hit else font
            m = QFontMetrics(f)
            if cx + m.horizontalAdvance(seg) > x + avail:      # elide the tail
                seg = m.elidedText(seg, Qt.ElideRight, max(0, x + avail - cx))
            p.setFont(f)
            p.setPen(MATCH if hit else QColor("#1f1f1f"))
            p.drawText(cx, base_y, seg)
            cx += m.horizontalAdvance(seg)
            if cx >= x + avail:
                break
        p.setFont(font)
        if right_text:
            p.setPen(QColor("#7a7a7a"))
            rr = QRect(r.right() - right_w, r.top(), right_w - (18 if chevron else 6), r.height())
            p.drawText(rr, Qt.AlignVCenter | Qt.AlignRight, fm.elidedText(right_text, Qt.ElideMiddle, rr.width()))
        if chevron:
            p.setPen(QPen(QColor("#505050"), 1.3))
            cx, cy = r.right() - 10, r.center().y()
            p.setRenderHint(QPainter.Antialiasing)
            p.drawLine(cx - 3, cy - 4, cx + 1, cy)
            p.drawLine(cx + 1, cy, cx - 3, cy + 4)
        p.restore()


class _Band(QWidget):
    """Blue header band. Root: our wordmark. Sub-menu: the folder name."""

    def __init__(self, title: str = "", wordmark: bool = False, parent=None):
        super().__init__(parent)
        self.title, self.wordmark = title, wordmark
        self.setFixedHeight(HEADER_H)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(6, 0, 4, 0)
        self.lay.setSpacing(0)
        self.lay.addStretch(1)

    def add_button(self, name: str, tip: str, checkable: bool = False) -> QToolButton:
        b = QToolButton(self)
        b.setIcon(icon(name, "white"))
        b.setIconSize(QSize(15, 15))
        b.setAutoRaise(True)
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.setStyleSheet("QToolButton{border:none;padding:3px;background:transparent}"
                        "QToolButton:hover{background:rgba(255,255,255,0.22)}"
                        "QToolButton:checked{background:rgba(255,255,255,0.35)}")
        self.lay.addWidget(b)
        return b

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, QColor(BAND_TOP))
        g.setColorAt(1, QColor(BAND_BOTTOM))
        p.fillRect(self.rect(), g)
        p.setRenderHint(QPainter.TextAntialiasing)
        if self.wordmark:
            f = QFont("Segoe UI", 14)
            f.setWeight(QFont.Black)
            f.setItalic(True)
            f.setLetterSpacing(QFont.AbsoluteSpacing, 2.5)
            p.setFont(f)
            # small "spark" mark of our own before the word
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#ffd54a"))
            cy = self.height() // 2
            p.drawPolygon([QPoint(10, cy + 6), QPoint(16, cy - 7), QPoint(16, cy - 1), QPoint(21, cy - 1),
                           QPoint(15, cy + 8), QPoint(15, cy + 2)])
            p.setPen(QColor("white"))
            p.drawText(QRect(26, 0, self.width() - 80, self.height()), Qt.AlignVCenter | Qt.AlignLeft,
                       "PHRASEFORGE")
        else:
            p.setPen(QColor("white"))
            p.setFont(self.font())
            fm = QFontMetrics(self.font())
            p.drawText(QRect(8, 0, self.width() - 40, self.height()), Qt.AlignVCenter | Qt.AlignLeft,
                       fm.elidedText(self.title, Qt.ElideRight, self.width() - 40))


class _ArrowButton(QToolButton):
    """▲ / ▼ scroll arrow; scrolls while hovered, like classic menus."""

    def __init__(self, up: bool, target: QListWidget, parent=None):
        super().__init__(parent)
        self.up, self.target = up, target
        self.setArrowType(Qt.UpArrow if up else Qt.DownArrow)
        self.setAutoRaise(True)
        self.setFixedHeight(12)
        self.setSizePolicy(self.sizePolicy().horizontalPolicy(), self.sizePolicy().verticalPolicy())
        self.setStyleSheet("QToolButton{border:none;background:transparent}")
        self.timer = QTimer(self)
        self.timer.setInterval(70)
        self.timer.timeout.connect(self.step)
        self.clicked.connect(self.step)

    def step(self):
        sb = self.target.verticalScrollBar()
        sb.setValue(sb.value() + (-sb.singleStep() if self.up else sb.singleStep()))

    def enterEvent(self, e):  # noqa: N802
        self.timer.start()
        super().enterEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        self.timer.stop()
        super().leaveEvent(e)


class _Footer(QLabel):
    clicked = Signal()

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setFixedHeight(ROW_H)
        self.setContentsMargins(8, 0, 8, 0)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = False

    def enterEvent(self, e):  # noqa: N802
        self.setStyleSheet(f"background:{SELECT.name()};")
        super().enterEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        self.setStyleSheet("")
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):  # noqa: N802
        if e.button() == Qt.LeftButton:
            self.clicked.emit()


# ---------------------------------------------------------------- one menu panel
class _Panel(QFrame):
    """A single menu column: header, scrollable rows, optional footer."""

    def __init__(self, popup: "PhrasePopup | None", folder_key, title: str = "", depth: int = 0,
                 store: Store | None = None):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.popup = popup if popup is not None else self
        self.folder_key = folder_key
        self.depth = depth
        self.setObjectName("PopupPanel")
        self.setStyleSheet("#PopupPanel{background:white;border:1px solid #8c8c8c}")
        size = _int_setting(store or popup.store, "popup.font_size", 9)
        self.setFont(QFont("Segoe UI", size))
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(1, 1, 1, 1)
        self.outer.setSpacing(0)
        self.header = QStackedWidget(self)
        self.header.setFixedHeight(HEADER_H)
        self.band = _Band(title, wordmark=(depth == 0 and folder_key is None), parent=self.header)
        self.header.addWidget(self.band)
        self.outer.addWidget(self.header)
        self.list = QListWidget(self)
        self.up_arrow = _ArrowButton(True, self.list, self)
        self.down_arrow = _ArrowButton(False, self.list, self)
        self.outer.addWidget(self.up_arrow)
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerItem)
        self.list.setUniformItemSizes(True)
        self.list.setMouseTracking(True)
        self.list.setStyleSheet("QListWidget{background:white;border:none;outline:0}"
                                "QListWidget::item{border:none}")
        self.list.setItemDelegate(_RowDelegate(self))
        self.list.itemEntered.connect(self.list.setCurrentItem)
        self.list.itemClicked.connect(self._activate)
        self.list.itemActivated.connect(self._activate)
        self.list.installEventFilter(self)
        self.outer.addWidget(self.list, 1)
        self.outer.addWidget(self.down_arrow)
        self.footer_line = QFrame(self)
        self.footer_line.setFrameShape(QFrame.HLine)
        self.footer_line.setStyleSheet("color:#d6d6d6")
        self.outer.addWidget(self.footer_line)
        self.footer = _Footer("New phrase...", self)
        self.footer.clicked.connect(self._footer_clicked)
        self.outer.addWidget(self.footer)
        self.pin_button = None
        self._typed = ""
        self._typed_timer = QTimer(self)
        self._typed_timer.setSingleShot(True)
        self._typed_timer.setInterval(900)
        self._typed_timer.timeout.connect(lambda: setattr(self, "_typed", ""))
        if depth > 0:
            self.pin_button = self.band.add_button("pin", "Keep the menu open", checkable=True)
            self.pin_button.toggled.connect(self.popup.set_pinned)

    # -------------------------------------------- rows
    def add_row(self, kind: str, ident, text: str, right: str = "", query: str = "",
                clip_text: str = "") -> QListWidgetItem:
        it = QListWidgetItem(text)
        it.setData(ROLE_KIND, kind)
        it.setData(ROLE_ID, ident)
        it.setData(ROLE_RIGHT, right)
        it.setData(ROLE_QUERY, query)
        it.setData(ROLE_TEXT, clip_text)
        it.setSizeHint(QSize(10, ROW_H))
        if kind == "empty":
            it.setFlags(Qt.NoItemFlags)
        self.list.addItem(it)
        return it

    def fill(self) -> None:
        """(Re)build the rows for this panel's folder."""
        self.list.clear()
        pop, st = self.popup, self.popup.store
        key = self.folder_key
        self.footer.setText("New phrase...")
        self._set_footer(True)
        if key == CLIPBOARD:
            entries = st.clipboard_entries(limit=max(1, pop.max_items))
            for e in entries:
                one = " ".join(e.text.split())
                self.add_row("clip", e.id, one[:200], clip_text=e.text)
            if not entries:
                self.add_row("empty", None, "(empty)")
            self.footer.setText("Clear clipboard cache")
            self._set_footer(bool(entries))
        elif key == LAST_USED:
            for p in pop.last_used_phrases():
                self.add_row("phrase", p.id, p.description, right=pop.right_text(p))
            if self.list.count() == 0:
                self.add_row("empty", None, "(empty)")
            self._set_footer(False)
        else:
            entries = pop.folder_entries(key)
            for kind, ident, text, right in entries:
                self.add_row(kind, ident, text, right=right)
            if not entries:
                self.add_row("empty", None, "(empty)")
        self._select_first()
        self.update_geometry()

    def _set_footer(self, visible: bool) -> None:
        self.footer.setVisible(visible)
        self.footer_line.setVisible(visible)

    def _select_first(self) -> None:
        for i in range(self.list.count()):
            if self.list.item(i).data(ROLE_KIND) != "empty":
                self.list.setCurrentRow(i)
                return

    def update_geometry(self) -> None:
        pop = self.popup
        n = max(1, self.list.count())
        scr = QGuiApplication.screenAt(self.pos()) or QGuiApplication.primaryScreen()
        avail_h = scr.availableGeometry().height() if scr else 900
        chrome = HEADER_H + 2 + (ROW_H + 1 if self.footer.isVisible() else 0)
        max_rows = max(3, min(pop.max_items, (avail_h - chrome - 24) // ROW_H))
        rows = min(n, max_rows)
        scroll = n > rows
        self.up_arrow.setVisible(scroll)
        self.down_arrow.setVisible(scroll)
        self.list.setFixedHeight(rows * ROW_H)
        if self.depth == 0:
            w = pop.menu_width
        else:
            fm = QFontMetrics(self.font())
            widest = max([fm.horizontalAdvance(self.list.item(i).text()) +
                          fm.horizontalAdvance(self.list.item(i).data(ROLE_RIGHT) or "")
                          for i in range(self.list.count())] + [fm.horizontalAdvance(self.band.title) + 30])
            w = max(180, min(480, widest + (60 if pop.show_icons else 40)))
        self.setFixedWidth(w)
        self.adjustSize()

    # -------------------------------------------- interaction
    def _activate(self, it: QListWidgetItem) -> None:
        if it is None:
            return
        kind = it.data(ROLE_KIND)
        if kind in ("folder", "special"):
            self.popup.open_submenu(self, it)
        elif kind == "phrase":
            self.popup.choose_phrase(it.data(ROLE_ID))
        elif kind == "clip":
            self.popup.choose_clip(it.data(ROLE_TEXT))

    def _footer_clicked(self) -> None:
        if self.folder_key == CLIPBOARD:
            self.popup.store.clear_clipboard(keep_pinned=True)
            self.fill()
            return
        self.popup.request_new_phrase(self.folder_key if isinstance(self.folder_key, int) else None)

    def handle_key(self, e) -> bool:
        k = e.key()
        cur = self.list.currentItem()
        if k in (Qt.Key_Return, Qt.Key_Enter):
            self._activate(cur)
            return True
        if k == Qt.Key_Right and cur is not None and cur.data(ROLE_KIND) in ("folder", "special"):
            self.popup.open_submenu(self, cur, focus=True)
            return True
        if k in (Qt.Key_Left, Qt.Key_Escape, Qt.Key_Backspace) and self.depth > 0:
            self.popup.close_from(self.depth, refocus=True)
            return True
        if k == Qt.Key_Escape:
            self.popup.hide_all(force=True)
            return True
        text = e.text()
        if text and text.isprintable() and not (e.modifiers() & (Qt.ControlModifier | Qt.AltModifier)):
            if self.depth == 0 and self.popup.quick_jump_mode == "search":
                self.popup.start_search(text)
                return True
            self._typed += text.lower()       # quick jump inside a menu
            self._typed_timer.start()
            for i in range(self.list.count()):
                if (self.list.item(i).text() or "").lower().startswith(self._typed):
                    self.list.setCurrentRow(i)
                    break
            return True
        return False

    def eventFilter(self, obj, e):  # noqa: N802
        if obj is self.list and e.type() == QEvent.KeyPress:
            if e.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_PageUp, Qt.Key_PageDown, Qt.Key_Home, Qt.Key_End):
                return False
            if self.handle_key(e):
                return True
        return super().eventFilter(obj, e)

    def changeEvent(self, e):  # noqa: N802
        if e.type() == QEvent.ActivationChange:
            QTimer.singleShot(80, self.popup.check_active)
        super().changeEvent(e)


# ---------------------------------------------------------------- the popup
class PhrasePopup(_Panel):
    phrase_chosen = Signal(int)
    clipboard_chosen = Signal(str)
    new_phrase_requested = Signal()

    def __init__(self, store: Store, parent=None):
        super().__init__(None, None, "", 0, store=store)
        self.popup = self
        self.store = store
        self.app_exe = ""
        self.pinned = False
        self.subs: list[_Panel] = []
        self.new_phrase_folder_id: int | None = None
        self.quick_jump_mode = "search"
        self._load_settings()
        # header: band with search + pin, or the search bar
        self.search_button = self.band.add_button("search", "Search [F3]")
        self.search_button.clicked.connect(lambda: self.start_search(""))
        self.pin_button = self.band.add_button("pin", "Keep the menu open", checkable=True)
        self.pin_button.toggled.connect(self.set_pinned)
        bar = QWidget(self.header)
        bar.setStyleSheet("background:white")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(4, 3, 4, 3)
        bl.setSpacing(2)
        self.search = QLineEdit(bar)
        self.search.setPlaceholderText("Search...")
        self.search.setFrame(False)
        f = QFont(self.font())
        f.setBold(True)
        self.search.setFont(f)
        self.search.setStyleSheet("QLineEdit{border:none;background:white}")
        self.search.textChanged.connect(self._search_changed)
        self.search.installEventFilter(self)
        bl.addWidget(self.search, 1)
        self.clear_button = QToolButton(bar)
        self.clear_button.setIcon(icon("remove", "#444444"))
        self.clear_button.setAutoRaise(True)
        self.clear_button.setToolTip("Close search")
        self.clear_button.clicked.connect(self.end_search)
        bl.addWidget(self.clear_button)
        self.header.addWidget(bar)
        self.search_bar = bar
        self.band.setToolTip("PhraseForge")

    # -------------------------------------------- settings / data
    def _load_settings(self) -> None:
        st = self.store
        self.max_items = max(3, _int_setting(st, "popup.max_items", 30))
        self.show_icons = _setting(st, "popup.show_icons", "1") == "1"
        self.menu_width = max(200, _int_setting(st, "popup.width", 350))
        self.position = _setting(st, "popup.position", "caret")
        self.sort = _setting(st, "popup.sort", "description")
        self.search_content = _setting(st, "popup.search_content", "0") == "1"
        self.match_case = _setting(st, "popup.search_match_case", "0") == "1"
        self.search_subfolders = _setting(st, "popup.search_subfolders", "1") == "1"
        self.show_clipboard = (_setting(st, "popup.show_clipboard_cache", "1") == "1"
                               and _setting(st, "clipboard_history.enabled", "1") == "1")
        self.show_last_used = _setting(st, "popup.show_last_used", "1") == "1"

    def _allowed(self, p) -> bool:
        if not p.enabled:
            return False
        if p.folder_id is not None:
            chain = self.store.folder_chain(p.folder_id)
            if any(not f.enabled or not f.show_in_popup for f in chain):
                return False
        return self.store.phrase_allowed_in_app(p.id, self.app_exe)

    def _folder_visible(self, f) -> bool:
        if not (f.enabled and f.show_in_popup):
            return False
        if self.app_exe:
            exe = self.app_exe.lower()
            inc = [a.strip().lower() for a in (f.apps_include or "").split(",") if a.strip()]
            exc = [a.strip().lower() for a in (f.apps_exclude or "").split(",") if a.strip()]
            if exe in exc or (inc and exe not in inc):
                return False
        return True

    def right_text(self, p) -> str:
        abbr = ", ".join(t.value for t in p.autotexts())
        hot = ", ".join(t.value.upper().replace("+", "-") for t in p.hotkeys())
        return "   ".join(x for x in (f"[{abbr}]" if abbr else "", f"({hot})" if hot else "") if x)

    def _sorted_phrases(self, phrases):
        if self.sort == "usage":
            return sorted(phrases, key=lambda p: (-p.use_count, p.description.lower()))
        return sorted(phrases, key=lambda p: p.description.lower())

    def folder_entries(self, folder_id) -> list[tuple[str, object, str, str]]:
        """[(kind, id, text, right)] for a folder: folders (incl. specials at root), then phrases."""
        folders = [("folder", f.id, f.name, "") for f in self.store.folders(folder_id) if self._folder_visible(f)]
        if folder_id is None:
            if self.show_clipboard:
                folders.append(("special", CLIPBOARD, "Clipboard Cache", ""))
            if self.show_last_used:
                folders.append(("special", LAST_USED, "Last Used", ""))
        folders.sort(key=lambda r: r[2].lower())
        phrases = [p for p in self.store.phrases(folder_id) if self._allowed(p)]
        rows = [("phrase", p.id, p.description, self.right_text(p)) for p in self._sorted_phrases(phrases)]
        return folders + rows

    def last_used_phrases(self, limit: int = 20):
        used = [p for p in self.store.phrases() if p.last_used and self._allowed(p)]
        return sorted(used, key=lambda p: p.last_used, reverse=True)[:limit]

    def _folder_path(self, folder_id) -> str:
        names = [f.name for f in reversed(self.store.folder_chain(folder_id))]
        return " › ".join(names)

    def search_entries(self, query: str) -> list[tuple[str, object, str, str]]:
        q = query if self.match_case else query.lower()

        def hit(text: str) -> bool:
            return q in (text if self.match_case else text.lower())

        rows = []
        for f in self.store.folders():
            if self._folder_visible(f) and hit(f.name) and all(self._folder_visible(c) for c in
                                                              self.store.folder_chain(f.id)):
                rows.append(("folder", f.id, f.name, self._folder_path(f.parent_id) if f.parent_id else ""))
        for p in self.store.phrases():
            if not self.search_subfolders and p.folder_id is not None:
                continue
            fields = [p.description] + [t.value for t in p.autotexts()]
            if self.search_content:
                fields.append(p.content)
            if any(hit(x) for x in fields) and self._allowed(p):
                rows.append(("phrase", p.id, p.description,
                             self._folder_path(p.folder_id) if p.folder_id else ""))
        # description matches first (starts-with before contains), then the rest
        def rank(r):
            t = r[2] if self.match_case else r[2].lower()
            return (0 if t.startswith(q) else 1 if q in t else 2, t)
        rows.sort(key=rank)
        return rows

    # -------------------------------------------- refresh / search
    def refresh(self) -> None:
        q = self.search.text().strip()
        if not q:
            self.header.setCurrentWidget(self.band)
            self.fill()
            return
        self.header.setCurrentWidget(self.search_bar)
        self.list.clear()
        rows = self.search_entries(q)
        for kind, ident, text, right in rows:
            self.add_row(kind, ident, text, right=right, query=q)
        if not rows:
            self.add_row("empty", None, "No matching phrases")
        self._set_footer(False)
        self._select_first()
        self.update_geometry()

    def _search_changed(self, _text: str) -> None:
        self.close_from(1)
        if self.search.text():
            self.header.setCurrentWidget(self.search_bar)
        self.refresh()

    def start_search(self, text: str = "") -> None:
        self.close_from(1)
        self.header.setCurrentWidget(self.search_bar)
        self.search.setText(text)
        self.search.setFocus()
        self.search.setCursorPosition(len(text))

    def end_search(self) -> None:
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.refresh()
        self.list.setFocus()

    # -------------------------------------------- sub-menus
    def open_submenu(self, parent_panel: _Panel, item: QListWidgetItem, focus: bool = False) -> _Panel:
        self.close_from(parent_panel.depth + 1)
        key = item.data(ROLE_ID)
        sub = _Panel(self, key, item.text(), parent_panel.depth + 1)
        if self.pin_button is not None and sub.pin_button is not None:
            sub.pin_button.setChecked(self.pinned)
        sub.fill()
        self.subs.append(sub)
        rect = parent_panel.list.visualItemRect(item)
        top_left = parent_panel.list.viewport().mapToGlobal(rect.topLeft())
        pg = parent_panel.frameGeometry()
        scr = QGuiApplication.screenAt(top_left) or QGuiApplication.primaryScreen()
        g = scr.availableGeometry()
        w, h = sub.width(), sub.sizeHint().height()
        x = pg.right() + 1
        if x + w > g.right():
            x = pg.left() - w - 1
        y = top_left.y() - HEADER_H - 1
        y = max(g.top(), min(y, g.bottom() - h))
        sub.move(x, y)
        if self.isVisible():
            sub.show()
            sub.raise_()
            if focus:
                sub.activateWindow()
                sub.list.setFocus()
        return sub

    def close_from(self, depth: int, refocus: bool = False) -> None:
        while self.subs and self.subs[-1].depth >= depth:
            s = self.subs.pop()
            s.hide()
            s.deleteLater()
        if refocus:
            target = self.subs[-1] if self.subs else self
            target.activateWindow()
            target.list.setFocus()

    def set_pinned(self, pinned: bool) -> None:
        self.pinned = bool(pinned)
        for b in [self.pin_button] + [s.pin_button for s in self.subs]:
            if b is not None and b.isChecked() != self.pinned:
                b.blockSignals(True)
                b.setChecked(self.pinned)
                b.blockSignals(False)

    # -------------------------------------------- results
    def choose_phrase(self, pid: int) -> None:
        if not self.pinned:
            self.hide_all(force=True)
        self.phrase_chosen.emit(pid)

    def choose_clip(self, text: str) -> None:
        if not self.pinned:
            self.hide_all(force=True)
        self.clipboard_chosen.emit(text)

    def request_new_phrase(self, folder_id: int | None) -> None:
        self.new_phrase_folder_id = folder_id
        self.hide_all(force=True)
        self.new_phrase_requested.emit()

    def visible_phrase_ids(self) -> list[int]:
        return [self.list.item(i).data(ROLE_ID) for i in range(self.list.count())
                if self.list.item(i).data(ROLE_KIND) == "phrase"]

    # -------------------------------------------- show / hide
    def show_at(self, x: int, y: int, app_exe: str = "") -> None:
        self.app_exe = app_exe or ""
        self._load_settings()
        self.close_from(1)
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.refresh()
        if self.position == "mouse":
            c = QCursor.pos()
            x, y = c.x(), c.y()
        scr = QGuiApplication.screenAt(QPoint(x, y)) or QGuiApplication.primaryScreen()
        g = scr.availableGeometry()
        h = self.sizeHint().height()
        w = self.width()
        if self.position == "center":
            px, py = g.center().x() - w // 2, g.center().y() - h // 2
        else:
            px = min(max(g.left(), x), g.right() - w)
            py = y + 4 if y + 4 + h <= g.bottom() else max(g.top(), y - h - 24)
        self.move(px, py)
        self.show()
        self.raise_()
        self.activateWindow()
        self.list.setFocus()

    def hide_all(self, force: bool = False) -> None:
        if self.pinned and not force:
            return
        self.close_from(1)
        self.hide()

    def check_active(self) -> None:
        if self.pinned or not self.isVisible():
            return
        active = QGuiApplication.focusWindow()
        panels = [self] + self.subs
        if active is None or not any(p.windowHandle() is active for p in panels if p.windowHandle()):
            self.hide_all()

    def eventFilter(self, obj, e):  # noqa: N802
        if obj is self.search and e.type() == QEvent.KeyPress:
            k = e.key()
            if k in (Qt.Key_Down, Qt.Key_Up, Qt.Key_PageDown, Qt.Key_PageUp):
                self.list.keyPressEvent(e)
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                self._activate(self.list.currentItem())
                return True
            if k == Qt.Key_Right and self.list.currentItem() is not None \
                    and self.list.currentItem().data(ROLE_KIND) in ("folder", "special"):
                self.open_submenu(self, self.list.currentItem(), focus=True)
                return True
            if k == Qt.Key_Escape:
                if self.search.text():
                    self.end_search()
                else:
                    self.hide_all(force=True)
                return True
        if obj is self.list and e.type() == QEvent.KeyPress and e.key() == Qt.Key_F3:
            self.start_search("")
            return True
        return super().eventFilter(obj, e)
