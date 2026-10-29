"""Password folders enforced everywhere, and imported/synced phrases need approval
before their privileged macros run (phraseforge/security.py)."""
import hashlib
from types import SimpleNamespace

import pytest

from phraseforge import io_formats
from phraseforge.cloud.sync import CloudSync, FolderRemote
from phraseforge.db import Store, hash_password
from phraseforge.host import ExpansionContext, ExpansionRequest
from phraseforge.macros.engine import MacroEngine
from phraseforge.models import Folder, Phrase
from phraseforge.security import LOCKS, privileged_reason, protected, scan_privileged
from tests.fakehost import FakeHost


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


# ---------------------------------------------------------------- privileged macros
@pytest.mark.parametrize("name,args,opts,expected", [
    ("run", ["calc.exe"], {}, True),
    ("open", ["https://x.test"], {}, True),
    ("http", ["https://x.test"], {}, True),
    ("outputfile", ["c:\\x.txt"], {}, True),
    ("setphrase", ["x"], {}, True),
    ("mail", ["a@b.test"], {}, False),                 # draft only
    ("mail", ["a@b.test"], {"send": ""}, True),
    ("key", ["ctrl+c"], {}, False),
    ("key", ["win+r"], {}, True),
    ("upper", ["x"], {}, False),
])
def test_privileged_reason(name, args, opts, expected):
    assert bool(privileged_reason(name, args, opts)) is expected


def test_scan_privileged_finds_reasons_once():
    assert scan_privileged("Hi {#run calc.exe} {#run notepad} {#upper x}") == ["start programs"]
    assert scan_privileged("{#key ctrl+v}{#mail a@b.test -subject x}") == []
    assert scan_privileged("{#mail a@b.test -send}") == ["create or send e-mail"]
    assert scan_privileged("{#key win+r}") == ["press Windows-key shortcuts"]
    assert scan_privileged("plain text") == []


def test_engine_blocks_privileged_calls_when_not_allowed():
    host = FakeHost()
    eng = MacroEngine(host)
    out = eng.expand_to_text("a{#run calc.exe}b{#upper x}", ExpansionContext(allow_privileged=False))
    assert "blocked" in out and out.startswith("a") and out.endswith("bX")
    assert not host.called("run_program")
    eng.expand_to_text("{#run calc.exe}", ExpansionContext())
    assert host.called("run_program")


def test_insert_of_unapproved_phrase_is_blocked_inside_an_approved_one(store):
    host = FakeHost()
    bad = store.add_phrase(Phrase("Bad", "{#run evil.exe}"))
    store.quarantine(bad.id, "imported")
    eng = MacroEngine(host, store=store)
    out = eng.expand_to_text('{#insert "Bad"}', ExpansionContext(phrase_description="Good"))
    assert "blocked" in out and not host.called("run_program")
    store.release_quarantine(bad.id)
    eng.expand_to_text('{#insert "Bad"}', ExpansionContext(phrase_description="Good"))
    assert host.called("run_program")


def test_insert_from_a_locked_folder_fails(store):
    f = store.add_folder(Folder("Secret", password_hash=hash_password("pw")))
    store.add_phrase(Phrase("Hidden", "top secret", folder_id=f.id))
    eng = MacroEngine(FakeHost(), store=store)
    out = eng.expand_to_text('{#insert "Hidden"}', ExpansionContext())
    assert "locked" in out and "top secret" not in out
    LOCKS.add(f.id)
    assert eng.expand_to_text('{#insert "Hidden"}', ExpansionContext()) == "top secret"


# ---------------------------------------------------------------- quarantine in the store
def test_imports_are_quarantined_and_own_phrases_are_not(store, tmp_path):
    own = store.add_phrase(Phrase("Mine", "{#run calc}"))
    csv = tmp_path / "p.csv"
    csv.write_text("description,content\nImported,{#run calc}\n", encoding="utf-8")
    io_formats.import_csv(store, csv)
    imported = store.find_phrase("Imported")
    assert store.quarantine_origin(own.id) is None
    assert store.quarantine_origin(imported.id) == "imported"
    store.add_phrase(Phrase("After", "x"))                # the import block has ended
    assert store.quarantine_origin(store.find_phrase("After").id) is None
    store.release_quarantine(imported.id)
    assert store.quarantine_origin(imported.id) is None


def test_json_import_and_language_versions_are_quarantined(store):
    io_formats.import_dict(store, {"phrases": [{"description": "J", "content": "{#http https://x.test}",
                                                "versions": {"Arabic": {"content": "{#run x}"}}}]})
    assert store.quarantine_origin(store.find_phrase("J").id) == "imported"
    p = store.add_phrase(Phrase("V", "x"))
    with store.quarantine_writes("imported"):
        store.set_phrase_version(p.id, "German", "{#run x}")
    assert store.quarantine_origin(p.id) == "imported"


def test_deleting_a_phrase_removes_its_quarantine_row(store):
    p = store.add_phrase(Phrase("X", "x"))
    store.quarantine(p.id)
    store.delete_phrase(p.id)
    assert store.quarantined() == {}


def test_opening_another_phrase_file_quarantines_only_new_or_changed(tmp_path):
    live = Store(tmp_path / "live.db")
    same = live.add_phrase(Phrase("Same", "{#run a}"))
    changed = live.add_phrase(Phrase("Changed", "old"))
    local_q = live.add_phrase(Phrase("LocalQ", "q"))
    live.quarantine(local_q.id, "imported")
    live.backup_to(tmp_path / "other.db")
    other = Store(tmp_path / "other.db")
    changed.content = "{#run b}"
    other.update_phrase(changed)
    new = other.add_phrase(Phrase("New", "{#run c}"))
    other.release_quarantine(local_q.id)          # the file claims LocalQ is approved: ignored
    other.quarantine(same.id, "imported")         # ... and its own rows are ignored too
    other.close()
    live.restore_from(tmp_path / "other.db", untrusted="imported")
    q = live.quarantined()
    assert q == {changed.id: "imported", new.id: "imported", local_q.id: "imported"}
    assert same.id not in q


def test_restoring_own_backup_keeps_its_quarantine_list(tmp_path):
    s = Store(tmp_path / "a.db")
    p = s.add_phrase(Phrase("P", "x"))
    s.quarantine(p.id, "synced")
    s.backup_to(tmp_path / "b.db")
    s.release_quarantine(p.id)
    s.restore_from(tmp_path / "b.db")
    assert s.quarantine_origin(p.id) == "synced"


def test_sync_pull_quarantines_phrases_it_adds_or_changes(tmp_path):
    remote = tmp_path / "cloud"
    a, b = Store(tmp_path / "A.db"), Store(tmp_path / "B.db")
    sa, sb = CloudSync(a, FolderRemote(remote), "A"), CloudSync(b, FolderRemote(remote), "B")
    a.add_phrase(Phrase("Shared", "{#run notepad}"))
    sa.sync()
    r = sb.sync()
    sb.apply_pull(r.pulled_file, r.remote_rev)
    shared = b.find_phrase("Shared")
    assert b.quarantine_origin(shared.id) == "synced"           # new on B
    b.release_quarantine(shared.id)                              # B's user approves it
    a.add_phrase(Phrase("Second", "{#http https://x.test}"))
    sa.sync()
    r = sb.sync()
    sb.apply_pull(r.pulled_file, r.remote_rev)
    assert b.quarantine_origin(shared.id) is None                # unchanged: stays approved
    assert b.quarantine_origin(b.find_phrase("Second").id) == "synced"


# ---------------------------------------------------------------- folder locks
def test_locks_follow_the_folder_chain(store):
    top = store.add_folder(Folder("Top", password_hash=hash_password("pw")))
    sub = store.add_folder(Folder("Sub", parent_id=top.id))
    free = store.add_folder(Folder("Free"))
    assert LOCKS.locked_folder(store, sub.id).id == top.id and LOCKS.is_locked(store, sub.id)
    assert not LOCKS.is_locked(store, free.id) and not LOCKS.is_locked(store, None)
    assert protected(store, sub.id) and not protected(store, free.id)
    assert not LOCKS.try_unlock(store, top, "wrong") and LOCKS.is_locked(store, sub.id)
    assert LOCKS.try_unlock(store, top, "pw") and not LOCKS.is_locked(store, sub.id)
    assert protected(store, sub.id)                       # still has a password


def test_unlock_upgrades_an_old_sha256_hash(store):
    f = store.add_folder(Folder("Old", password_hash=hashlib.sha256(b"phraseforge:pw").hexdigest()))
    assert LOCKS.try_unlock(store, f, "pw")
    assert store.get_folder(f.id).password_hash.startswith("scrypt$")


# ---------------------------------------------------------------- expansion gate (app._expand)
class _Engine:
    def __init__(self):
        self.seen = []

    def expand(self, text, ctx):
        self.seen.append((text, ctx.allow_privileged))
        raise RuntimeError("stop")        # only the decision matters here


def _fake_app(store, ui_answer=None):
    notes = []
    return SimpleNamespace(
        store=store, engine=_Engine(), notes=notes,
        host=SimpleNamespace(_ui=lambda fn: ui_answer(fn) if ui_answer else fn()),
        poster=SimpleNamespace(posted=SimpleNamespace(emit=lambda fn: notes.append(fn))),
        tray=SimpleNamespace(notify=lambda *a: None))


def _expand(app, req):
    from phraseforge.app import PhraseForgeApp
    try:
        PhraseForgeApp._expand(app, req, 0)
    except RuntimeError:
        return True        # reached the engine
    return False           # stopped before expanding


def test_locked_folder_asks_for_password_before_expanding(store, monkeypatch):
    from phraseforge.ui import dialogs
    f = store.add_folder(Folder("Secret", password_hash=hash_password("pw")))
    p = store.add_phrase(Phrase("S", "secret text", folder_id=f.id))
    asked = []
    monkeypatch.setattr(dialogs, "ask_folder_password", lambda st, folder, parent=None: asked.append(folder.id))
    app = _fake_app(store)
    assert not _expand(app, ExpansionRequest(phrase_id=p.id))           # refused: nothing typed
    assert asked == [f.id] and app.engine.seen == []
    assert not _expand(app, ExpansionRequest(phrase_id=p.id, automatic=True))
    assert asked == [f.id]                                               # automatic triggers never ask
    monkeypatch.setattr(dialogs, "ask_folder_password",
                        lambda st, folder, parent=None: LOCKS.try_unlock(st, folder, "pw"))
    assert _expand(app, ExpansionRequest(phrase_id=p.id))
    assert _expand(app, ExpansionRequest(phrase_id=p.id, automatic=True))   # unlocked for the session


def test_unapproved_phrase_asks_once_or_always(store, monkeypatch):
    from phraseforge.ui import dialogs
    p = store.add_phrase(Phrase("Imp", "{#run calc}"))
    store.quarantine(p.id, "imported")
    answers = iter(["", dialogs.ALLOW_ONCE, dialogs.ALLOW_ALWAYS])
    asked = []
    monkeypatch.setattr(dialogs, "approve_phrase", lambda d, o, r: (asked.append((d, o, r)), next(answers))[1])
    app = _fake_app(store)
    assert not _expand(app, ExpansionRequest(phrase_id=p.id))            # "Do not run"
    assert asked[0] == ("Imp", "imported", ["start programs"])
    assert _expand(app, ExpansionRequest(phrase_id=p.id))                # once
    assert app.engine.seen[-1] == ("{#run calc}", True)
    assert store.quarantine_origin(p.id) == "imported"
    assert _expand(app, ExpansionRequest(phrase_id=p.id))                # always
    assert store.quarantine_origin(p.id) is None
    assert _expand(app, ExpansionRequest(phrase_id=p.id)) and len(asked) == 3   # no more questions


def test_unapproved_phrase_from_automatic_trigger_is_skipped(store, monkeypatch):
    from phraseforge.ui import dialogs
    p = store.add_phrase(Phrase("Timer", "{#http https://x.test}"))
    store.quarantine(p.id, "synced")
    monkeypatch.setattr(dialogs, "approve_phrase", lambda *a: pytest.fail("must not ask"))
    app = _fake_app(store)
    assert not _expand(app, ExpansionRequest(phrase_id=p.id, automatic=True))
    assert len(app.notes) == 1                                           # tray notice queued


def test_unapproved_phrase_without_privileged_macros_runs_guarded(store, monkeypatch):
    from phraseforge.ui import dialogs
    p = store.add_phrase(Phrase("Plain", "hello {#upper x}"))
    store.quarantine(p.id, "imported")
    monkeypatch.setattr(dialogs, "approve_phrase", lambda *a: pytest.fail("must not ask"))
    app = _fake_app(store)
    assert _expand(app, ExpansionRequest(phrase_id=p.id, automatic=True))
    assert app.engine.seen[-1] == ("hello {#upper x}", False)           # engine still blocks if needed


def test_time_and_focus_requests_are_automatic(store):
    from phraseforge.triggers.manager import TriggerManager
    got = []
    tm = TriggerManager(store, on_expand=got.append, on_command=lambda *a: None)
    assert tm._automatic(1, "x.exe", "t").automatic
    assert not tm._request(1).automatic


# ---------------------------------------------------------------- phrase menu
def test_phrase_menu_hides_locked_folders_until_unlocked(store):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    assert QApplication.instance() or QApplication([])
    from phraseforge.ui.popup import PhrasePopup
    f = store.add_folder(Folder("Secret", password_hash=hash_password("pw")))
    store.add_phrase(Phrase("Hidden one", "x", folder_id=f.id))
    store.add_phrase(Phrase("Visible one", "y"))
    pop = PhrasePopup(store)
    assert "Secret" not in [r[2] for r in pop.folder_entries(None)]
    assert [r[2] for r in pop.search_entries("one")] == ["Visible one"]
    LOCKS.add(f.id)
    assert "Secret" in [r[2] for r in pop.folder_entries(None)]
    assert sorted(r[2] for r in pop.search_entries("one")) == ["Hidden one", "Visible one"]


def test_smartcomplete_skips_password_folders(store):
    from phraseforge.models import Trigger, TriggerKind
    from phraseforge.triggers.manager import TriggerManager
    f = store.add_folder(Folder("Secret", password_hash=hash_password("pw")))
    store.add_phrase(Phrase("S", "secret", folder_id=f.id,
                            triggers=[Trigger(TriggerKind.SMARTCOMPLETE, "secretword")]))
    store.add_phrase(Phrase("O", "open", triggers=[Trigger(TriggerKind.SMARTCOMPLETE, "openword")]))
    tm = TriggerManager(store, on_expand=lambda r: None, on_command=lambda *a: None)
    tm.reload()
    assert [target for _t, target in tm._smart] == ["openword"]
