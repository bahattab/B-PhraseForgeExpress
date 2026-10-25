"""AI completions for the {#ai} and {#translate} macros.

Providers: openai, anthropic, gpt4all, ollama, openrouter (and deepl for translation only). Keys and defaults come from
the settings table (ai.provider, ai.model, ai.*_key, ai.ollama_url).
Settings > AI text processing adds:
- ai.instructions.about / ai.instructions.respond: always added to the system prompt
- ai.presets: named prompts ({#ai -preset "Summarize" text})
Settings > Language Translation: translation.provider, translation.ignored_words,
translation.glossaries (see translation_system()).
"""
from __future__ import annotations

import json

import httpx

DEFAULT_MODELS = {
    "openai": "gpt-4.1-mini",
    "anthropic": "claude-sonnet-5-5",
    "gpt4all": "Llama 3 8B Instruct",   # GPT4All desktop app, local API server (OpenAI format)
    "ollama": "llama3.2",
    "openrouter": "openrouter/auto",
}


class AIError(RuntimeError):
    pass


def _post(url: str, headers: dict, payload: dict, timeout: float) -> dict:
    from phraseforge.net import client_kwargs
    try:
        with httpx.Client(timeout=timeout, **client_kwargs()) as c:
            r = c.post(url, headers=headers, json=payload)
    except httpx.HTTPError as e:
        raise AIError(str(e)) from e
    if r.status_code >= 400:
        raise AIError(f"HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def _messages(prompt: str, system: str) -> list[dict]:
    msgs = [{"role": "system", "content": system}] if system else []
    return msgs + [{"role": "user", "content": prompt}]


def full_system(settings: dict[str, str], system: str = "") -> str:
    """Macro system prompt + the user's custom instructions."""
    parts = [system.strip()] if system and system.strip() else []
    about = (settings.get("ai.instructions.about") or "").strip()
    respond = (settings.get("ai.instructions.respond") or "").strip()
    if about:
        parts.append("About the user:\n" + about)
    if respond:
        parts.append("How to respond:\n" + respond)
    return "\n\n".join(parts)


def presets(settings: dict[str, str]) -> list[dict]:
    try:
        v = json.loads(settings.get("ai.presets") or "[]")
        return [p for p in v if isinstance(p, dict) and p.get("name")] if isinstance(v, list) else []
    except ValueError:
        return []


def _find_preset(settings: dict[str, str], name: str) -> dict:
    for p in presets(settings):
        if p["name"].strip().lower() == (name or "").strip().lower():
            return p
    raise AIError(f"AI preset '{name}' not found (Settings > AI text processing > Custom presets)")


def preset_prompt(settings: dict[str, str], name: str) -> str:
    return str(_find_preset(settings, name).get("prompt", ""))


def preset_model(settings: dict[str, str], name: str) -> str:
    """Model chosen for a preset (PhraseExpress AI Presets > Model); "" = Auto."""
    m = str(_find_preset(settings, name).get("model", "") or "").strip()
    return "" if m.lower() == "auto" else m


def glossary_langs(settings: dict[str, str]) -> dict[str, tuple[str, str]]:
    """{glossary name: (source language, target language)} from translation.glossary_langs."""
    try:
        v = json.loads(settings.get("translation.glossary_langs") or "{}")
    except ValueError:
        return {}
    out = {}
    if isinstance(v, dict):
        for k, pair in v.items():
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                out[str(k)] = (str(pair[0]), str(pair[1]))
    return out


def translation_system(settings: dict[str, str], to: str, src: str = "", glossary: str = "") -> str:
    """System prompt for {#translate}: target language, ignored words, glossary pairs."""
    s = f"You are a translator. Translate the user's text{(' from ' + src) if src else ''} to {to}. " \
        "Output only the translation."
    ignored = [w.strip() for w in (settings.get("translation.ignored_words") or "").replace(",", "\n").splitlines()
               if w.strip()]
    if ignored:
        s += "\nNever translate these words; keep them exactly as written: " + ", ".join(ignored)
    try:
        gl = json.loads(settings.get("translation.glossaries") or "{}")
    except ValueError:
        gl = {}
    names = [glossary] if glossary else list(gl) if isinstance(gl, dict) else []
    if not glossary:
        # a glossary with languages set applies only when they match this translation
        langs = glossary_langs(settings)

        def fits(n):
            if n not in langs:
                return True
            s_lang, t_lang = (x.lower() for x in langs[n])
            return t_lang == to.lower() and (not src or s_lang == src.lower())
        names = [n for n in names if fits(n)]
    pairs = []
    for n in names:
        for line in str(gl.get(n, "")).splitlines() if isinstance(gl, dict) else []:
            if "=" in line:
                a, b = line.split("=", 1)
                if a.strip() and b.strip():
                    pairs.append(f"{a.strip()} -> {b.strip()}")
    if pairs:
        s += "\nAlways use these translations:\n" + "\n".join(pairs)
    return s


def complete(settings: dict[str, str], prompt: str, provider: str = "", model: str = "", system: str = "",
             timeout_s: float = 120, max_tokens: int = 1024, raw_system: bool = False) -> str:
    """raw_system=True skips the user's custom instructions (used by translation)."""
    provider = (provider or settings.get("ai.provider") or "openai").lower()
    if provider not in DEFAULT_MODELS:
        raise AIError(f"unknown AI provider '{provider}'")
    same_provider = (settings.get("ai.provider") or "openai").lower() == provider
    model = model or (settings.get("ai.model") if same_provider else "") or DEFAULT_MODELS[provider]
    if not raw_system:
        system = full_system(settings, system)

    if provider == "anthropic":
        key = settings.get("ai.anthropic_key", "")
        if not key:
            raise AIError("Anthropic API key is not set (Settings > AI)")
        payload = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
        if system:
            payload["system"] = system
        data = _post("https://api.anthropic.com/v1/messages",
                     {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                     payload, timeout_s)
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")

    if provider == "gpt4all":
        base = (settings.get("ai.gpt4all_url") or "http://localhost:4891/v1").rstrip("/")
        data = _post(f"{base}/chat/completions", {}, {"model": model, "max_tokens": max_tokens,
                                                      "messages": _messages(prompt, system)}, timeout_s)
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as e:
            raise AIError(f"unexpected response: {str(data)[:200]}") from e

    if provider == "ollama":
        base = (settings.get("ai.ollama_url") or "http://localhost:11434").rstrip("/")
        data = _post(f"{base}/api/chat", {}, {"model": model, "stream": False,
                                               "messages": _messages(prompt, system)}, timeout_s)
        return data.get("message", {}).get("content", "")

    if provider == "openai":
        key, url = settings.get("ai.openai_key", ""), "https://api.openai.com/v1/chat/completions"
    else:
        key, url = settings.get("ai.openrouter_key", ""), "https://openrouter.ai/api/v1/chat/completions"
    if not key:
        raise AIError(f"{provider} API key is not set (Settings > AI)")
    data = _post(url, {"Authorization": f"Bearer {key}"},
                 {"model": model, "messages": _messages(prompt, system)}, timeout_s)
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError) as e:
        raise AIError(f"unexpected response: {str(data)[:200]}") from e


# ---------------------------------------------------------------- DeepL (translation only)
DEEPL_LANGS = {
    "arabic": "AR", "bulgarian": "BG", "chinese": "ZH", "czech": "CS", "danish": "DA", "dutch": "NL",
    "english": "EN", "estonian": "ET", "finnish": "FI", "french": "FR", "german": "DE", "greek": "EL",
    "hungarian": "HU", "indonesian": "ID", "italian": "IT", "japanese": "JA", "korean": "KO",
    "latvian": "LV", "lithuanian": "LT", "norwegian": "NB", "polish": "PL", "portuguese": "PT",
    "romanian": "RO", "russian": "RU", "slovak": "SK", "slovenian": "SL", "spanish": "ES",
    "swedish": "SV", "turkish": "TR", "ukrainian": "UK",
}


def deepl_code(lang: str) -> str:
    """Language name or code -> DeepL code ("Arabic" -> "AR", "en-us" -> "EN-US")."""
    lang = (lang or "").strip()
    return DEEPL_LANGS.get(lang.lower(), lang.upper())


def deepl_translate(settings: dict[str, str], text: str, to: str, src: str = "", timeout_s: float = 60) -> str:
    """Translate with the DeepL API (Free keys end in ':fx'). Ignored words are wrapped in
    <keep> tags that DeepL leaves untranslated."""
    key = (settings.get("ai.deepl_key") or "").strip()
    if not key:
        raise AIError("DeepL API key is not set (Settings > Language Translation)")
    host = "api-free.deepl.com" if key.endswith(":fx") else "api.deepl.com"
    ignored = [w.strip() for w in (settings.get("translation.ignored_words") or "").replace(",", "\n").splitlines()
               if w.strip()]
    body = text
    payload: dict = {"target_lang": deepl_code(to)}
    if ignored:
        import re
        body = re.sub("|".join(re.escape(w) for w in sorted(ignored, key=len, reverse=True)),
                      lambda m: f"<keep>{m.group(0)}</keep>", text)
        payload.update(tag_handling="xml", ignore_tags=["keep"])
    payload["text"] = [body]
    if src:
        payload["source_lang"] = deepl_code(src).split("-")[0]
    data = _post(f"https://{host}/v2/translate", {"Authorization": f"DeepL-Auth-Key {key}"}, payload, timeout_s)
    try:
        out = data["translations"][0]["text"]
    except (KeyError, IndexError) as e:
        raise AIError(f"unexpected response: {str(data)[:200]}") from e
    return out.replace("<keep>", "").replace("</keep>", "")
