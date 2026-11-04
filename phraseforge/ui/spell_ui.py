"""Spell check in the phrase editor: red wavy underline and a suggestions menu.

The underline is a QSyntaxHighlighter format, so it is drawn on screen only and
never becomes part of the phrase's text or HTML.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QColor, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QMenu

from phraseforge import spell
from phraseforge.ui.i18n import tr


class _Relay(QObject):
    """Brings "dictionary ready" from the loader thread to the UI thread."""
    ready = Signal(str)


class SpellHighlighter(QSyntaxHighlighter):
    def __init__(self, document, checker: spell.SpellChecker):
        super().__init__(document)
        self.checker = checker
        self.fmt = QTextCharFormat()
        self.fmt.setUnderlineStyle(QTextCharFormat.SpellCheckUnderline)
        self.fmt.setUnderlineColor(QColor("#d32f2f"))
        self._relay = _Relay()
        self._relay.ready.connect(lambda _code: self.rehighlight(), Qt.QueuedConnection)
        self._listener = self._relay.ready.emit
        checker.listeners.append(self._listener)
        self.destroyed.connect(self._detach)

    def _detach(self, *_):
        try:
            self.checker.listeners.remove(self._listener)
        except ValueError:
            pass

    def highlightBlock(self, text: str) -> None:  # noqa: N802 (Qt override)
        if not self.checker.enabled():
            return
        for start, length, word in spell.words(text):
            if self.checker.is_misspelled(word):
                self.setFormat(start, length, self.fmt)


def word_at(cursor: QTextCursor) -> tuple[QTextCursor, str] | None:
    """The word under a cursor (a cursor that selects it, and its text), or None."""
    block = cursor.block()
    pos = cursor.position() - block.position()
    for start, length, word in spell.words(block.text()):
        if start <= pos <= start + length:
            c = QTextCursor(block)
            c.setPosition(block.position() + start)
            c.setPosition(block.position() + start + length, QTextCursor.KeepAnchor)
            return c, word
    return None


def add_spelling_actions(menu: QMenu, editor, cursor: QTextCursor, checker: spell.SpellChecker,
                         highlighter: SpellHighlighter | None = None) -> bool:
    """Put suggestions, Add to dictionary and Ignore all at the top of menu when the
    clicked word is misspelt. Returns True if anything was added."""
    hit = word_at(cursor) if cursor is not None else None
    if not hit or not checker.is_misspelled(hit[1]):
        return False
    sel, word = hit
    first = menu.actions()[0] if menu.actions() else None

    def add(action):
        if first is None:
            menu.addAction(action)
        else:
            menu.insertAction(first, action)
        return action

    def replace(text):
        c = QTextCursor(sel)
        c.insertText(text)
        editor.setTextCursor(c)

    def rehighlight():
        if highlighter is not None:
            highlighter.rehighlight()

    suggestions = checker.suggest_within(word)   # never blocks the menu for long
    if suggestions is None:
        a = add(_action(menu, tr("(still looking for suggestions; right-click again)")))
        a.setEnabled(False)
        suggestions = []
    elif not suggestions:
        a = add(_action(menu, tr("(no suggestions)")))
        a.setEnabled(False)
    for s in suggestions:
        a = add(_action(menu, s))
        f = a.font()
        f.setBold(True)
        a.setFont(f)
        a.triggered.connect(lambda _=False, t=s: replace(t))
    a = add(_action(menu, tr("Add to dictionary")))
    a.triggered.connect(lambda: (checker.add_word(word), rehighlight()))
    a = add(_action(menu, tr("Ignore all")))
    a.triggered.connect(lambda: (checker.ignore(word), rehighlight()))
    if first is not None:
        menu.insertSeparator(first)
    return True


def _action(menu: QMenu, text: str) -> QAction:
    return QAction(text, menu)
