"""AI completions for the {#ai} and {#translate} macros.

Providers: openai, anthropic, ollama, openrouter. Keys and defaults come from
the settings table (see db.DEFAULT_SETTINGS: ai.provider, ai.model, ai.*_key,
ai.ollama_url).
"""
from __future__ import annotations

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
    try:
        r = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    except httpx.HTTPError as e:
        raise AIError(str(e)) from e
    if r.status_code >= 400:
        raise AIError(f"HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def _messages(prompt: str, system: str) -> list[dict]:
    msgs = [{"role": "system", "content": system}] if system else []
    return msgs + [{"role": "user", "content": prompt}]


def complete(settings: dict[str, str], prompt: str, provider: str = "", model: str = "", system: str = "",
             timeout_s: float = 120, max_tokens: int = 1024) -> str:
    provider = (provider or settings.get("ai.provider") or "openai").lower()
    if provider not in DEFAULT_MODELS:
        raise AIError(f"unknown AI provider '{provider}'")
    same_provider = (settings.get("ai.provider") or "openai").lower() == provider
    model = model or (settings.get("ai.model") if same_provider else "") or DEFAULT_MODELS[provider]

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
