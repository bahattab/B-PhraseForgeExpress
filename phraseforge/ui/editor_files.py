"""Bring a Markdown, Word, RTF or text file into the phrase editor (PRD G-21, FR-EDT-02).

Markdown keeps its formatting (Qt's CommonMark/GitHub reader); Word and RTF come in as
their text (importers/files.py), as the import does.

The file is untrusted: Markdown images are dropped unless they are data: images (a local or
\\server path would be opened by Qt, and a UNC path sends the Windows login to that server),
and links keep only http, https and mailto targets. Macros the file contains make the phrase
"imported" again (PhraseEditor.insert_document), so privileged ones ask before they run.
"""
from __future__ import annotations

import re
from pathlib import Path

_IMG = re.compile(r"<img\b[^>]*>", re.I)
_SRC = re.compile(r"""\bsrc\s*=\s*["']\s*data:image/""", re.I)
_HREF = re.compile(r"""\bhref\s*=\s*(["'])(.*?)\1""", re.I | re.S)
SAFE_LINK = ("http://", "https://", "mailto:")

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
        return clean_html(_body(doc.toHtml())), True
    if ext in (".docx", ".docm", ".rtf"):
        from phraseforge.importers.files import file_text
        return file_text(p), False
    if ext in (".txt", ""):
        return p.read_text(encoding="utf-8-sig", errors="replace"), False
    raise ValueError(f"{ext} files cannot be inserted; use Markdown, Word, RTF or text.")


def clean_html(html: str) -> str:
    """Drop images that are not data: images and link targets other than http(s)/mailto."""
    html = _IMG.sub(lambda m: m.group(0) if _SRC.search(m.group(0)) else "", html)

    def href(m):
        url = m.group(2).strip()
        return m.group(0) if url.lower().startswith(SAFE_LINK) else 'href=""'
    return _HREF.sub(href, html)


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
