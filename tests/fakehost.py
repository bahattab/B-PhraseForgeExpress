"""Scripted HostServices for tests.

Queue answers per method:  host.answers["ask_input"].append("Bob")
A queued `Cancelled` (the class or an instance) makes that call raise Cancelled.
Every call is recorded in host.calls as (method, args).
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from phraseforge.host import Cancelled, FormField


class FakeHost:
    def __init__(self, settings: dict[str, str] | None = None):
        self.answers: dict[str, deque] = defaultdict(deque)
        self.calls: list[tuple[str, tuple]] = []
        self.vars: dict[tuple[str, str], str] = {}
        self.clipboard = ""
        self.history: list[str] = []
        self.phrases: dict[str, tuple[str, str]] = {}
        self.http: dict[str, str] = {}
        self.settings: dict[str, str] = dict(settings or {})
        self.focused = ("notepad.exe", "Untitled - Notepad")
        self.ai_reply = lambda prompt, provider, model, system: f"AI:{prompt}"
        self.ocr_text = "ocr text"
        self.windows_ok = True

    # helpers
    def queue(self, method: str, *values) -> "FakeHost":
        self.answers[method].extend(values)
        return self

    def _next(self, method: str, default: Any, *args):
        self.calls.append((method, args))
        q = self.answers[method]
        if q:
            v = q.popleft()
            if v is Cancelled or isinstance(v, Cancelled):
                raise Cancelled(method)
            return v
        return default

    def called(self, method: str) -> list[tuple]:
        return [a for m, a in self.calls if m == method]

    # user interaction
    def ask_input(self, prompt: str, default: str = "", multiline: bool = False) -> str:
        return self._next("ask_input", default, prompt, default, multiline)

    def show_form(self, title: str, fields: list[FormField]) -> dict[str, Any]:
        defaults = {f.name: f.default for f in fields}
        v = self._next("show_form", None, title, fields)
        return {**defaults, **(v or {})}

    def choose(self, prompt: str, options: list[str], multi: bool = False) -> list[str]:
        return self._next("choose", options[:1], prompt, options, multi)

    def pick_date(self, prompt: str, default_iso: str) -> str:
        return self._next("pick_date", default_iso, prompt, default_iso)

    def message(self, text: str, title: str = "") -> None:
        self.calls.append(("message", (text, title)))

    def select_screen_region(self):
        return self._next("select_screen_region", (0, 0, 10, 10))

    # clipboard
    def get_clipboard(self) -> str:
        return self.clipboard

    def set_clipboard(self, text: str) -> None:
        self.clipboard = text
        self.history.insert(0, text)

    def clipboard_history(self, index: int) -> str:
        return self.history[index] if 0 <= index < len(self.history) else ""

    # phrases + vars
    def phrase_content(self, description_or_id: str):
        return self.phrases.get(description_or_id.lower())

    def get_var(self, name: str, scope: str = "global") -> str:
        return self.vars.get((scope, name), "")

    def set_var(self, name: str, value: str, scope: str = "global") -> None:
        self.vars[(scope, name)] = value

    # OS
    def run_program(self, cmd: str, args: str = "", wait: bool = False, workdir: str = "") -> int:
        return self._next("run_program", 0, cmd, args, wait, workdir)

    def open_target(self, target: str) -> None:
        self.calls.append(("open_target", (target,)))

    def wait_for_window(self, title_substring: str, timeout_s: float) -> bool:
        self.calls.append(("wait_for_window", (title_substring, timeout_s)))
        return self.windows_ok

    def focused_app(self):
        return self.focused

    # integrations
    def http_request(self, method, url, headers=None, body=None, timeout_s=30) -> str:
        self.calls.append(("http_request", (method, url, headers, body)))
        return self.http.get(url, "")

    def ai_complete(self, prompt: str, provider: str = "", model: str = "", system: str = "") -> str:
        self.calls.append(("ai_complete", (prompt, provider, model, system)))
        return self.ai_reply(prompt, provider, model, system)

    def ocr_region(self, language: str = "English", keep_line_breaks: bool = True) -> str:
        self.calls.append(("ocr_region", (language, keep_line_breaks)))
        return self.ocr_text

    def ocr_image(self, path: str, language: str = "English") -> str:
        self.calls.append(("ocr_image", (path, language)))
        return self.ocr_text

    def setting(self, key: str, default: str = "") -> str:
        return self.settings.get(key, default)
