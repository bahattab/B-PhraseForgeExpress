"""Every setting the Settings dialog edits, with its default (all values are strings).

Keys that already exist in db.DEFAULT_SETTINGS keep their defaults there; they are
repeated here so the dialog can reset them. ensure_defaults(store) adds missing keys.
"""
from __future__ import annotations

import json

from phraseforge.db import DEFAULT_SETTINGS

DEFAULT_PRESETS = [
    {"name": "Correct grammar", "prompt": "Correct the grammar and spelling of this text. Keep its meaning and language."},
    {"name": "Simplify", "prompt": "Rewrite this text in simpler words."},
    {"name": "Summarize", "prompt": "Summarize this text briefly."},
    {"name": "Change from passive to active language", "prompt": "Rewrite this text using active voice."},
    {"name": "Create variation", "prompt": "Write a variation of this text with the same meaning."},
    {"name": "Rewrite more polite", "prompt": "Rewrite this text to be more polite."},
    {"name": "Rewrite more informal", "prompt": "Rewrite this text in a more informal tone."},
    {"name": "Change to first-person plural form", "prompt": "Rewrite this text in first-person plural (we)."},
    {"name": "Change to first-person form", "prompt": "Rewrite this text in first person (I)."},
    {"name": "Change to plural", "prompt": "Change this text to plural."},
    {"name": "Change to singular", "prompt": "Change this text to singular."},
]

SCHEMA: dict[str, str] = {
    # Features
    "features.clipboard_cache": "1",
    "features.last_used_folder": "1",
    "features.usage_statistics": "1",
    "features.detect_unwanted_replacements": "0",
    "features.suggest_gender": "1",
    "features.disable_capslock": "0",
    "autocorrect.capitalize_sentences": "1",
    "autocorrect.two_initial_capitals": "0",
    "app.start_with_windows": DEFAULT_SETTINGS["app.start_with_windows"],
    "app.diagnostic_mode": "0",
    "clipboard_history.max": DEFAULT_SETTINGS["clipboard_history.max"],
    "clipboard_history.enabled": "1",
    "last_used.max": "20",
    # Hotkeys
    "hotkey.new_phrase": "ctrl+alt+c",
    "hotkey.edit_last_phrase": "",
    "hotkey.open_settings": "",
    "popup.hotkey": DEFAULT_SETTINGS["popup.hotkey"],
    "hotkey.clear_clipboard_cache": "",
    "hotkey.pause": "",
    "pause.repetitions": "1",
    "pause.seconds": "10",
    "clipboard_history.hotkey": DEFAULT_SETTINGS["clipboard_history.hotkey"],
    # Display
    "ui.language": "auto",
    "display.prompt_after_new_phrase": "1",
    "display.highlight_unedited_languages": "1",
    "ui.theme": DEFAULT_SETTINGS["ui.theme"],
    # Sounds (enabled flag + optional .wav file per event)
    **{f"sound.{k}.{f}": ("0" if f == "enabled" else "")
       for k in ("phrase_insertion", "popup_display", "unwanted_detected", "unwanted_skipped",
                 "spelling_added", "clipboard_cache") for f in ("enabled", "file")},
    # Phrase file / database
    # Backup & Sync (cloud): provider off | gdrive | folder
    "sync.provider": "off",
    "sync.gdrive_folder": "PhraseForge",
    "sync.folder_path": "",
    "sync.auto": "1",
    "sync.interval_min": "15",
    "backup.cloud_auto": "1",
    "backup.cloud_interval_hours": "24",
    "backup.cloud_keep": "10",
    "backup.keep_enabled": "1",
    "backup.keep_count": "7",
    "backup.directory": "",            # empty = paths.backups_dir()
    "cache.mode": "first_use",         # none | preload | first_use
    # AI
    "ai.provider": DEFAULT_SETTINGS["ai.provider"],
    "ai.model": "",
    "ai.openai_key": "",
    "ai.anthropic_key": "",
    "ai.openrouter_key": "",
    "ai.ollama_url": DEFAULT_SETTINGS["ai.ollama_url"],
    "ai.presets": json.dumps(DEFAULT_PRESETS, ensure_ascii=False),
    "ai.instructions.about": "",
    "ai.instructions.respond": "",
    # Translation
    "translation.provider": "openai",
    "translation.ignored_words": "",
    "translation.glossaries": "{}",
    # Network
    "net.proxy_server": "",
    "net.proxy_port": "80",
    "net.proxy_user": "",
    "net.proxy_password": "",
    "updates.channel": "important",    # important | all | never
    "updates.beta": "0",
    "updates.auto": "1",
    # Screen OCR (Capture2Text)
    "ocr.cli_path": DEFAULT_SETTINGS["ocr.cli_path"],
    "ocr.language": DEFAULT_SETTINGS["ocr.language"],
    "ocr.keep_line_breaks": "1",
    "ocr.hotkey": DEFAULT_SETTINGS["ocr.hotkey"],
    # Phrase menu
    "menu.contents": "description_quickkey",
    "menu.sort_enabled": "1",
    "menu.sort_by": "description",
    "menu.sort_method": "alpha",
    "menu.sort_order": "asc",
    "menu.show_preview": "1",
    "menu.show_language_buttons": "1",
    "menu.hide_restricted": "1",
    "smartcomplete.min_chars": "3",
    "menu.position": "caret",
    "menu.position_fallback": "mouse",
    "menu.appearance": "{}",           # element -> color, plus "font"
    "menu.dim_dark": "1",
    "menu.width": "",
    "menu.confirm_hotkey": "tab",
    "menu.quickkey_modifier": "none",
    "menu.quickkey_keys": "numpad",
    "menu.search_hotkey": "f3",
    "menu.language_hotkey": "ctrl+right",
    "quicksearch.descriptions": "1",
    "quicksearch.match_case": "0",
    "quicksearch.subfolders": "1",
    "quicksearch.quick_jump": "1",
    # AutoComplete
    "autocomplete.learn_corrections": "0",
    "learning.enabled": DEFAULT_SETTINGS["learning.enabled"],   # "Suggest entered sentences"
    "autocomplete.suggest_words": "0",
    "autocomplete.filter_letter": "1",
    "autocomplete.filter_upper": "1",
    "autocomplete.filter_number": "0",
    "autocomplete.filter_special": "0",
    # Expert options
    "autotext.leading_delimiters": "\x00\n\t\r \"'<{([/\\-_",
    "autotext.delimiters": DEFAULT_SETTINGS["autotext.delimiters"],  # trailing delimiters
    "autotext.route_enter_tab": "0",
    "app.restrict_enabled": "0",
    "app.restrict_programs": "",
    "mail.method": "mailto",           # mapi | outlook | gmail | mailto
    "mail.utf8": "1",
    # Text insertion
    "output.method": "keys",           # clipboard | keys
    "output.key_method": "vk_packet",  # vk_packet | unicode | scancode
    "output.paste_long": "1",
    "output.paste_threshold": DEFAULT_SETTINGS["output.paste_threshold"],
    "output.format": "auto",           # auto | plain | rich | html
    "output.restore_clipboard": DEFAULT_SETTINGS["output.restore_clipboard"],
    "output.per_app_method": "1",
    "output.force_focus": "1",
    "output.minimize_main": "1",
    "output.uppercase_if": "0",
    "output.uppercase_chars": "2",
    # Delays (ms)
    "delay.focus": "200",
    "delay.clipboard_restore": "450",
    "delay.keypress": "90",
    "delay.paste": "10",
    # Phrase formatting
    "format.default": "plain",         # plain | rich
    "format.font": "Arial,10",
    "format.html_output": "auto",      # auto | inline | css
}


def ensure_defaults(store) -> int:
    """Insert every missing schema key with its default. Returns how many were added."""
    have = store.settings()
    added = 0
    for k, v in SCHEMA.items():
        if k not in have:
            store.set_setting(k, v)
            added += 1
    return added


def presets(store) -> list[dict]:
    try:
        v = json.loads(store.setting("ai.presets", SCHEMA["ai.presets"]) or "[]")
        return [p for p in v if isinstance(p, dict) and p.get("name")]
    except ValueError:
        return list(DEFAULT_PRESETS)


def glossaries(store) -> dict[str, str]:
    try:
        v = json.loads(store.setting("translation.glossaries", "{}") or "{}")
        return {str(k): str(t) for k, t in v.items()} if isinstance(v, dict) else {}
    except ValueError:
        return {}


# "#9#10#13 \"'>" notation PhraseExpress uses for delimiter fields
def encode_delimiters(s: str) -> str:
    out = []
    for ch in s:
        if ord(ch) < 32 or ch == "#":
            out.append(f"#{ord(ch)}")
        else:
            out.append(ch)
    return "".join(out)


def decode_delimiters(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        if s[i] == "#" and i + 1 < len(s) and s[i + 1].isdigit():
            # codes are 0-35 (control chars and '#'): take two digits only if that stays <= 35
            two = s[i + 1:i + 3]
            if len(two) == 2 and two.isdigit() and int(two) <= 35:
                out.append(chr(int(two)))
                i += 3
            else:
                out.append(chr(int(s[i + 1])))
                i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)
