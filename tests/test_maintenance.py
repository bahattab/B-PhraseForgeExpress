"""Maintenance tools: duplicates, backup compare, check and compact (G-27, FR-UI-01)."""
import pytest

from phraseforge import io_formats, maintenance, vault
from phraseforge.db import Store
from phraseforge.models import Folder, Phrase, Trigger, TriggerKind


def at(v):
    return Trigger(TriggerKind.AUTOTEXT, v)


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "p.db")
    yield s
    s.close()


def test_duplicates_by_text_anywhere_and_by_abbreviation(store):
    a = store.add_folder(Folder("A"))
    b = store.add_folder(Folder("B"))
    p1 = store.add_phrase(Phrase("Sig 1", "Best regards\nAna  ", folder_id=a.id))
    p2 = store.add_phrase(Phrase("Sig 2", "Best regards\nAna", folder_id=b.id))   # trailing spaces ignored
    store.add_phrase(Phrase("Other", "Kind regards", folder_id=b.id))
    x = store.add_phrase(Phrase("X", "x", triggers=[at("brb")]))
    y = store.add_phrase(Phrase("Y", "y", triggers=[at("BRB")], enabled=False))      # also switched-off ones
    store.add_phrase(Phrase("Empty 1", ""))
    store.add_phrase(Phrase("Empty 2", ""))
    groups = maintenance.find_duplicates(store)
    kinds = {(g.kind, tuple(g.phrase_ids)) for g in groups}
    assert ("content", (p1.id, p2.id)) in kinds
    assert ("autotext", (x.id, y.id)) in kinds
    assert len(groups) == 2                          # empty phrases are not duplicates of each other


def test_compare_a_backup_with_now_and_bring_a_phrase_back(store, tmp_path):
    f = store.add_folder(Folder("Mail"))
    keep = store.add_phrase(Phrase("Keep", "same", folder_id=f.id))
    edit = store.add_phrase(Phrase("Edit", "old text", folder_id=f.id, triggers=[at("ed")]))
    gone = store.add_phrase(Phrase("Gone", "bye", folder_id=f.id, triggers=[at("gn")]))
    backup = io_formats.backup(store, tmp_path / "backups")
    edit.content = "new text"
    store.update_phrase(edit)
    store.delete_phrase(gone.id)
    store.add_phrase(Phrase("New", "fresh"))
    changes = maintenance.compare(backup, store)
    got = [(c.kind, c.description, c.folder, c.fields) for c in changes]
    assert got == [("removed", "Gone", "Mail", []), ("changed", "Edit", "Mail", ["text"]),
                   ("added", "New", "", [])]
    removed = changes[0]
    p = maintenance.restore_phrase(store, removed)
    assert (p.content, [t.value for t in p.triggers]) == ("bye", ["gn"])
    assert store.quarantine_origin(p.id) == "imported"            # from a file: needs approval again
    old_edit = maintenance.restore_phrase(store, changes[1])
    assert old_edit.content == "old text" and old_edit.triggers == []   # the current one keeps "ed"
    assert keep.id                                                 # untouched phrases are not listed


def test_compare_two_backups_and_an_encrypted_one(store, tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "FAKE_DPAPI_FOR_TESTS", True)
    store.add_phrase(Phrase("One", "1"))
    b1 = io_formats.backup(store, tmp_path / "b")
    store.add_phrase(Phrase("Two", "2"))
    b2 = io_formats.backup(store, tmp_path / "b2")
    assert [(c.kind, c.description) for c in maintenance.compare(b1, b2)] == [("added", "Two")]
    store.enable_encryption()
    b3 = io_formats.backup(store, tmp_path / "b3")
    assert vault.is_encrypted(b3)
    store.add_phrase(Phrase("Three", "3"))
    assert [(c.kind, c.description) for c in maintenance.compare(b3, store)] == [("added", "Three")]


def test_check_and_compact(store, monkeypatch):
    for i in range(300):
        store.add_phrase(Phrase(f"P{i}", "x" * 2000))
    for p in store.phrases():
        store.delete_phrase(p.id)
    assert maintenance.check(store) == []
    before, after = maintenance.compact(store)
    assert after < before


def test_compact_an_encrypted_phrase_file(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "FAKE_DPAPI_FOR_TESTS", True)
    s = Store(tmp_path / "e.db")
    s.enable_encryption()
    for i in range(200):
        s.add_phrase(Phrase(f"P{i}", "y" * 2000))
    for p in s.phrases()[:190]:
        s.delete_phrase(p.id)
    s.flush()
    size_before = (tmp_path / "e.db").stat().st_size
    maintenance.compact(s)
    assert (tmp_path / "e.db").stat().st_size < size_before and vault.is_encrypted(tmp_path / "e.db")
    s.close()
    assert len(Store(tmp_path / "e.db").phrases()) == 10


def test_dialog(store, tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from phraseforge.ui.maintenance_dialog import MaintenanceDialog
    store.add_phrase(Phrase("A", "same"))
    store.add_phrase(Phrase("B", "same"))
    io_formats.backup(store, tmp_path / "bk")
    store.add_phrase(Phrase("C", "c"))
    d = MaintenanceDialog(store, backup_dir=str(tmp_path / "bk"))
    assert d.dups.topLevelItemCount() == 1
    d.compare()
    assert d.cmp.topLevelItemCount() == 1 and "1 added" in d.cmp_count.text()
    d.check()
    assert "good order" in d.db_result.text()
    d.deleteLater()
