"""OCR PDF / image without a cloud service.

Tools > OCR PDF / image uses Mistral OCR when a Mistral key is set. Without one, this
module does the work on the PC:

- PDF pages that already contain text (most PDFs made from documents) give their text
  directly through Qt's PDF module.
- Scanned PDF pages and image files are rendered to images and read with the OCR engine
  built into Windows (the same engine as screen OCR).

The result is saved like Mistral's: "<folder named after the file>/<name>.md".
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from phraseforge.mistral_ocr import IMAGE_TYPES, OCRPage, save_result

RENDER_DPI = 200          # good accuracy for Windows OCR, still fast
MAX_PAGES = 300


class LocalOCRError(RuntimeError):
    pass


def _png_of(image) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    image.save(buf, "PNG")
    buf.close()
    return bytes(data)


def _image_pages(path: Path) -> list[tuple[str, bytes]]:
    from PySide6.QtGui import QImage
    img = QImage(str(path))
    if img.isNull():
        raise LocalOCRError(f"The image could not be opened: {path.name}")
    return [("", _png_of(img))]


def _pdf_pages(path: Path) -> list[tuple[str, bytes]]:
    """(text layer, page image) per page; the image is rendered only when there is no text."""
    from PySide6.QtCore import QSize
    from PySide6.QtPdf import QPdfDocument
    doc = QPdfDocument()
    err = doc.load(str(path))
    if err != QPdfDocument.Error.None_:
        if err == QPdfDocument.Error.IncorrectPassword:
            raise LocalOCRError("The PDF is protected with a password.")
        raise LocalOCRError(f"The PDF could not be opened ({err.name}).")
    n = doc.pageCount()
    if n > MAX_PAGES:
        raise LocalOCRError(f"The PDF has {n} pages; at most {MAX_PAGES} can be read at once.")
    out = []
    for i in range(n):
        text = (doc.getAllText(i).text() or "").strip()
        if text:
            out.append((text, b""))
            continue
        pt = doc.pagePointSize(i)
        size = QSize(max(1, int(pt.width() * RENDER_DPI / 72)), max(1, int(pt.height() * RENDER_DPI / 72)))
        out.append(("", _png_of(doc.render(i, size))))
    doc.close()
    return out


def read_pages(path: str | Path) -> list[tuple[str, bytes]]:
    p = Path(path)
    if not p.is_file():
        raise LocalOCRError(f"File not found: {p}")
    ext = p.suffix.lower()
    if ext == ".pdf":
        return _pdf_pages(p)
    if ext in IMAGE_TYPES:
        return _image_pages(p)
    raise LocalOCRError("Only PDF files and images can be read.")


def ocr_file(path: str | Path, ocr_png: Callable[[bytes], str], out_root=None) -> tuple[Path, list[OCRPage]]:
    """PDF or image -> saved Markdown (see mistral_ocr.save_result). ocr_png reads one page image."""
    raw = read_pages(path)
    pages = []
    for i, (text, png) in enumerate(raw):
        if not text and png:
            text = (ocr_png(png) or "").strip()
        md = text
        if len(raw) > 1:
            md = f"## Page {i + 1}\n\n{text}" if text else f"## Page {i + 1}\n\n(no text found)"
        pages.append(OCRPage(i, md))
    if not any(p.markdown.strip() for p in pages) or all("(no text found)" in p.markdown for p in pages):
        raise LocalOCRError("No text was found in the file.")
    return save_result(pages, path, out_root), pages
