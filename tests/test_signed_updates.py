"""Signed in-app updates (FR-APP-05): only a setup signed by a built-in key is run."""
import io
import json

import pytest

from phraseforge import updates
from phraseforge.plugins.signing import new_key

BASE = "https://github.com/bahattab/B-PhraseForgeExpress/releases/download/v9.9.9/"
SETUP = BASE + "B-PhraseForgeExpress-Setup-9.9.9.exe"


@pytest.fixture
def keys():
    priv, pub = new_key()
    return priv, frozenset({pub})


class Resp(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_for(files):
    def opener(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        return Resp(files[url])
    return opener


def make_release(tmp_path, priv, body=b"MZ setup bytes"):
    exe = tmp_path / "src.exe"
    exe.write_bytes(body)
    sig = updates.sign_file(exe, priv)
    rel = {"version": "9.9.9", "setup_url": SETUP, "sig_url": SETUP + ".sig"}
    return rel, {SETUP: body, SETUP + ".sig": sig}


def test_release_lists_signature():
    api = {"tag_name": "v9.9.9", "html_url": BASE.replace("download/", "tag/"),
           "assets": [{"name": "B-PhraseForgeExpress-Setup-9.9.9.exe", "browser_download_url": SETUP},
                      {"name": "x.sig", "browser_download_url": SETUP + ".sig"}]}
    rel = updates.latest_release(opener=lambda req, timeout=None: Resp(json.dumps(api).encode()))
    assert rel["sig_url"] == SETUP + ".sig"


def test_good_update_is_verified(tmp_path, keys):
    priv, trusted = keys
    rel, files = make_release(tmp_path, priv)
    path = updates.download_verified(rel, tmp_path / "dl", opener=opener_for(files), keys=trusted)
    assert path.read_bytes() == b"MZ setup bytes"


def test_tampered_setup_is_refused_and_deleted(tmp_path, keys):
    priv, trusted = keys
    rel, files = make_release(tmp_path, priv)
    files[SETUP] = b"MZ evil"
    with pytest.raises(updates.UpdateError, match="does not match"):
        updates.download_verified(rel, tmp_path / "dl", opener=opener_for(files), keys=trusted)
    assert list((tmp_path / "dl").iterdir()) == []


def test_unknown_key_is_refused(tmp_path, keys):
    priv, _ = keys
    rel, files = make_release(tmp_path, priv)
    _, other = new_key()
    with pytest.raises(updates.UpdateError, match="does not trust"):
        updates.download_verified(rel, tmp_path / "dl", opener=opener_for(files), keys=frozenset({other}))


def test_no_keys_means_no_install(tmp_path, keys):
    priv, _ = keys
    rel, files = make_release(tmp_path, priv)
    assert not updates.can_install(rel, frozenset())
    assert updates.can_install(rel, keys[1])
    assert not updates.can_install(dict(rel, sig_url=""), keys[1])
    with pytest.raises(updates.UpdateError, match="download page"):
        updates.download_verified(rel, tmp_path, opener=opener_for(files), keys=frozenset())


def test_foreign_links_and_size_are_refused(tmp_path, keys):
    priv, trusted = keys
    rel, files = make_release(tmp_path, priv)
    bad = dict(rel, setup_url="https://evil.example/Setup.exe")
    with pytest.raises(updates.UpdateError):
        updates.download_verified(bad, tmp_path / "a", opener=opener_for(files), keys=trusted)
    files[SETUP + ".sig"] = b"x" * (70 * 1024)
    with pytest.raises(updates.UpdateError, match="larger"):
        updates.download_verified(rel, tmp_path / "b", opener=opener_for(files), keys=trusted)


def test_broken_signature_file(tmp_path, keys):
    exe = tmp_path / "a.exe"
    exe.write_bytes(b"x")
    for raw in (b"not json", b'{"key": "!!", "sig": "x"}', b"{}"):
        with pytest.raises(updates.UpdateError, match="cannot be read"):
            updates.verify_file(exe, raw, keys[1])


def test_sign_tool(tmp_path, keys, monkeypatch, capsys):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "sign_release", Path(__file__).resolve().parents[1] / "tools" / "sign_release.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    exe = tmp_path / "Setup.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setenv("PHRASEFORGE_RELEASE_KEY", keys[0])
    assert tool.main([str(exe)]) == 0
    updates.verify_file(exe, (tmp_path / "Setup.exe.sig").read_bytes(), keys[1])
    monkeypatch.delenv("PHRASEFORGE_RELEASE_KEY")
    assert tool.main([str(exe)]) == 0                 # no key: signs nothing, does not fail the build
