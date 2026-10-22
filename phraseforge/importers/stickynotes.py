"""Import Microsoft Sticky Notes into a PhraseForge folder (one phrase per note)."""
from __future__ import annotations

from dataclasses import dataclass

from phraseforge.db import Store
from phraseforge.models import Folder, Phrase
from phraseforge.stickynotes import StickyNote


@dataclass
class StickyImportReport:
    imported: int = 0
    folder_id: int | None = None


def import_notes(store: Store, notes: list[StickyNote], folder_name: str = "Sticky Notes",
                 into_folder_id: int | None = None) -> StickyImportReport:
    rep = StickyImportReport()
    notes = [n for n in notes if n.text.strip()]
    if not notes:
        return rep
    folder = store.add_folder(Folder(folder_name, parent_id=into_folder_id))
    rep.folder_id = folder.id
    for i, n in enumerate(notes, 1):
        when = n.updated.strftime("%Y-%m-%d %H:%M") if n.updated else ""
        store.add_phrase(Phrase(n.title, n.text, folder_id=folder.id, sort=i, tags=["sticky-notes"],
                                notes=f"Imported from Sticky Notes{(' (updated ' + when + ' UTC)') if when else ''}"))
        rep.imported += 1
    return rep
