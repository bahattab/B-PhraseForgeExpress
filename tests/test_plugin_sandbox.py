"""Low-integrity plugin sandbox (FR-PLG-02). The real checks run on Windows CI only."""
import json
import sys

import pytest

from phraseforge.plugins import manifest as mf
from phraseforge.plugins.host import PluginProcess

SCRIPT = r"""
import json, os, sys, tempfile
def try_write(path):
    try:
        with open(path, "w") as f:
            f.write("x")
        os.remove(path)
        return "written"
    except OSError as e:
        return "refused:" + type(e).__name__
def integrity():
    if sys.platform != "win32":
        return "n/a"
    import ctypes
    from ctypes import wintypes
    k32, adv = ctypes.windll.kernel32, ctypes.windll.advapi32
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    tok = wintypes.HANDLE()
    adv.OpenProcessToken(k32.GetCurrentProcess(), 0x0008, ctypes.byref(tok))
    buf = ctypes.create_string_buffer(64)
    n = wintypes.DWORD()
    adv.GetTokenInformation(tok, 25, buf, 64, ctypes.byref(n))
    sid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
    adv.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    adv.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)
    count = adv.GetSidSubAuthorityCount(ctypes.c_void_p(sid))[0]
    return hex(adv.GetSidSubAuthority(ctypes.c_void_p(sid), count - 1)[0])
for line in sys.stdin:
    m = json.loads(line)
    p = m.get("params") or {}
    res = {"own_folder": try_write(os.path.join(os.getcwd(), "probe.txt")),
           "target": try_write(p["target"]),
           "temp": try_write(os.path.join(tempfile.gettempdir(), "probe.txt")),
           "integrity": integrity()}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": res}) + "\n")
    sys.stdout.flush()
"""


def make(tmp_path, sandbox):
    folder = tmp_path / "plug"
    folder.mkdir()
    (folder / "plugin.py").write_text(SCRIPT)
    m = mf.parse('id = "probe"\nname = "P"\nversion = "1.0.0"\napi_version = "1.0"\nentry = "plugin.py"\n'
                 'runtime = "python-subprocess"\nkinds = ["macro"]\nmacros = ["x"]\n')
    return PluginProcess(m, folder, sandbox=sandbox)


@pytest.mark.skipif(sys.platform != "win32", reason="low integrity is a Windows feature")
def test_sandboxed_plugin_cannot_write_user_files(tmp_path):
    proc = make(tmp_path, sandbox=True)
    try:
        out = proc.call("probe", {"target": str(tmp_path / "user-file.txt")}, timeout=30)
    finally:
        proc.stop()
    assert out["integrity"] == "0x1000"                       # SECURITY_MANDATORY_LOW_RID
    assert out["own_folder"].startswith("refused") and out["target"].startswith("refused")
    assert out["temp"] == "written"                           # LocalLow temp still works
    assert not (tmp_path / "user-file.txt").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="low integrity is a Windows feature")
def test_sandbox_can_be_switched_off(tmp_path):
    proc = make(tmp_path, sandbox=False)
    try:
        out = proc.call("probe", {"target": str(tmp_path / "user-file.txt")}, timeout=30)
    finally:
        proc.stop()
    assert out["integrity"] == "0x2000" and out["target"] == "written"


def test_off_windows_the_plugin_runs_normally(tmp_path):
    if sys.platform == "win32":
        pytest.skip("covered by the Windows tests")
    proc = make(tmp_path, sandbox=True)
    try:
        out = proc.call("probe", {"target": str(tmp_path / "user-file.txt")}, timeout=30)
    finally:
        proc.stop()
    assert out["integrity"] == "n/a" and out["target"] == "written"


def test_manager_uses_the_setting(tmp_path):
    from phraseforge.db import Store
    from phraseforge.plugins import manager as pm
    st = Store(":memory:")
    mgr = pm.PluginManager(st, root=tmp_path / "plugins")
    from pathlib import Path
    mgr.install(Path(__file__).resolve().parents[1] / "examples" / "plugins" / "hello", accept=True)
    assert mgr.process("hello").sandbox is True
    mgr.stop_all()
    st.set_setting("plugins.sandbox", "0")
    mgr2 = pm.PluginManager(st, root=tmp_path / "plugins")
    assert mgr2.process("hello").sandbox is False
    mgr2.stop_all()


def test_env_block_and_cmdline():
    from phraseforge.plugins import sandbox
    assert sandbox._env_block({"b": "2", "A": "1"}) == "A=1\0b=2\0\0"
    assert sandbox._cmdline(["C:\\Py\\python.exe", "-I", "C:\\a b\\p.py"]) == 'C:\\Py\\python.exe -I "C:\\a b\\p.py"'
    with pytest.raises(sandbox.SandboxError) if sys.platform != "win32" else pytest.raises(Exception):
        if sys.platform != "win32":
            sandbox.launch(["x"], ".", {}, lambda p: None)
        else:
            raise Exception("skip")


def test_consent_text_matches_the_sandbox():
    from phraseforge.plugins.manifest import parse
    from phraseforge.ui.plugins_dialog import consent_text
    from pathlib import Path
    m = parse((Path(__file__).resolve().parents[1] / "examples" / "plugins" / "hello" / "plugin.toml").read_text())
    assert "limited Windows rights" in consent_text(m, [], False, sandboxed=True)
    assert "can still read your files" in consent_text(m, [], False, sandboxed=True)
    assert "runs with your Windows rights" in consent_text(m, [], False)
