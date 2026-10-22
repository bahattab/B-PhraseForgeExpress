"""Editor rows <-> models.Trigger, without Qt (used by the editor and the db migration).

A row is the dict one trigger row in the editor works on:
  type        autotext | smartcomplete | regex_autotext | hotkey | window | time | clipboard | regex_clipboard
  value, enabled, case_sensitive,
  word_pos    start | end | middle | entire
  exec        immediate | confirm | pause | continue
  lead_delim / trail_delim  one of models.DELIMITER_CHOICES
  remove_trailing, window_scope (any = title contains, program = exe name)
"""
from __future__ import annotations

from typing import Any

from phraseforge.models import AutotextMode, Trigger, TriggerKind

TYPES = [
    ("autotext", "Autotext"),
    ("smartcomplete", "SmartComplete"),
    ("regex_autotext", "RegEx Autotext"),
    ("hotkey", "Hotkey"),
    ("window", "Window"),
    ("time", "Time"),
    ("clipboard", "Clipboard"),
    ("regex_clipboard", "RegEx Clipboard"),
]
KIND_FOR_TYPE = {
    "autotext": TriggerKind.AUTOTEXT, "smartcomplete": TriggerKind.SMARTCOMPLETE,
    "regex_autotext": TriggerKind.REGEX, "hotkey": TriggerKind.HOTKEY, "window": TriggerKind.APP_FOCUS,
    "time": TriggerKind.TIME, "clipboard": TriggerKind.CLIPBOARD, "regex_clipboard": TriggerKind.CLIPBOARD_REGEX,
}
TYPE_FOR_KIND = {v: k for k, v in KIND_FOR_TYPE.items()}
# rows of these types are kept even without a value
VALUELESS_OK = {"smartcomplete"}


def default_row(type_: str = "autotext") -> dict[str, Any]:
    return {"type": type_, "value": "", "case_sensitive": False, "word_pos": "start",
            "exec": "immediate", "lead_delim": "Default", "trail_delim": "None", "remove_trailing": False,
            "window_scope": "any", "enabled": True}


def row_to_trigger(row: dict) -> Trigger | None:
    type_ = row.get("type", "autotext")
    kind = KIND_FOR_TYPE.get(type_)
    raw = row.get("value") or ""
    value = raw if type_ == "autotext" else raw.strip()
    if kind is None or (not value and type_ not in VALUELESS_OK):
        return None
    t = Trigger(kind=kind, value=value, enabled=bool(row.get("enabled", True)))
    if kind in (TriggerKind.AUTOTEXT, TriggerKind.SMARTCOMPLETE, TriggerKind.REGEX):
        t.case_sensitive = bool(row.get("case_sensitive"))
    if kind == TriggerKind.AUTOTEXT:
        t.word_pos = row.get("word_pos") or "start"
        t.exec_mode = row.get("exec") or "immediate"
        t.lead_delim = row.get("lead_delim") or "Default"
        t.trail_delim = row.get("trail_delim") or "None"
        t.remove_trailing = bool(row.get("remove_trailing"))
    elif kind == TriggerKind.REGEX:
        t.exec_mode = row.get("exec") or "immediate"
        t.mode = AutotextMode.IMMEDIATE
    elif kind == TriggerKind.APP_FOCUS:
        t.window_scope = row.get("window_scope") or "any"
    return t.sync_legacy()


def trigger_to_row(t: Trigger) -> dict:
    kind = TriggerKind(t.kind)
    row = default_row(TYPE_FOR_KIND.get(kind, "autotext"))
    row["value"] = t.value
    row["enabled"] = t.enabled
    row["case_sensitive"] = t.case_sensitive
    if kind == TriggerKind.AUTOTEXT:
        row.update(word_pos=t.eff_word_pos(), exec=t.eff_exec(), lead_delim=t.eff_lead(),
                   trail_delim=t.eff_trail(), remove_trailing=t.remove_trailing)
    elif kind == TriggerKind.REGEX:
        row["exec"] = t.eff_exec()
    elif kind == TriggerKind.APP_FOCUS:
        row["window_scope"] = t.window_scope or ("program" if t.value.lower().endswith(".exe") else "any")
    return row
