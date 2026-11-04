"""Administrator lockdown (PRD FR-APP-04, T-APP-04): the policy file, forced and locked
settings, editing disabled in the store and the UI, disabled macros, fail-closed parsing."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from phraseforge import policy
from phraseforge.db import Store
from phraseforge.models import Folder, Phrase

FULL = '''
settings_locked = true
editing_disabled = true
stats_enabled = false
macros_disabled = ["run", "#HTTP"]
locked_settings = ["sync.*", "ai.provider"]
message = "Call IT on 1234."

[settings]
"learning.enabled" = "0"
"app.check_updates" = false
"ui.theme" = "dark"
'''


@pytest.fixture(autouse=True)
def no_policy():
    policy.set_current(policy.NO_POLICY)
    yield
    policy.set_current(None)


@pytest.fixture
def store():
    s = Store(":memory:")
    yield s
    s.close()


def use(text):
    policy.set_current(policy.parse(text, "test.toml"))
    return policy.current()


# ---------------------------------------------------------------- the file
def test_parse_reads_every_key():
    p = policy.parse(FULL, "x")
    assert p.active and p.settings_locked and p.editing_disabled and not p.stats_enabled
    assert p.macros_disabled == {"run", "http"}
    assert p.forced == {"learning.enabled": "0", "app.check_updates": "0", "ui.theme": "dark"}
    assert p.setting_locked("sync.provider") and p.setting_locked("ai.provider") and p.setting_locked("ui.theme")
    assert p.setting_locked("features.usage_statistics") and not p.setting_locked("ai.model")
    assert p.notice("Settings") == "Settings is locked by your administrator. Call IT on 1234."


def test_no_file_means_no_policy(tmp_path):
    assert policy.load(tmp_path / "missing.toml") is policy.NO_POLICY
    assert not policy.NO_POLICY.active and not policy.NO_POLICY.setting_locked("ui.theme")


def test_a_broken_file_locks_settings_and_editing(tmp_path):
    for bad in ("settings_locked = maybe", 'editing_disabled = "yes"', "macros_disabled = 3",
                "[settings]\nx = 1\n[settings]\n"):
        f = tmp_path / "policy.toml"
        f.write_text(bad, encoding="utf-8")
        p = policy.load(f)
        assert p.settings_locked and p.editing_disabled and p.error, bad


def test_load_reads_utf8_with_bom_and_unknown_keys_are_ignored(tmp_path):
    f = tmp_path / "policy.toml"
    f.write_bytes('\ufeffediting_disabled = true\nmessage = "اتصل بالدعم"\nfuture_key = 1\n'.encode("utf-8"))
    p = policy.load(f)
    assert p.editing_disabled and not p.settings_locked and p.message == "اتصل بالدعم" and not p.error


def test_policy_path_is_fixed(monkeypatch):
    monkeypatch.setattr(policy.sys, "platform", "win32")
    monkeypatch.setenv("ProgramData", r"D:\PD")
    assert str(policy.policy_path()).replace("/", "\\").endswith(r"PD\PhraseForge\policy.toml")
    monkeypatch.setattr(policy.sys, "platform", "linux")
    assert str(policy.policy_path()) == "/etc/phraseforge/policy.toml"


# ---------------------------------------------------------------- settings
def test_forced_and_locked_settings_in_the_store(store):
    store.set_setting("ui.theme", "light")
    store.set_setting("sync.provider", "folder")
    use(FULL)
    assert store.setting("ui.theme") == "dark" and store.setting("app.check_updates", "1") == "0"
    assert store.setting("features.usage_statistics", "1") == "0"          # stats_enabled = false
    store.set_setting("ui.theme", "light")                                   # refused, no error
    store.set_setting("sync.provider", "gdrive")
    store.set_setting("ui.window_geometry", "abc")                           # not locked: saved
    assert store.settings()["ui.theme"] == "dark" and store.setting("sync.provider") == "folder"
    assert store.setting("ui.window_geometry") == "abc"
    policy.set_current(policy.NO_POLICY)
    assert store.setting("ui.theme") == "light"                              # the user's value was kept


# ---------------------------------------------------------------- editing
def test_editing_disabled_refuses_every_phrase_and_folder_change(store, tmp_path):
    f = store.add_folder(Folder("F"))
    p = store.add_phrase(Phrase("A", "a", folder_id=f.id))
    backup = tmp_path / "b.db"
    store.backup_to(backup)
    use("editing_disabled = true")
    for call in (lambda: store.add_phrase(Phrase("B", "b")), lambda: store.update_phrase(p),
                 lambda: store.delete_phrase(p.id), lambda: store.add_folder(Folder("G")),
                 lambda: store.update_folder(f), lambda: store.delete_folder(f.id),
                 lambda: store.set_phrase_version(p.id, "ar", "أ"), lambda: store.set_folder_triggers(f.id, []),
                 lambda: store.restore_from(backup), lambda: store.restore_from(backup, untrusted="imported")):
        with pytest.raises(policy.PolicyError, match="administrator"):
            call()
    assert [x.description for x in store.phrases()] == ["A"]
    store.record_use(p.id, app="x.exe", chars=1)                             # using phrases still works
    store.bump_suggestion("typed text here")
    store.restore_from(backup, untrusted="synced")                           # a sync pull is allowed
    with store.policy_bypass():
        store.add_phrase(Phrase("From admin", "x"))
    assert {x.description for x in store.phrases()} == {"A", "From admin"}


def test_disabled_macros_output_a_notice():
    from phraseforge.macros import MacroEngine
    from tests.fakehost import FakeHost
    use('macros_disabled = ["upper", "http"]')
    e = MacroEngine(FakeHost())
    assert e.expand_to_text("{#upper a} {#lower B}") == "[upper: disabled by your administrator] b"


# ---------------------------------------------------------------- UI
@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_main_window_is_read_only_and_settings_stay_closed(app, store, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from phraseforge.ui.main_window import MainWindow
    p = store.add_phrase(Phrase("A", "a"))
    use(FULL)
    shown = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: shown.append(a[2])))
    w = MainWindow(store)
    assert "administrator" in w.policy_label.text()
    w.select_phrase(p.id)
    w._update_actions()
    assert not w.btn_new_phrase.isEnabled() and not w.btn_import.isEnabled() and not w.btn_dup.isEnabled()
    assert not w.editor.isEnabled()
    assert w.save_current()
    w.show_settings()
    assert shown == ["Settings is locked by your administrator. Call IT on 1234."]


def test_main_window_without_policy_is_unchanged(app, store):
    from phraseforge.ui.main_window import MainWindow
    w = MainWindow(store)
    assert not hasattr(w, "policy_label") and w.btn_new_phrase.isEnabled()


def test_settings_dialog_disables_locked_settings(app, store):
    from phraseforge.ui.settings_dialog import SettingsDialog
    use('locked_settings = ["learning.*"]\n[settings]\n"spell.enabled" = "0"\n')
    d = SettingsDialog(store)
    widgets = {k: w for k, _g, _p, w in d._bindings if w is not None}
    assert not widgets["learning.enabled"].isEnabled() and not widgets["spell.enabled"].isEnabled()
    assert widgets["spell.enabled"].isChecked() is False and "administrator" in widgets["spell.enabled"].toolTip()
    assert widgets["autocomplete.suggest_words"].isEnabled()
    d.reset_defaults()
    assert not widgets["learning.enabled"].isEnabled()
    d.save()
    assert store.setting("spell.enabled") == "0"


def test_excepthook_shows_policy_errors_as_a_notice(app, monkeypatch):
    import sys
    from PySide6.QtWidgets import QMessageBox
    from phraseforge.ui import policy_ui
    use('editing_disabled = true\nmessage = "Ask IT."')
    shown, passed = [], []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: shown.append(a[2])))
    monkeypatch.setattr(sys, "excepthook", lambda *a: passed.append(a[0]))
    policy_ui.install_excepthook()
    sys.excepthook(policy.PolicyError, policy.PolicyError("x"), None)
    sys.excepthook(ValueError, ValueError("y"), None)
    assert shown == ["Editing phrases is locked by your administrator. Ask IT."] and passed == [ValueError]
