"""Checks for form fields with -required / -validate (PRD FR-MAC-04).

Used by the form dialog (OK stays disabled while a field is invalid) and by the tests.
"""
from __future__ import annotations

import os
import re
from typing import Any

from phraseforge.host import FormField

RULES = ("anything", "email", "url", "filepath", "folder", "letters", "numbers", "integer", "text",
         "date", "time", "phone", "regex:<pattern>")

_PATTERNS = {
    "email": r"[^@\s]+@[^@\s]+\.[^@\s]+",
    "url": r"(https?|ftp)://\S+",
    "letters": r"[^\W\d_]+",
    "numbers": r"-?\d+([.,]\d+)?",
    "integer": r"-?\d+",
    "date": r"\d{1,4}[./-]\d{1,2}[./-]\d{1,4}",
    "time": r"\d{1,2}:\d{2}(:\d{2})?",
    "phone": r"\+?[\d\s()./-]{5,}",
}

_MESSAGES = {
    "email": "an e-mail address", "url": "a web address", "letters": "letters only",
    "numbers": "a number", "integer": "a whole number", "date": "a date", "time": "a time",
    "phone": "a phone number", "filepath": "an existing file", "folder": "an existing folder",
    "text": "some text",
}


def _empty(v: Any) -> bool:
    if isinstance(v, bool):
        return not v
    if isinstance(v, (list, tuple)):
        return not v
    return v is None or str(v).strip() == ""


def rule_error(value: str, rule: str) -> str:
    """'' when `value` passes `rule`, else what was expected. Empty values pass:
    -required decides whether a field may stay empty."""
    rule = (rule or "").strip()
    v = (value or "").strip()
    if not rule or rule.lower() == "anything" or not v:
        return ""
    if rule.lower().startswith("regex:"):
        try:
            return "" if re.fullmatch(rule[6:], v) else "text matching the required pattern"
        except re.error:
            return "a valid pattern in the phrase (the -validate regex is broken)"
    r = rule.lower()
    if r == "text":
        return ""
    if r == "filepath":
        return "" if os.path.isfile(v) else _MESSAGES[r]
    if r == "folder":
        return "" if os.path.isdir(v) else _MESSAGES[r]
    pat = _PATTERNS.get(r)
    if pat is None:
        return ""          # unknown rule: do not block the user
    return "" if re.fullmatch(pat, v) else _MESSAGES[r]


def field_error(f: FormField, value: Any) -> str:
    """Message for the first problem with this field's value, or ''."""
    label = f.label or f.name
    if f.required and _empty(value):
        return f"{label}: required"
    if isinstance(value, (bool, list, tuple)):
        return ""
    msg = rule_error("" if value is None else str(value), f.validate)
    return f"{label}: please enter {msg}" if msg else ""
