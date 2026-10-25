"""PhraseExpress folder menu > Bulk edit and Sort (observed in PhraseExpress 18.0.84)."""
import pytest

from phraseforge import bulk_edit
from phraseforge.db import Store
from phraseforge.models import Folder, Phrase, Trigger, TriggerKind


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def _setup(store):
    f = store.add_folder(Folder("F"))
    a = store.add_phrase(Phrase("alpha ", "  text one  ", folder_id=f.id, triggers=[Trigger(TriggerKind.AUTOTEXT, "ao")]))
    b = store.add_phrase(Phrase("Beta", "<p>Rich <b>two</b></p>", folder_id=f.id, content_format="html"))
    other = store.add_phrase(Phrase("outside", "x"))
    return f, a, b, other


def test_text_ops_on_each_target(store):
    f, a, b, other = _setup(store)
    assert bulk_edit.apply_text_op(store, f.id, "description", "strip_trailing") == 1
    assert bulk_edit.apply_text_op(store, f.id, "description", "upper_first") == 1
    assert store.get_phrase(a.id).description == "Alpha"
    assert bulk_edit.apply_text_op(store, f.id, "content", "strip_leading") == 1
    assert store.get_phrase(a.id).content == "text one  "
    assert bulk_edit.apply_text_op(store, f.id, "autotext", "prefix", ";") == 1
    assert store.get_phrase(a.id).triggers[0].value == ";ao"
    bulk_edit.apply_text_op(store, f.id, "description", "upper")
    assert {store.get_phrase(i).description for i in (a.id, b.id)} == {"ALPHA", "BETA"}
    bulk_edit.apply_text_op(store, f.id, "description", "append", " (old)")
    assert store.get_phrase(b.id).description == "BETA (old)"
    assert store.get_phrase(other.id).description == "outside"          # other folders untouched
    with pytest.raises(ValueError):
        bulk_edit.apply_text_op(store, f.id, "notes", "upper")


def test_generate_descriptions_and_plain_text(store):
    f, a, b, _ = _setup(store)
    assert bulk_edit.generate_descriptions(store, f.id) == 2
    assert store.get_phrase(a.id).description == "text one"
    assert store.get_phrase(b.id).description == "Rich two"
    assert bulk_edit.convert_to_plain_text(store, f.id) == 1
    pb = store.get_phrase(b.id)
    assert pb.content_format == "text" and "<" not in pb.content and "Rich" in pb.content


def test_remove_duplicates_keeps_first(store):
    f = store.add_folder(Folder("F"))
    first = store.add_phrase(Phrase("Sig", "Best", folder_id=f.id))
    store.add_phrase(Phrase("Sig ", "Best", folder_id=f.id))
    store.add_phrase(Phrase("Sig", "Other", folder_id=f.id))
    assert bulk_edit.remove_duplicates(store, f.id) == 1
    left = store.phrases(f.id)
    assert len(left) == 2 and first.id in {p.id for p in left}


def test_sort_by_keys(store):
    f = store.add_folder(Folder("F"))
    ids = [store.add_phrase(Phrase(d, "", folder_id=f.id, use_count=n)).id
           for d, n in (("ccc", 1), ("a", 5), ("bb", 3))]
    bulk_edit.sort_phrases(store, f.id, "description")
    assert [p.description for p in sorted(store.phrases(f.id), key=lambda p: p.sort)] == ["a", "bb", "ccc"]
    bulk_edit.sort_phrases(store, f.id, "times_used", descending=True)
    assert [p.description for p in sorted(store.phrases(f.id), key=lambda p: p.sort)] == ["a", "bb", "ccc"]
    bulk_edit.sort_phrases(store, f.id, "description_length", descending=True)
    assert [p.description for p in sorted(store.phrases(f.id), key=lambda p: p.sort)] == ["ccc", "bb", "a"]
    assert len(ids) == 3


def test_folder_context_menu_has_bulk_edit_and_sort():
    from PySide6.QtWidgets import QApplication

    from phraseforge.ui.main_window import MainWindow
    QApplication.instance() or QApplication([])
    s = Store(":memory:")
    try:
        f = s.add_folder(Folder("F"))
        s.add_phrase(Phrase("b", "x ", folder_id=f.id))
        s.add_phrase(Phrase("b", "x ", folder_id=f.id))
        w = MainWindow(s)
        m = w.build_context_menu("folder", f.id)
        menus = {a.text(): a.menu() for a in m.actions() if a.menu()}
        bulk = {a.text(): a for a in menus["Bulk edit"].actions()}
        assert {"Remove duplicates", "Descriptions", "Phrase contents", "Autotexts"} <= set(bulk)
        sub = [a.text() for a in bulk["Phrase contents"].menu().actions() if a.text()]
        assert "Strip trailing spaces" in sub and "UPPERCASE" in sub and "Convert to plain text" in sub
        assert [a.text() for a in menus["Sort"].actions()] == [
            "Description", "Description length", "Date created", "Date modified", "Last used", "Times used"]
        assert w.bulk_remove_duplicates(f.id, confirm=False) == 1
        assert w.bulk_text(f.id, "content", "strip_trailing") == 1
        assert s.phrases(f.id)[0].content == "x"
        w.close()
    finally:
        s.close()
