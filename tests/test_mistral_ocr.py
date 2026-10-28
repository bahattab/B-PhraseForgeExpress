"""Mistral OCR: PDF / image to Markdown through the documented REST endpoint."""
import base64
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from phraseforge import mistral_ocr as mo  # noqa: E402

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def fake_response(*_):
    return {"pages": [
        {"index": 0, "markdown": "# Invoice\n\n![img-0.jpeg](img-0.jpeg)\n\n| a | b |\n|---|---|\n| 1 | 2 |",
         "images": [{"id": "img-0.jpeg", "image_base64": "data:image/jpeg;base64," + base64.b64encode(b"JPG").decode()}]},
        {"index": 1, "markdown": "مرحبا بالعالم", "images": []},
    ]}


def test_request_shape_for_pdf_and_image(tmp_path):
    pdf = tmp_path / "Report 2026.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    seen = {}

    def post(url, headers, payload):
        seen.update(url=url, headers=headers, payload=payload)
        return fake_response()
    md, pages = mo.ocr_file("k-123", pdf, post=post)
    assert seen["url"] == "https://api.mistral.ai/v1/ocr"
    assert seen["headers"]["Authorization"] == "Bearer k-123"
    p = seen["payload"]
    assert p["model"] == "mistral-ocr-latest" and p["include_image_base64"] is True
    assert p["document"]["type"] == "document_url"
    assert p["document"]["document_url"] == "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4 test").decode()
    # saved like the extension: folder named after the file, Markdown + images inside
    assert md == tmp_path / "Report-2026" / "Report-2026.md"
    text = md.read_text(encoding="utf-8")
    assert text.startswith("# Invoice") and "![img-0.jpeg](img-0.jpeg)" in text and "مرحبا بالعالم" in text
    assert (md.parent / "img-0.jpeg").read_bytes() == b"JPG" and len(pages) == 2
    img = tmp_path / "scan.png"
    img.write_bytes(PNG)
    doc = mo.document_for(img)
    assert doc["type"] == "image_url" and doc["image_url"].startswith("data:image/png;base64,")


def test_errors_and_safety(tmp_path):
    with pytest.raises(mo.MistralOCRError, match="API key is not set"):
        mo.run_ocr("", {"type": "image_url"}, post=fake_response)
    with pytest.raises(mo.MistralOCRError, match="not found"):
        mo.document_for(tmp_path / "missing.pdf")
    (tmp_path / "a.docx").write_bytes(b"x")
    with pytest.raises(mo.MistralOCRError, match="Only PDF"):
        mo.document_for(tmp_path / "a.docx")
    with pytest.raises(mo.MistralOCRError, match="no pages"):
        mo.run_ocr("k", {"type": "x"}, post=lambda *a: {"pages": []})
    # an image id with a path cannot write outside the result folder
    pages = [mo.OCRPage(0, "x", [("../../evil.png", b"E")])]
    md = mo.save_result(pages, tmp_path / "doc.pdf")
    assert (md.parent / "evil.png").exists() and not (tmp_path / "evil.png").exists()
    assert mo.safe_name("تقرير مالي 2026") == "تقرير-مالي-2026" and mo.safe_name("***")


def test_screen_capture_text_drops_image_links():
    text = mo.ocr_png_text("k", PNG, post=lambda u, h, p: (
        p["include_image_base64"] is False and p["document"]["type"] == "image_url") and fake_response())
    assert text.startswith("# Invoice") and "img-0" not in text and "مرحبا بالعالم" in text


def test_app_ocr_file_and_screen_engine(tmp_path):
    from phraseforge.app import PhraseForgeApp
    from phraseforge.db import Store
    store = Store(tmp_path / "m.db")
    notes = []

    class Fake:
        pass
    f = Fake()
    f.store = store
    f.tray = type("T", (), {"notify": lambda _s, t, m: notes.append((t, m))})()
    f.poster = type("P", (), {"posted": type("S", (), {"emit": staticmethod(lambda fn: fn())})()})()
    f.shown = 0
    f.show_settings = lambda: setattr(f, "shown", f.shown + 1)
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF")
    assert PhraseForgeApp.ocr_file(f, str(pdf), post=lambda *a: fake_response()) is None   # no key yet
    assert f.shown == 1 and "API key" in notes[-1][1]
    store.set_setting("ai.mistral_key", "k")
    md = PhraseForgeApp.ocr_file(f, str(pdf), post=lambda *a: fake_response(), open_result=False)
    assert md is not None and md.exists() and "2 page(s)" in notes[-1][1]
    assert store.setting("ai.mistral_key") == "k"
    raw = store.conn.execute("SELECT value FROM settings WHERE key='ai.mistral_key'").fetchone()[0]
    assert raw != "k"                                   # stored encrypted like the other keys
    store.close()
