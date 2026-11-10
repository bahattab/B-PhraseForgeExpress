"""Plugin signatures (FR-PLG-01 detached signature)."""
import dataclasses
import shutil
import zipfile
from pathlib import Path

import pytest

from phraseforge import policy
from phraseforge.db import Store
from phraseforge.plugins import install as inst
from phraseforge.plugins import manager as pm
from phraseforge.plugins import signing
from phraseforge.plugins.manifest import ManifestError

HELLO = Path(__file__).resolve().parents[1] / "examples" / "plugins" / "hello"


@pytest.fixture
def plugin(tmp_path):
    d = tmp_path / "hello"
    shutil.copytree(HELLO, d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return d


@pytest.fixture
def keys():
    return signing.new_key()


def zip_of(folder: Path, out: Path) -> Path:
    with zipfile.ZipFile(out, "w") as z:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(folder).as_posix())
    return out


def test_unsigned(plugin):
    assert inst.signature(plugin).state == "unsigned"


def test_signed_trusted_and_untrusted(plugin, keys, tmp_path):
    priv, pub = keys
    assert signing.sign_folder(plugin, priv) == pub
    assert inst.signature(plugin).state == "untrusted"
    sig = inst.signature(plugin, {pub})
    assert sig.state == "trusted" and len(sig.fingerprint) == 19
    assert inst.signature(zip_of(plugin, tmp_path / "h.pfplugin"), {pub}).state == "trusted"


@pytest.mark.parametrize("change", ["edit", "add", "remove"])
def test_any_file_change_breaks_it(plugin, keys, change):
    (plugin / "helper.py").write_text("x = 1")
    signing.sign_folder(plugin, keys[0])
    assert inst.signature(plugin).state == "untrusted"
    if change == "edit":
        (plugin / "main.py").write_text("print('evil')")
    elif change == "add":
        (plugin / "extra.py").write_text("x = 1")
    else:
        (plugin / "helper.py").unlink()
    assert inst.signature(plugin).state == "invalid"


def test_garbage_signature_file(plugin):
    (plugin / "plugin.sig").write_text("not json")
    assert inst.signature(plugin).state == "invalid"


def test_install_refuses_invalid_and_requires_trusted_when_asked(plugin, keys, tmp_path):
    priv, pub = keys
    root = tmp_path / "plugins"
    inst.install(plugin, root)                                       # unsigned is allowed by default
    with pytest.raises(ManifestError, match="trusted publisher"):
        inst.install(plugin, root, require_signed=True)
    signing.sign_folder(plugin, priv)
    with pytest.raises(ManifestError, match="trusted publisher"):
        inst.install(plugin, root, require_signed=True)
    inst.install(plugin, root, {pub}, require_signed=True)
    (plugin / "main.py").write_text("print('changed')")
    with pytest.raises(ManifestError, match="not valid"):
        inst.install(plugin, root, {pub})


def test_manager_uses_settings_and_policy_keys(plugin, keys, tmp_path, monkeypatch):
    priv, pub = keys
    signing.sign_folder(plugin, priv)
    st = Store(":memory:")
    mgr = pm.PluginManager(st, root=tmp_path / "plugins")
    st.set_setting("plugins.trusted_keys", f"# my publisher\n{pub}\n")
    assert mgr.signature(plugin).state == "trusted"                    # no policy: the user's keys count
    pol = dataclasses.replace(policy.NO_POLICY, plugins_require_signature=True)
    monkeypatch.setattr(policy, "current", lambda: pol)
    with pytest.raises(ManifestError):
        mgr.install(plugin, accept=True)
    pol2 = dataclasses.replace(pol, plugins_trusted_keys=frozenset({pub}))
    monkeypatch.setattr(policy, "current", lambda: pol2)
    assert mgr.signature(plugin).state == "trusted"
    mgr.install(plugin, accept=True)


def test_policy_parsing_and_fail_closed(tmp_path):
    p = policy.parse('plugins_require_signature = true\nplugins_trusted_keys = ["abc"]\n')
    assert p.plugins_require_signature and p.plugins_trusted_keys == {"abc"}
    bad = tmp_path / "policy.toml"
    bad.write_text("not = = toml")
    assert policy.load(bad).plugins_require_signature is True


def test_consent_text_shows_signature(plugin, keys):
    from phraseforge.plugins.manifest import parse
    from phraseforge.ui.plugins_dialog import consent_text
    m = parse((plugin / "plugin.toml").read_text())
    assert "Not signed" in consent_text(m, ["x"], False, sig=signing.Signature("unsigned"))
    priv, pub = keys
    assert signing.fingerprint(pub) in consent_text(m, ["x"], False, sig=signing.Signature("trusted", pub))


def test_pyc_in_signed_zip_is_never_installed(plugin, keys, tmp_path):
    """R: a .pyc / __pycache__ added to a signed package must not run under the signature."""
    priv, pub = keys
    signing.sign_folder(plugin, priv)
    pkg = zip_of(plugin, tmp_path / "h.pfplugin")
    with zipfile.ZipFile(pkg, "a") as z:
        z.writestr("__PyCache__/main.cpython-313.pyc", b"evil")
        z.writestr("helper.PYC", b"evil")
        z.writestr(".Git/config", b"x")
    assert inst.signature(pkg, {pub}).state == "trusted"
    root = tmp_path / "plugins"
    inst.install(pkg, root, {pub}, require_signed=True)
    names = {p.name.lower() for p in (root / "hello").rglob("*")}
    assert not names & {"__pycache__", "main.cpython-313.pyc", "helper.pyc", ".git", "config"}


def test_user_keys_do_not_count_when_policy_requires_signature(plugin, keys, tmp_path, monkeypatch):
    priv, pub = keys
    signing.sign_folder(plugin, priv)
    st = Store(":memory:")
    st.set_setting("plugins.trusted_keys", pub)
    mgr = pm.PluginManager(st, root=tmp_path / "plugins")
    pol = dataclasses.replace(policy.NO_POLICY, plugins_require_signature=True)
    monkeypatch.setattr(policy, "current", lambda: pol)
    assert mgr.signature(plugin).state == "untrusted"
    with pytest.raises(ManifestError):
        mgr.install(plugin, accept=True)


def test_indented_comment_lines_are_not_keys():
    assert signing.trusted_keys("  # note\n abc \n") == {"abc"}
