"""Prompt Optimizer: conversation, "Optimized Prompt:" marker, templates, project context, cache."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from phraseforge import ai  # noqa: E402
from phraseforge import prompt_optimizer as po  # noqa: E402

FINAL = "Based on your answers...\n\nOptimized Prompt:\nCreate an AI Teacher Web Page with:\n- Chat interface"


def test_extract_optimized():
    assert po.extract_optimized(FINAL) == "Create an AI Teacher Web Page with:\n- Chat interface"
    assert po.extract_optimized("**Optimized Prompt:**\n\"Do X\"") == "Do X"
    assert po.extract_optimized("What framework do you use?") == ""


def test_templates_fill_and_user_templates():
    api = next(t for t in po.BUILTIN_TEMPLATES if t.id == "api-endpoint")
    assert api.variables == ["method", "path", "functionality", "auth", "response"]
    text = api.fill({"method": "POST", "path": "/todos"})
    assert "- Method: POST" in text and "- Path: /todos" in text and "(not specified)" in text
    user = po.parse_templates(json.dumps([{"name": "Mine", "text": "Write {{what}}"}, {"bad": 1}]))
    assert [t.name for t in user] == ["Mine"] and user[0].variables == ["what"]
    assert po.parse_templates("not json") == []


def test_analyze_project(tmp_path):
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "App.tsx").write_text("x")
    (tmp_path / "web" / "util.ts").write_text("x")
    (tmp_path / "server.py").write_text("x")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "a.js").write_text("x")
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"react": "18", "express": "4"}}))
    (tmp_path / "requirements.txt").write_text("FastAPI==0.110\npytest\n")
    ctx = po.analyze_project(tmp_path)
    assert ctx.languages[0] == "TypeScript" and "Python" in ctx.languages and "JavaScript" not in ctx.languages
    assert set(ctx.frameworks) == {"React", "Express", "FastAPI", "pytest"}
    assert "Frameworks and libraries:" in ctx.describe()
    assert "user's project" in po.system_prompt(ctx.describe())


def test_conversation_history_cache_and_retry():
    calls = []

    def chat_fn(history, system):
        calls.append((list(history), system))
        return "Which framework?" if len(history) == 1 else FINAL
    cache = po.ReplyCache()
    c = po.Conversation({}, context="Languages: Python", chat_fn=chat_fn, cache=cache)
    assert c.send("help me build an AI teacher page") == "Which framework?"
    assert c.optimized() == ""
    c.send("React")
    assert c.optimized().startswith("Create an AI Teacher Web Page")
    assert [m["role"] for m in calls[1][0]] == ["user", "assistant", "user"]
    assert "Languages: Python" in calls[0][1] and "Optimized Prompt:" in calls[0][1]
    c2 = po.Conversation({}, context="Languages: Python", chat_fn=lambda h, s: 1 / 0, cache=cache)
    assert c2.send("help me build an AI teacher page") == "Which framework?"      # from the cache
    c3 = po.Conversation({}, chat_fn=lambda h, s: 1 / 0, cache=po.ReplyCache())
    with pytest.raises(ZeroDivisionError):
        c3.send("x")
    assert c3.history == []                                                    # failed turn removed
    t = [0.0]
    old = po.ReplyCache(ttl_s=10, clock=lambda: t[0])
    old.put("k", "v")
    t[0] = 11
    assert old.get("k") is None


def test_ai_chat_sends_the_whole_conversation(monkeypatch):
    seen = []
    monkeypatch.setattr(ai, "_post", lambda url, h, payload, t: (seen.append(payload),
                                                                 {"choices": [{"message": {"content": "ok"}}]})[1])
    hist = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}, {"role": "user", "content": "c"}]
    assert ai.chat({"ai.provider": "openai", "ai.openai_key": "k"}, hist, system="S", raw_system=True) == "ok"
    assert seen[-1]["messages"] == [{"role": "system", "content": "S"}] + hist
    monkeypatch.setattr(ai, "_post", lambda url, h, payload, t: (seen.append(payload),
                                                                 {"content": [{"type": "text", "text": "ok"}]})[1])
    ai.chat({"ai.provider": "anthropic", "ai.anthropic_key": "k"}, hist, system="S", raw_system=True)
    assert seen[-1]["messages"] == hist and seen[-1]["system"] == "S"
    with pytest.raises(ai.AIError):
        ai.chat({"ai.openai_key": "k"}, hist[:2])                    # must end with the user


def test_window(tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from phraseforge.db import Store
    from phraseforge.ui.prompt_optimizer import PromptOptimizerWindow
    store = Store(tmp_path / "o.db")
    replies = iter(["What should the page do?", FINAL])
    w = PromptOptimizerWindow(store, chat_fn=lambda h, s: next(replies))
    w.quiet = True
    assert not w.copy_btn.isEnabled()
    w.input.setPlainText("AI teacher page")
    w.send()
    assert w.input.toPlainText() == "" and "What should the page do?" in w.transcript.toPlainText()
    w.send("for kids")
    assert w.copy_btn.isEnabled() and w.copy_optimized() == QApplication.clipboard().text()
    got = []
    w.to_prompt_tower.connect(got.append)
    w.save_as_phrase.connect(lambda d, t: got.append((d, t)))
    w._save_phrase()
    assert got[-1][0].startswith("Create an AI Teacher Web Page")
    api = next(t for t in w.templates() if t.id == "api-endpoint")
    assert "Method: GET" in w.use_template(api, {"method": "GET"})
    w.input.setPlainText("Translate {{text}} to {{language}}")
    assert w._save_template("Translator")
    assert "Translator" in [t.name for t in w.templates()]
    w.new_conversation()
    assert w.conv.history == [] and not w.copy_btn.isEnabled()
    w.close()
    store.close()
