"""PromptBoost: structured prompts from short ones (ai.boost_prompt, hotkey, buttons, macro)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from phraseforge import ai  # noqa: E402

BOOSTED = "# Todo REST API\n\n- Use Express\n- Validate input for {#input name}"


def test_boost_prompt_wraps_the_original_and_cleans_the_reply():
    seen = []

    def fake(message):
        seen.append(message)
        return "```markdown\n" + BOOSTED + "\n```"
    assert ai.boost_prompt({}, "Create a REST API for {#input name}", complete_fn=fake) == BOOSTED
    m = seen[0]
    assert "<original_prompt>\nCreate a REST API for {#input name}\n</original_prompt>" in m
    assert "professional prompt engineer" in m and "Use Markdown formatting" in m
    with pytest.raises(ai.AIError):
        ai.boost_prompt({}, "  ", complete_fn=fake)
    with pytest.raises(ai.AIError):
        ai.boost_prompt({}, "x", complete_fn=lambda m: "  ")


def test_hotkey_command_and_macro_are_registered():
    from phraseforge.macros import registry
    from phraseforge.triggers.manager import COMMAND_HOTKEY_SETTINGS
    from phraseforge.db import DEFAULT_SETTINGS
    import phraseforge.macros.commands_extra  # noqa: F401
    assert COMMAND_HOTKEY_SETTINGS["promptboost.hotkey"] == "boost_selection"
    assert DEFAULT_SETTINGS["promptboost.hotkey"] == "ctrl+alt+b"
    fn = registry.REGISTRY["promptboost"][1]

    class Host:
        def ai_complete(self, prompt, provider="", model="", system=""):
            assert "<original_prompt>\nCreate a todo API\n</original_prompt>" in prompt
            return BOOSTED

    class RT:
        host = Host()
    assert fn(RT(), ["Create", "a", "todo", "API"], {}) == BOOSTED
    with pytest.raises(registry.MacroError):
        fn(RT(), [], {})


def test_boost_selection_replaces_selected_text(tmp_path):
    from phraseforge.app import PhraseForgeApp
    from phraseforge.db import Store

    class Fake:
        pass
    f = Fake()
    f.store = Store(tmp_path / "b.db")
    notes, typed = [], []
    f.poster = type("P", (), {"posted": type("S", (), {"emit": staticmethod(lambda fn: fn())})()})()
    f.tray = type("T", (), {"notify": lambda _s, t, m: notes.append(m)})()
    f._prepare_target = lambda h: h
    f._exe_of = lambda h: "notepad.exe"
    f._with_triggers_paused = lambda fn: fn()
    f.output = type("O", (), {"execute": lambda _s, acts, app_exe="": typed.extend(a.text for a in acts)})()
    out = PhraseForgeApp._boost_selection(f, 1, get_selection=lambda: "make a todo api",
                                          boost=lambda t: BOOSTED)
    assert out == BOOSTED and typed == [BOOSTED]
    typed.clear()
    assert PhraseForgeApp._boost_selection(f, 1, get_selection=lambda: "") == ""
    assert typed == [] and "Select the prompt text first" in notes[-1]
    assert PhraseForgeApp._boost_selection(f, 1, get_selection=lambda: "x", boost=lambda t: 1 / 0) == ""
    assert typed == [] and "not changed" in notes[-1]          # selection left alone on errors
    f.store.close()


def test_buttons_in_phrase_editor_and_prompt_tower(tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from phraseforge.db import Store
    from phraseforge.models import Phrase
    from phraseforge.ui.content_tab import build_content_tab
    from phraseforge.ui.phrase_editor import PhraseEditor
    from phraseforge.ui.prompt_tower import PromptTowerWindow
    from phraseforge.ui.ribbon import Ribbon
    store = Store(tmp_path / "u.db")
    p = store.add_phrase(Phrase("Ask", "Create a todo API"))
    rb = Ribbon()
    rb.add_tab("phrases", "Phrases")
    ed = PhraseEditor(store)
    tab = build_content_tab(rb, ed)
    ed.load(p.id)
    ctl = tab.controller
    assert ctl.b_boost is not None
    sent = []
    assert ctl.enhance_prompt(complete_fn=lambda m: (sent.append(m), BOOSTED)[1], quiet=True, mode="boost")
    assert "<original_prompt>\nCreate a todo API\n</original_prompt>" in sent[0]
    assert ed.content_edit.content() == BOOSTED
    w = PromptTowerWindow(store)
    w.quiet = True
    w.prefix.setPlainText("fix the login bug")
    assert w.boost_prefix(complete_fn=lambda m: "## Task\n- Fix the login bug")
    assert w.prefix.toPlainText() == "## Task\n- Fix the login bug"
    w.prefix.undo()
    assert w.prefix.toPlainText() == "fix the login bug"
    w.close()
    store.close()
