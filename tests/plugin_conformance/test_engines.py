"""FR-PLG-03 conformance: every bundled engine and a plugin engine answer the same contract."""
from pathlib import Path

import pytest

from phraseforge import ai
from phraseforge.db import Store
from phraseforge.plugins import engines
from phraseforge.plugins import manager as pm

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "plugins" / "echo-ai"


@pytest.fixture
def fake_http(monkeypatch):
    calls = []

    def post(url, headers, payload, timeout):
        calls.append((url, payload))
        if "anthropic" in url:
            return {"content": [{"type": "text", "text": "ok"}]}
        if "/api/chat" in url:
            return {"message": {"content": "ok"}}
        if "deepl" in url:
            return {"translations": [{"text": "ok"}]}
        return {"choices": [{"message": {"content": "ok"}}]}
    monkeypatch.setattr(ai, "_post", post)
    monkeypatch.setattr(ai, "free_translate", lambda text, to, src="", **k: "ok")
    return calls


@pytest.fixture
def settings():
    s = {f"ai.{p}_key": "k" for p in ai.DEFAULT_MODELS}
    s.update({"ai.deepl_key": "k", "ai.opencode_model": "m"})
    return s


@pytest.fixture
def plugin_engine(tmp_path):
    store = Store(":memory:")
    mgr = pm.PluginManager(store, tmp_path / "plugins")
    pm.set_current(mgr)
    mgr.install(EXAMPLE, accept=True)
    yield engines.engine("plugin:echo-ai")
    mgr.stop_all()
    pm.set_current(None)
    store.close()


def _check_contract(e, settings):
    d = e.describe()
    for k in engines.DESCRIBE_KEYS:
        assert k in d, k
    assert d["type"] in ("ai_engine", "translator")
    st = e.status(settings)
    assert set(st) >= {"configured", "error"}
    caps = e.capabilities()
    assert set(caps) == set(engines.CAPABILITY_KEYS) and all(isinstance(v, bool) for v in caps.values())
    schema = e.settings_schema()
    assert schema.get("type") == "object" and isinstance(schema.get("properties"), dict)
    assert isinstance(e.list_models(settings), list) and isinstance(e.list_languages(settings), list)


@pytest.mark.parametrize("provider", sorted(engines.BUILTIN))
def test_builtin_engine_conforms(provider, settings, fake_http):
    e = engines.BUILTIN[provider]
    _check_contract(e, settings)
    model_needed = provider in ("opencode", "kilocode")
    if model_needed:                       # these services have no default model: the user picks one
        settings = dict(settings, **{"ai.provider": provider, "ai.model": "m"})
    if e.kind == "ai_engine":
        out = e.generate(settings, [{"role": "user", "content": "hi"}], {"model": "m" if model_needed else ""})
        assert out == "ok"
    assert e.translate(settings, "hi", "en", "Arabic") == "ok"


def test_plugin_engine_conforms(plugin_engine, settings):
    e = plugin_engine
    _check_contract(e, settings)
    assert e.describe()["provider"] == "plugin:echo-ai"
    assert e.capabilities()["custom_instructions"] is True
    assert e.generate(settings, [{"role": "user", "content": "hi"}], {}) == "echo: hi"
    assert e.translate(settings, "hi", "en", "Arabic") == "[Arabic] hi"


def test_plugin_engine_through_ai_and_translation(plugin_engine):
    s = {"ai.provider": "plugin:echo-ai", "translation.provider": "plugin:echo-ai"}
    assert ai.complete(s, "hello") == "echo: hello"
    assert ai.complete(s, "hello", system="be brief") == "echo: hello (with instructions)"
    assert ai.translate_text(s, "Good {#date} morning", "Arabic") == "[Arabic] Good {#date} [Arabic] morning"
    assert ("Plugin: Echo AI", "plugin:echo-ai") in engines.choices("ai_engine")


def test_switched_off_plugin_engine_reports(plugin_engine):
    pm.current().set_enabled("echo-ai", False)
    with pytest.raises(ai.AIError, match="not installed or switched off"):
        ai.complete({"ai.provider": "plugin:echo-ai"}, "x")
