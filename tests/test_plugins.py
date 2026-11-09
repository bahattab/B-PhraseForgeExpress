"""G-13 stage 1: plugin manifest, safe install, out-of-process host with time limits,
macro plugins, declared secrets only, policy allow-list, Plugins window."""
import dataclasses
import shutil
import time
import zipfile
from pathlib import Path

import pytest

from phraseforge import policy
from phraseforge.db import Store, is_device_setting, is_secret_setting
from phraseforge.host import ExpansionContext
from phraseforge.macros import MacroEngine
from phraseforge.plugins import install as inst
from phraseforge.plugins import manager as pm
from phraseforge.plugins.host import PluginProcess, PluginTimeout
from phraseforge.plugins.manifest import ManifestError, parse
from tests.fakehost import FakeHost

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "plugins" / "hello"
GOOD = """id = "hello"
name = "Hello"
version = "1.0.0"
api_version = "1.0"
kinds = ["macro"]
entry = "main.py"
runtime = "python-subprocess"
macros = ["greet"]
"""


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


@pytest.fixture
def mgr(store, tmp_path):
    m = pm.PluginManager(store, tmp_path / "plugins")
    pm.set_current(m)
    yield m
    m.stop_all()
    pm.set_current(None)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------- FR-PLG-01 manifest
def test_good_manifest():
    m = parse(GOOD)
    assert m.id == "hello" and m.macros == ("greet",) and not m.permissions.privileged


@pytest.mark.parametrize("change,error", [
    ('id = "hello"', ""),
    ('id = "Hello"', "id may only"),
    ('version = "1.0.0"', ""),
    ('version = "one"', "version"),
    ('api_version = "2.0"', "not supported"),
    ('kinds = ["macro"]', ""),
    ('kinds = ["rocket"]', "kinds"),
    ('entry = "main.py"', ""),
    ('entry = "../evil.py"', "inside the plugin"),
    ('entry = "C:/evil.py"', "inside the plugin"),
    ('runtime = "python-subprocess"', ""),
    ('runtime = "dll"', "runtime"),
    ('macros = ["greet"]', ""),
    ('macros = ["Greet!"]', "not allowed"),
])
def test_manifest_errors(change, error):
    key = change.split(" ")[0]
    text = "\n".join(change if line.startswith(key + " ") else line for line in GOOD.splitlines())
    if not error:
        parse(text)
        return
    with pytest.raises(ManifestError, match=error):
        parse(text)


@pytest.mark.parametrize("extra,error", [
    ("bogus = 1", "unknown key"),
    ("[permissions]\nnetwork = [\"*.evil.com\"]", "not allowed"),
    ("[permissions]\nteleport = true", "unknown permission"),
    ("[permissions]\nfilesystem = [\"all\"]", "filesystem"),
    ("[permissions]\nclipboard = \"yes\"", "true or false"),
])
def test_manifest_permission_errors(extra, error):
    with pytest.raises(ManifestError, match=error):
        parse(GOOD + extra)


def test_missing_and_bad_toml():
    with pytest.raises(ManifestError, match="missing"):
        parse(GOOD.replace('name = "Hello"\n', ""))
    with pytest.raises(ManifestError, match="TOML"):
        parse("id = ")


def test_permission_diff():
    a = parse(GOOD + '[permissions]\nnetwork = ["a.com"]\n').permissions
    b = parse(GOOD + '[permissions]\nnetwork = ["a.com", "b.com"]\ninput = true\n').permissions
    assert b.wider_than(a) == ["network: b.com", "input"] and a.wider_than(b) == []
    assert b.privileged


# ---------------------------------------------------------------- install
def _zip(path: Path, files: dict[str, str]):
    with zipfile.ZipFile(path, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return path


def test_install_folder_and_zip(tmp_path):
    m = inst.install(EXAMPLE, tmp_path / "p")
    assert (tmp_path / "p" / "hello" / "main.py").is_file() and m.id == "hello"
    z = _zip(tmp_path / "x.pfplugin", {"hello/plugin.toml": GOOD, "hello/main.py": "print(1)"})
    inst.install(z, tmp_path / "q")
    assert (tmp_path / "q" / "hello" / "main.py").read_text() == "print(1)"


@pytest.mark.parametrize("files,error", [
    ({"plugin.toml": GOOD, "../evil.py": "x", "main.py": ""}, "unsafe path"),
    ({"plugin.toml": GOOD, "/abs.py": "x", "main.py": ""}, "unsafe path"),
    ({"plugin.toml": GOOD, "a\\..\\b.py": "x", "main.py": ""}, "unsafe path"),
    ({"readme.txt": "x"}, "no plugin.toml"),
    ({"plugin.toml": GOOD}, "entry main.py"),
])
def test_unsafe_packages_are_refused(tmp_path, files, error):
    z = _zip(tmp_path / "x.pfplugin", files)
    with pytest.raises(ManifestError, match=error):
        inst.install(z, tmp_path / "p")
    assert not (tmp_path / "p" / "hello").exists()


def test_bad_manifest_runs_no_code(tmp_path):
    marker = tmp_path / "ran"
    d = tmp_path / "bad"
    d.mkdir()
    (d / "plugin.toml").write_text(GOOD.replace('version = "1.0.0"', 'version = "x"'))
    (d / "main.py").write_text(f"open({str(marker)!r}, 'w').write('1')")
    with pytest.raises(ManifestError):
        inst.inspect(d)
    assert not marker.exists()


# ---------------------------------------------------------------- FR-PLG-02 host
def _hello_with_hang(tmp_path) -> Path:
    d = tmp_path / "src"
    shutil.copytree(EXAMPLE, d)
    t = (d / "plugin.toml").read_text().replace('"secret_len"]', '"secret_len", "hang"]')
    (d / "plugin.toml").write_text(t)
    return d


def test_process_calls_and_restarts(tmp_path):
    m = inst.install(EXAMPLE, tmp_path / "p")
    proc = PluginProcess(m, tmp_path / "p" / "hello")
    try:
        assert proc.call("macro", {"name": "greet", "args": ["Sam"], "opts": {}})["text"] == "Hello, Sam!"
        proc.stop()
        assert proc.call("macro", {"name": "shout", "args": ["hi"], "opts": {}})["text"] == "HI"
    finally:
        proc.stop()


def test_hanging_plugin_is_killed(tmp_path, monkeypatch):
    from phraseforge.plugins import host
    monkeypatch.setattr(host, "GRACE_S", 0.3)
    src = _hello_with_hang(tmp_path)
    m = inst.install(src, tmp_path / "p")
    proc = PluginProcess(m, tmp_path / "p" / "hello")
    try:
        t0 = time.monotonic()
        with pytest.raises(PluginTimeout):
            proc.call("macro", {"name": "hang", "args": [], "opts": {}}, timeout=0.5)
        assert time.monotonic() - t0 < 5 and not proc.running
        assert any("no answer" in e for e in proc.errors)
        assert proc.call("macro", {"name": "shout", "args": ["ok"], "opts": {}})["text"] == "OK"
    finally:
        proc.stop()


def test_plugin_gets_no_inherited_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    from phraseforge.plugins.host import _env
    assert "OPENAI_API_KEY" not in _env()


# ---------------------------------------------------------------- manager, macros, secrets, policy
def test_macro_plugin_in_phrases(mgr):
    with pytest.raises(PermissionError):
        mgr.install(EXAMPLE, accept=False)
    mgr.install(EXAMPLE, accept=True)
    eng = MacroEngine(FakeHost())
    assert eng.expand_to_text("{#hello.greet Sam -end .}", ExpansionContext()) == "Hello, Sam."
    assert eng.expand_to_text("{#hello.shout {#upper a}b}", ExpansionContext()) == "AB"
    assert eng.expand_to_text("{#hello.nosuch x}", ExpansionContext()) == "{#hello.nosuch x}"
    mgr.set_enabled("hello", False)
    assert eng.expand_to_text("{#hello.greet}", ExpansionContext()) == "{#hello.greet}"


def test_only_declared_secrets(mgr):
    mgr.install(EXAMPLE, accept=True)
    mgr.set_secret("hello", "token", "abcd")
    with pytest.raises(Exception):
        mgr.set_secret("hello", "other", "x")
    eng = MacroEngine(FakeHost())
    assert eng.expand_to_text("{#hello.secret_len}", ExpansionContext()) == "4"
    assert is_secret_setting("plugins.secret.hello.token") and is_device_setting("plugins.enabled")


def test_wider_update_is_switched_off_until_accepted(mgr, tmp_path):
    mgr.install(EXAMPLE, accept=True)
    d = tmp_path / "v2"
    shutil.copytree(EXAMPLE, d)
    (d / "plugin.toml").write_text((d / "plugin.toml").read_text().replace(
        'secrets = ["token"]', 'secrets = ["token"]\nnetwork = ["api.example.com"]'))
    m, asked = mgr.preview(d)
    assert asked == ["network: api.example.com"]
    from phraseforge.plugins import install as i2
    i2.install(d, mgr.root)                    # copied without consent (e.g. by hand)
    assert not mgr.is_enabled("hello")


def test_policy_allow_list(mgr):
    before = policy.current()
    policy.set_current(dataclasses.replace(before, plugins_allowed=frozenset({"other"})))
    try:
        with pytest.raises(PermissionError):
            mgr.install(EXAMPLE, accept=True)
    finally:
        policy.set_current(before)
    p = policy.parse('plugins_allowed = ["hello"]\n')
    assert p.plugins_allowed == frozenset({"hello"})
    assert policy.parse("").plugins_allowed is None


def test_privileged_plugin_needs_approved_phrase(mgr, tmp_path):
    d = tmp_path / "net"
    shutil.copytree(EXAMPLE, d)
    (d / "plugin.toml").write_text((d / "plugin.toml").read_text().replace(
        'secrets = ["token"]', 'secrets = ["token"]\nnetwork = ["api.example.com"]'))
    mgr.install(d, accept=True)
    eng = MacroEngine(FakeHost())
    ctx = ExpansionContext()
    ctx.allow_privileged = False
    assert "blocked" in eng.expand_to_text("{#hello.greet}", ctx)
    from phraseforge.security import PLUGIN_REASON, scan_privileged
    assert PLUGIN_REASON in scan_privileged("{#hello.greet}")
    assert scan_privileged("{#run notepad.exe}")       # the old checks still work


def test_plugins_dialog(qapp, mgr):
    from phraseforge.ui.plugins_dialog import PluginsDialog
    asked = []
    d = PluginsDialog(manager=mgr, ask=lambda text: asked.append(text) or True)
    assert d.install_from(str(EXAMPLE))
    assert asked and "receive secrets: token" in asked[0]
    assert d.tree.topLevelItemCount() == 1 and mgr.is_enabled("hello")
    d.remove_selected()            # nothing selected: nothing happens
    d.tree.setCurrentItem(d.tree.topLevelItem(0))
    d.remove_selected()
    assert mgr.installed() == {}
