"""AI completions for the {#ai} and {#translate} macros.

Providers: openai, anthropic, ollama, openrouter. Keys and defaults come from
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


def preset_prompt(settings: dict[str, str], name: str) -> str:
    for p in presets(settings):
        if p["name"].strip().lower() == (name or "").strip().lower():
            return str(p.get("prompt", ""))
    raise AIError(f"AI preset '{name}' not found (Settings > AI text processing > Custom presets)")


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
