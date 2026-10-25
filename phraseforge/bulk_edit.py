"""Bulk edit of every phrase in a folder, as in PhraseExpress's folder context menu
(Bulk edit > Remove duplicates / Descriptions / Phrase contents / Autotexts, and Sort).

All functions work on the phrases directly inside one folder (None = top level) and
return how many phrases they changed.
"""
from __future__ import annotations

from phraseforge.models import TriggerKind

# operation name -> function(text, arg) -> new text
TEXT_OPS = {
    "prefix": lambda s, a: (a or "") + s,
    "append": lambda s, a: s + (a or ""),
    "strip_trailing": lambda s, a: s.rstrip(),
    "strip_leading": lambda s, a: s.lstrip(),
    "upper_first": lambda s, a: s[:1].upper() + s[1:],
    "lower_first": lambda s, a: s[:1].lower() + s[1:],
    "upper": lambda s, a: s.upper(),
    "lower": lambda s, a: s.lower(),
}
TEXT_OP_TITLES = {
    "prefix": "Prefix text...", "append": "Append text...",
    "strip_trailing": "Strip trailing spaces", "strip_leading": "Strip leading spaces",
    "upper_first": "Upper case first letter", "lower_first": "Lower case first letter",
    "upper": "UPPERCASE", "lower": "lowercase",
}
TARGETS = ("description", "content", "autotext")

SORT_KEYS = {
    "description": ("Description", lambda p: p.description.casefold()),
    "description_length": ("Description length", lambda p: (len(p.description), p.description.casefold())),
    "created": ("Date created", lambda p: p.created or ""),
    "modified": ("Date modified", lambda p: p.modified or ""),
    "last_used": ("Last used", lambda p: p.last_used or ""),
    "times_used": ("Times used", lambda p: p.use_count),
}


def apply_text_op(store, folder_id, target: str, op: str, arg: str = "") -> int:
    """Run one text operation on the descriptions, contents or autotexts of a folder's phrases."""
    if target not in TARGETS or op not in TEXT_OPS:
        raise ValueError(f"unknown bulk edit {target}/{op}")
    fn = TEXT_OPS[op]
    changed = 0
    for p in store.phrases(folder_id):
        dirty = False
        if target == "description":
            new = fn(p.description, arg)
            if new and new != p.description:
                p.description, dirty = new, True
        elif target == "content":
            new = fn(p.content, arg)
            if new != p.content:
                p.content, dirty = new, True
        else:
            for t in p.triggers:
                if TriggerKind(t.kind) == TriggerKind.AUTOTEXT and t.value:
                    new = fn(t.value, arg)
                    if new and new != t.value:
                        t.value, dirty = new, True
        if dirty:
            store.update_phrase(p, record_history=False)
            changed += 1
    return changed


def generate_descriptions(store, folder_id, max_len: int = 60) -> int:
    """Description = first non-empty line of the phrase text (plain text for formatted phrases)."""
    from phraseforge.macros.engine import html_to_text
    changed = 0
    for p in store.phrases(folder_id):
        text = html_to_text(p.content) if p.content_format == "html" else p.content
        line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")[:max_len]
        if line and line != p.description:
            p.description = line
            store.update_phrase(p, record_history=False)
            changed += 1
    return changed


def convert_to_plain_text(store, folder_id) -> int:
    from phraseforge.macros.engine import html_to_text
    changed = 0
    for p in store.phrases(folder_id):
        if p.content_format == "html":
            p.content, p.content_format = html_to_text(p.content), "text"
            store.update_phrase(p, record_history=False)
            changed += 1
    return changed


def remove_duplicates(store, folder_id) -> int:
    """Delete phrases whose description and text both equal an earlier phrase in the folder."""
    seen, removed = set(), 0
    for p in sorted(store.phrases(folder_id), key=lambda p: (p.sort, p.id)):
        key = (p.description.strip(), p.content)
        if key in seen:
            store.delete_phrase(p.id)
            removed += 1
        else:
            seen.add(key)
    return removed


def sort_phrases(store, folder_id, key: str, descending: bool = False) -> int:
    """Store a new manual order (Phrase.sort) by one of SORT_KEYS."""
    _title, fn = SORT_KEYS[key]
    changed = 0
    for n, p in enumerate(sorted(store.phrases(folder_id), key=fn, reverse=descending)):
        if p.sort != n:
            p.sort = n
            store.update_phrase(p, record_history=False)
            changed += 1
    return changed
