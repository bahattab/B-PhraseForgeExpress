"""PhraseExpress 18 settings seen on the user's screenshots: AI engines, preset model,
DeepL/GPT4All, glossary languages, phrase menu contents, sorting and positions."""
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from phraseforge import ai
from phraseforge.db import Store
from phraseforge.models import Phrase, Trigger, TriggerKind


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def test_engine_lists_match_phraseexpress():
    from phraseforge.ui.settings_dialog import PROVIDERS, TRANSLATION_PROVIDERS
    # PhraseForge adds a free engine first so translation works without a key
    # PhraseExpress' engines, plus the free translator, Gemini, OpenCode Zen and Kilo Code
    pe = ["OpenAI", "Anthropic (Claude)", "GPT4All", "Ollama", "Google Gemini", "OpenRouter", "OpenCode Zen",
          "Kilo Code"]
    assert [t for t, _, _ in PROVIDERS] == pe
    assert [t for t, _, _ in TRANSLATION_PROVIDERS] == ["Free (MyMemory, no key)", "Deepl"] + pe


def test_gpt4all_uses_local_openai_format(monkeypatch):
    seen = {}

    def fake(url, headers, payload, timeout):
        seen.update(url=url, model=payload["model"])
        return {"choices": [{"message": {"content": "OK"}}]}
    monkeypatch.setattr(ai, "_post", fake)
    assert ai.complete({"ai.provider": "gpt4all"}, "hi") == "OK"
    assert seen == {"url": "http://localhost:4891/v1/chat/completions", "model": ai.DEFAULT_MODELS["gpt4all"]}


def test_deepl_translate_keeps_ignored_words(monkeypatch):
    seen = {}

    def fake(url, headers, payload, timeout):
        seen.update(url=url, headers=headers, payload=payload)
        return {"translations": [{"text": "Hallo <keep>PhraseForge</keep>"}]}
    monkeypatch.setattr(ai, "_post", fake)
    out = ai.deepl_translate({"ai.deepl_key": "abc:fx", "translation.ignored_words": "PhraseForge"},
                             "Hello PhraseForge", "German", "English")
    assert out == "Hallo PhraseForge"
    assert seen["url"] == "https://api-free.deepl.com/v2/translate"
    assert seen["headers"]["Authorization"] == "DeepL-Auth-Key abc:fx"
    p = seen["payload"]
    assert p["target_lang"] == "DE" and p["source_lang"] == "EN" and p["text"] == ["Hello <keep>PhraseForge</keep>"]
    with pytest.raises(ai.AIError):
        ai.deepl_translate({}, "x", "German")


def test_preset_model_and_glossary_languages():
    s = {"ai.presets": json.dumps([{"name": "Fix", "prompt": "Fix it", "model": "gpt-4.1"},
                                   {"name": "Short", "prompt": "Shorten", "model": "Auto"}])}
    assert ai.preset_model(s, "fix") == "gpt-4.1" and ai.preset_model(s, "Short") == ""
    g = {"translation.glossaries": json.dumps({"de": "car=Auto", "ar": "car=سيارة", "any": "PC=PC"}),
         "translation.glossary_langs": json.dumps({"de": ["English", "German"], "ar": ["English", "Arabic"]})}
    sysmsg = ai.translation_system(g, "Arabic", "English")
    assert "car -> سيارة" in sysmsg and "car -> Auto" not in sysmsg and "PC -> PC" in sysmsg
    assert "car -> Auto" in ai.translation_system(g, "Arabic", glossary="de")   # named glossary always applies


def test_settings_dialog_preset_model_glossary_langs(app, store):
    from phraseforge.ui.settings_dialog import SettingsDialog
    d = SettingsDialog(store)
    dlg = d._preset_dialog("Fix", "Fix it", "", run=False)
    assert dlg.windowTitle() == "AI Presets" and not dlg.model_box.isVisible()
    dlg.model_combo.setCurrentText("claude-sonnet-5-5")
    assert dlg.result_tuple() == ("Fix", "Fix it", "claude-sonnet-5-5")
    d.presets_list.clear()
    d.presets_list.addItem(d._preset_item(*dlg.result_tuple()))
    d._add_glossary("German", "English", "German")
    g = d._glossary_dialog(run=False)
    assert g.windowTitle() == "New Glossary" and g.src_combo.currentText() == "English"
    d.save()
    presets = json.loads(store.setting("ai.presets"))
    assert presets == [{"name": "Fix", "prompt": "Fix it", "model": "claude-sonnet-5-5"}]
    assert json.loads(store.setting("translation.glossary_langs")) == {"German": ["English", "German"]}


def test_menu_contents_columns(app, store):
    from phraseforge.ui.popup import ROLE_LEFT, ROLE_QK, ROLE_RIGHT, PhrasePopup, content_tokens
    assert content_tokens("autotext_description_quickkey_hotkey") == ["autotext", "description", "quickkey",
                                                                      "hotkey"]
    assert content_tokens("bogus") == ["description", "quickkey"]
    store.add_phrase(Phrase("Hello", "x", triggers=[Trigger(TriggerKind.AUTOTEXT, "hi"),
                                                     Trigger(TriggerKind.HOTKEY, "ctrl+alt+h")]))
    pop = PhrasePopup(store)
    store.set_setting("menu.contents", "autotext_description_quickkey_hotkey")
    pop.show_at(10, 10, caret=None)
    it = [pop.list.item(i) for i in range(pop.list.count()) if pop.list.item(i).text() == "Hello"][0]
    assert it.data(ROLE_LEFT) == "[hi]"
    assert it.data(ROLE_RIGHT).split("   ")[1] == "(CTRL-ALT-H)"
    store.set_setting("menu.contents", "quickkey_description")
    pop.show_at(10, 10, caret=None)
    it = [pop.list.item(i) for i in range(pop.list.count()) if pop.list.item(i).text() == "Hello"][0]
    assert it.data(ROLE_LEFT).startswith("NumPad") and not it.data(ROLE_QK) and not it.data(ROLE_RIGHT)
    pop.hide_all(force=True)


def test_sort_by_length_and_positions(app, store):
    from PySide6.QtGui import QGuiApplication

    from phraseforge.ui.popup import PhrasePopup
    a = store.add_phrase(Phrase("ccc", "x"))
    b = store.add_phrase(Phrase("a", "x"))
    c = store.add_phrase(Phrase("bb", "x"))
    pop = PhrasePopup(store)
    store.set_setting("menu.sort_enabled", "1")
    store.set_setting("menu.sort_method", "length")
    pop._load_settings()
    assert [p.id for p in pop._sorted_phrases([a, b, c])] == [b.id, c.id, a.id]

    g = QGuiApplication.primaryScreen().availableGeometry()
    assert pop.popup_origin("tray", 0, 0, 100, 50) == (g.right() - 108, g.bottom() - 58)
    assert pop.popup_origin("below", g.left() + 50, g.top() + 50, 100, 50) == (g.left() + 50, g.top() + 70)
    store.set_setting("menu.position", "fixed")
    pop._load_settings()
    assert pop.placement(5, 5, None)[0] == "mouse"          # no fixed spot saved yet
    pop.move(g.left() + 30, g.top() + 40)
    pop.remember_position()
    assert pop.fixed_pos() == (g.left() + 30, g.top() + 40)
    assert pop.placement(5, 5, None)[0] == "fixed"
    store.set_setting("menu.position", "above")
    pop._load_settings()
    assert pop.placement(5, 5, (g.left() + 60, g.top() + 300))[0] == "above"


def test_gemini_opencode_kilocode_use_openai_format(monkeypatch):
    seen = []

    def fake(url, headers, payload, timeout):
        seen.append((url, headers.get("Authorization"), payload["model"]))
        return {"choices": [{"message": {"content": "OK"}}]}
    monkeypatch.setattr(ai, "_post", fake)
    assert ai.complete({"ai.provider": "gemini", "ai.gemini_key": "g"}, "hi") == "OK"
    assert seen[-1] == ("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                        "Bearer g", "gemini-2.5-flash")
    assert ai.complete({"ai.provider": "opencode", "ai.opencode_key": "o", "ai.model": "kimi-k2"}, "hi") == "OK"
    assert seen[-1] == ("https://opencode.ai/zen/v1/chat/completions", "Bearer o", "kimi-k2")
    ai.complete({"ai.provider": "kilocode", "ai.kilocode_key": "k", "ai.model": "x/y",
                 "ai.kilocode_base_url": "https://example.test/v1/"}, "hi")
    assert seen[-1] == ("https://example.test/v1/chat/completions", "Bearer k", "x/y")
    with pytest.raises(ai.AIError, match="Enter the model"):
        ai.complete({"ai.provider": "kilocode", "ai.kilocode_key": "k"}, "hi")
    with pytest.raises(ai.AIError, match="Gemini API key is not set"):
        ai.complete({"ai.provider": "gemini"}, "hi")


def test_enhance_prompt():
    got = {}

    def fake(t):
        got["t"] = t
        return '"Summarize {#clipboard} in 3 bullet points, in Arabic."'
    out = ai.enhance_prompt({}, "summarize {#clipboard}", complete_fn=fake)
    assert out == "Summarize {#clipboard} in 3 bullet points, in Arabic." and got["t"] == "summarize {#clipboard}"
    with pytest.raises(ai.AIError):
        ai.enhance_prompt({}, "   ", complete_fn=fake)
