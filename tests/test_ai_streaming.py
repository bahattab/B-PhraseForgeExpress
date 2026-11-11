"""Live replies from the built-in engines (on_delta)."""
import json

import httpx
import pytest

from phraseforge import ai

REAL_CLIENT = httpx.Client


def serve(monkeypatch, body: str, status=200, seen=None):
    def handler(r):
        if seen is not None:
            seen.update(url=str(r.url), payload=json.loads(r.content), headers=dict(r.headers))
        return httpx.Response(status, content=body.encode())
    monkeypatch.setattr(ai.httpx, "Client", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler),
                                                                    timeout=kw.get("timeout")))


@pytest.fixture
def usage(monkeypatch):
    got = []
    monkeypatch.setattr(ai, "USAGE_HOOK", lambda *a: got.append(a))
    return got


def sse(*events):
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"


def test_openai_streams_pieces(monkeypatch, usage):
    seen = {}
    serve(monkeypatch, ": keep-alive\n\n" + sse(
        {"choices": [{"delta": {"role": "assistant"}}]},
        {"choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}}]},
        {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 2}}), seen=seen)
    pieces = []
    out = ai.chat({"ai.openai_key": "k"}, [{"role": "user", "content": "hi"}], "openai", "gpt-4o",
                  on_delta=pieces.append)
    assert out == "Hello" and pieces == ["Hel", "lo"]
    assert seen["payload"]["stream"] is True and seen["payload"]["stream_options"] == {"include_usage": True}
    assert usage == [("openai", "gpt-4o", 7, 2, 0)]


def test_openrouter_stream_has_no_openai_only_options(monkeypatch, usage):
    seen = {}
    serve(monkeypatch, sse({"choices": [{"delta": {"content": "x"}}]}), seen=seen)
    assert ai.chat({"ai.openrouter_key": "k"}, [{"role": "user", "content": "q"}], "openrouter",
                   on_delta=lambda t: None) == "x"
    assert "stream_options" not in seen["payload"]


def test_anthropic_streams_pieces(monkeypatch, usage):
    seen = {}
    body = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in [
        {"type": "message_start", "message": {"usage": {"input_tokens": 11, "output_tokens": 1}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "مر"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "حبا"}},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 4}},
        {"type": "message_stop"}])
    serve(monkeypatch, body, seen=seen)
    pieces = []
    out = ai.chat({"ai.anthropic_key": "k"}, [{"role": "user", "content": "hi"}], "anthropic",
                  on_delta=pieces.append)
    assert out == "مرحبا" and pieces == ["مر", "حبا"]
    assert seen["payload"]["stream"] is True and seen["headers"]["x-api-key"] == "k"
    assert usage[0][2:4] == (11, 4)


def test_anthropic_stream_error(monkeypatch):
    serve(monkeypatch, 'event: error\ndata: {"type": "error", "error": {"message": "Overloaded"}}\n\n')
    with pytest.raises(ai.AIError, match="Overloaded"):
        ai.chat({"ai.anthropic_key": "k"}, [{"role": "user", "content": "x"}], "anthropic", on_delta=lambda t: 0)


def test_ollama_streams_pieces(monkeypatch, usage):
    seen = {}
    lines = [{"message": {"content": "a"}, "done": False}, {"message": {"content": "b"}, "done": False},
             {"message": {"content": ""}, "done": True, "prompt_eval_count": 3, "eval_count": 2}]
    serve(monkeypatch, "\n".join(json.dumps(x) for x in lines) + "\n", seen=seen)
    pieces = []
    assert ai.chat({}, [{"role": "user", "content": "x"}], "ollama", "llama3.2", on_delta=pieces.append) == "ab"
    assert pieces == ["a", "b"] and seen["payload"]["stream"] is True
    assert usage == [("ollama", "llama3.2", 3, 2, 0)]


def test_http_error_while_streaming(monkeypatch):
    serve(monkeypatch, '{"error": "bad key"}', status=401)
    with pytest.raises(ai.AIError, match="401"):
        ai.chat({"ai.openai_key": "k"}, [{"role": "user", "content": "x"}], "openai", on_delta=lambda t: 0)


def test_display_error_does_not_end_the_reply(monkeypatch):
    serve(monkeypatch, sse({"choices": [{"delta": {"content": "a"}}]}, {"choices": [{"delta": {"content": "b"}}]}))

    def boom(_t):
        raise RuntimeError("window closed")
    assert ai.chat({"ai.openai_key": "k"}, [{"role": "user", "content": "x"}], "openai", on_delta=boom) == "ab"


def test_too_long_stream_is_cut_off(monkeypatch):
    monkeypatch.setattr(ai, "MAX_STREAM_CHARS", 5)
    serve(monkeypatch, sse(*[{"choices": [{"delta": {"content": "xxx"}}]}] * 3))
    with pytest.raises(ai.AIError, match="too long"):
        ai.chat({"ai.openai_key": "k"}, [{"role": "user", "content": "x"}], "openai", on_delta=lambda t: 0)


def test_without_on_delta_nothing_changes(monkeypatch):
    sent = {}
    monkeypatch.setattr(ai, "_post", lambda url, h, payload, t: sent.update(payload) or
                        {"choices": [{"message": {"content": "whole"}}]})
    assert ai.chat({"ai.openai_key": "k"}, [{"role": "user", "content": "x"}], "openai") == "whole"
    assert "stream" not in sent


def test_gpt4all_answers_in_one_piece(monkeypatch):
    monkeypatch.setattr(ai, "_post", lambda *a: {"choices": [{"message": {"content": "one"}}]})
    pieces = []
    assert ai.chat({}, [{"role": "user", "content": "x"}], "gpt4all", on_delta=pieces.append) == "one"
    assert pieces == []
