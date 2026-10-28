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
    "gemini": "gemini-2.5-flash",
    "opencode": "",          # OpenCode Zen and Kilo Code serve many models: the user picks one
    "kilocode": "",
}

# Cloud services that speak the OpenAI chat-completions format: base URL (can be changed with
# the setting ai.<provider>_base_url) and where to get a key.
OPENAI_COMPATIBLE = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    # https://ai.google.dev/gemini-api/docs/openai
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    # https://opencode.ai/docs/zen (chat/completions serves the non-GPT, non-Claude models)
    "opencode": "https://opencode.ai/zen/v1",
    # Kilo Gateway (OpenAI-compatible); the address can be changed in Settings if Kilo moves it
    "kilocode": "https://api.kilo.ai/api/gateway",
}
PROVIDER_NAMES = {"openai": "OpenAI", "anthropic": "Anthropic", "openrouter": "OpenRouter", "gemini": "Gemini",
                  "opencode": "OpenCode Zen", "kilocode": "Kilo Code", "deepl": "DeepL",
                  "ollama": "Ollama", "gpt4all": "GPT4All"}


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


def _with_system(history: list[dict], system: str) -> list[dict]:
    return ([{"role": "system", "content": system}] if system else []) + history


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
    """One prompt, one answer. raw_system=True skips the user's custom instructions (used by
    translation)."""
    return chat(settings, [{"role": "user", "content": prompt}], provider, model, system,
                timeout_s, max_tokens, raw_system)


def chat(settings: dict[str, str], history: list[dict], provider: str = "", model: str = "", system: str = "",
         timeout_s: float = 120, max_tokens: int = 1024, raw_system: bool = False) -> str:
    """A conversation: history is [{"role": "user"|"assistant", "content": "..."}, ...]
    (oldest first, ending with the user's turn). Returns the assistant's reply."""
    history = [{"role": m["role"], "content": m["content"]} for m in history
               if m.get("role") in ("user", "assistant")]
    if not history or history[-1]["role"] != "user":
        raise AIError("The conversation must end with a user message.")
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
        payload = {"model": model, "max_tokens": max_tokens, "messages": history}
        if system:
            payload["system"] = system
        data = _post("https://api.anthropic.com/v1/messages",
                     {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                     payload, timeout_s)
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")

    if provider == "gpt4all":
        base = (settings.get("ai.gpt4all_url") or "http://localhost:4891/v1").rstrip("/")
        data = _post(f"{base}/chat/completions", {}, {"model": model, "max_tokens": max_tokens,
                                                      "messages": _with_system(history, system)}, timeout_s)
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as e:
            raise AIError(f"unexpected response: {str(data)[:200]}") from e

    if provider == "ollama":
        base = (settings.get("ai.ollama_url") or "http://localhost:11434").rstrip("/")
        data = _post(f"{base}/api/chat", {}, {"model": model, "stream": False,
                                               "messages": _with_system(history, system)}, timeout_s)
        return data.get("message", {}).get("content", "")

    name = PROVIDER_NAMES.get(provider, provider)
    key = (settings.get(f"ai.{provider}_key") or "").strip()
    base = (settings.get(f"ai.{provider}_base_url") or OPENAI_COMPATIBLE[provider]).rstrip("/")
    url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    if not key:
        raise AIError(f"{name} API key is not set (Settings > AI)")
    if not model:
        raise AIError(f"Enter the model to use with {name} in Settings > AI > Model.")
    data = _post(url, {"Authorization": f"Bearer {key}"},
                 {"model": model, "messages": _with_system(history, system)}, timeout_s)
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


# ---------------------------------------------------------------- free translation (no key)
# MyMemory's public API (https://mymemory.translated.net/doc/spec.php): GET /get?q=&langpair=src|dst.
# Used when no translation key is set, so "Translate" works out of the box. Each request takes
# at most 500 bytes of text, and anonymous use has a daily limit.
MYMEMORY_URL = "https://api.mymemory.translated.net/get"
ISO_CODES = {
    "arabic": "ar", "english": "en", "french": "fr", "german": "de", "spanish": "es", "italian": "it",
    "portuguese": "pt", "russian": "ru", "turkish": "tr", "dutch": "nl", "polish": "pl", "swedish": "sv",
    "danish": "da", "norwegian": "no", "finnish": "fi", "czech": "cs", "greek": "el", "hungarian": "hu",
    "romanian": "ro", "bulgarian": "bg", "ukrainian": "uk", "chinese": "zh-CN", "japanese": "ja",
    "korean": "ko", "hindi": "hi", "hebrew": "he", "persian": "fa", "urdu": "ur", "indonesian": "id",
    "malay": "ms", "vietnamese": "vi", "thai": "th",
}


def iso_code(lang: str) -> str:
    lang = (lang or "").strip()
    return ISO_CODES.get(lang.lower(), lang.lower())


def guess_language(text: str) -> str:
    """'ar' when the text is mostly Arabic letters, else 'en' (MyMemory needs a source language)."""
    letters = [c for c in text if c.isalpha()]
    arabic = sum(1 for c in letters if "؀" <= c <= "ۿ" or "ݐ" <= c <= "ݿ")
    return "ar" if letters and arabic * 2 >= len(letters) else "en"


def _chunks(text: str, limit: int = 450) -> list[str]:
    """Split text into pieces of at most `limit` UTF-8 bytes, at line, sentence or word ends."""
    import re
    out: list[str] = []
    for part in re.split(r"(?<=[.!?؟\n])\s*", text):
        if not part:
            continue
        while len(part.encode("utf-8")) > limit:
            cut = part[:limit]
            while len(cut.encode("utf-8")) > limit:
                cut = cut[:-1]
            space = cut.rfind(" ")
            if space > len(cut) // 2:
                cut = cut[:space]
            out.append(cut)
            part = part[len(cut):].lstrip()
        if out and len((out[-1] + " " + part).encode("utf-8")) <= limit and not out[-1].endswith("\n"):
            out[-1] = out[-1] + " " + part
        else:
            out.append(part)
    return out


def free_translate(text: str, to: str, src: str = "", timeout_s: float = 20, get=None) -> str:
    """Translate with MyMemory (no key). get: test hook (url, params) -> JSON dict."""
    if not text.strip():
        return text
    dst = iso_code(to) or "en"
    source = iso_code(src) if src else guess_language(text)
    if source.split("-")[0] == dst.split("-")[0]:
        return text

    def _get(url, params):
        from phraseforge.net import client_kwargs
        try:
            with httpx.Client(timeout=timeout_s, **client_kwargs()) as c:
                r = c.get(url, params=params)
        except httpx.HTTPError as e:
            raise AIError(f"Translation service unreachable: {e}") from e
        if r.status_code >= 400:
            raise AIError(f"Translation service: HTTP {r.status_code}")
        return r.json()
    get = get or _get
    out = []
    for piece in _chunks(text):
        if not piece.strip():
            out.append(piece)
            continue
        data = get(MYMEMORY_URL, {"q": piece, "langpair": f"{source}|{dst}"})
        status = str(data.get("responseStatus", ""))
        translated = (data.get("responseData") or {}).get("translatedText") or ""
        if status != "200" or not translated:
            detail = data.get("responseDetails") or translated or status
            raise AIError(f"Translation service: {detail}")
        out.append(translated)
    return " ".join(p.strip() for p in out) if "\n" not in text else "\n".join(p.strip() for p in out)


def translate_text(settings: dict[str, str], text: str, to: str, src: str = "", complete_fn=None,
                   free_fn=None) -> str:
    """Translate with the engine chosen in Settings > Language Translation; without a key for
    it (or with "free"), use the free service. Macros like {#date} are kept as they are: only
    the text between them is translated."""
    import re
    provider = (settings.get("translation.provider") or "free").lower()
    has_key = provider in ("ollama", "gpt4all") or bool((settings.get(f"ai.{provider}_key", "") or "").strip())
    if provider == "deepl" and has_key:
        def one(t):
            return deepl_translate(settings, t, to, src)
    elif provider not in ("free", "deepl") and has_key:
        system = translation_system(settings, to, src)

        def one(t):
            return (complete_fn or (lambda x: complete(settings, x, provider, "", system, raw_system=True)))(t)
    else:
        source = src or guess_language(text)       # one source language for the whole phrase

        def one(t):
            return (free_fn or free_translate)(t, to, source)
    out = []
    for i, part in enumerate(re.split(r"(\{[^{}]*\})", text)):
        if i % 2 or not part.strip():
            out.append(part)                        # a macro, or only spaces / line breaks
            continue
        lead = part[:len(part) - len(part.lstrip())]
        trail = part[len(part.rstrip()):]
        out.append(lead + one(part.strip()).strip() + trail)
    return "".join(out)


# ---------------------------------------------------------------- "Enhance prompt"
ENHANCE_SYSTEM = (
    "You improve prompts written for AI assistants. Rewrite the user's prompt so it is clear, "
    "specific and complete: state the goal, the context, the constraints and the expected output "
    "format. Keep the user's language (answer in Arabic if the prompt is Arabic) and keep their "
    "intent. Keep every placeholder or macro in curly braces, such as {#clipboard} or {#input}, "
    "exactly as written. Reply with the improved prompt only, without explanations or quotes.")


def enhance_prompt(settings: dict[str, str], text: str, complete_fn=None) -> str:
    """Rewrite a prompt so it works better, with the AI engine from Settings > AI."""
    if not (text or "").strip():
        raise AIError("Write a prompt first.")
    fn = complete_fn or (lambda t: complete(settings, t, system=ENHANCE_SYSTEM, raw_system=True))
    out = (fn(text) or "").strip()
    if len(out) > 1 and out[0] == out[-1] and out[0] in "\"'`":
        out = out[1:-1].strip()
    if not out:
        raise AIError("The AI engine returned nothing.")
    return out


# ---------------------------------------------------------------- "Boost prompt" (PromptBoost)
# Instruction from the PromptBoost VS Code extension by Chris Dias
# (https://github.com/chrisdias/vscode-promptboost, MIT License, Copyright (c) 2025 Chris Dias),
# see THIRD_PARTY_NOTICES.md. PhraseForge adds the line about {#macros}.
BOOST_INSTRUCTION = """You are a professional prompt engineer specializing in crafting precise, effective prompts.
Your task is to enhance prompts by making them more specific, actionable, and effective.

**Formatting Requirements:**
- Use Markdown formatting in your response.
- Present requirements, constraints, and steps as bulleted or numbered lists.
- Separate context, instructions, and examples into clear paragraphs.
- Use headings if appropriate.
- Ensure the prompt is easy to read and visually organized.

**Instructions:**
- Improve the user prompt wrapped in `<original_prompt>` tags.
- Make instructions explicit and unambiguous.
- Add relevant context and constraints.
- Remove redundant information.
- Maintain the core intent.
- Ensure the prompt is self-contained.
- Use professional language.
- Add references to documentation or examples if applicable.
- Keep the language of the original prompt, and keep every placeholder in curly braces, such as {#clipboard}, exactly as written.

**For invalid or unclear prompts:**
- Respond with clear, professional guidance.
- Keep responses concise and actionable.
- Maintain a helpful, constructive tone.
- Focus on what the user should provide.
- Use a standard template for consistency.

**IMPORTANT:**
Your response must ONLY contain the enhanced prompt text, formatted as described.
Do not include any explanations, metadata, or wrapper tags.

<original_prompt>
{prompt}
</original_prompt>
"""


def boost_prompt(settings: dict[str, str], text: str, complete_fn=None) -> str:
    """PromptBoost: turn a short prompt into a structured (Markdown) one with the AI engine
    from Settings > AI. Raises AIError when it cannot (the caller keeps the original)."""
    if not (text or "").strip():
        raise AIError("Write a prompt first.")
    message = BOOST_INSTRUCTION.replace("{prompt}", text.strip())
    fn = complete_fn or (lambda m: complete(settings, m, raw_system=True))
    out = (fn(message) or "").strip()
    out = out.removeprefix("<original_prompt>").removesuffix("</original_prompt>").strip()
    if out.startswith("```") and out.endswith("```"):
        out = out.split("\n", 1)[1].rsplit("```", 1)[0].strip() if "\n" in out else out
    if not out:
        raise AIError("The AI engine returned nothing.")
    return out
