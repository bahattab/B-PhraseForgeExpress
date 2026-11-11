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

import base64
import json
import logging
import threading
import time

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


log = logging.getLogger(__name__)

class AIError(RuntimeError):
    pass


# ---------------------------------------------------------------- capabilities and usage
# Providers whose chat API accepts images (the chosen model must support them too; the
# service answers with an error otherwise). GPT4All's local server has no image input.
VISION_PROVIDERS = {"openai", "anthropic", "openrouter", "gemini", "ollama", "opencode", "kilocode"}
IMAGE_PROVIDERS = {"openai": "gpt-image-1", "gemini": "imagen-4.0-generate-001", "openrouter": ""}

# Called after each answer with (provider, model, input_tokens, output_tokens, images=0). The app sets it
# to add the numbers to the ai.usage setting; tests replace it.
USAGE_HOOK = None
USAGE_LOCK = threading.Lock()          # held while ai.usage is read and written back


def capabilities(provider: str) -> dict:
    provider = (provider or "").lower()
    if provider.startswith("plugin:"):
        from phraseforge.plugins import engines
        eng = engines.engine(provider)
        try:
            caps = eng.capabilities() if eng is not None else {}
        except Exception:     # noqa: BLE001 - a broken plugin has no capabilities
            caps = {}
        return {"vision": bool(caps.get("vision")), "image": bool(caps.get("image_gen")),
                "models": bool(caps.get("model_management"))}
    return {"vision": provider in VISION_PROVIDERS, "image": provider in IMAGE_PROVIDERS,
            "models": provider == "ollama"}


def _record(provider: str, model: str, data: dict, images: int = 0) -> None:
    u = data.get("usage") or {}
    inp = u.get("input_tokens", u.get("prompt_tokens", data.get("prompt_eval_count", 0))) or 0
    out = u.get("output_tokens", u.get("completion_tokens", data.get("eval_count", 0))) or 0
    if USAGE_HOOK is not None:
        try:
            USAGE_HOOK(provider, model, int(inp), int(out), images)
        except Exception:     # noqa: BLE001 - counting must never break an answer
            pass


def add_usage(stored: str, provider: str, model: str, inp: int, out: int, images: int = 0) -> str:
    """Adds one request to the JSON kept in the ai.usage setting:
    {"provider/model": {"requests": n, "input": n, "output": n, "images": n}, "since": "YYYY-MM-DD"}."""
    try:
        data = json.loads(stored or "{}")
        if not isinstance(data, dict):
            data = {}
    except ValueError:
        data = {}
    data.setdefault("since", time.strftime("%Y-%m-%d"))
    row = data.setdefault(f"{provider}/{model}" if model else provider, {})
    for k, v in (("requests", 1), ("input", inp), ("output", out), ("images", images)):
        row[k] = int(row.get(k, 0)) + int(v)
    return json.dumps(data)


def usage_rows(stored: str) -> list[tuple[str, int, int, int, int]]:
    """[(provider/model, requests, input tokens, output tokens, images)] sorted by requests."""
    try:
        data = json.loads(stored or "{}")
    except ValueError:
        return []
    rows = [(k, int(v.get("requests", 0)), int(v.get("input", 0)), int(v.get("output", 0)), int(v.get("images", 0)))
            for k, v in (data.items() if isinstance(data, dict) else []) if isinstance(v, dict)]
    return sorted(rows, key=lambda r: (-r[1], r[0]))


def image_mime(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"GIF8":
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise AIError("only PNG, JPEG, GIF and WebP images can be sent to an AI engine")


def _with_images(history: list[dict], images: list[bytes], provider: str) -> list[dict]:
    """Attach images to the last user message in the provider's format."""
    if not images:
        return history
    last = dict(history[-1])
    text = last["content"]
    for b in images:        # checked for every engine: Ollama got any local file (security R113)
        image_mime(b)
    if provider == "ollama":
        last["images"] = [base64.b64encode(b).decode() for b in images]
    elif provider == "anthropic":
        last["content"] = [{"type": "image", "source": {"type": "base64", "media_type": image_mime(b),
                                                        "data": base64.b64encode(b).decode()}} for b in images] \
            + [{"type": "text", "text": text}]
    else:                                                # OpenAI chat-completions format
        last["content"] = [{"type": "text", "text": text}] + [
            {"type": "image_url", "image_url": {"url": f"data:{image_mime(b)};base64,{base64.b64encode(b).decode()}"}}
            for b in images]
    return history[:-1] + [last]


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


MAX_STREAM_CHARS = 4 * 1024 * 1024      # a streamed reply longer than this is cut off


def _stream_lines(url: str, headers: dict, payload: dict, timeout: float):
    """POST and yield the response's lines as they arrive (SSE or NDJSON)."""
    from phraseforge.net import client_kwargs
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=min(timeout, 15)), **client_kwargs()) as c, \
                c.stream("POST", url, headers=headers, json=payload) as r:
            if r.status_code >= 400:
                r.read()
                raise AIError(f"HTTP {r.status_code}: {r.text[:300]}")
            yield from r.iter_lines()
    except httpx.HTTPError as e:
        raise AIError(str(e)) from e


def _sse_events(lines):
    """JSON objects from Server-Sent Events "data: {...}" lines; stops at "data: [DONE]"."""
    for line in lines:
        if not line.startswith("data:"):
            continue
        body = line[5:].strip()
        if body == "[DONE]":
            return
        try:
            obj = json.loads(body)
        except ValueError:
            continue
        if isinstance(obj, dict):
            yield obj


class _Collector:
    """Keeps the streamed text, passes each piece on, never lets the display break the call."""

    def __init__(self, on_delta):
        self.on_delta = on_delta
        self.parts: list[str] = []
        self.size = 0

    def add(self, piece) -> None:
        if not isinstance(piece, str) or not piece:
            return
        self.size += len(piece)
        if self.size > MAX_STREAM_CHARS:
            raise AIError("the reply is too long")
        self.parts.append(piece)
        try:
            self.on_delta(piece)
        except Exception:      # noqa: BLE001 - a closed window must not end the answer
            pass

    @property
    def text(self) -> str:
        return "".join(self.parts)


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
             timeout_s: float = 120, max_tokens: int = 1024, raw_system: bool = False,
             images: list[bytes] | None = None) -> str:
    """One prompt, one answer. raw_system=True skips the user's custom instructions (used by
    translation). images: PNG/JPEG/GIF/WebP bytes sent with the prompt (vision)."""
    return chat(settings, [{"role": "user", "content": prompt}], provider, model, system,
                timeout_s, max_tokens, raw_system, images)


def chat(settings: dict[str, str], history: list[dict], provider: str = "", model: str = "", system: str = "",
         timeout_s: float = 120, max_tokens: int = 1024, raw_system: bool = False,
         images: list[bytes] | None = None, on_delta=None) -> str:
    """A conversation: history is [{"role": "user"|"assistant", "content": "..."}, ...]
    (oldest first, ending with the user's turn). Returns the assistant's reply.
    on_delta(text): called with each piece of the reply as it is written: plugin engines ($/progress),
    OpenAI-compatible services, Anthropic and Ollama stream; GPT4All answers in one piece and does
    not call it."""
    history = [{"role": m["role"], "content": m["content"]} for m in history
               if m.get("role") in ("user", "assistant")]
    if not history or history[-1]["role"] != "user":
        raise AIError("The conversation must end with a user message.")
    provider = (provider or settings.get("ai.provider") or "openai").lower()
    if images and not capabilities(provider)["vision"]:
        raise AIError("engine has no vision")
    if provider.startswith("plugin:"):                  # an AI engine from a plugin (plugins/engines.py)
        from phraseforge.plugins import engines
        eng = engines.engine(provider)
        if eng is None or eng.kind != "ai_engine":
            raise AIError(f"the AI plugin '{provider[7:]}' is not installed or switched off")
        if images:
            history = _with_images(history, images, "openai")
        return eng.generate(settings, history, {"model": model, "max_tokens": max_tokens, "timeout": timeout_s,
                                                "on_delta": on_delta,
                                                "system": system if raw_system else full_system(settings, system)})
    if provider not in DEFAULT_MODELS:
        raise AIError(f"unknown AI provider '{provider}'")
    same_provider = (settings.get("ai.provider") or "openai").lower() == provider
    model = model or (settings.get("ai.model") if same_provider else "") or DEFAULT_MODELS[provider]
    if not raw_system:
        system = full_system(settings, system)
    history = _with_images(history, images or [], provider)

    if provider == "anthropic":
        key = settings.get("ai.anthropic_key", "")
        if not key:
            raise AIError("Anthropic API key is not set (Settings > AI)")
        payload = {"model": model, "max_tokens": max_tokens, "messages": history}
        if system:
            payload["system"] = system
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        if on_delta is not None:          # https://docs.anthropic.com/en/api/messages-streaming
            out, usage = _Collector(on_delta), {}
            for ev in _sse_events(_stream_lines("https://api.anthropic.com/v1/messages", headers,
                                                dict(payload, stream=True), timeout_s)):
                kind = ev.get("type")
                if kind == "content_block_delta" and (ev.get("delta") or {}).get("type") == "text_delta":
                    out.add(ev["delta"].get("text"))
                elif kind == "message_start":
                    usage.update(((ev.get("message") or {}).get("usage")) or {})
                elif kind == "message_delta":
                    usage.update(ev.get("usage") or {})
                elif kind == "error":
                    raise AIError(str((ev.get("error") or {}).get("message", ev))[:300])
            _record(provider, model, {"usage": usage}, len(images or []))
            return out.text
        data = _post("https://api.anthropic.com/v1/messages", headers, payload, timeout_s)
        _record(provider, model, data, len(images or []))
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")

    if provider == "gpt4all":
        base = (settings.get("ai.gpt4all_url") or "http://localhost:4891/v1").rstrip("/")
        data = _post(f"{base}/chat/completions", {}, {"model": model, "max_tokens": max_tokens,
                                                      "messages": _with_system(history, system)}, timeout_s)
        _record(provider, model, data, len(images or []))
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as e:
            raise AIError(f"unexpected response: {str(data)[:200]}") from e

    if provider == "ollama":
        base = (settings.get("ai.ollama_url") or "http://localhost:11434").rstrip("/")
        if on_delta is not None:          # NDJSON: one {"message": {"content": ...}} per line, then done
            out, last = _Collector(on_delta), {}
            for line in _stream_lines(f"{base}/api/chat", {}, {"model": model, "stream": True,
                                                              "messages": _with_system(history, system)}, timeout_s):
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(msg, dict):
                    continue
                if msg.get("error"):
                    raise AIError(str(msg["error"])[:300])
                out.add((msg.get("message") or {}).get("content"))
                if msg.get("done"):
                    last = msg
                    break
            _record(provider, model, last, len(images or []))
            return out.text
        data = _post(f"{base}/api/chat", {}, {"model": model, "stream": False,
                                               "messages": _with_system(history, system)}, timeout_s)
        _record(provider, model, data, len(images or []))
        return data.get("message", {}).get("content", "")

    name = PROVIDER_NAMES.get(provider, provider)
    key = (settings.get(f"ai.{provider}_key") or "").strip()
    base = (settings.get(f"ai.{provider}_base_url") or OPENAI_COMPATIBLE[provider]).rstrip("/")
    url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    if not key:
        raise AIError(f"{name} API key is not set (Settings > AI)")
    if not model:
        raise AIError(f"Enter the model to use with {name} in Settings > AI > Model.")
    if on_delta is not None:              # OpenAI-style SSE: choices[0].delta.content per event
        out, usage = _Collector(on_delta), {}
        payload = {"model": model, "messages": _with_system(history, system), "stream": True}
        if provider == "openai":
            payload["stream_options"] = {"include_usage": True}
        for ev in _sse_events(_stream_lines(url, {"Authorization": f"Bearer {key}"}, payload, timeout_s)):
            if ev.get("error"):
                err = ev["error"]
                raise AIError(str(err.get("message", err) if isinstance(err, dict) else err)[:300])
            for ch in ev.get("choices") or []:
                if isinstance(ch, dict):
                    out.add((ch.get("delta") or {}).get("content"))
            if isinstance(ev.get("usage"), dict):
                usage = ev["usage"]
        _record(provider, model, {"usage": usage}, len(images or []))
        return out.text
    data = _post(url, {"Authorization": f"Bearer {key}"},
                 {"model": model, "messages": _with_system(history, system)}, timeout_s)
    _record(provider, model, data, len(images or []))
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError) as e:
        raise AIError(f"unexpected response: {str(data)[:200]}") from e


# ---------------------------------------------------------------- image generation
def generate_image(settings: dict[str, str], prompt: str, provider: str = "", model: str = "",
                   size: str = "1024x1024", timeout_s: float = 180) -> bytes:
    """Image bytes for a text prompt ({#aiimage}). Uses the OpenAI images API format, which
    OpenAI and Gemini (OpenAI compatibility) serve; Settings > AI > Image engine picks one."""
    provider = (provider or settings.get("ai.image_provider") or settings.get("ai.provider") or "openai").lower()
    if provider.startswith("plugin:"):                  # an image engine from a plugin (plugins/engines.py)
        if not prompt.strip():
            raise AIError("describe the image to make")
        from phraseforge.plugins import engines
        eng = engines.engine(provider)
        if eng is None or eng.kind != "ai_engine":
            raise AIError(f"the AI plugin '{provider[7:]}' is not installed or switched off")
        return eng.generate_image(settings, prompt, model or settings.get("ai.image_model", ""), size or "1024x1024")
    if provider not in IMAGE_PROVIDERS or provider == "openrouter":
        raise AIError(f"{PROVIDER_NAMES.get(provider, provider)} cannot make images; choose OpenAI or Gemini "
                      "as the image engine in Settings > AI")
    if not prompt.strip():
        raise AIError("describe the image to make")
    size = (size or "1024x1024").lower()
    w, _, h = size.partition("x")
    if not (w.isdigit() and h.isdigit()):
        raise AIError(f"image size must look like 1024x1024, not '{size}'")
    key = (settings.get(f"ai.{provider}_key") or "").strip()
    if not key:
        raise AIError(f"{PROVIDER_NAMES[provider]} API key is not set (Settings > AI)")
    model = model or settings.get("ai.image_model") or IMAGE_PROVIDERS[provider]
    base = (settings.get(f"ai.{provider}_base_url") or OPENAI_COMPATIBLE[provider]).rstrip("/")
    payload = {"model": model, "prompt": prompt, "n": 1, "size": size}
    if provider == "gemini" or model.startswith("dall-e"):
        payload["response_format"] = "b64_json"          # gpt-image-* always answer in base64
    data = _post(f"{base}/images/generations", {"Authorization": f"Bearer {key}"}, payload, timeout_s)
    try:
        b64 = data["data"][0]["b64_json"]
    except (KeyError, IndexError, TypeError) as e:
        raise AIError(f"unexpected response: {str(data)[:200]}") from e
    if USAGE_HOOK is not None:
        try:
            USAGE_HOOK(provider, model, 0, 0, 1)
        except Exception:     # noqa: BLE001
            pass
    try:
        return base64.b64decode(b64)
    except ValueError as e:
        raise AIError("the image engine sent an image that could not be read") from e


# ---------------------------------------------------------------- model downloads
def pull_model(settings: dict[str, str], provider: str, model: str, progress=None, cancelled=lambda: False) -> None:
    """Download a model with Ollama or a plugin engine that has model_management.
    progress(status, done, total); a plugin reports status text only (done = total = 0) and
    cannot be cancelled once started."""
    provider = (provider or "").lower()
    if provider.startswith("plugin:"):
        from phraseforge.plugins import engines
        eng = engines.engine(provider)
        if eng is None or eng.kind != "ai_engine":
            raise AIError(f"the AI plugin '{provider[7:]}' is not installed or switched off")
        if not model.strip() or any(c.isspace() for c in model.strip()):
            raise AIError("type a model name without spaces")
        eng.pull_model(settings, model.strip(), (lambda st: progress(st, 0, 0)) if progress else None)
        return
    ollama_pull(settings, model, progress, cancelled)


# ---------------------------------------------------------------- Ollama model downloads
def _ollama_base(settings: dict[str, str]) -> str:
    return (settings.get("ai.ollama_url") or "http://localhost:11434").rstrip("/")


def ollama_models(settings: dict[str, str], timeout_s: float = 10) -> list[str]:
    """Names of the models the Ollama server already has."""
    from phraseforge.net import client_kwargs
    try:
        with httpx.Client(timeout=timeout_s, **client_kwargs()) as c:
            r = c.get(f"{_ollama_base(settings)}/api/tags")
    except httpx.HTTPError as e:
        raise AIError(str(e)) from e
    if r.status_code >= 400:
        raise AIError(f"HTTP {r.status_code}: {r.text[:300]}")
    try:
        models = r.json().get("models", [])
        return sorted(str(m["name"]) for m in models if isinstance(m, dict) and m.get("name"))
    except (ValueError, AttributeError, TypeError) as e:     # not Ollama's JSON (R117)
        raise AIError("the server did not answer like Ollama") from e


def _count(v) -> int:
    """A byte count from Ollama's progress line; anything else is 0 (R116)."""
    try:
        return max(0, int(v or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def ollama_pull(settings: dict[str, str], model: str, progress=None, cancelled=lambda: False,
                timeout_s: float = 3600) -> None:
    """Download a model into Ollama. progress(status, done_bytes, total_bytes) is called for each
    line Ollama streams; cancelled() returning True stops the download."""
    model = (model or "").strip()
    if not model or any(c.isspace() for c in model):
        raise AIError("enter a model name such as llama3.2 or qwen2.5:7b")
    from phraseforge.net import client_kwargs
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout_s, connect=10), **client_kwargs()) as c, \
                c.stream("POST", f"{_ollama_base(settings)}/api/pull", json={"model": model, "stream": True}) as r:
            if r.status_code >= 400:
                r.read()
                raise AIError(f"HTTP {r.status_code}: {r.text[:300]}")
            for line in r.iter_lines():
                if cancelled():
                    raise AIError("download cancelled")
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(msg, dict):
                    continue
                if msg.get("error"):
                    raise AIError(str(msg["error"]))
                if progress:
                    progress(str(msg.get("status", "")), _count(msg.get("completed")), _count(msg.get("total")))
                if msg.get("status") == "success":
                    return
    except httpx.HTTPError as e:
        raise AIError(str(e)) from e
    raise AIError("Ollama stopped before the download finished")


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


GLOSSARY_PREFIX = "PhraseForge: "


def _deepl_call(method: str, url: str, key: str, payload: dict | None = None, timeout: float = 30) -> dict:
    from phraseforge.net import client_kwargs
    try:
        with httpx.Client(timeout=timeout, **client_kwargs()) as c:
            r = c.request(method, url, headers={"Authorization": f"DeepL-Auth-Key {key}"}, json=payload)
    except httpx.HTTPError as e:
        raise AIError(str(e)) from e
    if r.status_code >= 400:
        raise AIError(f"DeepL HTTP {r.status_code}: {r.text[:300]}")
    if not r.content:
        return {}
    try:
        data = r.json()
    except ValueError as e:                  # a proxy or portal page, not DeepL (R128)
        raise AIError("DeepL did not answer with JSON (a proxy or sign-in page?)") from e
    if not isinstance(data, dict):
        raise AIError(f"unexpected response: {str(data)[:200]}")
    return data


# Glossaries already on DeepL, and uploads DeepL refused, in this run of PhraseForge:
# (key hash, server name) -> (glossary_id, time) / time. A {#loop} of translations then makes
# no glossary requests at all, and a glossary DeepL rejects is not sent again (R126, R129).
_GLOSSARY_IDS: dict = {}
_GLOSSARY_REFUSED: dict = {}
GLOSSARY_CACHE_S = 600


def glossary_entries(text: str) -> list[tuple[str, str]]:
    """Word=Translation lines of a glossary (DeepL takes each source term once; no tabs)."""
    seen, out = set(), []
    for line in (text or "").splitlines():
        a, sep, b = line.partition("=")
        a, b = a.strip(), b.strip()
        if sep and a and b and "\t" not in a + b and a not in seen:
            seen.add(a)
            out.append((a, b))
    return out


def _deepl_glossary_for(settings: dict[str, str], to: str, src: str, name: str) -> tuple[str, str] | None:
    """(glossary name, source language) to use for this translation, or None. A glossary is sent
    to DeepL only when its languages are set (Settings > Glossaries) and match, or when named."""
    try:
        gl = json.loads(settings.get("translation.glossaries") or "{}")
    except ValueError:
        return None
    if not isinstance(gl, dict):
        return None
    langs = glossary_langs(settings)
    target = deepl_code(to).split("-")[0].lower()
    for n in ([name] if name else list(gl)):
        if n not in gl or n not in langs or not glossary_entries(str(gl[n])):
            continue
        g_src, g_to = (deepl_code(x).split("-")[0].lower() for x in langs[n])
        if g_to == target and (not src or deepl_code(src).split("-")[0].lower() == g_src):
            return n, g_src
    return None


def _forget_glossary(gid: str) -> bool:
    """Drop a cached glossary id (the translation using it failed); True if one was cached."""
    gone = [k for k, v in _GLOSSARY_IDS.items() if v[0] == gid]
    for k in gone:
        del _GLOSSARY_IDS[k]
    return bool(gone)


def sync_deepl_glossary(settings: dict[str, str], name: str, timeout_s: float = 30) -> str:
    """Make sure DeepL has this glossary as written in Settings; returns its glossary_id.
    DeepL glossaries cannot be edited, so a changed glossary is uploaded again and the old
    copy deleted. The server copy is named "PhraseForge: <name> #<hash>" so no local state is kept."""
    import hashlib
    key = (settings.get("ai.deepl_key") or "").strip()
    if not key:
        raise AIError("DeepL API key is not set (Settings > Language Translation)")
    base = f"https://{'api-free.deepl.com' if key.endswith(':fx') else 'api.deepl.com'}/v2/glossaries"
    gl = json.loads(settings.get("translation.glossaries") or "{}")
    langs = glossary_langs(settings)
    if name not in gl or name not in langs:
        raise AIError(f"glossary '{name}' needs its source and target languages set (Settings > Glossaries)")
    src, to = (deepl_code(x).split("-")[0].lower() for x in langs[name])
    entries = glossary_entries(str(gl[name]))
    if not entries:
        raise AIError(f"glossary '{name}' has no Word=Translation lines")
    tsv = "\n".join(f"{a}\t{b}" for a, b in entries)
    digest = hashlib.sha256(f"{src}|{to}|{tsv}".encode()).hexdigest()[:10]
    wanted = f"{GLOSSARY_PREFIX}{name} #{digest}"
    import re
    import time as _time
    slot = (hashlib.sha256(key.encode()).hexdigest()[:16], wanted)
    now = _time.monotonic()
    hit = _GLOSSARY_IDS.get(slot)
    if hit and now - hit[1] < GLOSSARY_CACHE_S:
        return hit[0]
    if now - _GLOSSARY_REFUSED.get(slot, -1e9) < GLOSSARY_CACHE_S:
        raise AIError(f"DeepL refused glossary '{name}' (fix its lines in Settings > Glossaries)")
    own = re.compile(re.escape(f"{GLOSSARY_PREFIX}{name} #") + r"[0-9a-f]{10}")   # exactly this glossary (R126)
    listed = _deepl_call("GET", base, key, timeout=timeout_s).get("glossaries")
    if not isinstance(listed, list):
        raise AIError("unexpected response from DeepL's glossary list")
    found, preparing = "", False
    for g in listed:
        if not isinstance(g, dict):
            continue
        gname = str(g.get("name", ""))
        if gname == wanted:                               # never delete the copy we want (R127)
            if g.get("ready", True):
                found = found or str(g.get("glossary_id", ""))
            else:
                preparing = True
        elif own.fullmatch(gname):
            try:                                          # an older copy of this glossary
                _deepl_call("DELETE", f"{base}/{g.get('glossary_id', '')}", key, timeout=timeout_s)
            except AIError:
                pass
    if found:
        _GLOSSARY_IDS[slot] = (found, now)
        return found
    if preparing:
        raise AIError(f"DeepL is still preparing glossary '{name}'; try again in a moment")
    try:
        made = _deepl_call("POST", base, key, {"name": wanted, "source_lang": src, "target_lang": to,
                                              "entries": tsv, "entries_format": "tsv"}, timeout_s)
    except AIError as e:
        if any(f"HTTP {c}" in str(e) for c in (400, 413, 422)):   # the glossary itself was refused (R129)
            _GLOSSARY_REFUSED[slot] = now
            log.warning("DeepL refused glossary %r", name)
        raise
    gid = str(made.get("glossary_id", ""))
    if not gid:
        raise AIError(f"unexpected response: {str(made)[:200]}")
    _GLOSSARY_IDS[slot] = (gid, now)
    return gid


def deepl_translate(settings: dict[str, str], text: str, to: str, src: str = "", timeout_s: float = 60,
                    glossary: str = "") -> str:
    """Translate with the DeepL API (Free keys end in ':fx'). Ignored words are wrapped in
    <keep> tags that DeepL leaves untranslated. A matching glossary from Settings > Glossaries
    is uploaded to DeepL (sync_deepl_glossary) and used; DeepL takes one glossary per request."""
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
    use = _deepl_glossary_for(settings, to, src, glossary)
    if use is not None:
        try:
            payload["glossary_id"] = sync_deepl_glossary(settings, use[0], timeout_s)
            payload["source_lang"] = use[1].upper()       # DeepL needs the source with a glossary
        except AIError:
            if glossary:                                  # asked for by name: say why it failed
                raise
    elif glossary:
        raise AIError(f"glossary '{glossary}' does not fit this translation: set its languages in "
                      "Settings > Glossaries")
    try:
        data = _post(f"https://{host}/v2/translate", {"Authorization": f"DeepL-Auth-Key {key}"}, payload, timeout_s)
    except AIError:
        gid = payload.get("glossary_id")
        if not gid or not _forget_glossary(gid):
            raise
        payload["glossary_id"] = sync_deepl_glossary(settings, use[0], timeout_s)   # deleted on DeepL's site?
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
    plugin = None
    if provider.startswith("plugin:"):
        from phraseforge.plugins import engines
        plugin = engines.engine(provider)
        if plugin is None:
            raise AIError(f"the translation plugin '{provider[7:]}' is not installed or switched off")
    if plugin is not None:
        def one(t):
            if "translator" in plugin.manifest.kinds:
                return plugin.translate(settings, t, src, to)
            return plugin.generate(settings, [{"role": "user", "content": t}],
                                   {"system": translation_system(settings, to, src)})
    elif provider == "deepl" and has_key:
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
