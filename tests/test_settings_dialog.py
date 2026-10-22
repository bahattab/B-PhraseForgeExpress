import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QLineEdit, QPlainTextEdit, QSpinBox

from phraseforge.db import Store
from phraseforge.ui.settings_schema import (
    SCHEMA, decode_delimiters, encode_delimiters, ensure_defaults, glossaries, presets,
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def _dialog(store, **kw):
    from phraseforge.ui.settings_dialog import SettingsDialog
    return SettingsDialog(store, **kw)


def _changed_value(w):
    """Set a widget to a value different from its current one; return nothing."""
    from phraseforge.ui.settings_dialog import DataCombo, DelaySlider, Hotkey, KeyCombo, RadioGroup
    if isinstance(w, QCheckBox):
        w.setChecked(not w.isChecked())
    elif isinstance(w, QSpinBox):
        w.setValue(w.value() + 1 if w.value() < w.maximum() else w.value() - 1)
    elif isinstance(w, DataCombo):
        w.setCurrentIndex((w.currentIndex() + 1) % w.count())
    elif isinstance(w, QPlainTextEdit):
        w.setPlainText("line one\nline two")
    elif isinstance(w, QLineEdit):
        w.setText("changed-value")
    elif isinstance(w, RadioGroup):
        vals = list(w.buttons)
        w.set_value(vals[(vals.index(w.value()) + 1) % len(vals)])
    elif isinstance(w, DelaySlider):
        w.set_value("300" if w.value() != "300" else "400")
    elif isinstance(w, KeyCombo):
        w.set_value("f5" if w.value() != "f5" else "f6")
    elif isinstance(w, Hotkey):
        w.set_value("ctrl+alt+k" if w.value() != "ctrl+alt+k" else "shift+f9")
    else:
        raise AssertionError(f"no test value for {type(w).__name__}")


def test_tree_has_all_pages_and_each_constructs(app, store):
    from phraseforge.ui.settings_dialog import PAGES, pages
    d = _dialog(store)
    assert d.windowTitle() == "PhraseForge Settings"
    assert pages()[:3] == ["features", "hotkeys", "display"]
    for key in pages():
        d.show_page(key)
        assert d.current_page() == key
        assert d.stack.currentWidget() is not None
    # tree structure: children under their parents
    texts = [d.tree.topLevelItem(i).text(0) for i in range(d.tree.topLevelItemCount())]
    assert texts == [t for k, t, p in PAGES if p is None]
    assert d.tree.topLevelItem(texts.index("AI text processing")).childCount() == 2
    d2 = _dialog(store, page="expert_delays")
    assert d2.current_page() == "expert_delays"


def test_every_bound_control_round_trips(app, store):
    d = _dialog(store)
    widgets = [(k, g, w) for k, g, _p, w in d._bindings if w is not None]
    assert len(widgets) > 80
    for _k, _g, w in widgets:
        _changed_value(w)
    expected = {k: g() for k, g, _w in widgets}
    d.save()
    for k, v in expected.items():
        assert store.setting(k) == v, k
        if k in SCHEMA and k not in ("ocr.cli_path",):
            assert v != SCHEMA[k] or k in ("backup.directory",), f"{k} did not change"
    # a fresh dialog shows the saved values
    d2 = _dialog(store)
    got = d2.values()
    for k, v in expected.items():
        assert got[k] == v, k


def test_custom_bindings_round_trip(app, store):
    d = _dialog(store)
    d.delimiters.setText("#9#10 .,")
    d.leading.setText("#0#13 (")
    d.presets_list.clear()
    d.presets_list.addItem(d._preset_item("Shorten", "Make it short"))
    d._add_glossary("German")
    d.gloss_text.setPlainText("Haus=house")
    d._clip_max = "55"
    d._sound_files["phrase_insertion"] = r"C:\x.wav"
    d._set_font("Segoe UI,12")
    d._appearance["description"] = "#ff0000"
    d.save()
    assert store.setting("autotext.delimiters") == "\t\n .,"
    assert store.setting("autotext.leading_delimiters") == "\x00\r ("
    assert presets(store) == [{"name": "Shorten", "prompt": "Make it short"}]
    assert glossaries(store) == {"German": "Haus=house"}
    assert store.setting("clipboard_history.max") == "55"
    assert store.setting("sound.phrase_insertion.file") == r"C:\x.wav"
    assert store.setting("format.font") == "Segoe UI,12"
    assert json.loads(store.setting("menu.appearance"))["description"] == "#ff0000"


def test_ai_keys_follow_provider(app, store):
    d = _dialog(store)
    d.ai_provider.set_value("openai")
    d.ai_key.setText("sk-open")
    d.ai_provider.set_value("anthropic")
    assert d.ai_key.text() == ""
    d.ai_key.setText("sk-ant")
    d.ai_provider.set_value("ollama")
    assert d.ai_key_label.text() == "Ollama server URL:"
    d.ai_key.setText("http://box:11434")
    d.ai_provider.set_value("openai")
    assert d.ai_key.text() == "sk-open"
    d.save()
    assert store.setting("ai.openai_key") == "sk-open"
    assert store.setting("ai.anthropic_key") == "sk-ant"
    assert store.setting("ai.ollama_url") == "http://box:11434"
    assert store.setting("ai.provider") == "openai"


def test_reset_defaults_and_ensure_defaults(app, store):
    d = _dialog(store)
    for _k, _g, _p, w in d._bindings:
        if w is not None:
            _changed_value(w)
    d.save()
    d.reset_defaults()
    d.save()
    for k, _g, _p, _w in d._bindings:
        if k in SCHEMA:
            assert store.setting(k) == SCHEMA[k], k
    fresh = Store(":memory:")
    added = ensure_defaults(fresh)
    assert added > 50
    assert all(k in fresh.settings() for k in SCHEMA)
    assert ensure_defaults(fresh) == 0


def test_excluded_programs_and_export_import(app, store, tmp_path):
    d = _dialog(store)
    d.excluded.setPlainText("KeePass.exe\nbank.exe\n")
    d.theme.set_value("dark")
    d.save()
    assert store.excluded_apps() == {"keepass.exe", "bank.exe"}
    path = tmp_path / "s.json"
    d.export_to(str(path))
    other = Store(":memory:")
    d2 = _dialog(other)
    d2.import_from(str(path))
    assert other.setting("ui.theme") == "dark"
    assert other.excluded_apps() == {"keepass.exe", "bank.exe"}
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        d2.import_from(str(bad))


def test_old_call_style_and_hotkey_order(app, store):
    from PySide6.QtWidgets import QWidget
    parent = QWidget()
    d = _dialog(store, page=None)
    from phraseforge.ui.settings_dialog import SettingsDialog
    d2 = SettingsDialog(store, parent)          # main window passes the parent positionally
    assert d2.parent() is parent and d2.current_page() == "features"
    d.popup_hotkey.setText("shift+ctrl+p")
    assert d.popup_hotkey.text() == "ctrl+shift+p"


def test_app_method_table(app, store):
    d = _dialog(store)
    d.app_methods.load_json('{"winword.exe": "type"}')
    d.app_methods.add_row("Notepad.EXE", "paste")
    d.save()
    assert json.loads(store.setting("output.app_methods")) == {"winword.exe": "type", "notepad.exe": "paste"}
    d2 = _dialog(store)
    assert d2.app_methods.table.rowCount() == 2


def test_legacy_keys_migrate_once(app):
    from phraseforge.ui.settings_schema import migrate_legacy
    s = Store(":memory:")
    s.set_setting("popup.width", "420")
    s.set_setting("popup.sort", "usage")
    s.set_setting("popup.search_content", "1")
    s.set_setting("features.clipboard_cache", "0")     # old Features checkbox was off
    s.set_setting("stats.enabled", "0")
    ensure_defaults(s)
    assert s.setting("menu.width") == "420"
    assert s.setting("menu.sort_by") == "usage" and s.setting("menu.sort_order") == "desc"
    assert s.setting("quicksearch.descriptions") == "0"
    assert s.setting("clipboard_history.enabled") == "0"
    assert s.setting("features.clipboard_cache") == "1"   # neutralized for old readers
    assert s.setting("features.usage_statistics") == "0"
    s.set_setting("clipboard_history.enabled", "1")      # user turns it back on later
    assert migrate_legacy(s) == 0 and s.setting("clipboard_history.enabled") == "1"


def test_no_dead_options_in_dialog(app, store):
    """Options PhraseForge has no use for are gone from the dialog and the schema."""
    gone = ("updates.channel", "updates.beta", "updates.auto", "cache.mode", "features.suggest_gender",
            "display.highlight_unedited_languages", "menu.show_language_buttons", "menu.language_hotkey",
            "features.clipboard_cache")
    d = _dialog(store)
    bound = {k for k, _g, _p, _w in d._bindings}
    for k in gone:
        assert k not in SCHEMA and k not in bound, k
    assert "autotext.pause_ms" in bound and SCHEMA["autotext.pause_ms"] == "700"
    assert "clipboard_history.enabled" in bound       # the Features > Clipboard Cache checkbox


def unused_schema_keys() -> list[str]:
    """SCHEMA keys that no runtime module reads (settings dialog/schema don't count)."""
    import re
    from pathlib import Path
    from phraseforge.ui.settings_schema import UI_ONLY_KEYS
    root = Path(__file__).resolve().parent.parent / "phraseforge"
    skip = {"settings_dialog.py", "settings_schema.py"}
    src = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                    for p in root.rglob("*.py") if p.name not in skip)
    out = []
    for k in sorted(SCHEMA):
        if k in UI_ONLY_KEYS or f'"{k}"' in src or f"'{k}'" in src:
            continue
        # keys built at runtime, e.g. f"sound.{event}.enabled" or f"ai.{provider}_key"
        prefix = k.split(".")[0] + "."
        if re.search(r'f["\']' + re.escape(prefix) + r"\{", src):
            continue
        out.append(k)
    return out


def test_every_schema_key_has_a_runtime_reader():
    unused = unused_schema_keys()
    assert not unused, ("Settings that nothing reads (wire them up, remove them, or list them in "
                        f"settings_schema.UI_ONLY_KEYS): {unused}")


def test_delimiter_codec():
    for s in ["\t\n .,;:!?)]}'\"", "\x00\n\t\r \"'<{([/\\-_", "#1 a#b", "\t5"]:
        assert decode_delimiters(encode_delimiters(s)) == s
    assert encode_delimiters("\t\n") == "#9#10"
