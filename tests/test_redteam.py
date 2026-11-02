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
