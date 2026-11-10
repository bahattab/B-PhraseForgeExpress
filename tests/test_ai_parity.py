"""AI parity (G-14): vision, image generation, Ollama downloads, usage counts."""
import base64
import json
import random

import httpx
import pytest

from phraseforge import ai
from phraseforge.host import Cancelled, ExpansionContext, ImageAction
from phraseforge.macros import MacroEngine
from phraseforge.security import NETWORK_READ, scan_privileged
from tests.fakehost import FakeHost

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20
JPG = b"\xff\xd8\xff\xe0" + b"0" * 20


@pytest.fixture
def usage(monkeypatch):
    seen = []
    monkeypatch.setattr(ai, "USAGE_HOOK", lambda *a: seen.append(a))
    return seen


def fake_post(monkeypatch, reply):
    sent = {}

    def post(url, headers, payload, timeout):
        sent.update(url=url, headers=headers, payload=payload)
        return reply
    monkeypatch.setattr(ai, "_post", post)
    return sent


# ------------------------------------------------------------------ vision
def test_mime_detection():
    assert ai.image_mime(PNG) == "image/png"
    assert ai.image_mime(JPG) == "image/jpeg"
    assert ai.image_mime(b"GIF89a....") == "image/gif"
    assert ai.image_mime(b"RIFF\0\0\0\0WEBPVP8 ") == "image/webp"
    with pytest.raises(ai.AIError):
        ai.image_mime(b"BM not supported")


def test_openai_vision_format(monkeypatch, usage):
    sent = fake_post(monkeypatch, {"choices": [{"message": {"content": "a cat"}}],
                                   "usage": {"prompt_tokens": 50, "completion_tokens": 3}})
    out = ai.complete({"ai.openai_key": "k"}, "what is it?", "openai", "gpt-4o", images=[PNG])
    assert out == "a cat"
    content = sent["payload"]["messages"][-1]["content"]
    assert content[0] == {"type": "text", "text": "what is it?"}
    assert content[1]["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(PNG).decode()
    assert usage == [("openai", "gpt-4o", 50, 3, 1)]


def test_anthropic_vision_format(monkeypatch, usage):
    sent = fake_post(monkeypatch, {"content": [{"type": "text", "text": "ok"}],
                                   "usage": {"input_tokens": 9, "output_tokens": 1}})
    ai.complete({"ai.anthropic_key": "k"}, "describe", "anthropic", images=[JPG])
    content = sent["payload"]["messages"][-1]["content"]
    assert content[0]["source"] == {"type": "base64", "media_type": "image/jpeg",
                                    "data": base64.b64encode(JPG).decode()}
    assert content[-1] == {"type": "text", "text": "describe"}
    assert usage[0][2:] == (9, 1, 1)


def test_ollama_vision_format(monkeypatch, usage):
    sent = fake_post(monkeypatch, {"message": {"content": "x"}, "prompt_eval_count": 7, "eval_count": 2})
    ai.complete({}, "hi", "ollama", "llava", images=[PNG])
    last = sent["payload"]["messages"][-1]
    assert last["content"] == "hi" and last["images"] == [base64.b64encode(PNG).decode()]
    assert usage == [("ollama", "llava", 7, 2, 1)]


def test_no_vision_engine(monkeypatch):
    fake_post(monkeypatch, {})
    assert ai.capabilities("gpt4all")["vision"] is False
    with pytest.raises(ai.AIError, match="no vision"):
        ai.complete({}, "x", "gpt4all", images=[PNG])


def test_text_only_request_unchanged(monkeypatch):
    sent = fake_post(monkeypatch, {"choices": [{"message": {"content": "y"}}]})
    ai.complete({"ai.openai_key": "k"}, "plain", "openai")
    assert sent["payload"]["messages"][-1] == {"role": "user", "content": "plain"}


def test_broken_usage_hook_does_not_break_answer(monkeypatch):
    fake_post(monkeypatch, {"choices": [{"message": {"content": "fine"}}]})

    def boom(*a):
        raise RuntimeError("x")
    monkeypatch.setattr(ai, "USAGE_HOOK", boom)
    assert ai.complete({"ai.openai_key": "k"}, "p", "openai") == "fine"


# ------------------------------------------------------------------ usage
def test_add_usage_and_rows():
    s = ai.add_usage("", "openai", "gpt-4o", 10, 2)
    s = ai.add_usage(s, "openai", "gpt-4o", 5, 1)
    s = ai.add_usage(s, "openai", "gpt-image-1", 0, 0, 1)
    assert json.loads(s)["since"]
    assert ai.usage_rows(s) == [("openai/gpt-4o", 2, 15, 3, 0), ("openai/gpt-image-1", 1, 0, 0, 1)]
    assert ai.usage_rows("not json") == []
    assert json.loads(ai.add_usage("[1]", "x", "", 1, 1))["x"]["requests"] == 1


def test_usage_is_device_only():
    from phraseforge.db import DEVICE_SETTING_PREFIXES
    assert any("ai.usage".startswith(p) for p in DEVICE_SETTING_PREFIXES)


# ------------------------------------------------------------------ image generation
def test_generate_image(monkeypatch, usage):
    sent = fake_post(monkeypatch, {"data": [{"b64_json": base64.b64encode(PNG).decode()}]})
    out = ai.generate_image({"ai.openai_key": "k"}, "a red bike", size="512x512")
    assert out == PNG
    assert sent["url"] == "https://api.openai.com/v1/images/generations"
    assert sent["payload"] == {"model": "gpt-image-1", "prompt": "a red bike", "n": 1, "size": "512x512"}
    assert usage == [("openai", "gpt-image-1", 0, 0, 1)]


def test_generate_image_gemini_asks_for_base64(monkeypatch, usage):
    sent = fake_post(monkeypatch, {"data": [{"b64_json": base64.b64encode(PNG).decode()}]})
    ai.generate_image({"ai.gemini_key": "k", "ai.image_provider": "gemini"}, "x")
    assert sent["payload"]["response_format"] == "b64_json"
    assert "generativelanguage" in sent["url"]


@pytest.mark.parametrize("settings,prompt,size,msg", [
    ({"ai.openai_key": "k"}, "x", "big", "size"),
    ({"ai.openai_key": "k"}, "  ", "", "describe"),
    ({}, "x", "", "key is not set"),
    ({"ai.image_provider": "anthropic"}, "x", "", "cannot make images"),
])
def test_generate_image_errors(monkeypatch, settings, prompt, size, msg):
    fake_post(monkeypatch, {})
    with pytest.raises(ai.AIError, match=msg):
        ai.generate_image(settings, prompt, size=size)


def test_generate_image_bad_response(monkeypatch):
    fake_post(monkeypatch, {"data": []})
    with pytest.raises(ai.AIError, match="unexpected"):
        ai.generate_image({"ai.openai_key": "k"}, "x")


# ------------------------------------------------------------------ Ollama downloads
REAL_CLIENT = httpx.Client


def mock_ollama(monkeypatch, handler):
    real = REAL_CLIENT
    monkeypatch.setattr(ai.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler),
                                                             timeout=kw.get("timeout")))


def test_ollama_models(monkeypatch):
    mock_ollama(monkeypatch, lambda r: httpx.Response(200, json={"models": [{"name": "b"}, {"name": "a"}]}))
    assert ai.ollama_models({}) == ["a", "b"]


def test_ollama_pull_progress(monkeypatch):
    lines = [{"status": "pulling manifest"}, {"status": "downloading", "completed": 5, "total": 10},
             {"status": "success"}]
    seen = {}

    def handler(r):
        seen["body"] = json.loads(r.content)
        seen["url"] = str(r.url)
        return httpx.Response(200, content="\n".join(json.dumps(x) for x in lines).encode())
    mock_ollama(monkeypatch, handler)
    progress = []
    ai.ollama_pull({"ai.ollama_url": "http://pc:11434/"}, "llama3.2", lambda *a: progress.append(a))
    assert seen == {"body": {"model": "llama3.2", "stream": True}, "url": "http://pc:11434/api/pull"}
    assert progress[1] == ("downloading", 5, 10)


def test_ollama_pull_errors(monkeypatch):
    mock_ollama(monkeypatch, lambda r: httpx.Response(200, content=b'{"error": "file does not exist"}\n'))
    with pytest.raises(ai.AIError, match="does not exist"):
        ai.ollama_pull({}, "nope")
    mock_ollama(monkeypatch, lambda r: httpx.Response(200, content=b'{"status": "pulling"}\n'))
    with pytest.raises(ai.AIError, match="stopped before"):
        ai.ollama_pull({}, "half")
    with pytest.raises(ai.AIError, match="cancelled"):
        ai.ollama_pull({}, "half", cancelled=lambda: True)
    with pytest.raises(ai.AIError, match="model name"):
        ai.ollama_pull({}, "two words")


# ------------------------------------------------------------------ macros
class VisionHost(FakeHost):
    def __init__(self, settings=None):
        super().__init__(settings)
        self.clip_image = PNG
        self.region = JPG
        self.made = None

    def ai_vision(self, prompt, images, provider="", model="", system=""):
        self.calls.append(("ai_vision", (prompt, tuple(images), provider, model, system)))
        return " seen "

    def clipboard_image(self):
        return self.clip_image

    def capture_region(self):
        return self.region

    def ai_image(self, prompt, provider="", model="", size=""):
        self.made = (prompt, provider, model, size)
        return "/tmp/out.png"


def run(host, text):
    return MacroEngine(host, rng=random.Random(1)).expand(text, ExpansionContext())


def text(host, s):
    return MacroEngine(host, rng=random.Random(1)).expand_to_text(s, ExpansionContext())


def test_ai_image_sources(tmp_path):
    host = VisionHost({"ai.provider": "openai"})
    img = tmp_path / "p.png"
    img.write_bytes(PNG)
    assert text(host, '{#ai "what?" -image clipboard}') == "seen"
    assert text(host, f'{{#ai "both" -image "region|file:{img}"}}') == "seen"
    calls = host.called("ai_vision")
    assert calls[0][:2] == ("what?", (PNG,))
    assert calls[1][1] == (JPG, PNG)


def test_ai_image_no_vision_engine():
    host = VisionHost({"ai.provider": "gpt4all"})
    assert text(host, '{#ai "x" -image clipboard}') == "[ai: engine has no vision]"
    assert text(host, '{#ai "x" -image clipboard -provider openai}') == "seen"


def test_ai_image_errors(tmp_path):
    host = VisionHost({"ai.provider": "openai"})
    host.clip_image = None
    # errors are written into the text like other macro errors
    assert text(host, '{#ai "x" -image clipboard}') == "[ai: the clipboard holds no image]"
    assert "image not found" in text(host, f'{{#ai "x" -image "file:{tmp_path / "none.png"}"}}')
    assert "clipboard, region or file" in text(host, '{#ai "x" -image screen}')
    host.region = None
    with pytest.raises(Cancelled):
        text(host, '{#ai "x" -image region}')


def test_aiimage_macro():
    host = VisionHost()
    assert run(host, '{#aiimage -prompt "a red bike" -size 512x512 -provider gemini}') == [ImageAction("/tmp/out.png")]
    assert host.made == ("a red bike", "gemini", "", "512x512")
    run(host, "{#aiimage a cat}")
    assert host.made == ("a cat", "", "", "1024x1024")


def test_ai_network_image_needs_approval():
    assert scan_privileged(r'{#ai "x" -image "file:\\server\share\a.png"}') == [NETWORK_READ]
    assert scan_privileged('{#ai "x" -image clipboard}') == []
    assert scan_privileged('{#ai "x" -image "file:C:\\a.png"}') == []


def test_usage_write_does_not_notify(tmp_path):
    from phraseforge.db import Store
    st = Store(tmp_path / "x.db")
    seen = []
    st._listeners.append(lambda kind, id_=None: seen.append(kind))
    st.set_setting("ai.usage", "{}", notify=False)
    assert st.setting("ai.usage") == "{}"
    assert "setting" not in seen
    st.set_setting("ai.model", "m")
    assert "setting" in seen
