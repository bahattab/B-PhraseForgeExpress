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

Settings read (keys written by Settings > Phrase Menu; defaults in ui/settings_schema.py):
  menu.contents          right-hand text: description_quickkey | description |
                         description_autotext | description_autotext_hotkey
  menu.sort_enabled/sort_by/sort_method/sort_order   phrase order inside a folder
  menu.show_preview      tooltip with the phrase text
  menu.hide_restricted   hide phrases/folders restricted to other programs
  menu.position (+ menu.position_fallback when no caret)   caret | mouse | center
  menu.width             root menu width in px ("" = 350)
  menu.appearance        JSON colors (background, description, autotext, hotkey,
                         quickkey, selection) and "font"; menu.dim_dark dims them in dark mode
  menu.confirm_hotkey    extra key that inserts the selected phrase (besides Enter)
  menu.quickkey_modifier + menu.quickkey_keys   QuickKeys on the first rows
  menu.search_hotkey     opens quick search inside the menu (default F3)
  quicksearch.descriptions/match_case/subfolders/quick_jump
  features.last_used_folder + last_used.max, clipboard_history.enabled (folders shown)
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QLinearGradient, QPainter, QPen,
    QTextDocument, QTextOption,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QStackedWidget, QStyle, QStyledItemDelegate, QToolButton, QVBoxLayout, QWidget,
)

from phraseforge.db import Store
from phraseforge.ui.i18n import tr
from phraseforge.ui.iconset import icon

ROLE_KIND = Qt.UserRole          # "folder" | "phrase" | "clip" | "special" | "empty"
ROLE_ID = Qt.UserRole + 1        # folder id / phrase id / clipboard entry id / special key
ROLE_RIGHT = Qt.UserRole + 2     # grey secondary text on the right (autotext, path)
ROLE_QUERY = Qt.UserRole + 3     # text to highlight
ROLE_TEXT = Qt.UserRole + 4      # clipboard text
ROLE_QK = Qt.UserRole + 5        # QuickKey label shown on the right ("NumPad1")
ROLE_LEFT = Qt.UserRole + 6      # grey text before the description (menu.contents puts it first)

CONTENT_TOKENS = ("description", "quickkey", "autotext", "hotkey")


def content_tokens(contents: str) -> list[str]:
    """menu.contents value -> column order, e.g. "autotext_description_quickkey" ->
    ["autotext", "description", "quickkey"] (PhraseExpress "Phrase menu contents")."""
    toks = [t for t in (contents or "").split("_") if t in CONTENT_TOKENS]
    return toks if "description" in toks else ["description", "quickkey"]

CLIPBOARD = "clipboard"
LAST_USED = "last_used"
STICKY = "sticky_notes"          # Microsoft Sticky Notes (read-only, phraseforge.stickynotes)
STICKY_MAX = 200


def _sticky_available() -> bool:
    """Sticky Notes installed on this PC (tests monkeypatch this)."""
    try:
        from phraseforge import stickynotes
        return stickynotes.installed()
    except Exception:
        return False


def _sticky_notes() -> list:
    """The user's sticky notes, newest first (tests monkeypatch this)."""
    try:
        from phraseforge import stickynotes
        return stickynotes.read_notes()
    except Exception:
        return []

ROW_H = 32
HEADER_H = 32
BAND_TOP, BAND_BOTTOM = "#1d5fa8", "#3a8ad6"
SELECT = QColor("#cde3f6")
MATCH = QColor("#1565c0")


def _setting(store: Store, key: str, default: str | None = None) -> str:
    if default is None:
        from phraseforge.ui.settings_schema import SCHEMA
        default = SCHEMA.get(key, "")
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


QUICKKEY_COUNTS = {"numpad": 9, "digits": 9, "fkeys": 12, "letters": 26}


def quickkey_label(keys: str, index: int) -> str:
    """Name shown for the QuickKey of row `index` (0-based); "" if it has none."""
    if index >= QUICKKEY_COUNTS.get(keys, 0):
        return ""
    if keys == "numpad":
        return f"NumPad{index + 1}"
    if keys == "digits":
        return str(index + 1)
    if keys == "fkeys":
        return f"F{index + 1}"
    return chr(ord("A") + index)


def quickkey_index(keys: str, qt_key: int, keypad: bool) -> int:
    """Row index for a pressed key, or -1."""
    if keys in ("numpad", "digits") and Qt.Key_1 <= qt_key <= Qt.Key_9:
        if (keys == "numpad") != keypad:
            return -1
        return qt_key - Qt.Key_1
    if keys == "fkeys" and Qt.Key_F1 <= qt_key <= Qt.Key_F12:
        return qt_key - Qt.Key_F1
    if keys == "letters" and Qt.Key_A <= qt_key <= Qt.Key_Z:
        return qt_key - Qt.Key_A
    return -1


def key_matches(spec: str, e) -> bool:
    """Does a key event match a stored key name like "tab", "f3", "space", "ctrl+enter"?"""
    if not spec or spec.lower() in ("none", ""):
        return False
    from PySide6.QtGui import QKeySequence
    parts = [p for p in spec.lower().replace(" ", "").split("+") if p]
    names = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Meta", "enter": "Return",
             "esc": "Escape", "pgup": "PgUp", "pgdn": "PgDown", "del": "Del", "ins": "Ins"}
    text = "+".join(names.get(p, p.capitalize()) for p in parts)
    seq = QKeySequence(text)
    if seq.isEmpty():
        return False
    want = seq[0]
    mods = e.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier | Qt.MetaModifier)
    return want.key() == Qt.Key(e.key()) and want.keyboardModifiers() == mods


def natural_key(text: str):
    """Sort key that orders "item 2" before "item 10"."""
    import re
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", text or "")]


def _dim(color: str, factor: float = 0.55) -> str:
    c = QColor(color)
    if c.lightness() > 128:      # light colors get darker, dark text gets lighter
        c = c.darker(int(100 / factor))
    else:
        c = c.lighter(170)
    return c.name()


def has_rtl(text: str) -> bool:
    """True when the text contains Arabic or Hebrew letters."""
    return any("\u0590" <= ch <= "\u08ff" or "\ufb1d" <= ch <= "\ufefc" for ch in text or "")


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
        text = index.data(Qt.DisplayRole) or ""
        if option.direction == Qt.RightToLeft or has_rtl(text):
            p.save()
            try:
                self._paint_bidi(p, option, index, option.direction == Qt.RightToLeft)
            finally:
                p.restore()
            return
        p.save()
        r = option.rect
        kind = index.data(ROLE_KIND)
        colors = self.panel.popup.colors
        if option.state & QStyle.State_Selected and kind != "empty":
            p.fillRect(r, QColor(colors["selection"]))
        else:
            p.fillRect(r, QColor(colors["background"]))
        x = r.left() + 8
        if self.panel.popup.show_icons and kind in ("folder", "phrase", "special", "clip", "note"):
            name = {"folder": "folder", "phrase": "phrase", "clip": "clipboard_cache",
                    "note": "sticky_notes"}.get(kind)
            if kind == "special":
                name = {CLIPBOARD: "clipboard_cache", STICKY: "sticky_notes"}.get(index.data(ROLE_ID), "last_used")
            icon(name).paint(p, QRect(x, r.top() + (ROW_H - 16) // 2, 16, 16))
            x += 22
        font = QFont(self.panel.font())
        p.setFont(font)
        fm = QFontMetrics(font)
        right_text = index.data(ROLE_RIGHT) or ""
        qk = index.data(ROLE_QK) or ""
        if qk and not right_text:
            right_text = qk
        is_qk = bool(qk) and right_text == qk
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
        left = index.data(ROLE_LEFT) or ""
        if left:
            lw = min(fm.horizontalAdvance(left), avail // 2)
            p.setPen(QColor(colors["autotext"]))
            p.drawText(x, base_y, fm.elidedText(left, Qt.ElideRight, lw))
            x += lw + 10
            avail -= lw + 10
        cx = x
        bold = QFont(font)
        bold.setBold(True)
        for seg, hit in highlight_spans(text, query, self.panel.popup.match_case):
            f = bold if hit else font
            m = QFontMetrics(f)
            if cx + m.horizontalAdvance(seg) > x + avail:      # elide the tail
                seg = m.elidedText(seg, Qt.ElideRight, max(0, x + avail - cx))
            p.setFont(f)
            p.setPen(MATCH if hit else QColor(colors["description"]))
            p.drawText(cx, base_y, seg)
            cx += m.horizontalAdvance(seg)
            if cx >= x + avail:
                break
        p.setFont(font)
        if right_text:
            p.setPen(QColor(colors["quickkey" if is_qk else "autotext"]))
            rr = QRect(r.right() - right_w, r.top(), right_w - (18 if chevron else 6), r.height())
            p.drawText(rr, Qt.AlignVCenter | Qt.AlignRight, fm.elidedText(right_text, Qt.ElideMiddle, rr.width()))
        if chevron:
            p.setPen(QPen(QColor(colors["description"]), 1.3))
            cx, cy = r.right() - 10, r.center().y()
            p.setRenderHint(QPainter.Antialiasing)
            p.drawLine(cx - 3, cy - 4, cx + 1, cy)
            p.drawLine(cx + 1, cy, cx - 3, cy + 4)
        p.restore()

    def _paint_bidi(self, p: QPainter, option, index, rtl: bool):
        """Row painting for Arabic text and for the right-to-left layout.

        The description goes through QTextDocument so Arabic letters stay joined
        and in the right order even when the search match is highlighted. With
        rtl=True the whole row is mirrored: icon on the right, QuickKey/autotext
        and the folder chevron on the left."""
        r = option.rect
        kind = index.data(ROLE_KIND)
        colors = self.panel.popup.colors
        selected = option.state & QStyle.State_Selected and kind != "empty"
        p.fillRect(r, QColor(colors["selection" if selected else "background"]))
        font = QFont(self.panel.font())
        p.setFont(font)
        fm = QFontMetrics(font)

        def box(x, w):          # an LTR box (x from the row's left edge) mirrored when rtl
            return QRect(r.right() - x - w + 1, r.top(), w, r.height()) if rtl else QRect(r.left() + x, r.top(), w, r.height())

        x = 8
        if self.panel.popup.show_icons and kind in ("folder", "phrase", "special", "clip", "note"):
            name = {"folder": "folder", "phrase": "phrase", "clip": "clipboard_cache",
                    "note": "sticky_notes"}.get(kind)
            if kind == "special":
                name = {CLIPBOARD: "clipboard_cache", STICKY: "sticky_notes"}.get(index.data(ROLE_ID), "last_used")
            b = box(x, 16)
            icon(name).paint(p, QRect(b.left(), r.top() + (ROW_H - 16) // 2, 16, 16))
            x += 22
        right_text = index.data(ROLE_RIGHT) or ""
        qk = index.data(ROLE_QK) or ""
        if qk and not right_text:
            right_text = qk
        is_qk = bool(qk) and right_text == qk
        chevron = kind in ("folder", "special")
        right_w = 18 if chevron else 6
        if right_text:
            right_w += min(fm.horizontalAdvance(right_text) + 12, r.width() // 3)
        avail = r.width() - right_w - x
        text = index.data(Qt.DisplayRole) or ""
        start = Qt.AlignRight if rtl else Qt.AlignLeft
        end = Qt.AlignLeft if rtl else Qt.AlignRight
        if kind == "empty":
            p.setPen(QColor("#8a8a8a"))
            p.drawText(box(x, avail), Qt.AlignVCenter | start, text)
            return
        left = index.data(ROLE_LEFT) or ""
        if left:
            lw = min(fm.horizontalAdvance(left), avail // 2)
            p.setPen(QColor(colors["autotext"]))
            p.drawText(box(x, lw), Qt.AlignVCenter | start, fm.elidedText(left, Qt.ElideRight, lw))
            x += lw + 10
            avail -= lw + 10
        # description with highlighted matches
        from html import escape
        parts = []
        for seg, hit in highlight_spans(text, index.data(ROLE_QUERY) or "", self.panel.popup.match_case):
            seg = escape(seg)
            parts.append(f'<b style="color:{MATCH.name()}">{seg}</b>' if hit else seg)
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(font)
        opt = QTextOption()
        opt.setWrapMode(QTextOption.NoWrap)
        opt.setTextDirection(Qt.RightToLeft if (rtl or has_rtl(text)) else Qt.LeftToRight)
        doc.setDefaultTextOption(opt)
        doc.setDefaultStyleSheet(f"body {{ color: {QColor(colors['description']).name()}; }}")
        doc.setHtml(f"<body>{''.join(parts)}</body>")
        if doc.idealWidth() > avail:     # too long: plain elided text keeps the row tidy
            elided = fm.elidedText(text, Qt.ElideRight, max(0, avail))
            p.setPen(QColor(colors["description"]))
            p.drawText(box(x, avail), Qt.AlignVCenter | start, elided)
        else:
            w = int(doc.idealWidth()) + 1
            doc.setTextWidth(w)
            b = box(x, avail)
            left_x = b.right() - w + 1 if rtl else b.left()     # start side of the row
            top_y = r.top() + (r.height() - doc.size().height()) / 2
            p.translate(left_x, top_y)
            doc.drawContents(p, QRect(0, 0, w, r.height()))
            p.translate(-left_x, -top_y)
        if right_text:
            p.setPen(QColor(colors["quickkey" if is_qk else "autotext"]))
            inner = right_w - (18 if chevron else 6)
            rb = box(r.width() - right_w, inner)
            p.drawText(rb, Qt.AlignVCenter | end, fm.elidedText(right_text, Qt.ElideMiddle, inner))
        if chevron:
            p.setPen(QPen(QColor(colors["description"]), 1.3))
            cy = r.center().y()
            p.setRenderHint(QPainter.Antialiasing)
            if rtl:              # points left
                cx = r.left() + 10
                p.drawLine(cx + 3, cy - 4, cx - 1, cy)
                p.drawLine(cx - 1, cy, cx + 3, cy + 4)
            else:
                cx = r.right() - 10
                p.drawLine(cx - 3, cy - 4, cx + 1, cy)
                p.drawLine(cx + 1, cy, cx - 3, cy + 4)


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

    # drag the band to move the menu (PhraseExpress: "at a fixed position" then reopens there)
    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.window().pos()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):  # noqa: N802
        if getattr(self, "_drag", None) is not None and e.buttons() & Qt.LeftButton:
            self.window().move(e.globalPosition().toPoint() - self._drag)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):  # noqa: N802
        if getattr(self, "_drag", None) is not None:
            self._drag = None
            fn = getattr(self.window(), "remember_position", None)
            if callable(fn):
                fn()
        super().mouseReleaseEvent(e)

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
        self.setFont(QFont("Segoe UI", 9))
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
            self.apply_appearance()

    def apply_appearance(self) -> None:
        """Font and background from menu.appearance (see PhrasePopup._load_settings)."""
        pop = self.popup
        colors = getattr(pop, "colors", None)
        if not colors:
            return
        f = QFont("Segoe UI", 9)
        if getattr(pop, "menu_font", ""):
            f.fromString(pop.menu_font)
        self.setFont(f)
        self.footer.setFont(f)
        bg = colors["background"]
        # the app-wide style sheet sets a font on every widget ("* {font-family...}"),
        # which beats setFont(); repeat the menu font in this panel's own style sheet
        font_css = f'font-family:"{f.family()}"; font-size:{f.pointSizeF():g}pt;'
        self.setStyleSheet(f"#PopupPanel{{background:{bg};border:1px solid #8c8c8c}}"
                           f"#PopupPanel QListWidget, #PopupPanel QLabel{{{font_css}}}")
        self.list.setStyleSheet(f"QListWidget{{background:{bg};border:none;outline:0;{font_css}}}"
                                "QListWidget::item{border:none}")
        self.list.setFont(f)
        self.footer.setStyleSheet(f"color:{colors['description']};")

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
        elif self.popup.show_preview:
            tip = clip_text[:600] if kind in ("clip", "note") else self.popup.preview_text(kind, ident)
            if tip:
                it.setToolTip(tip)
        self.list.addItem(it)
        return it

    def assign_quickkeys(self) -> None:
        """Number the first rows with QuickKeys (menu.quickkey_keys)."""
        pop = self.popup
        n = 0
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(ROLE_KIND) == "empty":
                continue
            toks = content_tokens(pop.contents)
            label = quickkey_label(pop.quickkey_keys, n) if "quickkey" in toks else ""
            if label and pop.quickkey_modifier != "none":
                label = f"{pop.quickkey_modifier.capitalize()}+{label}"
            it.setData(ROLE_QK, label)
            is_phrase = it.data(ROLE_KIND) == "phrase"
            parts = dict(pop.phrase_parts(it.data(ROLE_ID))) if is_phrase else {}
            parts["quickkey"] = label
            i_desc = toks.index("description")
            before = [parts.get(t, "") for t in toks[:i_desc] if parts.get(t, "")]
            after = [parts.get(t, "") for t in toks[i_desc + 1:] if parts.get(t, "")]
            it.setData(ROLE_LEFT, "   ".join(before))
            if label in before:
                it.setData(ROLE_QK, "")          # drawn on the left instead
            if is_phrase:
                # a QuickKey alone on the right is drawn from ROLE_QK in its own colour
                it.setData(ROLE_RIGHT, "" if after == [label] else "   ".join(after))
            n += 1

    def quickkey_row(self, e) -> QListWidgetItem | None:
        """The row a QuickKey press selects, if the key and modifier match."""
        pop = self.popup
        mods = e.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier | Qt.MetaModifier)
        want = {"none": Qt.NoModifier, "ctrl": Qt.ControlModifier, "alt": Qt.AltModifier,
                "shift": Qt.ShiftModifier, "win": Qt.MetaModifier}.get(pop.quickkey_modifier, Qt.NoModifier)
        if mods != want:
            return None
        idx = quickkey_index(pop.quickkey_keys, e.key(), bool(e.modifiers() & Qt.KeypadModifier))
        if idx < 0:
            return None
        n = 0
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(ROLE_KIND) == "empty":
                continue
            if n == idx:
                return it
            n += 1
        return None

    def fill(self) -> None:
        """(Re)build the rows for this panel's folder."""
        self.list.clear()
        pop, st = self.popup, self.popup.store
        key = self.folder_key
        self.footer.setText("New phrase...")
        self._set_footer(True)
        if key == CLIPBOARD:
            entries = st.clipboard_entries(limit=max(1, pop.clipboard_max))
            for e in entries:
                one = " ".join(e.text.split())
                self.add_row("clip", e.id, one[:200], clip_text=e.text)
            if not entries:
                self.add_row("empty", None, "(empty)")
            self.footer.setText("Clear clipboard cache")
            self._set_footer(bool(entries))
        elif key == STICKY:
            notes = pop.sticky_notes()
            for n in notes[:STICKY_MAX]:
                self.add_row("note", n.id, n.title, clip_text=n.text)
            if not notes:
                self.add_row("empty", None, "(no notes)")
            self.footer.setText("Open Sticky Notes")
            self._set_footer(True)
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
        self.assign_quickkeys()
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
        strip = getattr(self, "lang_strip", None)
        if strip is not None and not strip.isHidden():
            chrome += strip.sizeHint().height()
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
        elif kind in ("clip", "note"):
            self.popup.choose_clip(it.data(ROLE_TEXT))

    def _footer_clicked(self) -> None:
        if self.folder_key == CLIPBOARD:
            self.popup.store.clear_clipboard(keep_pinned=True)
            self.fill()
            return
        if self.folder_key == STICKY:
            self.popup.hide_all(force=True)
            try:
                from phraseforge import stickynotes
                stickynotes.open_app()
            except Exception:
                pass
            return
        self.popup.request_new_phrase(self.folder_key if isinstance(self.folder_key, int) else None)

    def handle_key(self, e) -> bool:
        k = e.key()
        cur = self.list.currentItem()
        pop = self.popup
        if k in (Qt.Key_Return, Qt.Key_Enter) or key_matches(pop.confirm_hotkey, e):
            self._activate(cur)
            return True
        if key_matches(pop.search_hotkey, e):
            pop.start_search("")
            return True
        qk = self.quickkey_row(e)
        if qk is not None:
            self.list.setCurrentItem(qk)
            self._activate(qk)
            return True
        if k in (Qt.Key_Left, Qt.Key_Right) and pop.language_key_matches(e):
            pop.cycle_language(1 if k == Qt.Key_Right else -1)   # PhraseExpress "Language selection"
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
            if self.depth == 0 and not self.popup.quick_jump:
                self.popup.start_search(text)       # Quick Jump off: typing searches
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
        self.max_items = 30          # visible rows before the menu scrolls
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
        # language buttons (Settings > Phrase Menu > Show phrase language buttons)
        self.language = ""
        self.lang_strip = QWidget(self)
        self.lang_strip.setStyleSheet("background:#f3f3f3")
        self._lang_lay = QHBoxLayout(self.lang_strip)
        self._lang_lay.setContentsMargins(4, 2, 4, 2)
        self._lang_lay.setSpacing(2)
        self.lang_buttons: list[QToolButton] = []
        self.outer.insertWidget(1, self.lang_strip)
        self.lang_strip.setVisible(False)
        self.apply_appearance()

    # -------------------------------------------- language versions
    def _build_language_strip(self) -> None:
        for b in self.lang_buttons:
            b.setParent(None)
            b.deleteLater()
        self.lang_buttons = []
        langs = self.languages
        show = bool(langs) and self.show_language_buttons
        self.lang_strip.setVisible(show)
        if not langs:
            self.language = ""
            return
        if self.language and self.language not in langs:
            self.language = ""
        for code in [""] + langs:
            b = QToolButton(self.lang_strip)
            b.setText(code or "Default")
            b.setToolTip(f"Insert the {code} version" if code else "Insert the default version")
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.setChecked(code == self.language)
            b.setStyleSheet("QToolButton{padding:1px 6px;border:1px solid transparent}"
                            "QToolButton:checked{background:#dbe8f7;border:1px solid #7da2ce}")
            b.clicked.connect(lambda _=False, c=code: self.set_language(c))
            self._lang_lay.addWidget(b)
            self.lang_buttons.append(b)
        self._lang_lay.addStretch(1)

    def set_language(self, code: str) -> None:
        """Language version inserted from this menu ("" = default text)."""
        self.language = code if code in self.languages else ""
        for b in self.lang_buttons:
            b.setChecked((b.text() if b.text() != "Default" else "") == self.language)
        for panel in [self] + self.subs:
            for i in range(panel.list.count()):
                it = panel.list.item(i)
                if it.data(ROLE_KIND) == "phrase" and self.show_preview:
                    tip = self.preview_text("phrase", it.data(ROLE_ID))
                    it.setToolTip(tip or "")

    def cycle_language(self, step: int) -> None:
        order = [""] + self.languages
        if len(order) < 2:
            return
        i = order.index(self.language) if self.language in order else 0
        self.set_language(order[(i + step) % len(order)])

    def language_key_matches(self, e) -> bool:
        want = {"ctrl": Qt.ControlModifier, "alt": Qt.AltModifier, "shift": Qt.ShiftModifier,
                "win": Qt.MetaModifier}.get(self.language_modifier)
        if want is None or not self.languages:
            return False
        mods = e.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier | Qt.MetaModifier)
        return mods == want

    # -------------------------------------------- settings / data
    def _load_settings(self) -> None:
        import json
        st = self.store
        on = lambda key: _setting(st, key) == "1"   # noqa: E731
        self.show_icons = True
        self.menu_width = max(200, _int_setting(st, "menu.width", 350))
        self.position = _setting(st, "menu.position")
        self.position_fallback = _setting(st, "menu.position_fallback")
        self.contents = _setting(st, "menu.contents")
        self.sort_enabled = on("menu.sort_enabled")
        self.sort_by = _setting(st, "menu.sort_by")
        self.sort_method = _setting(st, "menu.sort_method")
        self.sort_order = _setting(st, "menu.sort_order")
        self.show_preview = on("menu.show_preview")
        self.hide_restricted = on("menu.hide_restricted")
        try:
            self.languages = list(st.phrase_languages())
        except Exception:
            self.languages = []
        self.show_language_buttons = _setting(st, "menu.language_buttons", "1") == "1"
        self.language_modifier = _setting(st, "menu.language_modifier", "ctrl")
        if hasattr(self, "lang_strip"):
            self._build_language_strip()
        self.confirm_hotkey = _setting(st, "menu.confirm_hotkey")
        self.quickkey_modifier = _setting(st, "menu.quickkey_modifier")
        self.quickkey_keys = _setting(st, "menu.quickkey_keys")
        self.search_hotkey = _setting(st, "menu.search_hotkey")
        self.search_descriptions = on("quicksearch.descriptions")
        self.match_case = on("quicksearch.match_case")
        self.search_subfolders = on("quicksearch.subfolders")
        self.quick_jump = on("quicksearch.quick_jump")
        self.show_clipboard = on("clipboard_history.enabled")
        self.clipboard_max = max(1, _int_setting(st, "clipboard_history.max", 200))
        self.show_last_used = on("features.last_used_folder")
        self.last_used_max = max(1, _int_setting(st, "last_used.max", 20))
        self.show_sticky = on("stickynotes.show_folder") and _sticky_available()
        self._notes_cache: list | None = None          # read lazily, once per menu opening
        try:
            app = json.loads(_setting(st, "menu.appearance") or "{}")
            app = app if isinstance(app, dict) else {}
        except ValueError:
            app = {}
        colors = {"background": "#ffffff", "description": "#1f1f1f", "autotext": "#7a7a7a",
                  "hotkey": "#7a7a7a", "quickkey": "#7a7a7a", "selection": SELECT.name()}
        colors.update({k: v for k, v in app.items() if k in colors and QColor(v).isValid()})
        if on("menu.dim_dark") and self._dark_mode():
            colors = {k: _dim(v) for k, v in colors.items()}
        self.colors = colors
        self.menu_font = app.get("font", "") if isinstance(app.get("font", ""), str) else ""

    def _dark_mode(self) -> bool:
        theme = _setting(self.store, "ui.theme", "system")
        if theme == "dark":
            return True
        if theme == "light":
            return False
        try:
            return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        except Exception:
            return False

    def preview_text(self, kind: str, ident) -> str:
        if kind != "phrase":
            return ""
        p = self.store.get_phrase(ident)
        if not p:
            return ""
        text, fmt = self.store.phrase_text(p, getattr(self, "language", "")) \
            if hasattr(self.store, "phrase_text") else (p.content, p.content_format)
        if fmt == "html":
            from PySide6.QtGui import QTextDocument
            d = QTextDocument()
            d.setHtml(text)
            text = d.toPlainText()
        return text[:600] + ("..." if len(text) > 600 else "")

    def _app_ok(self, p) -> bool:
        return not self.hide_restricted or self.store.phrase_allowed_in_app(p.id, self.app_exe)

    def _allowed(self, p) -> bool:
        if not p.enabled:
            return False
        if p.folder_id is not None:
            chain = self.store.folder_chain(p.folder_id)
            if any(not f.enabled or not f.show_in_popup for f in chain):
                return False
        return self._app_ok(p)

    def _folder_visible(self, f) -> bool:
        if not (f.enabled and f.show_in_popup):
            return False
        if self.app_exe and self.hide_restricted:
            exe = self.app_exe.lower()
            inc = [a.strip().lower() for a in (f.apps_include or "").split(",") if a.strip()]
            exc = [a.strip().lower() for a in (f.apps_exclude or "").split(",") if a.strip()]
            if exe in exc or (inc and exe not in inc):
                return False
        return True

    def right_text(self, p) -> str:
        """Grey autotext/hotkey text of a phrase, per menu.contents (also cached for the
        column layout done in assign_quickkeys)."""
        toks = content_tokens(self.contents)
        abbr = ", ".join(t.value for t in p.autotexts()) if "autotext" in toks else ""
        hot = ", ".join(t.value.upper().replace("+", "-") for t in p.hotkeys()) if "hotkey" in toks else ""
        parts = {"autotext": f"[{abbr}]" if abbr else "", "hotkey": f"({hot})" if hot else ""}
        if not hasattr(self, "_parts"):
            self._parts = {}
        self._parts[p.id] = parts
        after = toks[toks.index("description") + 1:]
        return "   ".join(parts[t] for t in after if t in parts and parts[t])

    def phrase_parts(self, phrase_id) -> dict:
        return getattr(self, "_parts", {}).get(phrase_id, {})

    def _sorted_phrases(self, phrases):
        """Order phrases per menu.sort_*; with sorting off keep the user's manual order."""
        phrases = list(phrases)
        if not self.sort_enabled:
            return sorted(phrases, key=lambda p: (p.sort, p.id or 0))

        def field(p):
            if self.sort_by == "autotext":
                return next((t.value for t in p.autotexts()), "")
            if self.sort_by == "usage":
                return p.use_count
            if self.sort_by == "last_used":
                return p.last_used or ""
            if self.sort_by == "created":
                return p.created or ""
            return p.description

        def key(p):
            v = field(p)
            if isinstance(v, int):
                return (v, natural_key(p.description))
            if self.sort_method == "length":
                return (len(v or ""), (v or "").lower())
            return natural_key(v) if self.sort_method == "numeric" else (v or "").lower()
        return sorted(phrases, key=key, reverse=self.sort_order == "desc")

    def folder_entries(self, folder_id) -> list[tuple[str, object, str, str]]:
        """[(kind, id, text, right)] for a folder: folders (incl. specials at root), then phrases."""
        folders = [("folder", f.id, f.name, "") for f in self.store.folders(folder_id) if self._folder_visible(f)]
        if folder_id is None:
            if self.show_clipboard:
                folders.append(("special", CLIPBOARD, tr("Clipboard Cache"), ""))
            if self.show_last_used:
                folders.append(("special", LAST_USED, tr("Last Used"), ""))
            if self.show_sticky:
                folders.append(("special", STICKY, tr("Sticky Notes"), ""))
        folders.sort(key=lambda r: r[2].lower())
        phrases = [p for p in self.store.phrases(folder_id) if self._allowed(p)]
        rows = [("phrase", p.id, p.description, self.right_text(p)) for p in self._sorted_phrases(phrases)]
        return folders + rows

    def sticky_notes(self) -> list:
        """Sticky notes (read lazily; read_notes itself is cached by file time)."""
        if not self.show_sticky:
            return []
        if self._notes_cache is None:
            self._notes_cache = list(_sticky_notes())
        return self._notes_cache

    def last_used_phrases(self, limit: int | None = None):
        used = [p for p in self.store.phrases() if p.last_used and self._allowed(p)]
        return sorted(used, key=lambda p: p.last_used, reverse=True)[:limit or self.last_used_max]

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
            # "Search within descriptions": descriptions + abbreviations; unchecked: phrase text too
            fields = [p.description] + [t.value for t in p.autotexts()]
            if not self.search_descriptions:
                fields.append(p.content)
            if any(hit(x) for x in fields) and self._allowed(p):
                rows.append(("phrase", p.id, p.description,
                             self._folder_path(p.folder_id) if p.folder_id else ""))
        self._note_text = {}
        for n in self.sticky_notes():
            if hit(n.title) or (not self.search_descriptions and hit(n.text)):
                self._note_text[n.id] = n.text
                rows.append(("note", n.id, n.title, "Sticky Notes"))
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
        notes = getattr(self, "_note_text", {})
        for kind, ident, text, right in rows:
            self.add_row(kind, ident, text, right=right, query=q,
                         clip_text=notes.get(ident, "") if kind == "note" else "")
        if not rows:
            self.add_row("empty", None, "No matching phrases")
        self.assign_quickkeys()
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
    def placement(self, x: int, y: int, caret: tuple[int, int] | None) -> tuple[str, int, int]:
        """Where to show the menu: ("caret"|"mouse"|"center", x, y) per menu.position/_fallback.
        `caret` is the caret position if known (None = no caret); x, y are used if the
        caller already resolved a point and no caret lookup is possible."""
        mode = self.position
        if mode in ("caret", "below", "above"):
            if caret is not None:
                return mode, caret[0], caret[1]
            mode = self.position_fallback
        if mode == "fixed" and not self.fixed_pos():
            mode = "mouse"
        if mode in ("mouse", "window", "monitor", "center"):
            c = QCursor.pos()
            return mode, c.x(), c.y()
        if mode in ("tray", "primary", "fixed"):
            return mode, x, y
        return "caret", x, y

    def fixed_pos(self):
        """(x, y) saved by dragging the title band (menu.fixed_pos), or None."""
        try:
            a, b = (int(v) for v in _setting(self.store, "menu.fixed_pos", "").split(","))
            return a, b
        except Exception:
            return None

    def remember_position(self) -> None:
        """Called after the band was dragged: "at a fixed position" reopens the menu here."""
        try:
            self.store.set_setting("menu.fixed_pos", f"{self.x()},{self.y()}")
        except Exception:
            pass

    def popup_origin(self, mode: str, x: int, y: int, w: int, h: int) -> tuple[int, int]:
        """Top-left corner for the menu for each PhraseExpress position choice."""
        if mode == "primary":
            g = QGuiApplication.primaryScreen().availableGeometry()
            return g.center().x() - w // 2, g.center().y() - h // 2
        scr = QGuiApplication.screenAt(QPoint(x, y)) or QGuiApplication.primaryScreen()
        g = scr.availableGeometry()
        if mode == "tray":
            g = QGuiApplication.primaryScreen().availableGeometry()
            return g.right() - w - 8, g.bottom() - h - 8
        if mode == "fixed":
            fx, fy = self.fixed_pos() or (x, y)
            return min(max(g.left(), fx), g.right() - w), min(max(g.top(), fy), g.bottom() - h)
        if mode == "window":
            rect = None
            try:
                from phraseforge.platform import windows
                rect = windows.foreground_rect()
            except Exception:
                rect = None
            if rect:
                l, t, r, b = rect
                return (l + r) // 2 - w // 2, (t + b) // 2 - h // 2
            mode = "monitor"
        if mode in ("monitor", "center"):
            return g.center().x() - w // 2, g.center().y() - h // 2
        px = min(max(g.left(), x), g.right() - w)
        if mode == "above":
            return px, max(g.top(), y - h - 24)
        if mode == "below":
            return px, min(y + 20, g.bottom() - h)
        return px, (y + 4 if y + 4 + h <= g.bottom() else max(g.top(), y - h - 24))

    @staticmethod
    def _caret() -> tuple[int, int] | None:
        try:
            from phraseforge.platform import windows
            return windows.caret_position()
        except Exception:
            return None

    def set_root_folder(self, folder=None) -> None:
        """Make the root panel show one folder (folder id, numeric str, "last_used" or
        "clipboard_cache") instead of the top level; None restores the normal menu."""
        key, title = None, ""
        if folder == "clipboard_cache":
            folder = CLIPBOARD
        if folder in (LAST_USED, CLIPBOARD, STICKY):
            key = folder
            title = tr({LAST_USED: "Last Used", CLIPBOARD: "Clipboard Cache", STICKY: "Sticky Notes"}[folder])
        elif folder is not None and str(folder).strip().lstrip("-").isdigit():
            f = self.store.get_folder(int(folder))
            if f is not None:
                key, title = f.id, f.name
        self.folder_key = key
        self.band.wordmark = key is None
        self.band.title = title
        self.band.update()

    def show_at(self, x: int, y: int, app_exe: str = "", search: bool = False,
                caret: tuple[int, int] | None | bool = True, folder=None) -> None:
        """Show the menu. caret=True looks the caret up; pass a (x, y) or None to skip the lookup.
        search=True opens straight into quick search. folder (id or "last_used" /
        "clipboard_cache") opens the menu on that folder's contents (folder triggers)."""
        self.app_exe = app_exe or ""
        self.set_root_folder(folder)
        self._load_settings()
        self.apply_appearance()
        self.close_from(1)
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.refresh()
        caret_pos = self._caret() if caret is True else caret
        mode, x, y = self.placement(x, y, caret_pos)
        px, py = self.popup_origin(mode, x, y, self.width(), self.sizeHint().height())
        self.move(px, py)
        self.show()
        self.raise_()
        self.activateWindow()
        self.list.setFocus()
        self._play_sound()
        if search:
            self.start_search("")

    def _play_sound(self) -> None:
        """sound.popup_display.*: phraseforge.sounds.play_event(event, store) checks the
        enabled flag and file itself (module owned by the runtime layer)."""
        try:
            from phraseforge import sounds
            sounds.play_event("popup_display", self.store)
        except Exception:
            pass

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
        if not hasattr(self, "search"):          # events during construction
            return False
        if obj is self.search and e.type() == QEvent.KeyPress:
            k = e.key()
            if k in (Qt.Key_Down, Qt.Key_Up, Qt.Key_PageDown, Qt.Key_PageUp):
                self.list.keyPressEvent(e)
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter) or key_matches(self.confirm_hotkey, e):
                self._activate(self.list.currentItem())
                return True
            qk = self.quickkey_row(e) if self.quickkey_modifier != "none" or \
                self.quickkey_keys in ("numpad", "fkeys") else None
            if qk is not None:           # unmodified digits/letters are search text here
                self.list.setCurrentItem(qk)
                self._activate(qk)
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
        return super().eventFilter(obj, e)
