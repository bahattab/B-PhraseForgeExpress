"""Import PhraseExpress settings from its config.xml (FR-IMP-01, G-14).

PhraseExpress keeps its options in %APPDATA%\\PhraseExpress\\config.xml: <xml><pexconfig>, one element
per key. The layout below was checked against a real PhraseExpress 18.0.84 file:

- <AI><DefAITextEngine> and <Translation><DefTranslationEngine>: engine names (OpenRouter, OpenAI...).
- <AIPresets><Preset>: "name|prompt|n|n|n|model|flag". The prompt may itself hold commas and quotes,
  so the five fields at the end are counted from the right. The three numbers are PhraseExpress
  options with no PhraseForge equivalent and are left out.
- <Translation><glossaries><glossary>: <name>, <fromlang>, <tolang>, <dict>. <IgnoreWords>.
- <Expert><CharsBefore>/<CharsAfter>: autotext delimiters in the "#9#13" notation, which
  PhraseForge's Expert page uses too. <DeclinedApps>/<AllowedApps>: program lists.

Secrets are never imported: <*APIKey> and the <AzureAD> tokens are obfuscated in the file
(not plaintext, U-05), and the user is told which keys to enter again. Hotkeys (<General><...Shortcut>)
are stored as numbers whose encoding is not documented, so they are listed and not applied.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

MAX_CONFIG_BYTES = 8 * 1024 * 1024   # a real config.xml is about 40 KB

# PhraseExpress engine name (letters only, lower case) -> PhraseForge provider id
_ENGINES = {"openai": "openai", "chatgpt": "openai", "anthropic": "anthropic", "anthropicclaude": "anthropic",
            "claude": "anthropic", "gpt4all": "gpt4all", "ollama": "ollama", "openrouter": "openrouter",
            "gemini": "gemini", "googlegemini": "gemini", "deepl": "deepl"}
_SECRET_LABELS = {"OpenAIAPIKey": "OpenAI", "OpenRouterAPIKey": "OpenRouter", "AnthropicClaudeAPIKey": "Anthropic",
                  "DeeplAPIKey": "DeepL", "GPT4AllAPIKey": "GPT4All", "OllamaAPIKey": "Ollama",
                  "GeminiAPIKey": "Gemini"}
_HOTKEYS = {"NewPhraseShortcut": "New phrase", "TrayPopupShortcut": "Main menu (tray popup)",
            "QuickSearchShortcut": "Quick search", "LastUsedShortcut": "Last used phrases",
            "OpenSetShortcut": "Open the main window", "EnDisAppShortcut": "Enable/disable",
            "ClearClbCacheHotkey": "Clear the clipboard cache", "SkipHotkey": "Skip"}
# PhraseExpress writes glossary languages as DeepL codes (EN, AR); PhraseForge uses names
_LANG_NAMES = {"AR": "Arabic", "EN": "English", "FR": "French", "DE": "German", "ES": "Spanish", "IT": "Italian",
               "PT": "Portuguese", "TR": "Turkish", "FA": "Persian", "UR": "Urdu", "RU": "Russian", "ZH": "Chinese",
               "JA": "Japanese", "KO": "Korean", "HI": "Hindi", "ID": "Indonesian", "NL": "Dutch", "PL": "Polish",
               "SV": "Swedish", "DA": "Danish", "FI": "Finnish", "EL": "Greek", "CS": "Czech", "UK": "Ukrainian"}


def lang_name(code: str) -> str:
    c = (code or "").strip()
    return _LANG_NAMES.get(c.upper().split("-")[0], c)


@dataclass
class ConfigData:
    ai_engine: str = ""
    translation_engine: str = ""
    presets: list[dict] = field(default_factory=list)
    glossaries: list[dict] = field(default_factory=list)
    ignored_words: list[str] = field(default_factory=list)
    leading: str | None = None
    trailing: str | None = None
    excluded_apps: list[str] = field(default_factory=list)
    allowed_apps: list[str] = field(default_factory=list)
    secrets: list[str] = field(default_factory=list)      # names of services whose key is set
    hotkeys: list[str] = field(default_factory=list)      # "New phrase" etc., with a value set
    version: str = ""


@dataclass
class ConfigReport:
    presets_added: int = 0
    presets_updated: int = 0
    glossaries: int = 0
    changed: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _engine(name: str) -> str:
    return _ENGINES.get(re.sub(r"[^a-z0-9]", "", (name or "").lower()), "")


def _text(el) -> str:
    return "" if el is None or el.text is None else el.text.strip()


def _apps(s: str) -> list[str]:
    out = []
    for a in re.split(r"[|;,\r\n]+", s or ""):
        a = a.strip()
        if a and ":" not in a.split("\\")[-1]:      # AppMethods-style "exe|3" pairs are not apps
            out.append(a.split("\\")[-1].lower())
    return list(dict.fromkeys(out))


def parse_preset(raw: str) -> dict | None:
    """'name|prompt|n|n|n|model|flag' -> {"name", "prompt", "model"}; None if it is not one."""
    parts = (raw or "").split("|")
    if len(parts) < 7 or not parts[0].strip():
        return None
    name = parts[0].strip()
    prompt = "|".join(parts[1:-5]).strip()
    model = parts[-2].strip()
    if not prompt:
        return None
    return {"name": name, "prompt": prompt, "model": model}


def parse_config(path: str | Path) -> ConfigData:
    import xml.etree.ElementTree as ET
    p = Path(path)
    if p.stat().st_size > MAX_CONFIG_BYTES:
        raise ValueError(f"{p.name} is larger than {MAX_CONFIG_BYTES // (1024 * 1024)} MB: "
                         "not a PhraseExpress config.xml.")
    raw = p.read_bytes()
    if b"<!DOCTYPE" in raw[:4096].upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("This file declares XML entities, which a PhraseExpress config.xml never does.")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise ValueError(f"This XML file could not be read: {e}") from e
    cfg = root if root.tag == "pexconfig" else root.find("pexconfig")
    if cfg is None:
        raise ValueError("This is not a PhraseExpress config.xml (no <pexconfig> element).")
    d = ConfigData()
    d.version = _text(cfg.find("Other/Version"))
    d.ai_engine = _engine(_text(cfg.find("AI/DefAITextEngine")))
    d.translation_engine = _engine(_text(cfg.find("Translation/DefTranslationEngine")))
    for el in cfg.findall("AIPresets/Preset"):
        pr = parse_preset(el.text or "")
        if pr:
            d.presets.append(pr)
    for g in cfg.findall("Translation/glossaries/glossary"):
        name = _text(g.find("name"))
        if not name:
            continue
        d.glossaries.append({"name": name, "from": _text(g.find("fromlang")), "to": _text(g.find("tolang")),
                             "dict": (g.findtext("dict") or "").strip()})
    d.ignored_words = [w.strip() for w in re.split(r"[|;,\r\n]+", _text(cfg.find("Translation/IgnoreWords")))
                       if w.strip()]
    exp = cfg.find("Expert")
    if exp is not None:
        # delimiters keep their spaces: read the raw text, not the stripped one
        cb, ca = exp.find("CharsBefore"), exp.find("CharsAfter")
        d.leading = cb.text if cb is not None and cb.text else None
        d.trailing = ca.text if ca is not None and ca.text else None
        d.excluded_apps = _apps(_text(exp.find("DeclinedApps")))
        d.allowed_apps = _apps(_text(exp.find("AllowedApps")))
    for tag, label in _SECRET_LABELS.items():
        if _text(cfg.find(f"AI/{tag}")):
            d.secrets.append(label)
    if _text(cfg.find("AzureAD/AccToken")):
        d.secrets.append("Microsoft account sign-in")
    for tag, label in _HOTKEYS.items():
        v = _text(cfg.find(f"General/{tag}"))
        if v and v != "0":
            d.hotkeys.append(label)
    return d


def apply_config(store, d: ConfigData, *, engines: bool = True, presets: bool = True, glossaries: bool = True,
                 delimiters: bool = True, apps: bool = True) -> ConfigReport:
    """Write the parsed settings into PhraseForge. Presets and glossaries are merged by name;
    nothing the user has is deleted."""
    from phraseforge.ui.settings_schema import decode_delimiters
    from phraseforge.ui.settings_schema import presets as current_presets
    rep = ConfigReport()
    if engines:
        if d.ai_engine and d.ai_engine != "deepl":
            store.set_setting("ai.provider", d.ai_engine)
            rep.changed.append("AI text engine")
        if d.translation_engine:
            store.set_setting("translation.provider", d.translation_engine)
            rep.changed.append("Translation engine")
    if presets and d.presets:
        have = current_presets(store)
        index = {p["name"].strip().lower(): i for i, p in enumerate(have)}
        for pr in d.presets:
            new = {"name": pr["name"], "prompt": pr["prompt"]}
            if pr["model"]:
                new["model"] = pr["model"]
            i = index.get(pr["name"].lower())
            if i is None:
                index[pr["name"].lower()] = len(have)
                have.append(new)
                rep.presets_added += 1
            elif have[i].get("prompt") != new["prompt"] or have[i].get("model", "") != new.get("model", ""):
                have[i] = {**have[i], **new}
                if "model" not in new:
                    have[i].pop("model", None)
                rep.presets_updated += 1
        store.set_setting("ai.presets", json.dumps(have, ensure_ascii=False))
    if glossaries and (d.glossaries or d.ignored_words):
        try:
            gl = json.loads(store.setting("translation.glossaries", "{}") or "{}")
        except ValueError:
            gl = {}
        try:
            langs = json.loads(store.setting("translation.glossary_langs", "{}") or "{}")
        except ValueError:
            langs = {}
        gl = gl if isinstance(gl, dict) else {}
        langs = langs if isinstance(langs, dict) else {}
        for g in d.glossaries:
            if g["dict"] or g["name"] not in gl:
                gl[g["name"]] = g["dict"]
            if g["from"] and g["to"]:
                langs[g["name"]] = [lang_name(g["from"]), lang_name(g["to"])]
            rep.glossaries += 1
        store.set_setting("translation.glossaries", json.dumps(gl, ensure_ascii=False))
        store.set_setting("translation.glossary_langs", json.dumps(langs, ensure_ascii=False))
        if d.ignored_words:
            old = [w.strip() for w in (store.setting("translation.ignored_words", "") or "").splitlines() if w.strip()]
            store.set_setting("translation.ignored_words", "\n".join(dict.fromkeys(old + d.ignored_words)))
            rep.changed.append("Words not to translate")
    if delimiters:
        if d.leading is not None:
            store.set_setting("autotext.leading_delimiters", decode_delimiters(d.leading))
            rep.changed.append("Leading delimiters")
        if d.trailing is not None:
            store.set_setting("autotext.delimiters", decode_delimiters(d.trailing))
            rep.changed.append("Trailing delimiters")
    if apps:
        if d.excluded_apps:
            store.set_excluded_apps(sorted(store.excluded_apps() | set(d.excluded_apps)))
            rep.changed.append("Excluded programs")
        if d.allowed_apps:
            store.set_setting("app.restrict_programs", ", ".join(d.allowed_apps))
            store.set_setting("app.restrict_enabled", "1")
            rep.changed.append("Execute only in specific programs")
    if d.secrets:
        rep.notes.append("API keys are not imported. Enter them again in Settings: " + ", ".join(d.secrets) + ".")
    if d.hotkeys:
        rep.notes.append("Program hotkeys are not imported (PhraseExpress stores them in an undocumented "
                         "format). Set them again in Settings > Hotkeys: " + ", ".join(d.hotkeys) + ".")
    return rep


def import_config(store, path: str | Path, **parts) -> ConfigReport:
    return apply_config(store, parse_config(path), **parts)
