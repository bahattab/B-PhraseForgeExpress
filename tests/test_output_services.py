"""Output path and service settings: output targets, delays, text insertion,
sounds, backups, proxy, AI/translation, mail, OCR, diagnostics, command dispatch."""
import json
import logging
import os
import queue
import types

import pytest

from phraseforge import ai, net, output_target, sounds
from phraseforge.db import Store
from phraseforge.host import CursorAction, HtmlAction, KeyAction, TextAction
from phraseforge.models import Folder, OutputMode, Phrase
from phraseforge.platform.output import OutputExecutor, apply_format, html_for_output


# ------------------------------------------------------------------ output executor
class FakeSI:
    def __init__(self, calls): self.calls = calls
    def release_modifiers(self): self.calls.append(("release",))
    def backspace(self, n): self.calls.append(("bs", n))
    def type_text(self, t, **kw): self.calls.append(("type", t, kw))
    def send_keys(self, k, repeat=1, **kw): self.calls.append(("keys", k, repeat, kw))
    def press_left(self, n): self.calls.append(("left", n))
    def mouse_move(self, x, y): pass
    def mouse_click(self, *a, **k): pass


class FakeCB:
    def __init__(self, calls): self.calls = calls
    def save_all(self): self.calls.append(("save",)); return ["snap"]
    def restore(self, s): self.calls.append(("restore", s))
    def set_text(self, t): self.calls.append(("clip", t))
    def set_html(self, h, p, formats="html"): self.calls.append(("html", h, p))
    def set_image(self, p): self.calls.append(("image", p))


def executor(settings):
    calls = []
    ex = OutputExecutor(lambda k, d="": settings.get(k, d))
    ex.sendinput, ex.clipboard = FakeSI(calls), FakeCB(calls)
    return ex, calls


def kinds(calls):
    return [c[0] for c in calls]


def test_paste_long_off_types_everything():
    ex, calls = executor({"output.paste_threshold": "3", "output.paste_long": "0", "delay.clipboard_restore": "50"})
    ex.execute([TextAction("long text here")])
    assert ("type", "long text here", {}) in calls and "clip" not in kinds(calls)


def test_paste_long_on_pastes_over_threshold():
    ex, calls = executor({"output.paste_threshold": "3", "delay.clipboard_restore": "50", "delay.paste": "20"})
    ex.execute([TextAction("long text here")])
    assert ("clip", "long text here") in calls and ("restore", ["snap"]) in calls


def test_per_app_method_overrides_auto():
    ex, calls = executor({"output.app_methods": json.dumps({"notepad.exe": "paste"}),
                          "delay.clipboard_restore": "50"})
    ex.execute([TextAction("hi")], app_exe="NOTEPAD.EXE")
    assert ("clip", "hi") in calls
    ex2, calls2 = executor({"output.per_app_method": "0", "output.app_methods": json.dumps({"notepad.exe": "paste"})})
    ex2.execute([TextAction("hi")], app_exe="notepad.exe")
    assert ("type", "hi", {}) in calls2


def test_per_app_does_not_override_explicit_mode():
    ex, calls = executor({"output.app_methods": json.dumps({"x.exe": "paste"})})
    ex.execute([TextAction("hi")], mode=OutputMode.TYPE, app_exe="x.exe")
    assert ("type", "hi", {}) in calls


def test_key_method_and_delays_reach_sendinput():
    ex, calls = executor({"output.key_method": "scancode", "delay.keypress": "35"})
    ex.execute([TextAction("ab"), KeyAction("tab", 2)])
    assert ("type", "ab", {"method": "scancode", "char_delay_ms": 0}) in calls
    assert ("keys", "tab", 2, {"delay_ms": 35}) in calls


def test_pastemethod_key_delay_from_macro():
    ex, calls = executor({})
    ex.execute([TextAction("ab")], key_delay_ms=40)
    assert ("type", "ab", {"method": "vk_packet", "char_delay_ms": 40}) in calls


def test_output_format_conversions():
    acts = [TextAction("a<b"), HtmlAction("<style>p{}</style><b>x</b>", "x")]
    plain = apply_format(acts, "plain")
    assert [type(a) for a in plain] == [TextAction, TextAction] and plain[1].text == "x"
    rich = apply_format(acts, "rich")
    assert isinstance(rich[0], HtmlAction) and rich[0].html == "a&lt;b"
    src = apply_format(acts, "html", "inline")
    assert src[1].text == "<b>x</b>"
    assert html_for_output("<style>q</style><i>y</i>", "css") == "<style>q</style><i>y</i>"


# ------------------------------------------------------------------ sounds
def test_sounds(monkeypatch, tmp_path):
    played = []
    monkeypatch.setattr(sounds, "player", lambda path, alias: played.append((path, alias)))
    s = {"sound.phrase_insertion.enabled": "0"}
    assert not sounds.play(lambda k, d="": s.get(k, d), "phrase_insertion")
    s["sound.phrase_insertion.enabled"] = "1"
    s["sound.phrase_insertion.file"] = str(tmp_path / "missing.wav")
    assert sounds.play(lambda k, d="": s.get(k, d), "phrase_insertion")
    assert played[-1] == ("", "SystemAsterisk")          # missing file -> system sound
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"RIFF")
    s["sound.phrase_insertion.file"] = str(wav)
    sounds.play(lambda k, d="": s.get(k, d), "phrase_insertion")
    assert played[-1] == (str(wav), "SystemAsterisk")
    assert not sounds.play(lambda k, d="": "1", "nope")


# ------------------------------------------------------------------ proxy / AI / translation / mail
def test_proxy_url_and_env(monkeypatch):
    assert net.proxy_url({}) is None
    url = net.proxy_url({"net.proxy_server": "proxy.lan", "net.proxy_port": "8080",
                         "net.proxy_user": "me", "net.proxy_password": "p@ss"})
    assert url == "http://me:p%40ss@proxy.lan:8080"
    for v in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(v, raising=False)
    net.configure({"net.proxy_server": "https://p.example:3128"})
    assert os.environ["HTTPS_PROXY"] == "https://p.example:3128" and net.client_kwargs() == {"proxy": "https://p.example:3128"}
    net.configure({})
    assert "HTTPS_PROXY" not in os.environ and net.client_kwargs() == {}


def test_ai_instructions_presets_and_translation(monkeypatch):
    sent = []
    monkeypatch.setattr(ai, "_post", lambda url, h, payload, t: sent.append(payload) or
                        {"choices": [{"message": {"content": "ok"}}]})
    st = {"ai.openai_key": "k", "ai.instructions.about": "I am a lawyer.", "ai.instructions.respond": "Be brief."}
    assert ai.complete(st, "hi", system="Role") == "ok"
    sys_msg = sent[-1]["messages"][0]["content"]
    assert sys_msg.startswith("Role") and "lawyer" in sys_msg and "Be brief." in sys_msg
    ai.complete(st, "hi", system="T", raw_system=True)
    assert sent[-1]["messages"][0]["content"] == "T"
    presets = {"ai.presets": json.dumps([{"name": "Summarize", "prompt": "Summarize this."}])}
    assert ai.preset_prompt(presets, "summarize") == "Summarize this."
    with pytest.raises(ai.AIError):
        ai.preset_prompt(presets, "nope")
    tr = ai.translation_system({"translation.ignored_words": "PhraseForge\nACME",
                                "translation.glossaries": json.dumps({"Legal": "contract=عقد"})}, "Arabic")
    assert "Arabic" in tr and "PhraseForge, ACME" in tr and "contract -> عقد" in tr


def test_ai_and_translate_macros(tmp_path):
    from phraseforge.macros import MacroEngine
    from tests.fakehost import FakeHost
    host = FakeHost({"ai.presets": json.dumps([{"name": "Polite", "prompt": "Make polite:"}]),
                     "translation.provider": "anthropic", "translation.ignored_words": "Bob"})
    eng = MacroEngine(host)
    eng.expand('{#ai "give it" -preset Polite}', None)
    assert host.called("ai_complete")[-1][0] == "Make polite:\n\ngive it"
    eng.expand("{#translate Hi Bob -to Arabic}", None)
    prompt, provider, model, system = host.called("ai_complete")[-1]
    assert provider == "anthropic" and "Bob" in system and system.startswith("You are a translator.")


def test_mail_url_methods():
    from phraseforge.macros.commands import mail_url
    assert mail_url("a@b.com", {"subject": "Hi there", "body": "é"}) == "mailto:a@b.com?subject=Hi%20there&body=%C3%A9"
    g = mail_url("a@b.com", {"subject": "S"}, "gmail")
    assert g.startswith("https://mail.google.com/mail/?") and "to=a%40b.com" in g and "su=S" in g


def test_ocr_keep_line_breaks_setting():
    from phraseforge.macros import MacroEngine
    from tests.fakehost import FakeHost
    host = FakeHost({"ocr.keep_line_breaks": "0"})
    eng = MacroEngine(host)
    eng.expand("{#ocr -lang English}", None)
    assert host.called("ocr_region")[-1] == ("English", False)
    eng.expand("{#ocr -lang English -linebreaks}", None)
    assert host.called("ocr_region")[-1] == ("English", True)


# ------------------------------------------------------------------ output target
def test_output_target_resolution(tmp_path):
    s = Store(tmp_path / "s.db")
    f = s.add_folder(Folder("Mail"))
    sub = s.add_folder(Folder("Sub", parent_id=f.id))
    p = s.add_phrase(Phrase("P", "x", folder_id=sub.id))
    q = s.add_phrase(Phrase("Q", "x"))
    assert output_target.resolve(s, p) == ("current", {})
    f.output_target = "clipboard"                                   # folder "for all phrases" setting
    s.update_folder(f)
    assert output_target.resolve(s, s.get_phrase(p.id))[0] == "clipboard"   # inherited from folder chain
    output_target.remember_program(s, p.id, r"C:\Windows\notepad.exe")
    t, opts = output_target.resolve(s, s.get_phrase(p.id))
    assert t == "program" and opts["output_program"].endswith("notepad.exe")
    assert output_target.resolve(s, q) == ("current", {})


def test_output_target_legacy_extras_still_honoured(tmp_path):
    s = Store(tmp_path / "s.db")
    f = s.add_folder(Folder("Mail"))
    p = s.add_phrase(Phrase("P", "x", folder_id=f.id))
    s.set_setting("ui.trigger_extras", json.dumps({f"f:{f.id}": {"output_target": "email"}}))
    assert output_target.resolve(s, p)[0] == "email"


def test_output_target_text_helpers(tmp_path):
    acts = [TextAction("a\r\n"), CursorAction(), HtmlAction("<b>b</b>", "b"), KeyAction("tab")]
    assert output_target.plain_text(acts) == "a\nb"
    assert "<b>b</b>" in output_target.html_of(acts)
    assert output_target.html_of([TextAction("x")]) is None
    p = output_target.write_text_file(tmp_path / "out", "line1\nline2")
    assert p.suffix == ".txt" and p.read_text(encoding="utf-8-sig").splitlines() == ["line1", "line2"]
    assert output_target.safe_filename('a:b/c?') == "a_b_c_"


# ------------------------------------------------------------------ local backups
def test_auto_backup_and_prune(tmp_path):
    from phraseforge import io_formats
    s = Store(tmp_path / "s.db")
    d = tmp_path / "bk"
    s.set_setting("backup.directory", str(d))
    s.set_setting("backup.keep_count", "2")
    assert io_formats.auto_backup(s) is not None
    assert io_formats.auto_backup(s) is None                   # not due yet (daily)
    for _ in range(3):
        io_formats.auto_backup(s, force=True)
    assert len(io_formats.list_backups(d)) == 2
    s.set_setting("backup.keep_enabled", "0")
    assert io_formats.auto_backup(s, force=True) is None


# ------------------------------------------------------------------ clipboard cache switch
def test_clipboard_cache_feature_switch(monkeypatch):
    from phraseforge.clipboard_history import ClipboardHistory
    monkeypatch.setattr(sounds, "player", lambda *a: None)
    s = Store(":memory:")
    ch = ClipboardHistory(s, watcher_factory=lambda cb: None, foreground_app=lambda: ("x.exe", ""))
    ch.on_clipboard_text("one")
    s.set_setting("features.clipboard_cache", "0")
    ch.on_clipboard_text("two")
    assert [e.text for e in s.clipboard_entries()] == ["one"]


# ------------------------------------------------------------------ app helpers
def test_uppercase_rule():
    from phraseforge.app import uppercase_wanted
    assert uppercase_wanted("BR#", True, 2)
    assert not uppercase_wanted("Br#", True, 2)
    assert not uppercase_wanted("BR#", False, 2)
    assert not uppercase_wanted("B", True, 2)


def test_diagnostic_logging(tmp_path, monkeypatch):
    monkeypatch.setenv("PHRASEFORGE_HOME", str(tmp_path))
    from phraseforge.app import configure_logging
    s = Store(":memory:")
    root = logging.getLogger()
    level = root.level
    try:
        s.set_setting("app.diagnostic_mode", "1")
        configure_logging(s)
        assert root.level == logging.DEBUG and any(getattr(h, "_pf_diag", False) for h in root.handlers)
        s.set_setting("app.diagnostic_mode", "0")
        configure_logging(s)
        assert not any(getattr(h, "_pf_diag", False) for h in root.handlers)
    finally:
        root.setLevel(level)


def test_command_dispatch():
    from phraseforge.app import PhraseForgeApp
    posted, played = [], []
    fake = types.SimpleNamespace(
        poster=types.SimpleNamespace(posted=types.SimpleNamespace(emit=posted.append)),
        _jobs=queue.Queue(), store=Store(":memory:"))
    for name in ("_build_commands", "register_command", "on_command", "_confirm_cmd", "_folder_popup_cmd"):
        setattr(fake, name, types.MethodType(getattr(PhraseForgeApp, name), fake))
    fake._play = played.append
    fake._confirm = lambda pid, erase, hwnd: posted.append(("confirm", pid, erase))
    fake._build_commands()
    fake.on_command("ocr")
    assert fake._jobs.get_nowait()[0] == "ocr"
    fake.on_command("confirm:5:3")
    posted.pop()()                                   # run the posted lambda
    assert posted[-1] == ("confirm", 5, 3)
    shown = []
    fake._show_popup = lambda hwnd, folder=None, search=False: shown.append(folder)
    fake.on_command("choose:7,9:3")                  # several phrases share one autotext
    assert fake._jobs.get_nowait() == ("replace", "3:", 0)
    posted.pop()()
    assert shown == ["choice:7,9"]
    fake.on_command("sound:popup_display")
    assert played == ["popup_display"]
    seen = []
    fake.register_command("smartcomplete", lambda arg, hwnd: seen.append(arg))
    fake.on_command("smartcomplete:12:4")
    assert seen == ["12:4"]
    fake.on_command("no_such_command")                # logged, no exception
