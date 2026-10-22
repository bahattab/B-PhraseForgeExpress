"""Import OneNote notebooks / section groups / sections as PhraseForge folders.

Each section group and section becomes a folder; each page becomes a phrase whose
description is the page title and whose content is the page text (via the official
OneNote COM API in phraseforge.onenote). Sub-pages are kept flat in their section.
Run off the UI thread: reading 1,000+ pages takes a while.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from phraseforge.db import Store
from phraseforge.models import Folder, Phrase
from phraseforge.onenote import Node, OneNote, find, page_text_from_xml


@dataclass
class OneNoteImportReport:
    imported: int = 0
    folders: int = 0
    skipped_empty: int = 0
    folder_id: int | None = None          # top folder created for the import
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False


def _count_pages(node: Node) -> int:
    return sum(1 for n in node.walk() if n.kind == "page")


def import_nodes(store: Store, client: OneNote, refs: list[str], include_ocr: bool = False,
                 progress: Callable[[int, int, str], bool | None] | None = None,
                 skip_empty: bool = True, into_folder_id: int | None = None) -> OneNoteImportReport:
    """Import the given notebooks/groups/sections (OneNote IDs or paths).

    progress(done, total, page_path) is called per page; returning False cancels.
    A top folder "OneNote" groups everything when more than one ref is imported.
    """
    rep = OneNoteImportReport()
    tree = client.notebooks()
    nodes: list[Node] = []
    for ref in refs:
        n = find(tree, ref)
        if n is None:
            rep.errors.append(f"Not found: {ref}")
        elif n.kind == "page":
            rep.errors.append(f"Choose sections, not single pages: {ref}")
        else:
            nodes.append(n)
    # drop nodes already inside another selected node
    ids = {n.id for n in nodes}
    nodes = [n for n in nodes if not any(a.id in ids and a.id != n.id and n in list(a.walk()) for a in nodes)]
    if not nodes:
        return rep
    total = sum(_count_pages(n) for n in nodes)
    done = 0
    parent = into_folder_id
    if len(nodes) > 1:
        top = store.add_folder(Folder("OneNote", parent_id=into_folder_id))
        rep.folders += 1
        parent = top.id
        rep.folder_id = top.id

    def add_container(n: Node, parent_id: int | None) -> bool:
        nonlocal done
        f = store.add_folder(Folder(n.name or "(untitled)", parent_id=parent_id))
        rep.folders += 1
        if rep.folder_id is None:
            rep.folder_id = f.id
        sort = 0
        for child in n.children:
            if child.kind in ("group", "section", "notebook"):
                if not add_container(child, f.id):
                    return False
                continue
            # page
            done += 1
            if progress is not None and progress(done, total, child.path) is False:
                rep.cancelled = True
                return False
            try:
                title, text = page_text_from_xml(client.page_xml(child.id), include_ocr=include_ocr)
            except Exception as e:  # one unreadable page must not stop the import
                rep.errors.append(f"{child.path}: {e}")
                continue
            if skip_empty and not text.strip():
                rep.skipped_empty += 1
                continue
            sort += 1
            store.add_phrase(Phrase(title or child.name or "(untitled)", text, folder_id=f.id,
                                    sort=sort, tags=["onenote"],
                                    notes=f"Imported from OneNote: {child.path}"))
            rep.imported += 1
        return True

    for n in nodes:
        if not add_container(n, parent):
            break
    return rep
