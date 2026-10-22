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
    APP_FOCUS = "app_focus"          # a window (exe name or title text) gets focus
    SMARTCOMPLETE = "smartcomplete"  # suggest the phrase while its value/content is being typed


class AutotextMode(str, Enum):
    IMMEDIATE = "immediate"          # expand as soon as abbreviation is typed
    DELIMITER = "delimiter"          # expand after space/enter/punctuation
    CONFIRM = "confirm"              # show a small "expand?" tip first


class OutputMode(str, Enum):
    AUTO = "auto"                    # paste long/rich text, type short text
    TYPE = "type"                    # simulate keystrokes
    PASTE = "paste"                  # via clipboard + Ctrl+V (restores clipboard)


WORD_POSITIONS = ("start", "end", "middle", "entire")
EXEC_MODES = ("immediate", "confirm", "pause", "continue")
DELIMITER_CHOICES = ("Default", "None", "Space", "Enter", "Tab", "Punctuation", "Any non-letter")


@dataclass
class Trigger:
    kind: TriggerKind
    value: str
    id: int | None = None
    phrase_id: int | None = None     # owner: a phrase ...
    # autotext options
    mode: AutotextMode = AutotextMode.DELIMITER
    case_sensitive: bool = False
    word_start_only: bool = True     # only match at a word boundary
    enabled: bool = True
    folder_id: int | None = None     # ... or a folder (opens that folder's popup) ...
    special: str = ""                # ... or a special folder: "last_used" | "clipboard_cache"
    # PhraseExpress-style options; "" = derive from mode/word_start_only (older data)
    word_pos: str = ""               # start | end | middle | entire
    exec_mode: str = ""              # immediate | confirm | pause | continue
    lead_delim: str = ""             # one of DELIMITER_CHOICES ("" = Default)
    trail_delim: str = ""            # one of DELIMITER_CHOICES ("" = from mode)
    remove_trailing: bool = False    # drop the trailing delimiter after expansion
    window_scope: str = ""           # APP_FOCUS: "" / "any" = title contains, "program" = exe name

    # effective values (old rows only have mode/word_start_only)
    def eff_word_pos(self) -> str:
        return self.word_pos or ("start" if self.word_start_only else "middle")

    def eff_exec(self) -> str:
        if self.exec_mode:
            return self.exec_mode
        return "confirm" if AutotextMode(self.mode) == AutotextMode.CONFIRM else "immediate"

    def eff_trail(self) -> str:
        if self.trail_delim:
            return self.trail_delim
        return "None" if AutotextMode(self.mode) == AutotextMode.IMMEDIATE else "Default"

    def eff_lead(self) -> str:
        return self.lead_delim or "Default"

    def to_dict(self) -> dict:
        d = dict(vars(self))
        d["kind"] = TriggerKind(self.kind).value
        d["mode"] = AutotextMode(self.mode).value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Trigger":
        """Tolerant of older exports (missing keys) and unknown extra keys."""
        names = set(cls.__dataclass_fields__)
        kw = {k: v for k, v in d.items() if k in names and k not in ("id", "phrase_id", "folder_id")}
        kw["kind"] = TriggerKind(d["kind"])
        kw["mode"] = AutotextMode(d.get("mode", "delimiter"))
        for b in ("case_sensitive", "word_start_only", "enabled", "remove_trailing"):
            if b in kw:
                kw[b] = bool(kw[b])
        return cls(**kw)

    def sync_legacy(self) -> "Trigger":
        """Keep mode/word_start_only consistent with the new fields (older readers use them)."""
        if self.exec_mode == "confirm":
            self.mode = AutotextMode.CONFIRM
        elif self.trail_delim or self.exec_mode:
            self.mode = AutotextMode.IMMEDIATE if self.eff_trail() == "None" else AutotextMode.DELIMITER
        if self.word_pos:
            self.word_start_only = self.word_pos in ("start", "entire")
        return self


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
    notes: str = ""
    triggers: list["Trigger"] = field(default_factory=list)   # filled by Store.get_folder
    # "Output target for all phrases in this folder"; "current" = not set
    output_target: str = "current"
    output_target_arg: str = ""


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
    # where the text goes: current | program | clipboard | textfile | email
    output_target: str = "current"
    output_target_arg: str = ""      # program exe/title, file path or e-mail address

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
