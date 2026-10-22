"""Where an expanded phrase goes ("Output target" in the phrase / folder editor).

Targets (reference/phraseexpress/15_combo_output_target.png):
  current    Current application (normal typing/pasting)
  program    Specific program: start it (or focus it if running) and insert there
  clipboard  Put the text on the clipboard only
  textfile   Save the text to a .txt file
  email      Open a new e-mail with the text as body

The choice is stored by the editors in setting "ui.trigger_extras" (JSON):
"p:<phrase id>" -> {"output_target": ..., "output_program": exe path},
"f:<folder id>" -> same keys for "all phrases in this folder" (folder chain, nearest wins),
"special.<kind>.output_target" settings for the Last Used / Clipboard Cache folders.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from phraseforge.host import CursorAction, HtmlAction, ImageAction, TextAction

TARGETS = ("current", "program", "clipboard", "textfile", "email", "onenote")
# onenote: arg = OneNote page (append) or section (new page) path/ID;
#          "" -> setting onenote.default_target -> OneNote's Quick Notes
EXTRAS_KEY = "ui.trigger_extras"


def _extras(store) -> dict:
    try:
        v = json.loads(store.setting(EXTRAS_KEY, "") or "{}")
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


def _opts(arg: str) -> dict:
    return {"output_program": arg or "", "arg": arg or ""}


def resolve(store, phrase) -> tuple[str, dict]:
    """(target, options) for a phrase: its own choice, else the nearest folder's, else current.

    Reads the phrases/folders output_target columns (schema v2). Old data kept in
    the "ui.trigger_extras" setting is still honoured until the migration removes it.
    """
    own = getattr(phrase, "output_target", "") or ""
    if own in TARGETS and own != "current":
        return own, _opts(getattr(phrase, "output_target_arg", ""))
    for f in store.folder_chain(phrase.folder_id):
        ft = getattr(f, "output_target", "") or ""
        if ft in TARGETS and ft != "current":
            return ft, _opts(getattr(f, "output_target_arg", ""))
    ex = _extras(store)                       # legacy fallback
    if ex:
        own_x = ex.get(f"p:{phrase.id}") or {}
        if isinstance(own_x, dict) and own_x.get("output_target") in TARGETS and own_x["output_target"] != "current":
            return own_x["output_target"], own_x
        for f in store.folder_chain(phrase.folder_id):
            fx = ex.get(f"f:{f.id}") or {}
            if isinstance(fx, dict) and fx.get("output_target") in TARGETS and fx["output_target"] != "current":
                return fx["output_target"], fx
    return "current", {}


def remember_program(store, phrase_id: int, exe: str) -> None:
    """Store the program chosen for a phrase whose target is 'Specific program'."""
    p = store.get_phrase(phrase_id)
    if p is None:
        return
    p.output_target, p.output_target_arg = "program", exe
    store.update_phrase(p, record_history=False)


def plain_text(actions) -> str:
    """Text of the actions as it would appear (keys/cursor/sleep dropped)."""
    out = []
    for a in actions:
        if isinstance(a, TextAction):
            out.append(a.text)
        elif isinstance(a, HtmlAction):
            out.append(a.plain)
    return "".join(out).replace("\r\n", "\n")


def html_of(actions) -> str | None:
    if not any(isinstance(a, HtmlAction) for a in actions):
        return None
    import html as _h
    parts = []
    for a in actions:
        if isinstance(a, HtmlAction):
            parts.append(a.html)
        elif isinstance(a, TextAction):
            parts.append(_h.escape(a.text).replace("\n", "<br>"))
    return "".join(parts)


def only_text(actions) -> list:
    """Actions usable inside another program (drop the {#cursor} for a fresh window? keep it)."""
    return [a for a in actions if isinstance(a, (TextAction, HtmlAction, ImageAction, CursorAction))] or actions


def write_text_file(path: str | Path, text: str) -> Path:
    p = Path(path)
    if not p.suffix:
        p = p.with_suffix(".txt")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8-sig", newline="\r\n" if os.name == "nt" else "\n")
    return p


def safe_filename(name: str) -> str:
    bad = '<>:"/\\|?*'
    s = "".join("_" if c in bad or ord(c) < 32 else c for c in (name or "phrase")).strip(" .")
    return (s or "phrase")[:80]
