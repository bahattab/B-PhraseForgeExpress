"""Every setting the Settings dialog edits, with its default (all values are strings).

Keys that already exist in db.DEFAULT_SETTINGS keep their defaults there; they are
repeated here so the dialog can reset them. ensure_defaults(store) adds missing keys.
"""
from __future__ import annotations

import json

from phraseforge.filesearch import DEFAULT_CUSTOM_COMMANDS as FILESEARCH_COMMANDS
from phraseforge.filesearch import DEFAULT_PRIORITY_RULES as FILESEARCH_PRIORITIES
from phraseforge.db import DEFAULT_SETTINGS
from phraseforge.onenote import DEFAULT_EXE as _ONENOTE_EXE

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
    # Features ("Clipboard Cache" checkbox edits clipboard_history.enabled below)
    "features.last_used_folder": "1",
    "features.usage_statistics": "1",
    "features.detect_unwanted_replacements": "0",
    "features.disable_capslock": "0",
    "autocorrect.capitalize_sentences": "1",
    "autocorrect.two_initial_capitals": "0",
    "app.start_with_windows": DEFAULT_SETTINGS["app.start_with_windows"],
    "updates.auto_check": "1",
    "app.diagnostic_mode": "0",
    "clipboard_history.max": DEFAULT_SETTINGS["clipboard_history.max"],
    "clipboard_history.enabled": "1",
    "last_used.max": "20",
    # Hotkeys
    "hotkey.new_phrase": "ctrl+alt+c",
    "hotkey.edit_last_phrase": "",
    "hotkey.new_phrase_from_clipboard": "",
    "hotkey.toggle_expansion": "",
    "hotkey.open_main": "",
    "tray.left_click_popup": "0",   # PhraseExpress: left click on the tray icon opens the phrase menu
    "hotkey.open_settings": "",
    "popup.hotkey": DEFAULT_SETTINGS["popup.hotkey"],
    "hotkey.clear_clipboard_cache": "",
    "hotkey.pause": "",
    "hotkey.popup_search": "",
    "pause.repetitions": "1",
    "pause.seconds": "10",
    "clipboard_history.hotkey": DEFAULT_SETTINGS["clipboard_history.hotkey"],
    # Display
    "ui.language": "auto",
    "date.lang": "en",                   # month/day names in {#date}
    "date.calendar": "gregorian",        # gregorian | hijri (tabular)
    "date.digits": "latin",              # latin | arabic (٠-٩)
    "phrase.languages": "[]",            # languages offered for phrase versions (JSON list)
    "phrase.active_language": "",        # version inserted by autotext/hotkeys ("" = default)
    "display.highlight_unedited": "1",
    "menu.language_buttons": "1",
    "menu.language_modifier": "ctrl",    # + Left/Right in the phrase menu picks the language
    "display.prompt_after_new_phrase": "1",
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
    # AI
    "ai.provider": DEFAULT_SETTINGS["ai.provider"],
    "ai.model": "",
    "ai.openai_key": "",
    "ai.anthropic_key": "",
    "ai.openrouter_key": "",
    "ai.gemini_key": "",
    "ai.opencode_key": "",
    "ai.kilocode_key": "",
    "ai.mistral_key": "",
    "ocr.engine": "windows",            # windows (built in, offline) | mistral (cloud)
    "ai.ollama_url": DEFAULT_SETTINGS["ai.ollama_url"],
    "ai.gpt4all_url": DEFAULT_SETTINGS["ai.gpt4all_url"],
    "ai.deepl_key": "",
    "ai.presets": json.dumps(DEFAULT_PRESETS, ensure_ascii=False),
    "ai.instructions.about": "",
    "ai.instructions.respond": "",
    # Translation
    "translation.provider": "free",
    "translation.ignored_words": "",
    "translation.glossaries": "{}",
    "translation.glossary_langs": "{}",
    # Network
    "net.proxy_server": "",
    "net.proxy_port": "80",
    "net.proxy_user": "",
    "net.proxy_password": "",
    "net.allow_private_hosts": "0",        # {#http} to localhost / LAN addresses
    # Screen OCR (Capture2Text)
    "ocr.language": DEFAULT_SETTINGS["ocr.language"],
    "ocr.keep_line_breaks": "1",
    "ocr.hotkey": DEFAULT_SETTINGS["ocr.hotkey"],
    # modelled on Capture2Text's tray menu and Settings pages (docs/menus/capture2text.md)
    "ocr.save_to_clipboard": "1",
    "ocr.show_popup": "1",
    "ocr.quick_languages": "Arabic, English",
    "ocr.recapture_hotkey": "",
    "ocr.quick1_hotkey": "",
    "ocr.quick2_hotkey": "",
    "ocr.quick3_hotkey": "",
    "ocr.textline_hotkey": "",
    "ocr.forward_hotkey": "",
    "ocr.bubble_hotkey": "",
    "ocr.scale": "0",                    # 0 = automatic, 1-4 = enlarge the capture
    "ocr.whitelist": "",
    "ocr.blacklist": "",
    "ocr.replace_rules": "",
    "ocr.log_file": "",
    "ocr.log_format": "${capture}${linebreak}",
    # OneNote (desktop app, official COM API)
    "onenote.exe": _ONENOTE_EXE,
    "onenote.default_target": "",          # page/section path; "" = Quick Notes
    "onenote.send_hotkey": "",
    "onenote.clip_hotkey": "",
    "onenote.quick_note_hotkey": "",       # "New quick note" window
    # Search files (Listary-style launcher)
    "filesearch.enabled": "1",
    "filesearch.hotkey": "ctrl+alt+f",
    "promptboost.hotkey": "ctrl+alt+b",
    "filesearch.roots": "",
    "filesearch.refresh_minutes": "30",
    "filesearch.include_hidden": "0",
    "filesearch.double_ctrl": "1",          # press Ctrl twice to open Search files
    "filesearch.web_keywords": "",           # "g=https://...{q}" per line; empty = built-in list
    # modelled on Listary's Options window (docs/menus/listary.md)
    "filesearch.press_again": "hide",        # hotkey while open: hide | keep
    "filesearch.filters": "",                # extra "keyword = Name; ext=pdf,docx; in=C:\\Docs"
    "filesearch.priorities": FILESEARCH_PRIORITIES,
    "filesearch.actions": 'Edit with Notepad = notepad.exe | "{path}"',
    "filesearch.commands": FILESEARCH_COMMANDS,  # "keyword = Title | program | parameter with {query}"
    "filesearch.favorites": "",              # folders listed while the search box is empty
    "onenote.clip_action": "image",        # image | ocr | both
    "onenote.include_ocr": "0",            # include text OneNote recognised in images
    # Phrase menu
    "menu.contents": "description_quickkey",
    "menu.sort_enabled": "1",
    "menu.sort_by": "description",
    "menu.sort_method": "alpha",
    "menu.sort_order": "asc",
    "menu.show_preview": "1",
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
    "quicksearch.descriptions": "1",
    "quicksearch.match_case": "0",
    "quicksearch.subfolders": "1",
    "quicksearch.quick_jump": "1",
    # AutoComplete
    "autocomplete.learn_corrections": "0",
    "learning.enabled": DEFAULT_SETTINGS["learning.enabled"],   # "Suggest entered sentences"
    "learning.remind_abbreviation": "1",   # tip when a phrase with an autotext is typed in full
    "autocomplete.suggest_words": "0",
    "autocomplete.filter_letter": "1",
    "autocomplete.filter_upper": "1",
    "autocomplete.filter_number": "0",
    "autocomplete.filter_special": "0",
    # Expert options
    "autotext.leading_delimiters": "\x00\n\t\r \"'<{([/\\-_",
    "autotext.delimiters": DEFAULT_SETTINGS["autotext.delimiters"],  # trailing delimiters
    "autotext.route_enter_tab": "0",
    # ms without typing that counts as a "pause" (autotext "When pausing") and the
    # window for "When continue typing quickly"; read by the trigger layer
    "autotext.pause_ms": "700",
    "app.restrict_enabled": "0",
    "app.restrict_programs": "",
    "mail.method": "mailto",           # mapi | outlook | gmail | mailto
    "mail.utf8": "1",
    # Text insertion
    "output.method": "keys",           # clipboard | keys
    "output.key_method": "vk_packet",  # vk_packet | unicode | scancode
    "output.paste_long": "1",
    "output.paste_threshold": DEFAULT_SETTINGS["output.paste_threshold"],
    "output.rich_formats": "html",      # html | rtf_html | rtf: clipboard formats of formatted phrases
    "output.format": "auto",           # auto | plain | rich | html
    "output.restore_clipboard": DEFAULT_SETTINGS["output.restore_clipboard"],
    "output.per_app_method": "1",
    "output.app_methods": "{}",        # {"winword.exe": "type" | "paste"}
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


# Keys only the Settings dialog itself needs (no runtime reader is expected).
# tests/test_settings_dialog.py fails if any other SCHEMA key has no runtime reader.
UI_ONLY_KEYS: set[str] = set()

# Old key -> (new key, value mapping or None to copy). Applied once, when the new key
# is not stored yet: earlier builds of the popup read popup.*, the stats window
# stats.enabled and the Features page features.clipboard_cache.
LEGACY_KEYS: dict[str, tuple[str, dict | None]] = {
    "popup.width": ("menu.width", None),
    "popup.position": ("menu.position", None),
    "popup.sort": ("menu.sort_by", {"usage": "usage", "description": "description"}),
    "popup.search_match_case": ("quicksearch.match_case", None),
    "popup.search_subfolders": ("quicksearch.subfolders", None),
    "popup.search_content": ("quicksearch.descriptions", {"1": "0", "0": "1"}),
    "popup.show_last_used": ("features.last_used_folder", None),
    "popup.show_clipboard_cache": ("clipboard_history.enabled", None),
    "features.clipboard_cache": ("clipboard_history.enabled", None),
    "stats.enabled": ("features.usage_statistics", None),
}


# On/off switches whose new key always exists (db defaults): an old "0" wins once,
# then the old key is set to "1" so it no longer matters to anyone still reading it.
LEGACY_OFF_SWITCHES = ("features.clipboard_cache", "popup.show_clipboard_cache", "stats.enabled")


def migrate_legacy(store, have: dict[str, str] | None = None) -> int:
    """Copy values of old keys to their canonical keys (only where the new key is unset)."""
    have = store.settings() if have is None else have
    done = 0
    for old in LEGACY_OFF_SWITCHES:
        if have.get(old) == "0":
            new = LEGACY_KEYS[old][0]
            store.set_setting(new, "0")
            store.set_setting(old, "1")
            have[new], have[old] = "0", "1"
            done += 1
    for old, (new, mapping) in LEGACY_KEYS.items():
        if old in have and new not in have and have[old] != "":
            val = have[old] if mapping is None else mapping.get(have[old])
            if val is None:
                continue
            store.set_setting(new, val)
            have[new] = val
            done += 1
            if old == "popup.sort" and val == "usage":
                store.set_setting("menu.sort_order", "desc")
                have["menu.sort_order"] = "desc"
    return done


def ensure_defaults(store) -> int:
    """Migrate legacy keys, then insert every missing schema key with its default.
    Returns how many defaults were added."""
    have = store.settings()
    migrate_legacy(store, have)
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
