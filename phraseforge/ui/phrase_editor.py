"""Right-hand editor panel, modelled on PhraseExpress (reference/phraseexpress 01, 07, 09, 21).

- ChipTextEdit: phrase content editor that shows each {#macro} as a boxed chip
  (a QTextObject holding the exact macro text) and serialises back to the exact
  original text with content().
- PhraseEditor: Description (+ tag button), Phrase content, Trigger rows,
  Output target. Saves itself when you leave a field or switch phrases.
- FolderEditor: Description, Trigger rows, Notes.
- SpecialFolderEditor: "last_used" and "clipboard_cache" pseudo folders.
"""
from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QObject, QRectF, QSizeF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction, QColor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPen, QPyTextObject,
    QTextCharFormat, QTextCursor, QTextDocument, QTextFormat, QTextOption,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTabBar, QTextEdit, QToolButton, QVBoxLayout, QWidget,
)

from phraseforge.models import Phrase, TriggerKind
from phraseforge.ui.iconset import icon
from phraseforge.ui.pe_style import caption
from phraseforge.ui.trigger_editor import (
    AddTagDialog, TriggerList, default_row, rows_for_triggers,
)

from PySide6.QtCore import QLocale

LATIN_DIGITS = QLocale(QLocale.English, QLocale.UnitedStates)   # numbers as 0-9 like PhraseExpress
CHIP_TYPE = QTextFormat.UserObject + 1
TOKEN_PROP = QTextFormat.UserProperty + 1
OBJ = "￼"

OUTPUT_TARGETS = [("current", "Current application"), ("program", "Specific program"),
                  ("clipboard", "Clipboard"), ("textfile", "Text file"), ("email", "E-mail"),
                  ("onenote", "OneNote")]

# Friendly chip labels (PhraseExpress shows macro names, not parameters).
DISPLAY = {
    "date": "Date/Time", "time": "Date/Time", "datetime": "Date/Time", "timestamp": "Date/Time",
    "datecalc": "Date Calculation", "timecalc": "Time Calculation", "datepick": "Calendar",
    "cursor": "Set cursor position", "clipboard": "Clipboard", "clipboardhistory": "Clipboard history",
    "setclipboard": "Put text into clipboard", "selection": "Selected text", "insert": "Insert phrase",
    "input": "Manual text input", "inputmemo": "Manual text input", "form": "Form", "endform": "End of form",
    "key": "Keypress", "keys": "Keypress", "sleep": "Wait", "run": "Run program", "open": "Open file",
    "mail": "Create email", "if": "If", "else": "Else", "elseif": "Else if", "endif": "End if",
    "loop": "Macro loop", "endloop": "End loop", "foreach": "For each", "endforeach": "End for each",
    "set": "Set variable", "var": "Output variable", "calc": "Calculation", "random": "Random number",
    "randomtext": "Random text", "upper": "Convert to UPPER CASE", "lower": "Convert to lower case",
    "trim": "Trim", "replace": "Replace text", "regexget": "Extract substring with RegEx",
    "substr": "Substring", "length": "Text length", "textfile": "External document", "xls": "MS Excel cells",
    "xml": "XML file XPATH content", "sql": "Database query", "http": "Open web page", "env": "Environment variable",
    "ai": "AI text processing", "translate": "Translate text", "ocr": "Screen OCR", "ocrfile": "Image OCR",
    "message": "Message box", "waitfor": "Set application focus", "separator": "Separator",
    "ask": "Form input", "askchoice": "Drop down", "askcheck": "Check box", "askdate": "Calendar",
    "onenote": "OneNote page",
}
KEY_NAMES = {"enter", "tab", "esc", "bksp", "del", "up", "down", "left", "right", "home", "end",
             "pgup", "pgdn", "ins"} | {f"f{i}" for i in range(1, 13)}


# ---------------------------------------------------------------- tokens
def split_tokens(text: str) -> list[tuple[bool, str]]:
    """Split content into (is_macro, text) parts. Nested braces stay inside one token;
    '{{' is a literal brace and never starts a macro."""
    parts: list[tuple[bool, str]] = []
    buf: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text.startswith("{{", i):
            buf.append("{{"); i += 2; continue
        if text.startswith("{#", i):
            depth, j, quote = 0, i, None
            while j < n:
                c = text[j]
                if quote:
                    if c == "\\" and j + 1 < n:
                        j += 2; continue
                    if c == quote:
                        quote = None
                elif c == '"':
                    quote = c
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            if j < n:  # complete token
                if buf:
                    parts.append((False, "".join(buf))); buf = []
                parts.append((True, text[i:j + 1]))
                i = j + 1
                continue
        buf.append(text[i]); i += 1
    if buf:
        parts.append((False, "".join(buf)))
    return parts


def macro_name(token: str) -> str:
    m = re.match(r"\{#\s*([A-Za-z_][\w]*)", token)
    return m.group(1).lower() if m else ""


def display_name(token: str) -> str:
    try:
        from phraseforge.ui import macro_ui
        fn = getattr(macro_ui, "display_name", None)
        if fn:
            label = fn(token)
            if label:
                return label
    except Exception:
        pass
    name = macro_name(token)
    if name in KEY_NAMES:
        return name.capitalize() if len(name) > 3 else name.upper()
    return DISPLAY.get(name) or (name.capitalize() if name else token)


def chip_colors(token: str) -> tuple[QColor, QColor]:
    """(background, border) by macro family, similar to PhraseExpress's colouring."""
    name = macro_name(token)
    if name in ("date", "time", "datetime", "timestamp", "datecalc", "timecalc", "datepick"):
        return QColor("#f9d7d3"), QColor("#7a2a20")
    if name in ("cursor", "key", "keys", "sleep", "mouse") or name in KEY_NAMES:
        return QColor("#dbe8f7"), QColor("#1f3f66")
    if name.startswith("form") or name.startswith("ask") or name in ("input", "inputmemo", "choose"):
        return QColor("#e2f0d9"), QColor("#2d5a1e")
    return QColor("#fde6c4"), QColor("#6b3d00")


class ChipObject(QPyTextObject):
    """Draws a macro chip; the document stores one U+FFFC per chip."""

    def __init__(self, editor: "ChipTextEdit"):
        super().__init__(editor)
        self.editor = editor

    def _label(self, fmt) -> str:
        token = fmt.property(TOKEN_PROP) or ""
        return token if self.editor.show_macro_params else display_name(token)

    def intrinsicSize(self, doc, pos, fmt):
        fmt = fmt.toCharFormat()
        fm = QFontMetricsF(QFont(fmt.font()))
        w = fm.horizontalAdvance(self._label(fmt)) + 6
        return QSizeF(w, fm.height() + 2)

    def drawObject(self, painter: QPainter, rect: QRectF, doc, pos, fmt):
        fmt = fmt.toCharFormat()
        token = fmt.property(TOKEN_PROP) or ""
        bg, border = chip_colors(token)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)
        r = rect.adjusted(0.5, 0.5, -0.5, -0.5)
        painter.fillRect(r, bg)
        painter.setPen(QPen(border, 1))
        painter.drawRect(r)
        painter.setFont(fmt.font())
        painter.setPen(QColor("#1a1a1a"))
        painter.drawText(r.adjusted(3, 0, -2, 0), Qt.AlignVCenter | Qt.AlignLeft, self._label(fmt))
        painter.restore()


def first_strong_rtl(text: str) -> bool:
    """True when the first letter with a direction is Arabic/Hebrew (Unicode bidi rule)."""
    import unicodedata
    for ch in text or "":
        d = unicodedata.bidirectional(ch)
        if d in ("R", "AL"):
            return True
        if d == "L":
            return False
    return False


class ChipTextEdit(QTextEdit):
    focus_changed = Signal(bool)
    chip_activated = Signal(int)          # document position of a double-clicked chip
    view_option_toggled = Signal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ContentEditor")
        self.show_macro_params = False
        self.rich = False
        self._chip = ChipObject(self)
        self.document().documentLayout().registerHandler(CHIP_TYPE, self._chip)
        self.setAcceptRichText(False)
        self.setTabChangesFocus(False)
        self.document().setDocumentMargin(6)
        self.context_menu_hook = None   # callable(QMenu, chip_pos|None) set by PhraseEditor
        # Arabic/Hebrew: each paragraph takes its direction from its first strong letter
        opt = self.document().defaultTextOption()
        opt.setTextDirection(Qt.LayoutDirectionAuto)
        self.document().setDefaultTextOption(opt)

    # -------------------------------------------------- right-to-left writing
    def set_paragraph_direction(self, rtl: bool) -> None:
        """Make the selected paragraphs right-to-left (Arabic) or left-to-right, like
        Windows' Ctrl+Right Shift / Ctrl+Left Shift. Kept in rich (HTML) phrases."""
        c = self.textCursor()
        fmt = c.blockFormat()
        fmt.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
        fmt.setAlignment((Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignAbsolute)
        c.mergeBlockFormat(fmt)
        self.setTextCursor(c)

    def paragraph_is_rtl(self) -> bool:
        b = self.textCursor().block()
        d = b.blockFormat().layoutDirection()
        if d == Qt.LayoutDirectionAuto:
            return first_strong_rtl(b.text())
        return d == Qt.RightToLeft

    def keyPressEvent(self, e):  # noqa: N802
        self._shift_side = 0
        if e.key() == Qt.Key_Shift and e.modifiers() & Qt.ControlModifier:
            # scan codes: 0x36 right Shift, 0x2A left Shift (Windows)
            sc = e.nativeScanCode()
            self._shift_side = 1 if sc == 0x36 else -1 if sc == 0x2A else 0
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):  # noqa: N802
        if e.key() == Qt.Key_Shift and getattr(self, "_shift_side", 0) and e.modifiers() & Qt.ControlModifier:
            self.set_paragraph_direction(self._shift_side > 0)
            self._shift_side = 0
        super().keyReleaseEvent(e)

    # -------------------------------------------------- content in/out
    def chip_format(self, token: str, base: QTextCharFormat | None = None) -> QTextCharFormat:
        fmt = QTextCharFormat(base) if base is not None else QTextCharFormat()
        fmt.setObjectType(CHIP_TYPE)
        fmt.setVerticalAlignment(QTextCharFormat.AlignBottom)   # sit on the text line, not above it
        fmt.setProperty(TOKEN_PROP, token)
        return fmt

    def insert_content(self, text: str, cursor: QTextCursor | None = None) -> None:
        c = cursor or self.textCursor()
        base = c.charFormat()
        base.setObjectType(0)
        base.clearProperty(TOKEN_PROP)
        for is_macro, part in split_tokens(text):
            if is_macro:
                c.insertText(OBJ, self.chip_format(part, base))
            else:
                c.insertText(part, base)
        if cursor is None:
            self.setTextCursor(c)

    def set_content(self, text: str, html: bool = False) -> None:
        self.rich = html
        self.setAcceptRichText(html)
        doc = self.document()
        doc.blockSignals(True)
        try:
            if html:
                doc.setHtml(text or "")
                self._chipify_document()
            else:
                doc.setPlainText("")
                self.insert_content(text or "", QTextCursor(doc))
        finally:
            doc.blockSignals(False)
        doc.setModified(False)
        self.moveCursor(QTextCursor.Start)
        self.viewport().update()

    def _chipify_document(self) -> None:
        """Replace macro text inside a rich document with chips (end to start)."""
        doc = self.document()
        plain = doc.toPlainText()
        spans, pos = [], 0
        for is_macro, part in split_tokens(plain):
            if is_macro:
                spans.append((pos, part))
            pos += len(part)
        for start, token in reversed(spans):
            c = QTextCursor(doc)
            c.setPosition(start)
            c.setPosition(start + len(token), QTextCursor.KeepAnchor)
            base = c.charFormat()
            c.insertText(OBJ, self.chip_format(token, base))

    def content(self) -> str:
        """Exact phrase text: chips become their macro text again."""
        if self.rich:
            clone = self.document().clone()
            for pos, token in reversed(self._chip_positions(clone)):
                c = QTextCursor(clone)
                c.setPosition(pos)
                c.setPosition(pos + 1, QTextCursor.KeepAnchor)
                fmt = c.charFormat()
                fmt.setObjectType(0)
                fmt.clearProperty(TOKEN_PROP)
                c.insertText(token, fmt)
            return clone.toHtml()
        out: list[str] = []
        block = self.document().begin()
        first = True
        while block.isValid():
            if not first:
                out.append("\n")
            first = False
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                fmt = frag.charFormat()
                if fmt.objectType() == CHIP_TYPE:
                    out.append((fmt.property(TOKEN_PROP) or "") * frag.text().count(OBJ))
                else:
                    out.append(frag.text().replace(" ", "\n"))
                it += 1
            block = block.next()
        return "".join(out)

    @staticmethod
    def _chip_positions(doc: QTextDocument) -> list[tuple[int, str]]:
        res = []
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                fmt = frag.charFormat()
                if fmt.objectType() == CHIP_TYPE:
                    for k in range(len(frag.text())):
                        res.append((frag.position() + k, fmt.property(TOKEN_PROP) or ""))
                it += 1
            block = block.next()
        return res

    def plain_preview_text(self) -> str:
        """Text with chips shown by label (for word/char counts)."""
        return self.content() if not self.rich else self.document().toPlainText().replace(OBJ, " ")

    # -------------------------------------------------- chips under the mouse/cursor
    def chip_at(self, pos: int) -> tuple[int, str] | None:
        for p in (pos, pos - 1):
            if p < 0:
                continue
            c = QTextCursor(self.document())
            c.setPosition(p)
            c.setPosition(p + 1, QTextCursor.KeepAnchor)
            fmt = c.charFormat()
            if fmt.objectType() == CHIP_TYPE and c.selectedText() == OBJ:
                return p, fmt.property(TOKEN_PROP) or ""
        return None

    def replace_chip(self, pos: int, new_text: str) -> None:
        c = QTextCursor(self.document())
        c.setPosition(pos)
        c.setPosition(pos + 1, QTextCursor.KeepAnchor)
        c.removeSelectedText()
        self.insert_content(new_text, c)

    def mouseDoubleClickEvent(self, e):
        c = self.cursorForPosition(e.position().toPoint())
        hit = self.chip_at(c.position())
        if hit:
            self.chip_activated.emit(hit[0])
            return
        super().mouseDoubleClickEvent(e)

    # -------------------------------------------------- clipboard: keep macros as text
    def createMimeDataFromSelection(self):
        from PySide6.QtCore import QMimeData
        c = self.textCursor()
        md = QMimeData()   # Qt's own mime data recomputes text lazily and would drop the macros
        md.setText(self.content_range(c.selectionStart(), c.selectionEnd()))  # macros copy as exact text
        if self.rich:
            md.setHtml(super().createMimeDataFromSelection().html())
        return md

    def content_range(self, start: int, end: int) -> str:
        """Plain text between two document positions with chips expanded."""
        out: list[str] = []
        block = self.document().findBlock(start)
        while block.isValid() and block.position() <= end:
            if block.position() > start:
                out.append("\n")
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                a, b = max(start, frag.position()), min(end, frag.position() + frag.length())
                if a < b:
                    fmt = frag.charFormat()
                    if fmt.objectType() == CHIP_TYPE:
                        out.append((fmt.property(TOKEN_PROP) or "") * (b - a))
                    else:
                        out.append(frag.text()[a - frag.position():b - frag.position()])
                it += 1
            block = block.next()
        return "".join(out)

    def insertFromMimeData(self, source):
        if source.hasText() and not (self.rich and source.hasHtml()):
            self.insert_content(source.text())
        else:
            super().insertFromMimeData(source)

    # -------------------------------------------------- misc
    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.focus_changed.emit(True)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.focus_changed.emit(False)

    def contextMenuEvent(self, e):
        c = self.cursorForPosition(e.pos())
        hit = self.chip_at(c.position())
        m = QMenu(self)
        if self.context_menu_hook:
            self.context_menu_hook(m, hit)
        else:
            m = self.createStandardContextMenu()
        m.exec(e.globalPos())


def _serialise_plain(doc: QTextDocument) -> str:
    out, block, first = [], doc.begin(), True
    while block.isValid():
        if not first:
            out.append("\n")
        first = False
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            fmt = frag.charFormat()
            if fmt.objectType() == CHIP_TYPE:
                out.append((fmt.property(TOKEN_PROP) or "") * frag.text().count(OBJ))
            else:
                out.append(frag.text())
            it += 1
        block = block.next()
    return "".join(out)


class Ruler(QWidget):
    """Thin horizontal ruler shown above the editor (View > Show rulers)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(16)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#f7f7f7"))
        p.setPen(QColor("#9a9a9a"))
        step = 10
        for i, x in enumerate(range(6, self.width(), step)):
            h = 8 if i % 10 == 0 else (5 if i % 5 == 0 else 3)
            p.drawLine(x, self.height() - 1, x, self.height() - 1 - h)
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)


class _FocusOutSaver(QObject):
    """Event filter: save when a field loses focus."""

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.FocusOut:
            QTimer.singleShot(0, self.callback)
        return False


def _output_combo() -> QComboBox:
    c = QComboBox()
    for k, label in OUTPUT_TARGETS:
        c.addItem(label, k)
    c.setFixedWidth(144)
    return c


OUTPUT_ARG_HINTS = {"program": "program (e.g. notepad.exe) or window title",
                    "textfile": r"file path, e.g. C:\Notes\log.txt",
                    "email": "e-mail address",
                    "onenote": "OneNote page or section (empty = default from Settings, else Quick Notes)"}


class OutputTargetRow(QWidget):
    """Output target combo + an argument field for targets that need one.
    For "OneNote" a Browse... button opens the OneNote picker (stores the page/section path)."""
    changed = Signal()

    def __init__(self, parent=None, picker_factory=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.combo = _output_combo()
        self.arg = QLineEdit()
        self.browse = QPushButton("Browse...")
        self.browse.setToolTip("Choose a OneNote page or section")
        self.browse.clicked.connect(self._browse_onenote)
        self.picker_factory = picker_factory      # tests inject a fake picker
        h.addWidget(self.combo)
        h.addWidget(self.arg, 1)
        h.addWidget(self.browse)
        h.addStretch(0)
        self.combo.currentIndexChanged.connect(self._sync)
        self.combo.currentIndexChanged.connect(lambda *_: self.changed.emit())
        self.arg.textEdited.connect(lambda *_: self.changed.emit())
        self._sync()

    def _sync(self, *_):
        hint = OUTPUT_ARG_HINTS.get(self.combo.currentData())
        self.arg.setVisible(hint is not None)
        self.arg.setPlaceholderText(hint or "")
        self.browse.setVisible(self.combo.currentData() == "onenote")
        self.arg.setToolTip(self.arg.text() if self.combo.currentData() == "onenote" else "")

    def _browse_onenote(self) -> None:
        if self.picker_factory is not None:
            picker = self.picker_factory(self)
        else:
            from phraseforge.ui.onenote_picker import OneNotePicker
            picker = OneNotePicker(self, mode="target", current=self.arg.text())
        if picker.exec():
            ref = picker.selected_ref()
            if ref is not None:
                self.arg.setText(ref)
                self._sync()
                self.changed.emit()

    def set(self, target: str, arg: str = "") -> None:
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(max(0, self.combo.findData(target or "current")))
        self.combo.blockSignals(False)
        self.arg.setText(arg or "")
        self._sync()

    def target(self) -> str:
        return self.combo.currentData() or "current"

    def target_arg(self) -> str:
        return self.arg.text().strip() if self.arg.isVisible() or self.target() in OUTPUT_ARG_HINTS else ""

    # QComboBox-compatible bits older callers used
    def currentData(self):
        return self.target()

    def setCurrentIndex(self, i: int) -> None:
        self.combo.setCurrentIndex(i)

    def findData(self, v):
        return self.combo.findData(v)


# ---------------------------------------------------------------- phrase editor
class PhraseEditor(QWidget):
    saved = Signal(int)
    content_focus_changed = Signal(bool)
    status_changed = Signal(dict)
    view_options_changed = Signal(dict)
    format_changed = Signal(bool)          # True when the phrase became rich text

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.phrase: Phrase | None = None
        self.dirty = False
        self._loading = False
        self.zoom = 100
        self.view = {"word_wrap": True, "show_special": False, "show_macro_params": False, "rulers": False}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 6)
        lay.setSpacing(3)

        lay.addWidget(self._u_caption("Description"))
        row = QHBoxLayout(); row.setSpacing(8)
        self.description = QLineEdit()
        row.addWidget(self.description, 1)
        self.tag_button = QToolButton()
        self.tag_button.setIcon(icon("tag"))
        self.tag_button.setAutoRaise(True)
        self.tag_button.setToolTip("Add a tag")
        self.tag_button.clicked.connect(self.add_tag)
        row.addWidget(self.tag_button)
        lay.addLayout(row)
        self.tags_label = QLabel()
        self.tags_label.setObjectName("TagsLine")
        self.tags_label.setTextFormat(Qt.RichText)
        self.tags_label.linkActivated.connect(self._remove_tag)
        self.tags_label.setVisible(False)
        lay.addWidget(self.tags_label)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(caption("Phrase content"))
        head.addStretch(1)
        # PhraseExpress-style language versions of the same phrase
        self.lang_bar = QTabBar()
        self.lang_bar.setProperty("pf_user", True)      # language names, not UI text
        self.lang_bar.setDrawBase(False)
        self.lang_bar.setExpanding(False)
        self.lang_bar.setDocumentMode(True)
        self.lang_bar.currentChanged.connect(self._switch_language)
        head.addWidget(self.lang_bar)
        self.lang_button = QToolButton()
        self.lang_button.setIcon(icon("languages"))
        self.lang_button.setAutoRaise(True)
        self.lang_button.setToolTip("Language versions")
        self.lang_button.setPopupMode(QToolButton.InstantPopup)
        self.lang_menu = QMenu(self.lang_button)
        self.lang_menu.aboutToShow.connect(self._fill_lang_menu)
        self.lang_button.setMenu(self.lang_menu)
        head.addWidget(self.lang_button)
        lay.addLayout(head)
        self._versions: dict[str, tuple[str, str]] = {}
        self._deleted_versions: set[str] = set()
        self._lang = ""                     # "" = default version (the phrase's own content)
        self.ruler = Ruler()
        self.ruler.setVisible(False)
        lay.addWidget(self.ruler)
        self.content_edit = ChipTextEdit()
        self.content_edit.setMinimumHeight(120)
        lay.addWidget(self.content_edit, 1)

        self.triggers = TriggerList("Trigger")
        lay.addWidget(self.triggers)
        lay.addWidget(caption("Output target:"))
        self.output_target = OutputTargetRow()
        lay.addWidget(self.output_target)

        # wiring
        self.description.textEdited.connect(self._mark_dirty)
        self.content_edit.textChanged.connect(self._content_changed)
        self.triggers.changed.connect(self._mark_dirty)
        self.output_target.changed.connect(self._mark_dirty)
        self.content_edit.focus_changed.connect(self.content_focus_changed)
        self.content_edit.chip_activated.connect(self.edit_chip)
        self.content_edit.cursorPositionChanged.connect(self._emit_status)
        self.content_edit.context_menu_hook = self._build_context_menu
        self._saver = _FocusOutSaver(self._autosave)
        for w in (self.description, self.content_edit):
            w.installEventFilter(self._saver)
        self.setEnabled(False)

    @staticmethod
    def _u_caption(text: str) -> QLabel:
        lab = caption(text)
        lab.setTextFormat(Qt.RichText)
        lab.setText(f"<u>{text[0]}</u>{text[1:]}")
        return lab

    def _apply_default_font(self) -> None:
        """Settings > Phrase Formatting > font for unformatted phrases ("Family,size")."""
        spec = self.store.setting("format.font", "Arial,10") or "Arial,10"
        family, _, size = spec.partition(",")
        f = QFont(family.strip() or "Arial")
        try:
            f.setPointSizeF(float(size.strip() or 10))
        except ValueError:
            f.setPointSize(10)
        self.content_edit.document().setDefaultFont(f)

    # -------------------------------------------------- load / save
    def load(self, phrase_id: int | None) -> None:
        if self.phrase is not None and self.dirty:
            self.save()
        self._loading = True
        try:
            self.phrase = self.store.get_phrase(phrase_id) if phrase_id is not None else None
            p = self.phrase
            self.setEnabled(p is not None)
            if p is None:
                self.description.clear()
                self.content_edit.set_content("")
                self.triggers.set_rows([default_row("autotext")])
                self.output_target.set("current")
                self._refresh_tags([])
                return
            self.description.setText(p.description)
            self._apply_default_font()
            fresh = not p.content and p.content_format == "text" and not p.triggers
            if fresh and self.store.setting("format.default", "plain") == "rich":
                self.content_edit.set_content("", html=True)     # new phrase starts formatted (saved as HTML)
            else:
                self.content_edit.set_content(p.content, html=(p.content_format == "html"))
            self.triggers.set_rows(rows_for_triggers(p.triggers) or [default_row("autotext")])
            self.output_target.set(p.output_target, p.output_target_arg)
            self._refresh_tags(p.tags)
            self._versions = dict(self.store.phrase_versions(p.id)) if hasattr(self.store, "phrase_versions") else {}
            self._deleted_versions = set()
            self._lang = ""
            self._default = (p.content, p.content_format)
            self._fill_lang_bar()
        finally:
            self._loading = False
            self.dirty = False
        self._emit_status()

    def save(self) -> bool:
        p = self.phrase
        if p is None or not self.dirty:
            return False
        p.description = self.description.text().strip() or p.description
        self._stash_language()
        p.content, p.content_format = getattr(self, "_default", (self.content_edit.content(),
                                                                 "html" if self.content_edit.rich else "text"))
        p.triggers = self.triggers.triggers()
        p.output_target = self.output_target.target()
        p.output_target_arg = self.output_target.target_arg()
        self.store.update_phrase(p)
        if hasattr(self.store, "set_phrase_version"):
            for lang in self._deleted_versions:
                self.store.delete_phrase_version(p.id, lang)
            old = self.store.phrase_versions(p.id)
            for lang, (text, fmt) in self._versions.items():
                if old.get(lang) != (text, fmt):
                    self.store.set_phrase_version(p.id, lang, text, fmt)
            self._deleted_versions = set()
        self.dirty = False
        self.saved.emit(p.id)
        return True

    # -------------------------------------------------- language versions
    def languages(self) -> list[str]:
        """Configured languages plus any this phrase already has."""
        langs = list(self.store.phrase_languages()) if hasattr(self.store, "phrase_languages") else []
        for k in self._versions:
            if k.lower() not in (x.lower() for x in langs):
                langs.append(k)
        return langs

    def _fill_lang_bar(self) -> None:
        bar = self.lang_bar
        bar.blockSignals(True)
        while bar.count():
            bar.removeTab(0)
        langs = self.languages()
        bar.addTab("Default")
        bar.setTabData(0, "")
        highlight = self.store.setting("display.highlight_unedited", "1") == "1"
        for lang in langs:
            i = bar.addTab(lang)
            bar.setTabData(i, lang)
            if lang not in self._versions and highlight:
                bar.setTabTextColor(i, QColor("#b06000"))   # no own text yet: uses the default
                bar.setTabToolTip(i, f"No {lang} version yet; the default text is used.")
        idx = next((i for i in range(bar.count()) if bar.tabData(i) == self._lang), 0)
        bar.setCurrentIndex(idx)
        bar.setVisible(bool(langs))
        bar.blockSignals(False)

    def _stash_language(self) -> None:
        """Keep the editor's text as the current language's version."""
        if self.phrase is None:
            return
        text = self.content_edit.content()
        fmt = "html" if self.content_edit.rich else "text"
        if not self._lang:
            self._default = (text, fmt)
        elif text.strip() and (text, fmt) != getattr(self, "_default", None):
            self._versions[self._lang] = (text, fmt)
            self._deleted_versions.discard(self._lang)

    def _switch_language(self, index: int) -> None:
        if self.phrase is None or index < 0:
            return
        was_dirty = self.dirty
        self._stash_language()
        self._lang = self.lang_bar.tabData(index) or ""
        text, fmt = self._versions.get(self._lang, self._default) if self._lang else self._default
        self._loading = True
        try:
            self.content_edit.set_content(text, html=(fmt == "html"))
        finally:
            self._loading = False
        self.dirty = was_dirty
        self._fill_lang_bar()

    def current_language(self) -> str:
        return self._lang

    def add_language(self, lang: str) -> None:
        lang = (lang or "").strip()
        if not lang:
            return
        langs = self.store.phrase_languages()
        if lang.lower() not in (x.lower() for x in langs):
            self.store.set_phrase_languages(langs + [lang])
        self._fill_lang_bar()
        i = next((i for i in range(self.lang_bar.count()) if (self.lang_bar.tabData(i) or "").lower()
                  == lang.lower()), 0)
        self.lang_bar.setCurrentIndex(i)

    def remove_language_version(self) -> None:
        if not self._lang:
            return
        self._versions.pop(self._lang, None)
        self._deleted_versions.add(self._lang)
        self.dirty = True
        self._loading = True
        try:
            self.content_edit.set_content(self._default[0], html=(self._default[1] == "html"))
        finally:
            self._loading = False
        self._fill_lang_bar()

    def translate_current(self, translate=None) -> bool:
        """Fill the current language version with an AI/DeepL translation of the default text."""
        if not self._lang or self.phrase is None:
            return False
        src = self._default[0]
        if translate is None:
            translate = self._ai_translate
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            out = translate(src, self._lang)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Translate", f"Translation failed: {str(e)[:200]}")
            return False
        QApplication.restoreOverrideCursor()
        self.content_edit.set_content(out, html=False)
        self._versions[self._lang] = (out, "text")
        self.dirty = True
        self._fill_lang_bar()
        return True

    def _ai_translate(self, text: str, lang: str) -> str:
        from phraseforge import ai
        st = dict(self.store.settings())
        prov = st.get("translation.provider", "")
        if prov == "deepl":
            return ai.deepl_translate(st, text, lang)
        return ai.complete(st, text, provider=prov, system=ai.translation_system(st, lang), raw_system=True).strip()

    def _fill_lang_menu(self) -> None:
        m = self.lang_menu
        m.clear()
        add = m.addMenu("Add language")
        have = {x.lower() for x in self.languages()}
        from phraseforge.ui.settings_dialog import TRANSLATION_LANGUAGES
        for lang in TRANSLATION_LANGUAGES:
            if lang.lower() not in have:
                add.addAction(lang).triggered.connect(lambda _=False, l=lang: self.add_language(l))
        add.addSeparator()
        add.addAction("Other...").triggered.connect(self._ask_language)
        a = m.addAction("Translate default text into this language")
        a.setEnabled(bool(self._lang))
        a.triggered.connect(lambda: self.translate_current())
        a = m.addAction("Delete this language version")
        a.setEnabled(bool(self._lang) and self._lang in self._versions)
        a.triggered.connect(self.remove_language_version)

    def _ask_language(self) -> None:
        lang, ok = QInputDialog.getText(self, "Add language", "Language name:")
        if ok:
            self.add_language(lang)

    def _autosave(self):
        if self.dirty and not self._loading:
            self.save()

    def _mark_dirty(self, *_):
        if not self._loading and self.phrase is not None:
            self.dirty = True

    def _content_changed(self):
        self._mark_dirty()
        self._emit_status()

    # -------------------------------------------------- tags
    def _refresh_tags(self, tags: list[str]):
        if not tags:
            self.tags_label.setVisible(False)
            return
        links = " ".join(f'<span style="background:#e2f0d9;border:1px solid #9ac17f">&nbsp;{t}&nbsp;</span>'
                         f'<a href="{t}" style="color:#888;text-decoration:none">×</a>' for t in tags)
        self.tags_label.setText("Tags: " + links)
        self.tags_label.setVisible(True)

    def add_tag(self):
        if not self.phrase:
            return
        existing = [r[0] for r in self.store.conn.execute("SELECT name FROM tags")]
        dlg = AddTagDialog(existing, self)
        if dlg.exec() and dlg.tag():
            if dlg.tag() not in self.phrase.tags:
                self.phrase.tags.append(dlg.tag())
                self.dirty = True
                self.save()
            self._refresh_tags(self.phrase.tags)

    def _remove_tag(self, tag: str):
        if self.phrase and tag in self.phrase.tags:
            self.phrase.tags.remove(tag)
            self.dirty = True
            self.save()
            self._refresh_tags(self.phrase.tags)

    # -------------------------------------------------- macros
    def insert_macro(self, text: str) -> None:
        if self.phrase is None:
            return
        self.content_edit.setFocus()
        self.content_edit.insert_content(text)
        self._mark_dirty()

    def edit_chip(self, pos: int) -> None:
        hit = self.content_edit.chip_at(pos + 1) or self.content_edit.chip_at(pos)
        if not hit:
            return
        token = hit[1]
        new = None
        try:
            from phraseforge.ui import macro_ui
            fn = getattr(macro_ui, "edit_macro", None)
            if fn:
                new = fn(token, self)
        except Exception:
            new = None
        if new is None:
            new, ok = QInputDialog.getMultiLineText(self, f'Edit macro "{display_name(token)}"',
                                                    "Macro:", token)
            if not ok:
                return
        if new != token:
            self.content_edit.replace_chip(hit[0], new)
            self._mark_dirty()

    # -------------------------------------------------- rich text
    def make_rich(self) -> None:
        """Called before applying formatting: plain phrases become HTML phrases."""
        if not self.content_edit.rich:
            self.content_edit.rich = True
            self.content_edit.setAcceptRichText(True)
            self._mark_dirty()
            self.format_changed.emit(True)

    # -------------------------------------------------- view options / status
    def set_view_options(self, word_wrap: bool = True, show_special: bool = False,
                         show_macro_params: bool = False, rulers: bool = False) -> None:
        self.view = {"word_wrap": word_wrap, "show_special": show_special,
                     "show_macro_params": show_macro_params, "rulers": rulers}
        ed = self.content_edit
        ed.setLineWrapMode(QTextEdit.WidgetWidth if word_wrap else QTextEdit.NoWrap)
        opt = ed.document().defaultTextOption()
        flags = QTextOption.Flag(0)
        if show_special:
            flags = QTextOption.ShowTabsAndSpaces | QTextOption.ShowLineAndParagraphSeparators
        opt.setFlags(flags)
        ed.document().setDefaultTextOption(opt)
        ed.show_macro_params = show_macro_params
        ed.document().markContentsDirty(0, ed.document().characterCount())
        ed.viewport().update()
        self.ruler.setVisible(rulers)
        self.view_options_changed.emit(dict(self.view))

    def set_zoom(self, percent: int) -> None:
        percent = max(50, min(400, int(percent)))
        delta = percent - self.zoom
        self.zoom = percent
        f = self.content_edit.font()
        f.setPointSizeF(max(4.0, 9.0 * percent / 100))
        self.content_edit.document().setDefaultFont(f)
        self._emit_status()
        return delta

    def _emit_status(self, *_):
        text = self.content_edit.toPlainText().replace(OBJ, "")
        words = len(re.findall(r"\S+", text))
        try:
            loc = QGuiApplication.inputMethod().locale()
            lang = f"{loc.languageToString(loc.language())} ({loc.territoryToString(loc.territory())})"
        except Exception:
            lang = ""
        self.status_changed.emit({"language": lang, "chars": len(self.content_edit.content()) if self.phrase else 0,
                                  "words": words, "zoom": self.zoom})

    # -------------------------------------------------- context menu (16_context_menu_content)
    def _build_context_menu(self, m: QMenu, hit) -> None:
        ed = self.content_edit
        if hit:
            m.addAction(f'Edit macro "{display_name(hit[1])}"').triggered.connect(lambda: self.edit_chip(hit[0]))
        else:
            a = m.addAction("Edit macro"); a.setEnabled(False)
        ins = m.addMenu("Insert macro")
        self._fill_insert_macro_menu(ins)
        m.addAction("AI text generator").triggered.connect(self._ai_generator)
        m.addSeparator()
        a = m.addAction("Right-to-left paragraph"); a.setShortcut("Ctrl+Right Shift")
        a.triggered.connect(lambda: ed.set_paragraph_direction(True))
        a = m.addAction("Left-to-right paragraph"); a.setShortcut("Ctrl+Left Shift")
        a.triggered.connect(lambda: ed.set_paragraph_direction(False))
        m.addSeparator()
        m.addAction("Preview").triggered.connect(self.preview)
        m.addSeparator()
        a = m.addAction("Undo"); a.setShortcut("Ctrl+Z"); a.setEnabled(ed.document().isUndoAvailable())
        a.triggered.connect(ed.undo)
        m.addSeparator()
        has_sel = ed.textCursor().hasSelection()
        for text, key, slot, enabled in (("Cut", "Ctrl+X", ed.cut, has_sel), ("Copy", "Ctrl+C", ed.copy, has_sel),
                                          ("Paste", "Ctrl+V", ed.paste, ed.canPaste())):
            a = m.addAction(text); a.setShortcut(key); a.setEnabled(enabled); a.triggered.connect(slot)
        m.addSeparator()
        a = m.addAction("Select All"); a.setShortcut("Ctrl+A"); a.triggered.connect(ed.selectAll)
        m.addSeparator()
        for key, label in (("rulers", "Show rulers"), ("show_special", "Show special characters"),
                           ("word_wrap", "Word Wrap"), ("show_macro_params", "Show macro parameters")):
            a = m.addAction(label)
            a.setCheckable(True)
            a.setChecked(self.view[key])
            a.triggered.connect(lambda on, k=key: self.set_view_options(**dict(self.view, **{k: on})))
        for a in m.actions():
            a.setShortcutVisibleInContextMenu(True)

    def _fill_insert_macro_menu(self, menu: QMenu) -> None:
        try:
            from phraseforge.ui import macro_ui
            fn = getattr(macro_ui, "fill_macro_menu", None)
            if fn:
                fn(menu, self.insert_macro)
                return
        except Exception:
            pass
        try:
            from phraseforge.macros import catalog
            groups: dict[str, QMenu] = {}
            for info in catalog():
                sub = groups.get(info.category)
                if sub is None:
                    sub = groups[info.category] = menu.addMenu(info.category)
                a = sub.addAction(info.name)
                a.setToolTip(info.description)
                a.triggered.connect(lambda _=False, t=info.template or info.syntax: self.insert_macro(t))
        except Exception:
            menu.addAction("(no macros available)").setEnabled(False)

    def _ai_generator(self):
        prompt, ok = QInputDialog.getMultiLineText(self, "AI text generator",
                                                   "Describe the text the AI should write:")
        if ok and prompt.strip():
            safe = prompt.strip().replace('"', '\\"')
            self.insert_macro(f'{{#ai "{safe}"}}')

    def preview(self):
        text = self.content_edit.content()
        try:
            from phraseforge.ui.main_window import preview_text
            out = preview_text(self.store, text)
        except Exception:
            out = text
        QMessageBox.information(self, "Preview", out if len(out) < 4000 else out[:4000] + "…")


# ---------------------------------------------------------------- folder editor (09)
class FolderEditor(QWidget):
    saved = Signal(int)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.folder = None
        self.dirty = False
        self._loading = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 6)
        lay.setSpacing(3)
        lay.addWidget(PhraseEditor._u_caption("Description"))
        self.description = QLineEdit()
        lay.addWidget(self.description)
        self.triggers = TriggerList("Trigger")
        lay.addWidget(self.triggers)
        lay.addWidget(caption("Abbreviation prefix (typed before every autotext in this folder):"))
        self.prefix = QLineEdit()
        self.prefix.setPlaceholderText("e.g. ;  (empty = none, or the parent folder's prefix)")
        lay.addWidget(self.prefix)
        lay.addWidget(caption("Output target for all phrases in this folder:"))
        self.output_target = OutputTargetRow()
        lay.addWidget(self.output_target)
        lay.addWidget(caption("Notes:"))
        self.notes = QPlainTextEdit()
        lay.addWidget(self.notes, 1)
        self.description.textEdited.connect(self._mark_dirty)
        self.prefix.textEdited.connect(self._mark_dirty)
        self.triggers.changed.connect(self._mark_dirty)
        self.output_target.changed.connect(self._mark_dirty)
        self.notes.textChanged.connect(self._mark_dirty)
        self._saver = _FocusOutSaver(self._autosave)
        for w in (self.description, self.prefix, self.notes):
            w.installEventFilter(self._saver)
        self.setEnabled(False)

    def load(self, folder_id: int | None) -> None:
        if self.dirty:
            self.save()
        self._loading = True
        try:
            self.folder = self.store.get_folder(folder_id) if folder_id is not None else None
            self.setEnabled(self.folder is not None)
            f = self.folder
            self.description.setText(f.name if f else "")
            self.triggers.set_rows((rows_for_triggers(f.triggers) if f else []) or [default_row("autotext")])
            self.output_target.set(f.output_target if f else "current", f.output_target_arg if f else "")
            self.prefix.setText(f.abbrev_prefix if f else "")
            self.notes.setPlainText(f.notes if f else "")
        finally:
            self._loading = False
            self.dirty = False

    def save(self) -> bool:
        f = self.folder
        if f is None or not self.dirty:
            return False
        name = self.description.text().strip()
        if name:
            f.name = name
        f.notes = self.notes.toPlainText()
        f.abbrev_prefix = self.prefix.text().strip()
        f.output_target = self.output_target.target()
        f.output_target_arg = self.output_target.target_arg()
        self.store.update_folder(f)
        f.triggers = self.triggers.triggers()
        self.store.set_folder_triggers(f.id, f.triggers)
        self.dirty = False
        self.saved.emit(f.id)
        return True

    def _autosave(self):
        if self.dirty and not self._loading:
            self.save()

    def _mark_dirty(self, *_):
        if not self._loading and self.folder is not None:
            self.dirty = True


# ---------------------------------------------------------------- special folders (21)
SPECIAL = {
    "last_used": {"title": "Last Used", "max_key": "special.last_used.max_items", "max_default": "20"},
    "clipboard_cache": {"title": "Clipboard Cache", "max_key": "clipboard_history.max", "max_default": "20"},
}


class SpecialFolderEditor(QWidget):
    """'Last Used' and 'Clipboard Cache' pseudo folders. All values live in settings."""
    saved = Signal(str)

    def __init__(self, store, kind: str, parent=None):
        super().__init__(parent)
        assert kind in SPECIAL
        self.store, self.kind = store, kind
        self.spec = SPECIAL[kind]
        self._loading = False
        self.dirty = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 6)
        lay.setSpacing(3)
        lay.addWidget(PhraseEditor._u_caption("Description"))
        self.description = QLineEdit()
        lay.addWidget(self.description)
        self.triggers = TriggerList("Trigger")
        lay.addWidget(self.triggers)
        lay.addWidget(caption("Output target for all phrases in this folder:"))
        self.output_target = _output_combo()
        lay.addWidget(self.output_target)
        box = QGroupBox("Options")
        box.setStyleSheet("QGroupBox{font-weight:normal} QGroupBox::title{font-weight:normal}")
        bl = QVBoxLayout(box)
        bl.setSpacing(4)
        self.clear_on_exit = QCheckBox("Clear folder on exit")
        bl.addWidget(self.clear_on_exit)
        mx = QHBoxLayout()
        mx.addWidget(QLabel("Maximum number of items:"))
        self.max_items = QSpinBox(); self.max_items.setRange(1, 10000); self.max_items.setFixedWidth(58)
        self.max_items.setLocale(LATIN_DIGITS)
        mx.addWidget(self.max_items); mx.addStretch(1)
        bl.addLayout(mx)
        self.remove_formatting = self.trim = self.filter_dupes = self.desktop_menu = self.desktop_after = None
        if kind == "clipboard_cache":
            self.remove_formatting = QCheckBox("Remove text formatting")
            bl.addWidget(self.remove_formatting)
            self.trim = QCheckBox("Trim leading/trailing spaces/lines")
            trim_row = QHBoxLayout(); trim_row.setContentsMargins(16, 0, 0, 0); trim_row.addWidget(self.trim)
            bl.addLayout(trim_row)
            self.filter_dupes = QCheckBox("Filter duplicates")
            bl.addWidget(self.filter_dupes)
            dm = QHBoxLayout()
            self.desktop_menu = QCheckBox("Show desktop menu after")
            self.desktop_after = QSpinBox(); self.desktop_after.setRange(1, 100); self.desktop_after.setFixedWidth(58)
            self.desktop_after.setLocale(LATIN_DIGITS)
            dm.addWidget(self.desktop_menu); dm.addWidget(self.desktop_after); dm.addWidget(QLabel("copy actions"))
            dm.addStretch(1)
            bl.addLayout(dm)
            self.remove_formatting.toggled.connect(lambda on: self.trim.setEnabled(on))
        lay.addWidget(box)
        lay.addStretch(1)

        for sig in (self.description.textEdited, self.triggers.changed, self.output_target.currentIndexChanged,
                    self.clear_on_exit.toggled, self.max_items.valueChanged):
            sig.connect(self._changed)
        for w in (self.remove_formatting, self.trim, self.filter_dupes, self.desktop_menu):
            if w is not None:
                w.toggled.connect(self._changed)
        if self.desktop_after is not None:
            self.desktop_after.valueChanged.connect(self._changed)
        self.load()

    def _key(self, name: str) -> str:
        return f"special.{self.kind}.{name}"

    def load(self, *_):
        s = self.store.setting
        self._loading = True
        try:
            self.description.setText(s(self._key("description"), self.spec["title"]))
            rows = rows_for_triggers(self.store.special_triggers(self.kind))
            if not rows and self.kind == "clipboard_cache":
                hk = s("clipboard_history.hotkey", "ctrl+alt+v")
                rows = [dict(default_row("hotkey"), value=hk)] if hk else None
            self.triggers.set_rows(rows or [default_row("autotext")])
            i = self.output_target.findData(s(self._key("output_target"), "current"))
            self.output_target.setCurrentIndex(max(0, i))
            self.clear_on_exit.setChecked(s(self._key("clear_on_exit"), "0") == "1")
            self.max_items.setValue(int(s(self.spec["max_key"], self.spec["max_default"]) or 20))
            if self.kind == "clipboard_cache":
                self.remove_formatting.setChecked(s(self._key("remove_formatting"), "0") == "1")
                self.trim.setChecked(s(self._key("trim"), "0") == "1")
                self.trim.setEnabled(self.remove_formatting.isChecked())
                self.filter_dupes.setChecked(s(self._key("filter_duplicates"), "1") == "1")
                self.desktop_menu.setChecked(s(self._key("desktop_menu"), "0") == "1")
                self.desktop_after.setValue(int(s(self._key("desktop_menu_after"), "10") or 10))
        finally:
            self._loading = False
            self.dirty = False

    def _changed(self, *_):
        if not self._loading:
            self.dirty = True
            self.save()

    def save(self) -> bool:
        if not self.dirty:
            return False
        st = self.store.set_setting
        st(self._key("description"), self.description.text())
        st(self._key("output_target"), self.output_target.currentData())
        st(self._key("clear_on_exit"), "1" if self.clear_on_exit.isChecked() else "0")
        st(self.spec["max_key"], str(self.max_items.value()))
        rows = self.triggers.meaningful_rows()
        # the Clipboard Cache hotkey is the clipboard_history.hotkey setting, not a trigger row
        keep = [t for t in self.triggers.triggers()
                if not (self.kind == "clipboard_cache" and t.kind == TriggerKind.HOTKEY)]
        self.store.set_special_triggers(self.kind, keep)
        if self.kind == "clipboard_cache":
            hk = next((r["value"] for r in rows if r["type"] == "hotkey"), "")
            st("clipboard_history.hotkey", hk)
            st(self._key("remove_formatting"), "1" if self.remove_formatting.isChecked() else "0")
            st(self._key("trim"), "1" if self.trim.isChecked() else "0")
            st(self._key("filter_duplicates"), "1" if self.filter_dupes.isChecked() else "0")
            st(self._key("desktop_menu"), "1" if self.desktop_menu.isChecked() else "0")
            st(self._key("desktop_menu_after"), str(self.desktop_after.value()))
        self.dirty = False
        self.saved.emit(self.kind)
        return True
