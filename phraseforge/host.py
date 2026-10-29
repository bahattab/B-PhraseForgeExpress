"""Contracts between modules.

The macro engine produces Actions and asks HostServices for anything that needs
the user, the OS, or the network. The UI and platform layers implement
HostServices; tests use FakeHost.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


# ---------------------------------------------------------------- actions
@dataclass
class TextAction:
    text: str


@dataclass
class HtmlAction:
    """Rich text; output layer pastes it as HTML + plain fallback."""
    html: str
    plain: str


@dataclass
class KeyAction:
    """Key chord or named key, e.g. 'enter', 'tab', 'ctrl+a', 'shift+left'."""
    keys: str
    repeat: int = 1


@dataclass
class CursorAction:
    """Final caret position marker ({#cursor})."""


@dataclass
class SleepAction:
    ms: int


@dataclass
class MouseAction:
    kind: str           # "click" | "move" | "rclick" | "dblclick"
    x: int | None = None
    y: int | None = None


@dataclass
class ImageAction:
    path: str           # pasted as image via clipboard


Action = TextAction | HtmlAction | KeyAction | CursorAction | SleepAction | MouseAction | ImageAction


@dataclass
class FormField:
    """One field in a fill-in form ({#form...} macros)."""
    kind: str           # "edit" | "memo" | "combo" | "checkbox" | "radio" | "date" | "label" | "number"
    name: str
    label: str = ""
    default: Any = ""
    options: list[str] = field(default_factory=list)


@dataclass
class ExpansionContext:
    phrase_id: int | None = None
    phrase_description: str = ""
    typed_abbreviation: str = ""     # what the user typed, used for case matching
    selected_text: str = ""          # text selected in target app when triggered
    app_exe: str = ""                # focused app at trigger time
    window_title: str = ""
    regex_groups: tuple[str, ...] = ()  # groups from a regex trigger
    depth: int = 0                   # nesting depth for {#insert}
    allow_privileged: bool = True    # False: {#run}, {#http}, ... are blocked (unapproved phrase)


class Cancelled(Exception):
    """Raised by HostServices when the user cancels a prompt; aborts expansion."""


# ---------------------------------------------------------------- services
class HostServices(Protocol):
    # user interaction
    def ask_input(self, prompt: str, default: str = "", multiline: bool = False) -> str: ...
    def show_form(self, title: str, fields: list[FormField]) -> dict[str, Any]: ...
    def choose(self, prompt: str, options: list[str], multi: bool = False) -> list[str]: ...
    def pick_date(self, prompt: str, default_iso: str) -> str: ...
    def message(self, text: str, title: str = "") -> None: ...
    def select_screen_region(self) -> tuple[int, int, int, int] | None: ...

    # clipboard
    def get_clipboard(self) -> str: ...
    def set_clipboard(self, text: str) -> None: ...
    def clipboard_history(self, index: int) -> str: ...   # 0 = newest

    # phrases + variables
    def phrase_content(self, description_or_id: str) -> tuple[str, str] | None: ...  # (content, format)
    def get_var(self, name: str, scope: str = "global") -> str: ...
    def set_var(self, name: str, value: str, scope: str = "global") -> None: ...

    # OS
    def run_program(self, cmd: str, args: str = "", wait: bool = False, workdir: str = "") -> int: ...
    def open_target(self, target: str) -> None: ...          # file, folder or URL
    def wait_for_window(self, title_substring: str, timeout_s: float) -> bool: ...
    def focused_app(self) -> tuple[str, str]: ...            # (exe, title)

    # integrations
    def http_request(self, method: str, url: str, headers: dict[str, str] | None = None,
                     body: str | None = None, timeout_s: float = 30) -> str: ...
    def ai_complete(self, prompt: str, provider: str = "", model: str = "",
                    system: str = "") -> str: ...
    def ocr_region(self, language: str = "English", keep_line_breaks: bool = True, rect=None) -> str: ...
    def ocr_image(self, path: str, language: str = "English") -> str: ...
    def setting(self, key: str, default: str = "") -> str: ...


@dataclass
class ExpansionRequest:
    """Emitted by the trigger layer when a phrase should be expanded."""
    phrase_id: int
    erase_chars: int = 0            # chars of typed abbreviation to delete first
    context: ExpansionContext = field(default_factory=ExpansionContext)
    trailing_delimiter: str = ""    # delimiter typed after abbreviation, re-typed after expansion
    language: str = ""              # language version to insert ("" = phrase.active_language / default)
    automatic: bool = False         # fired without a user action (time, window focus, clipboard)
