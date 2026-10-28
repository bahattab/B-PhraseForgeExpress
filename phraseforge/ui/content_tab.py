"""'Phrase content' contextual ribbon tab (reference/phraseexpress/07_editing_content.png).

Groups: Clipboard | Font | Paragraph | Insert | Macros. Any formatting turns the
phrase into a rich-text (HTML) phrase; plain phrases stay plain otherwise.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextListFormat
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFontComboBox,
    QFormLayout, QHBoxLayout, QLineEdit, QMenu, QSpinBox, QToolButton, QWidget,
)

from phraseforge.ui.iconset import icon
from phraseforge.ui.ribbon import Ribbon, RibbonTab

SIZES = ["8", "9", "10", "11", "12", "14", "16", "18", "20", "22", "24", "26", "28", "36", "48", "72"]


def _icon_button(icon_name: str, tip: str, slot=None, checkable: bool = False, menu: QMenu | None = None) -> QToolButton:
    b = QToolButton()
    b.setObjectName("RibbonSmall")
    b.setIcon(icon(icon_name))
    b.setToolTip(tip)
    b.setAutoRaise(True)
    b.setCheckable(checkable)
    if menu is not None:
        b.setMenu(menu)
        b.setPopupMode(QToolButton.MenuButtonPopup if slot else QToolButton.InstantPopup)
    if slot:
        b.clicked.connect(lambda _=False: slot())
    return b


def _row(*widgets) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(1)
    for x in widgets:
        h.addWidget(x)
    h.addStretch(1)
    return w


class ParagraphDialog(QDialog):
    def __init__(self, fmt: QTextBlockFormat, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Paragraph")
        f = QFormLayout(self)
        self.align = QComboBox(); self.align.addItems(["Left", "Center", "Right", "Justify"])
        al = fmt.alignment()
        self.align.setCurrentIndex(1 if al & Qt.AlignHCenter else 2 if al & Qt.AlignRight else 3 if al & Qt.AlignJustify else 0)
        self.left = QDoubleSpinBox(); self.left.setSuffix(" pt"); self.left.setRange(0, 500); self.left.setValue(fmt.leftMargin())
        self.right = QDoubleSpinBox(); self.right.setSuffix(" pt"); self.right.setRange(0, 500); self.right.setValue(fmt.rightMargin())
        self.first = QDoubleSpinBox(); self.first.setSuffix(" pt"); self.first.setRange(-200, 500); self.first.setValue(fmt.textIndent())
        self.before = QDoubleSpinBox(); self.before.setSuffix(" pt"); self.before.setRange(0, 200); self.before.setValue(fmt.topMargin())
        self.after = QDoubleSpinBox(); self.after.setSuffix(" pt"); self.after.setRange(0, 200); self.after.setValue(fmt.bottomMargin())
        self.line = QComboBox(); self.line.addItems(["Single", "1.5 lines", "Double"])
        h = fmt.lineHeight()
        self.line.setCurrentIndex(1 if 140 <= h < 190 else 2 if h >= 190 else 0)
        for label, w in (("Alignment:", self.align), ("Left indent:", self.left), ("Right indent:", self.right),
                         ("First line:", self.first), ("Spacing before:", self.before),
                         ("Spacing after:", self.after), ("Line spacing:", self.line)):
            f.addRow(label, w)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        f.addRow(bb)

    def block_format(self) -> QTextBlockFormat:
        b = QTextBlockFormat()
        b.setAlignment([Qt.AlignLeft, Qt.AlignHCenter, Qt.AlignRight, Qt.AlignJustify][self.align.currentIndex()])
        b.setLeftMargin(self.left.value()); b.setRightMargin(self.right.value())
        b.setTextIndent(self.first.value())
        b.setTopMargin(self.before.value()); b.setBottomMargin(self.after.value())
        b.setLineHeight([100, 150, 200][self.line.currentIndex()], QTextBlockFormat.ProportionalHeight.value)
        return b


class HyperlinkDialog(QDialog):
    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hyperlink")
        self.setMinimumWidth(420)
        f = QFormLayout(self)
        self.text = QLineEdit(text); self.url = QLineEdit("https://")
        f.addRow("Text to display:", self.text); f.addRow("Address:", self.url)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        f.addRow(bb)


class TableDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Insert table")
        f = QFormLayout(self)
        self.rows = QSpinBox(); self.rows.setRange(1, 100); self.rows.setValue(2)
        self.cols = QSpinBox(); self.cols.setRange(1, 30); self.cols.setValue(2)
        f.addRow("Rows:", self.rows); f.addRow("Columns:", self.cols)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        f.addRow(bb)


class ContentTabController:
    """Owns the widgets of the content tab and keeps them in sync with the cursor."""

    def __init__(self, ribbon: Ribbon, editor):
        self.ribbon, self.editor = ribbon, editor
        self.ed = editor.content_edit
        self.tab: RibbonTab = ribbon.add_tab("content", "Phrase content", contextual=True)
        self._build_clipboard()
        self._build_font()
        self._build_paragraph()
        self._build_insert()
        self._build_macros()
        self._build_ai()
        self.ed.currentCharFormatChanged.connect(self._sync_char)
        self.ed.cursorPositionChanged.connect(self._sync_block)
        editor.content_focus_changed.connect(self._focus)

    # -------------------------------------------------- groups
    def _build_clipboard(self):
        g = self.tab.add_group("Clipboard")
        paste_menu = QMenu(g)
        paste_menu.addAction("Paste").triggered.connect(self.ed.paste)
        paste_menu.addAction("Paste as plain text").triggered.connect(self._paste_plain)
        g.add_large("Paste", "paste", self.ed.paste, menu=paste_menu)
        col = g.add_column()
        col.add_small("Cut", "cut", self.ed.cut)
        col.add_small("Copy", "copy", self.ed.copy)

    def _build_font(self):
        g = self.tab.add_group("Font")
        col = g.add_column()
        self.font_combo = QFontComboBox(); self.font_combo.setFixedWidth(140)
        self.font_combo.setCurrentFont(QFont("Arial"))
        self.font_combo.currentFontChanged.connect(lambda f: self._char(lambda c: c.setFontFamilies([f.family()])))
        self.size_combo = QComboBox(); self.size_combo.setEditable(True); self.size_combo.addItems(SIZES)
        self.size_combo.setFixedWidth(52); self.size_combo.setCurrentText("10")
        self.size_combo.textActivated.connect(self._set_size)
        col.add_widget(_row(self.font_combo, self.size_combo))
        self.b_bold = _icon_button("bold", "Bold (Ctrl+B)", self._toggle_bold, True)
        self.b_italic = _icon_button("italic", "Italic (Ctrl+I)", lambda: self._char(lambda c: c.setFontItalic(self.b_italic.isChecked())), True)
        self.b_under = _icon_button("underline", "Underline (Ctrl+U)", lambda: self._char(lambda c: c.setFontUnderline(self.b_under.isChecked())), True)
        self.b_strike = _icon_button("strike", "Strikethrough", lambda: self._char(lambda c: c.setFontStrikeOut(self.b_strike.isChecked())), True)
        self.b_sub = _icon_button("subscript", "Subscript", lambda: self._valign(QTextCharFormat.AlignSubScript, self.b_sub), True)
        self.b_sup = _icon_button("superscript", "Superscript", lambda: self._valign(QTextCharFormat.AlignSuperScript, self.b_sup), True)
        hl_menu = QMenu(g)
        hl_menu.addAction("No highlight").triggered.connect(lambda: self._char(lambda c: c.clearBackground()))
        hl_menu.addAction("More colors...").triggered.connect(lambda: self._pick_color(background=True))
        self.b_high = _icon_button("highlight", "Text highlight color", lambda: self._apply_color("#ffff00", True), menu=hl_menu)
        fc_menu = QMenu(g)
        fc_menu.addAction("Automatic").triggered.connect(lambda: self._char(lambda c: c.clearForeground()))
        fc_menu.addAction("More colors...").triggered.connect(lambda: self._pick_color(background=False))
        self.b_color = _icon_button("font_color", "Font color", lambda: self._apply_color("#c00000", False), menu=fc_menu)
        col.add_widget(_row(self.b_bold, self.b_italic, self.b_under, self.b_strike, self.b_sub, self.b_sup,
                            self.b_high, self.b_color))
        for b, key in ((self.b_bold, "Ctrl+B"), (self.b_italic, "Ctrl+I"), (self.b_under, "Ctrl+U")):
            b.setShortcut(key)

    def _build_paragraph(self):
        g = self.tab.add_group("Paragraph")
        col = g.add_column()
        num_menu = QMenu(g)
        for label, style in (("1. 2. 3.", QTextListFormat.ListDecimal), ("a. b. c.", QTextListFormat.ListLowerAlpha),
                             ("A. B. C.", QTextListFormat.ListUpperAlpha), ("i. ii. iii.", QTextListFormat.ListLowerRoman)):
            num_menu.addAction(label).triggered.connect(lambda _=False, s=style: self._list(s))
        col.add_widget(_row(
            _icon_button("indent_less", "Decrease indent", lambda: self._indent(-1)),
            _icon_button("indent_more", "Increase indent", lambda: self._indent(1)),
            _icon_button("bullets", "Bullets", lambda: self._list(QTextListFormat.ListDisc)),
            _icon_button("numbering", "Numbering", lambda: self._list(QTextListFormat.ListDecimal), menu=num_menu)))
        self.align_buttons = []
        for name, tip, al in (("align_left", "Align left", Qt.AlignLeft), ("align_center", "Center", Qt.AlignHCenter),
                              ("align_right", "Align right", Qt.AlignRight), ("align_justify", "Justify", Qt.AlignJustify)):
            b = _icon_button(name, tip, lambda a=al: self._align(a), True)
            b.setProperty("align", int(al.value) if hasattr(al, "value") else int(al))
            self.align_buttons.append(b)
        col.add_widget(_row(*self.align_buttons))
        g.add_large("Paragraph...", "paragraph", self._paragraph_dialog)

    def _build_insert(self):
        g = self.tab.add_group("Insert")
        col = g.add_column()
        col.add_small("Picture...", "picture", self._insert_picture)
        col.add_small("Hyperlink...", "hyperlink", self._insert_link)
        tmenu = QMenu(g)
        for r, c in ((2, 2), (3, 3), (4, 4)):
            tmenu.addAction(f"{r} x {c} table").triggered.connect(lambda _=False, r=r, c=c: self._insert_table(r, c))
        tmenu.addSeparator()
        tmenu.addAction("Insert table...").triggered.connect(self._table_dialog)
        col.add_small("Table", "table", menu=tmenu)

    def _build_macros(self):
        g = self.tab.add_group("Macros")
        try:
            from phraseforge.ui.macro_ui import build_macro_group
            build_macro_group(g, self.editor.insert_macro)
            return
        except Exception:
            pass
        m = QMenu(g)
        self.editor._fill_insert_macro_menu(m)
        g.add_large("Insert\nmacro", "m_programming", menu=m)

    def _build_ai(self):
        g = self.tab.add_group("AI")
        self.b_enhance = g.add_large("Enhance\nprompt", "m_ai", self.enhance_prompt)
        self.b_enhance.setToolTip("Rewrite the selected text (or the whole phrase) as a clearer, more "
                                  "complete AI prompt, with the engine from Settings > AI.")

    def enhance_prompt(self, complete_fn=None, quiet: bool = False) -> bool:
        """Replace the selection (or all the text) with an improved prompt. Ctrl+Z undoes it."""
        from phraseforge.ui.ai_ui import enhance
        c = self.ed.textCursor()
        if not c.hasSelection():
            c.select(QTextCursor.Document)
        # macros are shown as chips: expand them so the AI sees (and keeps) {#clipboard} etc.
        if hasattr(self.ed, "content_range"):
            text = self.ed.content_range(c.selectionStart(), c.selectionEnd())
        else:
            text = c.selection().toPlainText()
        store = getattr(self.editor, "store", None)
        if store is None:
            return False
        out = enhance(store, text, parent=self.ed, quiet=quiet, complete_fn=complete_fn)
        if not out:
            return False
        c.beginEditBlock()
        c.removeSelectedText()
        if hasattr(self.ed, "insert_content"):
            self.ed.insert_content(out, c)          # macros become chips again
        else:
            c.insertText(out)
        c.endEditBlock()
        self.ed.setFocus()
        return True

    # -------------------------------------------------- actions
    def _focus(self, has_focus: bool):
        if has_focus:
            self.ribbon.set_contextual("content", True, activate=True)

    def _char(self, mutate):
        self.editor.make_rich()
        fmt = QTextCharFormat()
        mutate(fmt)
        c = self.ed.textCursor()
        if not c.hasSelection():
            c.select(QTextCursor.WordUnderCursor)
        c.mergeCharFormat(fmt)
        self.ed.mergeCurrentCharFormat(fmt)
        self.ed.setFocus()

    def _toggle_bold(self):
        self._char(lambda c: c.setFontWeight(QFont.Bold if self.b_bold.isChecked() else QFont.Normal))

    def _valign(self, align, button):
        self._char(lambda c: c.setVerticalAlignment(align if button.isChecked() else QTextCharFormat.AlignNormal))

    def _set_size(self, text: str):
        try:
            size = float(text)
        except ValueError:
            return
        self._char(lambda c: c.setFontPointSize(size))

    def _apply_color(self, color: str, background: bool):
        from PySide6.QtGui import QColor
        self._char(lambda c: c.setBackground(QColor(color)) if background else c.setForeground(QColor(color)))

    def _pick_color(self, background: bool):
        col = QColorDialog.getColor(parent=self.ed)
        if col.isValid():
            self._apply_color(col.name(), background)

    def _paste_plain(self):
        from PySide6.QtGui import QGuiApplication
        self.ed.insert_content(QGuiApplication.clipboard().text())

    def _block(self, mutate):
        self.editor.make_rich()
        c = self.ed.textCursor()
        fmt = c.blockFormat()
        mutate(fmt)
        c.setBlockFormat(fmt)
        self.ed.setFocus()

    def _indent(self, d: int):
        self._block(lambda f: f.setIndent(max(0, f.indent() + d)))

    def _align(self, al):
        self.editor.make_rich()
        self.ed.setAlignment(al)
        self._sync_block()

    def _list(self, style):
        self.editor.make_rich()
        c = self.ed.textCursor()
        lst = c.currentList()
        if lst and lst.format().style() == style:
            bf = QTextBlockFormat(); bf.setObjectIndex(-1)
            lst.remove(c.block())
            c.setBlockFormat(bf)
        else:
            lf = QTextListFormat(); lf.setStyle(style)
            c.createList(lf)
        self.ed.setFocus()

    def _paragraph_dialog(self):
        dlg = ParagraphDialog(self.ed.textCursor().blockFormat(), self.ed)
        if dlg.exec():
            self.editor.make_rich()
            self.ed.textCursor().mergeBlockFormat(dlg.block_format())

    def _insert_picture(self):
        path, _ = QFileDialog.getOpenFileName(self.ed, "Insert picture", "",
                                              "Images (*.png *.jpg *.jpeg *.gif *.bmp *.svg)")
        if path:
            self.editor.make_rich()
            from PySide6.QtCore import QUrl
            self.ed.textCursor().insertImage(QUrl.fromLocalFile(path).toString())

    def _insert_link(self):
        c = self.ed.textCursor()
        dlg = HyperlinkDialog(c.selectedText(), self.ed)
        if dlg.exec() and dlg.url.text().strip():
            self.editor.make_rich()
            text = dlg.text.text() or dlg.url.text()
            c.insertHtml(f'<a href="{dlg.url.text().strip()}">{text}</a>')

    def _insert_table(self, rows: int, cols: int):
        self.editor.make_rich()
        from PySide6.QtGui import QTextTableFormat
        tf = QTextTableFormat(); tf.setBorder(1); tf.setCellPadding(3); tf.setCellSpacing(0)
        self.ed.textCursor().insertTable(rows, cols, tf)

    def _table_dialog(self):
        dlg = TableDialog(self.ed)
        if dlg.exec():
            self._insert_table(dlg.rows.value(), dlg.cols.value())

    # -------------------------------------------------- reflect cursor state
    def _sync_char(self, fmt: QTextCharFormat):
        for b, on in ((self.b_bold, fmt.fontWeight() >= QFont.Bold), (self.b_italic, fmt.fontItalic()),
                      (self.b_under, fmt.fontUnderline()), (self.b_strike, fmt.fontStrikeOut()),
                      (self.b_sub, fmt.verticalAlignment() == QTextCharFormat.AlignSubScript),
                      (self.b_sup, fmt.verticalAlignment() == QTextCharFormat.AlignSuperScript)):
            b.blockSignals(True); b.setChecked(bool(on)); b.blockSignals(False)
        fams = fmt.fontFamilies() if hasattr(fmt, "fontFamilies") else None
        if fams:
            self.font_combo.blockSignals(True)
            self.font_combo.setCurrentFont(QFont(fams[0] if isinstance(fams, list) else str(fams)))
            self.font_combo.blockSignals(False)
        if fmt.fontPointSize() > 0:
            self.size_combo.setCurrentText(f"{fmt.fontPointSize():g}")

    def _sync_block(self):
        al = self.ed.alignment()
        for b in self.align_buttons:
            b.blockSignals(True)
            b.setChecked(bool(int(al.value if hasattr(al, "value") else al) & b.property("align")))
            b.blockSignals(False)


def build_content_tab(ribbon: Ribbon, editor) -> RibbonTab:
    """Add the 'Phrase content' contextual tab (key "content") wired to a PhraseEditor."""
    ctl = ContentTabController(ribbon, editor)
    ctl.tab.controller = ctl          # keep the controller alive with the tab
    return ctl.tab
