"""Export phrases as a Word document (.docx) or a PDF, with Arabic right to left.

DOCX is written directly as Office Open XML (no extra library): each paragraph whose
first letter is Arabic/Hebrew gets <w:bidi/> and its runs <w:rtl/>, so Word shows it
right to left. PDF is drawn by Qt (QTextDocument + QPdfWriter), which shapes Arabic
letters; paragraphs carry dir="rtl" the same way.
"""
from __future__ import annotations

import html as _html
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape as _xml

from phraseforge.db import Store
from phraseforge.models import Phrase, TriggerKind


def is_rtl(text: str) -> bool:
    for ch in text or "":
        d = unicodedata.bidirectional(ch)
        if d in ("R", "AL"):
            return True
        if d == "L":
            return False
    return False


def plain_text(content: str, fmt: str) -> str:
    """Phrase content as plain text: HTML tags removed, '{{' shown as '{'."""
    if fmt == "html" or re.search(r"(?i)</?(p|br|div|b|i|span)\b", content or "") and fmt != "text":
        content = re.sub(r"(?i)<br\s*/?>", "\n", content or "")
        content = re.sub(r"(?i)</(p|div|li|h\d)>", "\n", content)
        content = re.sub(r"(?is)<(style|script)[^>]*>.*?</\1>", "", content)
        content = _html.unescape(re.sub(r"<[^>]+>", "", content))
    return (content or "").replace("{{", "{").strip("\n")


@dataclass
class Entry:
    folder: str
    description: str
    triggers: list[tuple[str, str]]               # (label, value)
    text: str
    versions: list[tuple[str, str]] = field(default_factory=list)   # (language, text)


LABELS = {
    "en": {"title": "Phrases", "autotext": "Autotext", "hotkey": "Hotkey", "folder": "Folder",
           "created": "Created", "count": "phrases", "version": "Version",
           "nofolder": "Not in a folder"},
    "ar": {"title": "العبارات", "autotext": "الاختصار", "hotkey": "مفتاح الاختصار", "folder": "المجلد",
           "created": "تاريخ الإنشاء", "count": "عبارة", "version": "النسخة",
           "nofolder": "خارج المجلدات"},
}


def collect(store: Store, phrases: list[Phrase], language: str = "",
            include_versions: bool = True) -> list[Entry]:
    from phraseforge.io_formats import folder_path
    out = []
    for p in phrases:
        if p is None:
            continue
        content, fmt = store.phrase_text(p, language) if language else (p.content, p.content_format)
        trig = []
        for t in p.triggers:
            if t.enabled and t.value:
                trig.append(("hotkey" if t.kind == TriggerKind.HOTKEY else "autotext", t.value))
        versions = []
        if include_versions:
            for lang, (vtext, vfmt) in sorted(store.phrase_versions(p.id).items()):
                if lang != language:
                    versions.append((lang, plain_text(vtext, vfmt)))
        out.append(Entry(folder_path(store, p.folder_id), p.description, trig, plain_text(content, fmt), versions))
    return out


def _header(entries: list[Entry], ui_lang: str, title: str | None) -> tuple[str, str]:
    lab = LABELS.get(ui_lang, LABELS["en"])
    head = title or lab["title"]
    # LRM marks keep the date and the count in reading order inside Arabic text
    sub = f"{lab['created']}: \u200e{datetime.now():%Y-%m-%d %H:%M}\u200e · {len(entries)} {lab['count']}"
    return head, sub


# ------------------------------------------------------------------ DOCX
def _run(text: str, rtl: bool, bold=False, size=None, color=None, italic=False) -> str:
    props = []
    if bold:
        props += ["<w:b/>", "<w:bCs/>"]
    if italic:
        props += ["<w:i/>", "<w:iCs/>"]
    if color:
        props.append(f'<w:color w:val="{color}"/>')
    if size:
        props += [f'<w:sz w:val="{size}"/>', f'<w:szCs w:val="{size}"/>']
    if rtl:
        props.append("<w:rtl/>")
    rpr = f"<w:rPr>{''.join(props)}</w:rPr>" if props else ""
    parts = []
    for i, line in enumerate(text.split("\n")):
        if i:
            parts.append("<w:br/>")
        parts.append(f'<w:t xml:space="preserve">{_xml(line)}</w:t>')
    return f"<w:r>{rpr}{''.join(parts)}</w:r>"


def _para(text: str, style: str | None = None, bold=False, size=None, color=None, italic=False,
          force_rtl: bool | None = None) -> str:
    rtl = is_rtl(text) if force_rtl is None else force_rtl
    ppr = []
    if style:
        ppr.append(f'<w:pStyle w:val="{style}"/>')
    if rtl:
        ppr.append("<w:bidi/>")
    p = f"<w:pPr>{''.join(ppr)}</w:pPr>" if ppr else ""
    return f"<w:p>{p}{_run(text, rtl, bold, size, color, italic)}</w:p>"


_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Arial"/>
<w:sz w:val="22"/><w:szCs w:val="22"/><w:lang w:val="en-US" w:bidi="ar-SA"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="80"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/>
<w:pPr><w:spacing w:after="120"/></w:pPr><w:rPr><w:b/><w:bCs/><w:sz w:val="40"/><w:szCs w:val="40"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>
<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="80"/><w:outlineLvl w:val="0"/></w:pPr>
<w:rPr><w:b/><w:bCs/><w:color w:val="2B579A"/><w:sz w:val="30"/><w:szCs w:val="30"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/>
<w:pPr><w:keepNext/><w:spacing w:before="160" w:after="40"/><w:outlineLvl w:val="1"/></w:pPr>
<w:rPr><w:b/><w:bCs/><w:sz w:val="25"/><w:szCs w:val="25"/></w:rPr></w:style>
</w:styles>"""

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""

_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""


def _core(title: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f"<dc:title>{_xml(title)}</dc:title><dc:creator>PhraseForge</dc:creator>"
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created></cp:coreProperties>')


def export_docx(entries: list[Entry], path: str | Path, ui_lang: str = "en", title: str | None = None) -> int:
    lab = LABELS.get(ui_lang, LABELS["en"])
    head, sub = _header(entries, ui_lang, title)
    rtl_ui = ui_lang == "ar"
    body = [_para(head, "Title", force_rtl=rtl_ui or None), _para(sub, color="666666", force_rtl=rtl_ui or None)]
    folder = None
    for e in entries:
        if e.folder != folder:
            folder = e.folder
            body.append(_para(folder or lab["nofolder"], "Heading1", force_rtl=is_rtl(folder) or (rtl_ui and not folder)))
        body.append(_para(e.description or "-", "Heading2"))
        for kind, value in e.triggers:
            line = f"{lab[kind]}: {value}"
            body.append(_para(line, color="2B579A", size=20, force_rtl=rtl_ui))
        if e.text:
            for chunk in e.text.split("\n\n"):
                body.append(_para(chunk))
        for lang, text in e.versions:
            body.append(_para(f"{lab['version']} \u200e{lang}\u200e:", italic=True, color="666666", size=20, force_rtl=rtl_ui))
            for chunk in text.split("\n\n"):
                body.append(_para(chunk))
    sect = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" w:header="567" w:footer="567" w:gutter="0"/>'
            + ("<w:bidi/>" if rtl_ui else "") + "</w:sectPr>")
    doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f"<w:body>{''.join(body)}{sect}</w:body></w:document>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", _STYLES)
        z.writestr("docProps/core.xml", _core(head))
    return len(entries)


# ------------------------------------------------------------------ PDF
def to_html(entries: list[Entry], ui_lang: str = "en", title: str | None = None) -> str:
    lab = LABELS.get(ui_lang, LABELS["en"])
    head, sub = _header(entries, ui_lang, title)

    def p(text: str, tag: str = "p", style: str = "", rtl: bool | None = None) -> str:
        r = is_rtl(text) if rtl is None else rtl
        attrs = f' dir="{"rtl" if r else "ltr"}" align="{"right" if r else "left"}"'
        if style:
            attrs += f' style="{style}"'
        return f"<{tag}{attrs}>{_html.escape(text).replace(chr(10), '<br>')}</{tag}>"

    rtl_ui = ui_lang == "ar"
    out = [p(head, "h1", rtl=rtl_ui or None), p(sub, style="color:#666666", rtl=rtl_ui or None)]
    folder = None
    for e in entries:
        if e.folder != folder:
            folder = e.folder
            out.append(p(folder or lab["nofolder"], "h2", "color:#2B579A", rtl=is_rtl(folder) or (rtl_ui and not folder)))
        out.append(p(e.description or "-", "h3"))
        for kind, value in e.triggers:
            out.append(p(f"{lab[kind]}: {value}", style="color:#2B579A;font-size:9pt", rtl=rtl_ui))
        for chunk in (e.text.split("\n\n") if e.text else []):
            out.append(p(chunk))
        for lang, text in e.versions:
            out.append(p(f"{lab['version']} \u200e{lang}\u200e:", style="color:#666666;font-style:italic;font-size:9pt", rtl=rtl_ui))
            for chunk in text.split("\n\n"):
                out.append(p(chunk))
    return ("<html><body style=\"font-family:'Segoe UI','Arial';font-size:10.5pt\">"
            + "".join(out) + "</body></html>")


def export_pdf(entries: list[Entry], path: str | Path, ui_lang: str = "en", title: str | None = None) -> int:
    from PySide6.QtCore import QMarginsF
    from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument
    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setPageMargins(QMarginsF(18, 18, 18, 18), QPageLayout.Millimeter)
    writer.setTitle(_header(entries, ui_lang, title)[0])
    writer.setCreator("PhraseForge")
    doc = QTextDocument()
    doc.setHtml(to_html(entries, ui_lang, title))
    doc.print_(writer)
    return len(entries)


def export(store: Store, phrases: list[Phrase], path: str | Path, ui_lang: str = "en",
           language: str = "", include_versions: bool = True) -> int:
    """Write .docx or .pdf by the file extension."""
    entries = collect(store, phrases, language, include_versions)
    ext = Path(path).suffix.lower()
    if ext == ".docx":
        return export_docx(entries, path, ui_lang)
    if ext == ".pdf":
        return export_pdf(entries, path, ui_lang)
    raise ValueError(f"Unsupported document type: {ext}")
