"""Mistral OCR: PDF and image to Markdown with the Mistral AI OCR API (cloud).

PhraseForge's own version of the "Mistral OCR Unofficial" VS Code extension
(https://github.com/sldyns/mistral-ocr-unofficial, MIT): pick a PDF or image, send it to
Mistral's OCR, and save the Markdown of every page plus the images it found in a folder
named after the file. The extension ran a separate Python script with the mistralai package;
PhraseForge calls the documented REST endpoint directly (no extra program or package):

    POST https://api.mistral.ai/v1/ocr
    {"model": "mistral-ocr-latest",
     "document": {"type": "document_url", "document_url": "data:application/pdf;base64,..."},
     "include_image_base64": true}
    -> {"pages": [{"index": 0, "markdown": "...", "images": [{"id": "img-0.jpeg",
                                                               "image_base64": "data:image/jpeg;base64,..."}]}]}

The file is uploaded to Mistral's servers; the key is set in Settings > Screen OCR.
"""
from __future__ import annotations

import base64
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

OCR_URL = "https://api.mistral.ai/v1/ocr"
MODEL = "mistral-ocr-latest"
MAX_BYTES = 50 * 1024 * 1024          # Mistral's documented limit for one document
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
               ".bmp": "image/bmp", ".webp": "image/webp", ".tif": "image/tiff", ".tiff": "image/tiff",
               ".avif": "image/avif"}
FILE_FILTER = "PDF and images (*.pdf *.png *.jpg *.jpeg *.gif *.bmp *.webp *.tif *.tiff *.avif)"


class MistralOCRError(RuntimeError):
    pass


@dataclass
class OCRPage:
    index: int
    markdown: str
    images: list[tuple[str, bytes]] = field(default_factory=list)     # (id, image bytes)


def _data_url(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def document_for(path: str | Path | None = None, data: bytes | None = None, mime: str = "") -> dict:
    """The "document" part of the request for a PDF or image file (or raw bytes)."""
    if path is not None:
        p = Path(path)
        if not p.is_file():
            raise MistralOCRError(f"File not found: {p}")
        data = p.read_bytes()
        ext = p.suffix.lower()
        mime = "application/pdf" if ext == ".pdf" else IMAGE_TYPES.get(ext, "")
        if not mime:
            raise MistralOCRError("Only PDF files and images can be read.")
    if not data:
        raise MistralOCRError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise MistralOCRError("The file is larger than 50 MB, the limit of Mistral OCR.")
    if mime == "application/pdf":
        return {"type": "document_url", "document_url": _data_url(data, mime)}
    return {"type": "image_url", "image_url": _data_url(data, mime or "image/png")}


def _decode_image(b64: str) -> bytes:
    if "," in b64 and b64.startswith("data:"):
        b64 = b64.split(",", 1)[1]
    try:
        return base64.b64decode(b64)
    except ValueError:
        return b""


def parse_response(data: dict) -> list[OCRPage]:
    pages = []
    for i, p in enumerate(data.get("pages") or []):
        imgs = []
        for img in p.get("images") or []:
            raw = _decode_image(img.get("image_base64") or "")
            if raw and img.get("id"):
                imgs.append((str(img["id"]), raw))
        pages.append(OCRPage(int(p.get("index", i)), p.get("markdown") or "", imgs))
    if not pages:
        raise MistralOCRError(f"Mistral OCR returned no pages: {str(data)[:200]}")
    return pages


def run_ocr(api_key: str, document: dict, include_images: bool = True, post=None,
            timeout_s: float = 180) -> list[OCRPage]:
    """Call the OCR endpoint. post: test hook (url, headers, payload) -> JSON dict."""
    key = (api_key or "").strip()
    if not key:
        raise MistralOCRError("Mistral API key is not set (Settings > Screen OCR > Mistral OCR).")
    payload = {"model": MODEL, "document": document, "include_image_base64": bool(include_images)}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if post is None:
        def post(url, hdrs, body):
            import httpx
            from phraseforge.net import client_kwargs
            try:
                with httpx.Client(timeout=timeout_s, **client_kwargs()) as c:
                    r = c.post(url, headers=hdrs, json=body)
            except httpx.HTTPError as e:
                raise MistralOCRError(f"Mistral OCR could not be reached: {e}") from e
            if r.status_code == 401:
                raise MistralOCRError("Mistral rejected the API key (401). Check it in Settings > Screen OCR.")
            if r.status_code >= 400:
                raise MistralOCRError(f"Mistral OCR: HTTP {r.status_code}: {r.text[:300]}")
            return r.json()
    return parse_response(post(OCR_URL, headers, payload))


def markdown_of(pages: list[OCRPage]) -> str:
    """All pages as one Markdown text. Image links stay "![img-0.jpeg](img-0.jpeg)", which
    point to the images saved next to the Markdown file by save_result()."""
    return "\n\n".join(p.markdown.strip() for p in pages if p.markdown.strip())


def safe_name(stem: str) -> str:
    """Folder name for the results: letters (any language), digits, '-' and '_'."""
    s = re.sub(r"[^\w\s-]", "", stem, flags=re.UNICODE).strip()
    s = re.sub(r"[-\s]+", "-", s)
    return s or str(uuid.uuid4())


def save_result(pages: list[OCRPage], source: str | Path, out_root: str | Path | None = None) -> Path:
    """Save "<folder named after the file>/<name>.md" and its images next to the source file
    (like the extension). Returns the Markdown file's path."""
    src = Path(source)
    name = safe_name(src.stem)
    folder = Path(out_root or src.parent) / name
    folder.mkdir(parents=True, exist_ok=True)
    for p in pages:
        for img_id, raw in p.images:
            safe_id = Path(img_id).name                     # never write outside the folder
            (folder / safe_id).write_bytes(raw)
    md_path = folder / f"{name}.md"
    md_path.write_text(markdown_of(pages), encoding="utf-8")
    return md_path


def ocr_file(api_key: str, path: str | Path, out_root=None, post=None) -> tuple[Path, list[OCRPage]]:
    """PDF or image file -> saved Markdown folder (see save_result)."""
    pages = run_ocr(api_key, document_for(path), include_images=True, post=post)
    return save_result(pages, path, out_root), pages


def ocr_png_text(api_key: str, png: bytes, post=None) -> str:
    """Screen capture -> text (Settings > Screen OCR > engine "Mistral"). Markdown image
    references are dropped; headings and lists stay as Mistral wrote them."""
    pages = run_ocr(api_key, document_for(data=png, mime="image/png"), include_images=False, post=post)
    text = markdown_of(pages)
    return re.sub(r"!\[[^\]]*\]\([^)]*\)\s*", "", text).strip()
