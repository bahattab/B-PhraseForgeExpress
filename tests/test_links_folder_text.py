"""Phrase links, folder text before/after each phrase, sorting by two fields (G-18 rest)."""
from datetime import datetime

import pytest

from phraseforge import bulk_edit
from phraseforge.app import wrap_in_folder_text
from phraseforge.cloud.sync import CloudSync, FolderRemote
from phraseforge.db import Store, link_uid
from phraseforge.macros import MacroEngine
from phraseforge.models import Folder, Phrase
from tests.fakehost import FakeHost

NOW = datetime(2026, 11, 9, 9, 0, 0)


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "p.db")
    yield s
    s.close()


def expand(store, p):
    p = store.get_phrase(p.id)
    return MacroEngine(FakeHost(), store, clock=lambda: NOW).expand_to_text(wrap_in_folder_text(store, p))


def test_a_link_follows_the_phrase_it_points_to(store):
    src = store.add_phrase(Phrase("Address", "Main Street 1"))
    f = store.add_folder(Folder("Shortcuts"))
    link = store.create_link(src.id, f.id)
    assert link_uid(link.content) == store.phrase_uid(src.id)
    assert expand(store, link) == "Main Street 1"
    src.content = "Market Square 7"
    store.update_phrase(src)
    assert expand(store, link) == "Market Square 7"          # follows edits
    store.delete_phrase(src.id)
    assert "linked phrase was deleted" in expand(store, link)


def test_a_link_keeps_working_after_the_phrase_goes_through_the_trash(store):
    src = store.add_phrase(Phrase("Sig", "Regards"))
    link = store.create_link(src.id, None)
    tid = store.trash_phrase(src.id)
    store.restore_trash(tid)
    assert expand(store, link) == "Regards"


def test_a_link_does_not_lift_the_targets_approval(store):
    from phraseforge.host import ExpansionContext
    src = store.add_phrase(Phrase("Run", "{#run calc.exe}"))
    store.quarantine(src.id, "imported")
    link = store.create_link(src.id, None)              # the link itself is approved...
    host = FakeHost()
    ctx = ExpansionContext()
    ctx.allow_privileged = True
    out = MacroEngine(host, store, clock=lambda: NOW).expand_to_text(link.content, ctx)
    assert "blocked" in out and not [c for c in host.calls if "run" in str(c).lower()]   # ...the target is not


def test_link_uid_only_matches_a_whole_link():
    assert link_uid("{#insert -uid 0123456789abcdef}") == "0123456789abcdef"
    assert link_uid("Hi {#insert -uid 0123456789abcdef}") is None
    assert link_uid("plain") is None


def test_folder_text_wraps_every_phrase_in_the_subtree(store):
    outer = store.add_folder(Folder("Mail", text_before="Hello,\n", text_after="\nRegards"))
    inner = store.add_folder(Folder("Sales", parent_id=outer.id, text_before="[Sales] ", text_after=" [/Sales]"))
    p = store.add_phrase(Phrase("Offer", "Our offer", folder_id=inner.id))
    assert expand(store, p) == "Hello,\n[Sales] Our offer [/Sales]\nRegards"
    q = store.add_phrase(Phrase("Plain", "x"))
    assert expand(store, q) == "x"
    m = store.add_phrase(Phrase("Macro", "body", folder_id=store.add_folder(
        Folder("M", text_before="{#date -format yyyy} ")).id))
    assert expand(store, m) == "2026 body"


def test_folder_text_in_a_formatted_phrase_is_escaped(store):
    f = store.add_folder(Folder("F", text_before="<b>a & b</b>\n"))
    p = store.add_phrase(Phrase("H", "<p>hi</p>", folder_id=f.id, content_format="html"))
    assert wrap_in_folder_text(store, p) == "&lt;b&gt;a &amp; b&lt;/b&gt;<br><p>hi</p>"


def test_changing_folder_text_counts_for_approval(store):
    f = store.add_folder(Folder("F"))
    p = store.add_phrase(Phrase("P", "text", folder_id=f.id))
    before = store.phrase_fingerprints()[p.id]
    f.text_before = "{#run cmd.exe}"
    store.update_folder(f)
    assert store.phrase_fingerprints()[p.id] != before     # a sync that adds it quarantines the phrase


def test_folder_text_syncs_and_merges(tmp_path):
    a, b = Store(tmp_path / "A.db"), Store(tmp_path / "B.db")
    sa = CloudSync(a, FolderRemote(tmp_path / "cloud"), device="A")
    sb = CloudSync(b, FolderRemote(tmp_path / "cloud"), device="B")

    def run(cs):
        r = cs.sync()
        if r.action in ("pulled", "merged"):
            cs.apply_pull(r.pulled_file, r.remote_rev)
    f = a.add_folder(Folder("F"))
    a.add_phrase(Phrase("P", "p", folder_id=f.id))
    run(sa)
    run(sb)
    fa = a.get_folder(f.id)
    fa.text_after = " -- A"
    a.update_folder(fa)
    b.add_phrase(Phrase("Q", "q"))
    run(sa)
    run(sb)
    fb = next(x for x in b.folders() if x.name == "F")
    assert fb.text_after == " -- A"
    pb = b.find_phrase("P")
    assert pb.id in b.quarantined()                            # the new folder text needs approval
    a.close()
    b.close()


def test_sort_by_two_fields(store):
    f = store.add_folder(Folder("F"))
    for name, uses in (("b", 1), ("a", 1), ("c", 5), ("d", 0)):
        store.add_phrase(Phrase(name, name, folder_id=f.id, use_count=uses))
    bulk_edit.sort_phrases_by(store, f.id, [("times_used", True), ("description", False)])
    assert [p.description for p in store.phrases(f.id)] == ["c", "a", "b", "d"]


def test_dialogs(store):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from phraseforge.ui.main_dialogs import FolderDialog, SortTwoDialog
    f = store.add_folder(Folder("F"))
    d = FolderDialog(f)
    d.before.setPlainText("Hi ")
    d.after.setPlainText(" Bye")
    store.update_folder(d.apply())
    assert store.folder_wrap(f.id) == ("Hi ", " Bye")
    s = SortTwoDialog()
    assert s.keys() == [("description", False), ("modified", False)]
