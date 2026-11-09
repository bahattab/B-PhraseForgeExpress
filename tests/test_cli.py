"""FR-APP-02: command-line switches."""
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from phraseforge import cli, paths, policy
from phraseforge.db import Store
from phraseforge.models import Phrase


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def test_parse_flags_and_values():
    o = cli.parse(["--minimized", "--no-hook", "--no-clipboard", "--readonly", "--debug", "--log-file", "x.log",
                   "--import", "a.csv", "--import=b.xml", "--open", "lib.db", "--exec", "Sig", "--edit=7", "-style", "x"])
    assert {"minimized", "no-hook", "no-clipboard", "readonly", "debug"} <= o.flags
    assert o.log_file == "x.log" and o.imports == ["a.csv", "b.xml"] and o.opens == ["lib.db"]
    assert o.execs == ["Sig"] and o.edits == ["7"] and o.rest == ["-style", "x"]
    assert o.actions


@pytest.mark.parametrize("bad", [["--import"], ["--exec", "--debug"], ["--log-file"]])
def test_missing_value(bad):
    with pytest.raises(cli.UsageError):
        cli.parse(bad)


def test_url():
    assert cli.parse_url("phraseforge://exec/abc123") == ("exec", "abc123")
    assert cli.parse_url("PhraseForge://edit/My%20phrase") == ("edit", "My phrase")
    assert cli.parse_url("phraseforge://delete/x") is None
    assert cli.parse_url("https://exec/x") is None
    o = cli.parse(["phraseforge://exec/abc"])
    assert o.url_execs == ["abc"] and o.execs == [] and o.actions


def test_forwarded_keeps_links_as_links():
    o = cli.parse(["--shutdown", "--import", "a b.csv", "--exec", "x", "phraseforge://exec/u1", "--no-hook"])
    assert cli.forwarded(o) == ["--shutdown", "--import", "a b.csv", "--exec", "x", "phraseforge://exec/u1"]
    assert cli.parse(cli.forwarded(o)).url_execs == ["u1"]


class FakeApp:
    def __init__(self, store, confirm=True):
        self.store = store
        self.expanded, self.shown, self.selected, self.quitted = [], 0, [], False
        self.confirm_link_exec = lambda p: confirm
        self.main_window = SimpleNamespace(select_phrase=self.selected.append, refresh_tree=lambda: None,
                                           import_phraseexpress_path=lambda p, show_message=True: object())

    def quit(self):
        self.quitted = True

    def show_main(self):
        self.shown += 1

    def on_expand_request(self, req):
        self.expanded.append(req.phrase_id)


def test_run_actions(store):
    p = store.add_phrase(Phrase("Sig", "Best"))
    uid = store.phrase_uid(p.id)
    app = FakeApp(store)
    assert cli.run_actions(app, cli.parse(["--exec", "Sig", "--exec", uid, "--edit", str(p.id)])) == []
    assert app.expanded == [p.id, p.id] and app.selected == [p.id]
    probs = cli.run_actions(app, cli.parse(["--exec", "nope"]))
    assert probs and "nope" in probs[0]


def test_link_asks_first(store):
    p = store.add_phrase(Phrase("Sig", "Best"))
    uid = store.phrase_uid(p.id)
    no = FakeApp(store, confirm=False)
    cli.run_actions(no, cli.parse([f"phraseforge://exec/{uid}"]))
    assert no.expanded == []
    yes = FakeApp(store, confirm=True)
    cli.run_actions(yes, cli.parse([f"phraseforge://exec/{uid}"]))
    assert yes.expanded == [p.id]


def test_shutdown_action(store):
    app = FakeApp(store)
    cli.run_actions(app, cli.parse(["--shutdown", "--exec", "x"]))
    assert app.quitted and app.expanded == []


def test_open_mounts_read_only_library(store, tmp_path):
    lib = tmp_path / "team.db"
    other = Store(str(lib))
    other.add_phrase(Phrase("Team", "t"))
    other.close()
    assert cli.run_actions(FakeApp(store), cli.parse(["--open", str(lib)])) == []
    from phraseforge import libraries
    libs = libraries.manager(store).libraries()
    assert len(libs) == 1 and libs[0].mode == "ro"


def test_readonly_refuses_edits(store):
    import dataclasses
    before = policy.current()
    policy.set_current(dataclasses.replace(before, editing_disabled=True))
    try:
        with pytest.raises(policy.PolicyError):
            store.add_phrase(Phrase("x", "y"))
    finally:
        policy.set_current(before)


class FakeReg:
    HKEY_CURRENT_USER, REG_SZ = "HKCU", 1

    def __init__(self):
        self.keys = {}

    def CreateKey(self, root, path):
        d = self.keys.setdefault(path, {})

        class K:
            def __enter__(s):
                return d

            def __exit__(s, *a):
                return False
        return K()

    def SetValueEx(self, k, name, _r, _t, value):
        k[name] = value

    def DeleteKey(self, root, path):
        if path not in self.keys:
            raise OSError("no such key")
        self.keys.pop(path)


def test_url_protocol_registration(monkeypatch):
    monkeypatch.setattr(paths, "is_portable", lambda: False)
    reg = FakeReg()
    cli.register_url_protocol(reg)
    assert reg.keys[r"Software\Classes\phraseforge"]["URL Protocol"] == ""
    assert "%1" in reg.keys[r"Software\Classes\phraseforge\shell\open\command"][""]
    cli.unregister_url_protocol(reg)
    assert reg.keys == {}
    monkeypatch.setattr(paths, "is_portable", lambda: True)
    with pytest.raises(paths.PortableRefused):
        cli.register_url_protocol(FakeReg())


def _run(*args, home):
    env = dict(os.environ, PHRASEFORGE_HOME=str(home), QT_QPA_PLATFORM="offscreen")
    return subprocess.run([sys.executable, "-m", "phraseforge", *args], env=env, capture_output=True,
                          text=True, timeout=120)


def test_real_process_usage_error(tmp_path):
    r = _run("--exec", home=tmp_path)
    assert r.returncode == 2 and "--exec needs a value" in r.stderr


def test_real_process_shutdown_with_nothing_running(tmp_path):
    r = _run("--shutdown", home=tmp_path)
    assert r.returncode == 0
    assert not any(tmp_path.glob("*.db"))                        # it never opened a phrase file
