"""Plugin engines get what built-in engines have: images, usage counts, model downloads (G-13)."""
import base64
from pathlib import Path

import pytest

from phraseforge import ai
from phraseforge.db import Store
from phraseforge.plugins import engines
from phraseforge.plugins import manager as pm

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "plugins" / "echo-ai"
P = "plugin:echo-ai"


@pytest.fixture
def eng(tmp_path):
    store = Store(":memory:")
    mgr = pm.PluginManager(store, tmp_path / "plugins")
    pm.set_current(mgr)
    mgr.install(EXAMPLE, accept=True)
    yield engines.engine(P)
    mgr.stop_all()
    pm.set_current(None)
    store.close()


@pytest.fixture
def usage(monkeypatch):
    seen = []
    monkeypatch.setattr(ai, "USAGE_HOOK", lambda *a: seen.append(a))
    return seen


def test_capabilities_reach_ai(eng):
    assert ai.capabilities(P) == {"vision": False, "image": True, "models": True}
    assert eng.list_models({}, kind="image") == ["echo-image-1"]


def test_generate_counts_usage(eng, usage):
    assert ai.complete({}, "two words", P, model="echo-1") == "echo: two words"
    assert usage == [(P, "echo-1", 2, 3, 0)]


def test_generate_image(eng, usage):
    data = ai.generate_image({"ai.image_provider": P}, "a red bike")
    assert ai.image_mime(data) == "image/png"
    assert usage == [(P, "default", 3, 0, 1)]
    with pytest.raises(ai.AIError, match="describe"):
        ai.generate_image({}, "  ", provider=P)


def test_pull_model_reports_progress(eng):
    seen = []
    ai.pull_model({}, P, "echo-2", lambda st, d, t: seen.append((st, d, t)))
    assert seen[0] == ("pulling manifest", 0, 0) and seen[-1][0] == "verifying"
    with pytest.raises(ai.AIError, match="without spaces"):
        ai.pull_model({}, P, "two words")


def fake_reply(monkeypatch, eng, caps, reply):
    monkeypatch.setattr(type(eng), "capabilities", lambda self: dict(caps))
    monkeypatch.setattr(type(eng), "_call", lambda self, method, params=None, **k: reply)


@pytest.mark.parametrize("reply,msg", [
    ({}, "without an image"),
    ({"image": "not base64!"}, "could not be read"),
    ({"image": base64.b64encode(b"BM bitmap").decode()}, "PNG, JPEG"),
    ({"image": "A" * (engines.MAX_IMAGE * 2)}, "12 MB"),
    ("text", "without an image"),
])
def test_bad_images_are_refused(eng, monkeypatch, reply, msg):
    fake_reply(monkeypatch, eng, {"image_gen": True}, reply)
    with pytest.raises(ai.AIError, match=msg):
        eng.generate_image({}, "x")


def test_missing_capability_is_refused(eng, monkeypatch):
    fake_reply(monkeypatch, eng, {}, {"image": "x"})
    with pytest.raises(ai.AIError, match="cannot make images"):
        eng.generate_image({}, "x")
    with pytest.raises(ai.AIError, match="cannot download models"):
        eng.pull_model({}, "m")


@pytest.mark.parametrize("u,expect", [
    ({"input_tokens": 5, "output_tokens": 7}, (5, 7)),
    ({"input_tokens": -1, "output_tokens": True}, (0, 0)),
    ({"input_tokens": 10 ** 12, "output_tokens": "9"}, (0, 0)),
])
def test_usage_values_are_checked(eng, monkeypatch, usage, u, expect):
    fake_reply(monkeypatch, eng, {}, {"text": "ok", "usage": u})
    eng.generate({}, [{"role": "user", "content": "x"}], {"model": "m"})
    assert usage == [(P, "m", *expect, 0)]


def test_no_usage_no_count(eng, monkeypatch, usage):
    fake_reply(monkeypatch, eng, {}, {"text": "ok"})
    eng.generate({}, [{"role": "user", "content": "x"}], {})
    assert usage == []


def test_status_lines_are_plain():
    assert engines._status("<b>big</b>\n\nline " + "x" * 300) .startswith("\u2039b\u203abig")
    assert len(engines._status("y" * 500)) == 200
