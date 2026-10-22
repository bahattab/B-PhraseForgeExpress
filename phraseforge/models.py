"""Plain data classes shared by every module."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TriggerKind(str, Enum):
    AUTOTEXT = "autotext"            # typed abbreviation
    HOTKEY = "hotkey"                # global key combination, e.g. "ctrl+alt+k"
    REGEX = "regex"                  # regex over recently typed text
    CLIPBOARD = "clipboard"          # clipboard text equals value
    CLIPBOARD_REGEX = "clipboard_regex"  # clipboard text matches regex
    TIME = "time"                    # "HH:MM" daily, or "every:<minutes>"
    APP_FOCUS = "app_focus"          # an app (exe name) gets focus


class AutotextMode(str, Enum):
    IMMEDIATE = "immediate"          # expand as soon as abbreviation is typed
    DELIMITER = "delimiter"          # expand after space/enter/punctuation
    CONFIRM = "confirm"              # show a small "expand?" tip first


class OutputMode(str, Enum):
    AUTO = "auto"                    # paste long/rich text, type short text
    TYPE = "type"                    # simulate keystrokes
    PASTE = "paste"                  # via clipboard + Ctrl+V (restores clipboard)


@dataclass
class Trigger:
    kind: TriggerKind
    value: str
    id: int | None = None
    phrase_id: int | None = None
    # autotext options
    mode: AutotextMode = AutotextMode.DELIMITER
    case_sensitive: bool = False
    word_start_only: bool = True     # only match at a word boundary
    enabled: bool = True


@dataclass
class Folder:
    name: str
    id: int | None = None
    parent_id: int | None = None
    sort: int = 0
    enabled: bool = True
    # comma separated exe names, e.g. "winword.exe,outlook.exe"; empty = all apps
    apps_include: str = ""
    apps_exclude: str = ""
    password_hash: str = ""          # empty = not protected
    show_in_popup: bool = True


@dataclass
class Phrase:
    description: str
    content: str = ""
    id: int | None = None
    folder_id: int | None = None
    content_format: str = "text"     # "text" or "html"
    output_mode: OutputMode = OutputMode.AUTO
    apps_include: str = ""
    apps_exclude: str = ""
    enabled: bool = True
    sort: int = 0
    tags: list[str] = field(default_factory=list)
    triggers: list[Trigger] = field(default_factory=list)
    use_count: int = 0
    last_used: str | None = None     # ISO timestamp
    created: str | None = None
    modified: str | None = None
    notes: str = ""

    def autotexts(self) -> list[Trigger]:
        return [t for t in self.triggers if t.kind == TriggerKind.AUTOTEXT and t.enabled]

    def hotkeys(self) -> list[Trigger]:
        return [t for t in self.triggers if t.kind == TriggerKind.HOTKEY and t.enabled]


@dataclass
class ClipboardEntry:
    text: str
    id: int | None = None
    created: str | None = None
    source_app: str = ""
    pinned: bool = False
