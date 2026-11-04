"""Administrator lockdown (PRD FR-APP-04, gap G-28).

PhraseExpress reads a machine-wide file (C:\\ProgramData\\PhraseExpress\\config.xml with
ConfigDisabled, EditDisabled, DoStats) so an administrator can stop users changing
settings or phrases. PhraseForge reads

    %ProgramData%\\PhraseForge\\policy.toml        (Windows)
    /etc/phraseforge/policy.toml                 (elsewhere)

The administrator makes the file read-only for users (by default only
Administrators can write to %ProgramData% subfolders they create). There is
deliberately no environment variable or command-line switch to point at another
file, as that would let a user turn the policy off.

    settings_locked  = true            # Settings cannot be opened
    editing_disabled = true            # phrases and folders cannot be created, changed or deleted
    stats_enabled    = false           # same as forcing features.usage_statistics = "0"
    macros_disabled  = ["run", "http"] # these macros output a notice instead of running
    locked_settings  = ["sync.*", "ai.provider"]   # cannot be changed (wildcards allowed)
    message          = "Contact IT on 1234."      # added to every "locked" notice

    [settings]                         # forced values: the user's own value is ignored
    "learning.enabled" = "0"
    "app.check_updates" = "0"

A file that cannot be read or parsed locks Settings and editing (fail closed) and
the reason is logged, so a typo cannot silently open everything up.
"""
from __future__ import annotations

import fnmatch
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


class PolicyError(PermissionError):
    """An action the administrator's policy does not allow."""


@dataclass(frozen=True)
class Policy:
    settings_locked: bool = False
    editing_disabled: bool = False
    stats_enabled: bool = True
    macros_disabled: frozenset[str] = frozenset()
    locked_settings: tuple[str, ...] = ()
    forced: dict[str, str] = field(default_factory=dict)
    message: str = ""
    source: str = ""                       # file it came from ("" = no policy)
    error: str = ""                        # set when the file was unreadable (fail closed)

    @property
    def active(self) -> bool:
        return bool(self.source)

    def forced_value(self, key: str) -> str | None:
        if key in self.forced:
            return self.forced[key]
        if key == "features.usage_statistics" and not self.stats_enabled:
            return "0"
        return None

    def setting_locked(self, key: str) -> bool:
        """The store refuses to change this setting. (settings_locked only keeps the Settings
        window closed: PhraseForge itself still saves window sizes, counters and the like.)"""
        if self.forced_value(key) is not None:
            return True
        return any(fnmatch.fnmatchcase(key, pat) for pat in self.locked_settings)

    def macro_disabled(self, name: str) -> bool:
        return name.lower() in self.macros_disabled

    def notice(self, what: str) -> str:
        text = f"{what} is locked by your administrator."
        return f"{text} {self.message}" if self.message else text


NO_POLICY = Policy()


def policy_path() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("ProgramData") or r"C:\ProgramData") / "PhraseForge" / "policy.toml"
    return Path("/etc/phraseforge/policy.toml")


def _strings(v, key: str) -> list[str]:
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ValueError(f"{key} must be a list of strings")
    return v


def parse(text: str, source: str = "policy.toml") -> Policy:
    import tomllib
    data = tomllib.loads(text)
    known = {"settings_locked", "editing_disabled", "stats_enabled", "macros_disabled", "locked_settings",
             "settings", "message", "plugins_allowed"}
    for k in data:
        if k not in known:
            log.warning("policy %s: unknown key %r ignored", source, k)

    def flag(k, default):
        v = data.get(k, default)
        if not isinstance(v, bool):
            raise ValueError(f"{k} must be true or false")
        return v
    forced = data.get("settings", {})
    if not isinstance(forced, dict):
        raise ValueError("[settings] must be a table")
    return Policy(
        settings_locked=flag("settings_locked", False),
        editing_disabled=flag("editing_disabled", False),
        stats_enabled=flag("stats_enabled", True),
        macros_disabled=frozenset(x.lower().lstrip("#") for x in _strings(data.get("macros_disabled", []),
                                                                         "macros_disabled")),
        locked_settings=tuple(_strings(data.get("locked_settings", []), "locked_settings")),
        forced={str(k): ("1" if v is True else "0" if v is False else str(v)) for k, v in forced.items()},
        message=str(data.get("message", "")),
        source=source)


def load(path: Path | None = None) -> Policy:
    p = path or policy_path()
    try:
        if not p.is_file():
            return NO_POLICY
        return parse(p.read_text(encoding="utf-8-sig"), str(p))
    except Exception as e:                  # unreadable or invalid: lock rather than open up
        log.error("policy file %s could not be read, Settings and editing stay locked: %s", p, e)
        return Policy(settings_locked=True, editing_disabled=True, source=str(p), error=str(e))


_current: Policy | None = None


def current() -> Policy:
    """The machine's policy, read once per run (reload() reads it again)."""
    global _current
    if _current is None:
        _current = load()
        if _current.active:
            log.info("administrator policy %s: settings_locked=%s editing_disabled=%s",
                     _current.source, _current.settings_locked, _current.editing_disabled)
    return _current


def reload() -> Policy:
    global _current
    _current = None
    return current()


def set_current(p: Policy | None) -> None:
    """For tests and the self-test: use this policy instead of the file."""
    global _current
    _current = p
