"""Microsoft OneNote integration through OneNote's official COM API (desktop OneNote).

Uses the documented OneNote.Application interface (GetHierarchy, GetPageContent,
UpdatePageContent, CreateNewPage, GetSpecialLocation, NavigateTo). No reverse
engineering: the type library is loaded from ONENOTE.EXE's own resource #3,
because Office Click-to-Run registers it for 32-bit only and a 64-bit process
would otherwise get "Library not registered".

The XML helpers (parse_hierarchy, page_text_from_xml, outline_xml, ...) are pure
functions so they can be tested without OneNote.
"""
from __future__ import annotations

import base64
import html
import os
import re
import threading
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

NS = "http://schemas.microsoft.com/office/onenote/2013/onenote"
_N = f"{{{NS}}}"
DEFAULT_EXE = r"C:\Program Files\Microsoft Office\root\Office16\ONENOTE.EXE"
CAPTURE_EXE = r"C:\Program Files\Microsoft Office\root\Office16\onenotecapture.exe"

# OneNote enums (documented in the OneNote 2013 developer reference)
HS_PAGES = 4               # HierarchyScope.hsPages
XS_2013 = 2                # XMLSchema.xs2013
PI_BASIC = 0               # PageInfo.piBasic
SL_UNFILED_NOTES = 2       # SpecialLocation.slUnfiledNotesSection
NPS_DEFAULT = 0            # NewPageStyle.npsDefault


class OneNoteError(RuntimeError):
    pass


@dataclass
class Node:
    id: str
    name: str
    kind: str                       # notebook | group | section | page
    path: str = ""                  # "Notebook/Group/Section/Page"
    children: list["Node"] = field(default_factory=list)
    level: int = 1                  # page indentation level (sub-pages)

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


# ---------------------------------------------------------------- pure XML helpers
_KIND = {"Notebook": "notebook", "SectionGroup": "group", "Section": "section", "Page": "page"}


def parse_hierarchy(xml: str) -> list[Node]:
    """GetHierarchy XML -> notebook trees (recycle bins are skipped)."""
    root = ET.fromstring(xml)

    def build(el, parent_path: str) -> Node | None:
        tag = el.tag.replace(_N, "")
        kind = _KIND.get(tag)
        if not kind or el.get("isRecycleBin") == "true" or el.get("isInRecycleBin") == "true":
            return None
        name = el.get("name", "")
        path = f"{parent_path}/{name}" if parent_path else name
        n = Node(el.get("ID", ""), name, kind, path, level=int(el.get("pageLevel", "1") or 1))
        for child in el:
            c = build(child, path)
            if c is not None:
                n.children.append(c)
        return n

    return [n for n in (build(el, "") for el in root) if n is not None]


def flatten(nodes: list[Node], kind: str | None = None) -> list[Node]:
    out = []
    for n in nodes:
        for x in n.walk():
            if kind is None or x.kind == kind:
                out.append(x)
    return out


def find(nodes: list[Node], ref: str, kind: str | None = None) -> Node | None:
    """Find by OneNote ID or by path ("Notebook/Section/Page", case-insensitive, '\\' allowed)."""
    if not ref:
        return None
    want = ref.replace("\\", "/").strip("/").lower()
    for n in flatten(nodes, kind):
        if n.id == ref or n.path.lower() == want:
            return n
    # a unique page/section name also works
    hits = [n for n in flatten(nodes, kind) if n.name.lower() == want]
    return hits[0] if len(hits) == 1 else None


def _strip_html(s: str) -> str:
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s)


def page_text_from_xml(xml: str, include_title: bool = False, include_ocr: bool = False) -> tuple[str, str]:
    """GetPageContent XML -> (title, text). Each OE paragraph becomes a line; tables cells tab-separated.
    include_ocr adds the text OneNote recognised in images (OCRText) on its own line."""
    root = ET.fromstring(xml)
    title_el = root.find(f"{_N}Title")
    title = ""
    if title_el is not None:
        title = " ".join(_strip_html(t.text or "") for t in title_el.iter(f"{_N}T")).strip()
    lines: list[str] = []

    def oe_text(oe) -> str:
        parts = [_strip_html(t.text or "") for t in oe.findall(f"{_N}T")]
        tbl = oe.find(f"{_N}Table")
        if tbl is not None:
            for row in tbl.findall(f"{_N}Row"):
                cells = []
                for cell in row.findall(f"{_N}Cell"):
                    cells.append(" ".join(_strip_html(t.text or "") for t in cell.iter(f"{_N}T")).strip())
                lines.append("\t".join(cells))
        return "".join(parts)

    def walk(container) -> None:
        """Paragraphs in document order; table cells are handled by oe_text, not walked again."""
        for oe in container.findall(f"{_N}OE"):
            if oe.find(f"{_N}T") is not None:
                lines.append(oe_text(oe))
            elif oe.find(f"{_N}Table") is not None:
                oe_text(oe)
            elif include_ocr:
                for ocr in oe.iter(f"{_N}OCRText"):
                    if (ocr.text or "").strip():
                        lines.append(ocr.text.strip())
            for kids in oe.findall(f"{_N}OEChildren"):     # indented sub-paragraphs
                walk(kids)

    for outline in root.findall(f"{_N}Outline"):
        for kids in outline.findall(f"{_N}OEChildren"):
            walk(kids)
        lines.append("")                         # blank line between outlines
    text = "\n".join(lines).strip("\n")
    if include_title and title:
        text = f"{title}\n\n{text}" if text else title
    return title, text


def _cdata(s: str) -> str:
    return "<![CDATA[" + s.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def outline_xml(text: str = "", image_png: bytes | None = None) -> str:
    """One OneNote outline (text box): one paragraph per line, optional image first."""
    oes = []
    if image_png:
        b64 = base64.b64encode(image_png).decode("ascii")
        oes.append(f'<one:OE><one:Image format="png"><one:Data>{b64}</one:Data></one:Image></one:OE>')
    for line in (text or "").replace("\r\n", "\n").split("\n"):
        oes.append(f"<one:OE><one:T>{_cdata(html.escape(line, quote=False))}</one:T></one:OE>")
    return f"<one:Outline><one:OEChildren>{''.join(oes)}</one:OEChildren></one:Outline>"


def page_update_xml(page_id: str, text: str = "", image_png: bytes | None = None, title: str | None = None) -> str:
    """UpdatePageContent XML that adds a new outline (and optionally sets the title)."""
    t = ""
    if title is not None:
        t = f"<one:Title><one:OE><one:T>{_cdata(html.escape(title, quote=False))}</one:T></one:OE></one:Title>"
    return (f'<?xml version="1.0"?><one:Page xmlns:one="{NS}" ID="{html.escape(page_id)}">'
            f"{t}{outline_xml(text, image_png)}</one:Page>")


# ---------------------------------------------------------------- COM client
_tls = threading.local()


def _com_app(exe: str = DEFAULT_EXE):
    """OneNote.Application for the current thread (COM objects are per apartment)."""
    app = getattr(_tls, "app", None)
    if app is not None:
        return app
    try:
        import comtypes
        import comtypes.client
        from comtypes.typeinfo import LoadTypeLibEx
    except ImportError as e:
        raise OneNoteError("The 'comtypes' package is missing (pip install comtypes).") from e
    try:
        comtypes.CoInitialize()
    except OSError:
        pass  # already initialised on this thread
    if not Path(exe).is_file():
        raise OneNoteError(f"OneNote desktop app not found: {exe}")
    try:
        mod = comtypes.client.GetModule(LoadTypeLibEx(exe + "\\3"))
        app = comtypes.client.CreateObject("OneNote.Application", interface=mod.IApplication)
    except Exception as e:
        raise OneNoteError(f"Could not connect to OneNote: {e}") from e
    _tls.app = app
    return app


class OneNote:
    def __init__(self, exe: str = "", app=None):
        self.exe = exe or DEFAULT_EXE
        self._app = app                      # tests pass a fake

    @property
    def app(self):
        return self._app or _com_app(self.exe)

    def available(self) -> bool:
        try:
            self.app.GetSpecialLocation(SL_UNFILED_NOTES)
            return True
        except Exception:
            return False

    # ---- reading
    def notebooks(self) -> list[Node]:
        return parse_hierarchy(self.app.GetHierarchy("", HS_PAGES, XS_2013))

    def page_xml(self, page_id: str) -> str:
        return self.app.GetPageContent(page_id, PI_BASIC, XS_2013)

    def page_text(self, ref: str, include_title: bool = False, nodes: list[Node] | None = None,
                  include_ocr: bool = False) -> str:
        node = find(nodes or self.notebooks(), ref, "page")
        if node is None:
            raise OneNoteError(f"OneNote page not found: {ref}")
        return page_text_from_xml(self.page_xml(node.id), include_title, include_ocr)[1]

    # ---- writing
    def quick_notes_section(self) -> str:
        """Section ID of OneNote's Quick Notes (GetSpecialLocation returns its file path)."""
        path = self.app.GetSpecialLocation(SL_UNFILED_NOTES)
        return self.app.OpenHierarchy(path, "", 0)          # CreateFileType.cftNone

    def create_page(self, section_id: str, title: str, text: str = "", image_png: bytes | None = None) -> str:
        page_id = self.app.CreateNewPage(section_id, NPS_DEFAULT)
        self.app.UpdatePageContent(page_update_xml(page_id, text, image_png, title=title), 0, XS_2013, False)
        return page_id

    def append(self, page_id: str, text: str = "", image_png: bytes | None = None) -> None:
        self.app.UpdatePageContent(page_update_xml(page_id, text, image_png), 0, XS_2013, False)

    def send(self, text: str = "", image_png: bytes | None = None, target: str = "", title: str = "") -> str:
        """Send text/image to OneNote. target: page path/ID (append), section path/ID (new page),
        or "" for a new page in Quick Notes. Returns the page ID."""
        if target:
            nodes = self.notebooks()
            node = find(nodes, target)
            if node is None:
                raise OneNoteError(f"OneNote page or section not found: {target}")
            if node.kind == "page":
                self.append(node.id, text, image_png)
                return node.id
            if node.kind == "section":
                return self.create_page(node.id, title or _title_from(text), text, image_png)
            raise OneNoteError("Choose a OneNote page or section (not a notebook or group).")
        return self.create_page(self.quick_notes_section(), title or _title_from(text), text, image_png)

    def navigate(self, object_id: str) -> None:
        self.app.NavigateTo(object_id, "", False)


def _title_from(text: str) -> str:
    first = next((l.strip() for l in (text or "").splitlines() if l.strip()), "")
    return (first[:60] + "...") if len(first) > 60 else (first or "PhraseForge")


def capture_exe() -> str:
    return CAPTURE_EXE if os.path.isfile(CAPTURE_EXE) else ""
