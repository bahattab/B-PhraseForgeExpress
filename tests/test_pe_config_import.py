"""PhraseExpress config.xml import (FR-IMP-01, G-14). The fixture keeps the layout of a real
PhraseExpress 18.0.84 config.xml; the API key values are made up."""
import json

import pytest

from phraseforge.db import Store
from phraseforge.importers import pe_config

CONFIG = """<?xml version="1.0" encoding="utf-8"?>
<xml>
\t<pexconfig>
\t\t<Other><Version>18.0.84</Version></Other>
\t\t<Translation>
\t\t\t<DefTranslationEngine>OpenRouter</DefTranslationEngine>
\t\t\t<IgnoreWords>PhraseForge|Riyadh</IgnoreWords>
\t\t\t<glossaries>
\t\t\t\t<glossary><name/><fromlang>EN</fromlang><tolang>AR</tolang><dict/></glossary>
\t\t\t\t<glossary><name>E to A</name><fromlang>EN</fromlang><tolang>AR</tolang><dict>cat=قطة</dict></glossary>
\t\t\t\t<glossary><name>A to E</name><fromlang>AR</fromlang><tolang>EN</tolang><dict/></glossary>
\t\t\t</glossaries>
\t\t</Translation>
\t\t<AI>
\t\t\t<DefAITextEngine>OpenRouter</DefAITextEngine>
\t\t\t<DeeplAPIKey/>
\t\t\t<OpenAIAPIKey>QgBEOT4rUjsCEx0WLzw+IX5e
GDYbKDwJ</OpenAIAPIKey>
\t\t\t<OpenRouterAPIKey>QgBEOQZdLh0/EzAaL1Yl</OpenRouterAPIKey>
\t\t\t<AnthropicClaudeAPIKey/>
\t\t</AI>
\t\t<AzureAD><AccToken>EnlAEwg2IyFQ</AccToken></AzureAD>
\t\t<General>
\t\t\t<NewPhraseShortcut>3139</NewPhraseShortcut>
\t\t\t<LastUsedShortcut>0</LastUsedShortcut>
\t\t\t<TrayPopupShortcut>2080</TrayPopupShortcut>
\t\t\t<QuickSearchShortcut>114</QuickSearchShortcut>
\t\t</General>
\t\t<Expert>
\t\t\t<AllowedApps/>
\t\t\t<DeclinedApps>KeePass.exe|C:\\Tools\\putty.exe</DeclinedApps>
\t\t\t<AppMethods>pidgin.exe|3:safari.exe|3</AppMethods>
\t\t\t<CharsBefore>#0#10#9#13 "'&lt;{([/\\-_</CharsBefore>
\t\t\t<CharsAfter>#9#10#13 "'&gt;}]).,?!/\\:;-_ </CharsAfter>
\t\t</Expert>
\t\t<AIPresets>
\t\t\t<Preset>Create Effective Detailed AI Prompt|Create Effective Detailed AI Prompt|0|70|50|gpt-4o|0</Preset>
\t\t\t<Preset>0 - Translate to Arabic|Translate from English to Arabic|100|70|50|openrouter/free|0</Preset>
\t\t\t<Preset>0 - Create a perfect prompt|Generate, refine  and Optimizer prompt to perfection,"I need a role | a task"|0|80|80||0</Preset>
\t\t\t<Preset>broken|only two</Preset>
\t\t</AIPresets>
\t</pexconfig>
</xml>
"""


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


@pytest.fixture
def cfg(tmp_path):
    p = tmp_path / "config.xml"
    p.write_text(CONFIG, encoding="utf-8")
    return p


def test_parse_real_layout(cfg):
    d = pe_config.parse_config(cfg)
    assert d.version == "18.0.84"
    assert d.ai_engine == d.translation_engine == "openrouter"
    assert [p["name"] for p in d.presets] == ["Create Effective Detailed AI Prompt", "0 - Translate to Arabic",
                                             "0 - Create a perfect prompt"]
    assert d.presets[0]["model"] == "gpt-4o" and d.presets[1]["model"] == "openrouter/free"
    # a prompt with commas, quotes and a "|" keeps all of it; the five trailing fields are dropped
    assert d.presets[2] == {"name": "0 - Create a perfect prompt", "model": "",
                            "prompt": 'Generate, refine  and Optimizer prompt to perfection,"I need a role | a task"'}
    assert [g["name"] for g in d.glossaries] == ["E to A", "A to E"]     # the unnamed one is left out
    assert d.ignored_words == ["PhraseForge", "Riyadh"]
    assert d.excluded_apps == ["keepass.exe", "putty.exe"]
    assert d.allowed_apps == []
    assert d.secrets == ["OpenAI", "OpenRouter", "Microsoft account sign-in"]
    assert d.hotkeys == ["New phrase", "Main menu (tray popup)", "Quick search"]


def test_apply_merges_and_never_imports_keys(store, cfg):
    store.set_setting("ai.presets", json.dumps([{"name": "Mine", "prompt": "keep me"},
                                                {"name": "0 - translate to arabic", "prompt": "old"}]))
    store.set_excluded_apps(["notepad.exe"])
    rep = pe_config.import_config(store, cfg)
    assert (rep.presets_added, rep.presets_updated, rep.glossaries) == (2, 1, 2)
    presets = json.loads(store.setting("ai.presets"))
    assert presets[0] == {"name": "Mine", "prompt": "keep me"}
    assert presets[1]["prompt"] == "Translate from English to Arabic"
    assert presets[1]["model"] == "openrouter/free"
    assert "model" not in presets[3]
    assert store.setting("ai.provider") == "openrouter"
    assert store.setting("translation.provider") == "openrouter"
    assert json.loads(store.setting("translation.glossaries"))["E to A"] == "cat=قطة"
    assert json.loads(store.setting("translation.glossary_langs"))["E to A"] == ["English", "Arabic"]
    assert store.setting("translation.ignored_words").splitlines() == ["PhraseForge", "Riyadh"]
    assert store.setting("autotext.leading_delimiters") == "\x00\n\t\r \"'<{([/\\-_"
    assert store.setting("autotext.delimiters") == "\t\n\r \"'>}]).,?!/\\:;-_ "
    assert store.excluded_apps() == {"notepad.exe", "keepass.exe", "putty.exe"}
    assert store.setting("app.restrict_enabled", "0") == "0"
    # nothing secret reaches the store, and the user is told which keys to enter again
    blob = json.dumps(store.settings(), ensure_ascii=False)
    assert "QgBEO" not in blob and "EnlAEw" not in blob
    assert any("OpenAI, OpenRouter" in n for n in rep.notes)
    assert any("Hotkeys" in n for n in rep.notes)
    # a second import changes nothing
    again = pe_config.import_config(store, cfg)
    assert (again.presets_added, again.presets_updated) == (0, 0)


def test_glossary_languages_feed_translation(store, cfg):
    from phraseforge import ai
    pe_config.import_config(store, cfg)
    s = store.settings()
    assert "cat -> قطة" in ai.translation_system(s, "Arabic", "English")
    assert "cat -> قطة" not in ai.translation_system(s, "English", "Arabic")


def test_parts_can_be_left_out(store, cfg):
    store.set_setting("ai.provider", "openai")
    store.set_setting("autotext.delimiters", " ")
    pe_config.import_config(store, cfg, delimiters=False, engines=False)
    assert store.setting("autotext.delimiters") == " "
    assert store.setting("ai.provider") == "openai"


@pytest.mark.parametrize("text, err", [
    ("<root><a/></root>", "pexconfig"),
    ("<xml><pexconfig>", "could not be read"),
    ('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><xml><pexconfig/></xml>', "entities"),
])
def test_bad_files(tmp_path, text, err):
    p = tmp_path / "config.xml"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match=err):
        pe_config.parse_config(p)


def test_oversized_file_is_refused(tmp_path, monkeypatch):
    p = tmp_path / "config.xml"
    p.write_text("<xml><pexconfig/></xml>", encoding="utf-8")
    monkeypatch.setattr(pe_config, "MAX_CONFIG_BYTES", 5)
    with pytest.raises(ValueError, match="larger than"):
        pe_config.parse_config(p)


def test_preset_parser_edges():
    assert pe_config.parse_preset("") is None
    assert pe_config.parse_preset("|prompt|0|0|0||0") is None
    assert pe_config.parse_preset("name||0|0|0||0") is None
    assert pe_config.lang_name("en") == "English" and pe_config.lang_name("xx") == "xx"


def test_main_window_menu_import(tmp_path, cfg, monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
    QApplication.instance() or QApplication([])
    from phraseforge.ui.main_window import MainWindow
    s = Store(tmp_path / "t.db")
    mw = MainWindow(s)
    seen = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(cfg), "")))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: seen.append(a[2]) or QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: seen.append(a[2])))
    mw.import_phraseexpress_config()
    assert "3 AI preset(s)" in seen[0]
    assert "Added 3 AI preset(s), updated 0." in seen[1] and "API keys are not imported" in seen[1]
    assert any(p["name"] == "0 - Translate to Arabic" for p in json.loads(s.setting("ai.presets")))
    mw.close()
    s.close()
