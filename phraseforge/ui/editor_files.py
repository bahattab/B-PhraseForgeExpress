"""Bring a Markdown, Word, RTF or text file into the phrase editor (PRD G-21, FR-EDT-02).

Markdown keeps its formatting (Qt's CommonMark/GitHub reader); Word and RTF come in as
their text (importers/files.py), as the import does. Images and links in Markdown stay
references: nothing is fetched from the network.
"""
from __future__ import annotations

from pathlib import Path

MAX_FILE = 4 * 1024 * 1024
MARKDOWN = (".md", ".markdown", ".mdown")
FILTER = "Documents (*.md *.markdown *.docx *.docm *.rtf *.txt);;All files (*)"


def read_for_editor(path: str | Path) -> tuple[str, bool]:
    """(content, is_html) for a file. Raises ValueError for one that is too big or unknown."""
    p = Path(path)
    if p.stat().st_size > MAX_FILE:
        raise ValueError("The file is larger than 4 MB.")
    ext = p.suffix.lower()
    if ext in MARKDOWN:
        from PySide6.QtGui import QTextDocument
        doc = QTextDocument()
        doc.setMarkdown(p.read_text(encoding="utf-8-sig", errors="replace"))
        return _body(doc.toHtml()), True
    if ext in (".docx", ".docm", ".rtf"):
        from phraseforge.importers.files import file_text
        return file_text(p), False
    if ext in (".txt", ""):
        return p.read_text(encoding="utf-8-sig", errors="replace"), False
    raise ValueError(f"{ext} files cannot be inserted; use Markdown, Word, RTF or text.")


def markdown_to_plain(text: str) -> str:
    from PySide6.QtGui import QTextDocument
    doc = QTextDocument()
    doc.setMarkdown(text)
    return doc.toPlainText()


def _body(html: str) -> str:
    """The part of Qt's full HTML page that goes into an existing document."""
    lo = html.find("<body")
    if lo < 0:
        return html
    lo = html.find(">", lo) + 1
    hi = html.rfind("</body>")
    return html[lo:hi if hi > lo else len(html)]
