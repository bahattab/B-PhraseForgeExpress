"""AI and translation engines behind one contract (PRD FR-PLG-03 and FR-PLG-06).

Every engine, built in or from a plugin, answers the same calls; they are the JSON-RPC
methods a plugin of kind "ai_engine" or "translator" implements:

  describe()          {type, provider, name, urls, is_local, needs_api_key, configurable}
  status()            {configured, error}
  capabilities()      {glossaries, ignored_words, custom_instructions, vision, image_gen,
                       image_edit, usage_stats, model_management}
  settings_schema()   JSON Schema of the engine's own settings
  list_models()       [model names]
  list_languages()    [language names or codes]
  generate(messages, params)      -> {text}      ai_engine
  translate(text, from, to)       -> {text}      translator

The built-in engines (OpenAI, Anthropic, OpenRouter, Gemini, OpenCode Zen, Kilo Code, Ollama,
GPT4All, DeepL and the free MyMemory service) are "builtin" plugins: they run inside
PhraseForge (runtime builtin, FR-PLG-06) and pass the same conformance tests
(tests/plugin_conformance/). A plugin engine is chosen as provider "plugin:<id>" in Settings
> AI or > Language Translation; its secrets come from the plugin's declared secrets.
"""
from __future__ import annotations

from phraseforge import ai

CAPABILITY_KEYS = ("glossaries", "ignored_words", "custom_instructions", "vision", "image_gen", "image_edit",
                   "usage_stats", "model_management")
DESCRIBE_KEYS = ("type", "provider", "name", "urls", "is_local", "needs_api_key", "configurable")
AI_TIMEOUT_S = 60.0
PLUGIN_PREFIX = "plugin:"

_URLS = {"openai": "https://platform.openai.com/api-keys", "anthropic": "https://console.anthropic.com/settings/keys",
         "gemini": "https://aistudio.google.com/apikey", "openrouter": "https://openrouter.ai/keys",
         "opencode": "https://opencode.ai/zen", "kilocode": "https://app.kilo.ai",
         "ollama": "https://ollama.com/download", "gpt4all": "https://www.nomic.ai/gpt4all",
         "deepl": "https://www.deepl.com/your-account/keys", "free": "https://mymemory.translated.net/"}
LOCAL = {"ollama": "ai.ollama_url", "gpt4all": "ai.gpt4all_url"}


class Engine:
    """The contract. settings: the PhraseForge settings dict (keys, URLs, instructions)."""
    kind = "ai_engine"
    provider = ""

    def describe(self) -> dict:
        raise NotImplementedError

    def status(self, settings: dict) -> dict:
        raise NotImplementedError

    def capabilities(self) -> dict:
        return {k: False for k in CAPABILITY_KEYS}

    def settings_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    def list_models(self, settings: dict) -> list[str]:
        return []

    def list_languages(self, settings: dict) -> list[str]:
        return []

    def generate(self, settings: dict, messages: list[dict], params: dict) -> str:
        raise ai.AIError(f"{self.provider} does not write text")

    def translate(self, settings: dict, text: str, src: str, to: str) -> str:
        raise ai.AIError(f"{self.provider} does not translate")


class BuiltinChatEngine(Engine):
    kind = "ai_engine"

    def __init__(self, provider: str):
        self.provider = provider

    def describe(self) -> dict:
        local = self.provider in LOCAL
        return {"type": "ai_engine", "provider": self.provider, "name": ai.PROVIDER_NAMES.get(self.provider, self.provider),
                "urls": [_URLS.get(self.provider, "")], "is_local": local, "needs_api_key": not local,
                "configurable": True}

    def status(self, settings: dict) -> dict:
        if self.provider in LOCAL:
            return {"configured": True, "error": ""}
        ok = bool((settings.get(f"ai.{self.provider}_key") or "").strip())
        return {"configured": ok, "error": "" if ok else "API key is not set"}

    def capabilities(self) -> dict:
        caps = super().capabilities()
        caps.update(glossaries=True, ignored_words=True, custom_instructions=True)
        return caps

    def settings_schema(self) -> dict:
        props = {"model": {"type": "string", "default": ai.DEFAULT_MODELS.get(self.provider, "")}}
        if self.provider in LOCAL:
            props["url"] = {"type": "string", "setting": LOCAL[self.provider]}
        else:
            props["api_key"] = {"type": "string", "secret": True, "setting": f"ai.{self.provider}_key"}
        return {"type": "object", "properties": props}

    def list_models(self, settings: dict) -> list[str]:
        m = ai.DEFAULT_MODELS.get(self.provider, "")
        return [m] if m else []

    def list_languages(self, settings: dict) -> list[str]:
        return sorted(k.capitalize() for k in ai.DEEPL_LANGS)          # an LLM translates any of these

    def generate(self, settings: dict, messages: list[dict], params: dict) -> str:
        return ai.chat(settings, messages, self.provider, params.get("model", ""), params.get("system", ""),
                       float(params.get("timeout", 120)), int(params.get("max_tokens", 1024)),
                       bool(params.get("raw_system", False)))

    def translate(self, settings: dict, text: str, src: str, to: str) -> str:
        system = ai.translation_system(settings, to, src)
        return ai.complete(settings, text, self.provider, "", system, raw_system=True)


class DeepLEngine(Engine):
    kind = "translator"
    provider = "deepl"

    def describe(self) -> dict:
        return {"type": "translator", "provider": "deepl", "name": "DeepL", "urls": [_URLS["deepl"]],
                "is_local": False, "needs_api_key": True, "configurable": True}

    def status(self, settings: dict) -> dict:
        ok = bool((settings.get("ai.deepl_key") or "").strip())
        return {"configured": ok, "error": "" if ok else "API key is not set"}

    def capabilities(self) -> dict:
        caps = super().capabilities()
        caps.update(ignored_words=True)
        return caps

    def settings_schema(self) -> dict:
        return {"type": "object", "properties": {"api_key": {"type": "string", "secret": True, "setting": "ai.deepl_key"}}}

    def list_languages(self, settings: dict) -> list[str]:
        return sorted(k.capitalize() for k in ai.DEEPL_LANGS)

    def translate(self, settings: dict, text: str, src: str, to: str) -> str:
        return ai.deepl_translate(settings, text, to, src)


class FreeEngine(Engine):
    kind = "translator"
    provider = "free"

    def describe(self) -> dict:
        return {"type": "translator", "provider": "free", "name": "MyMemory (free)", "urls": [_URLS["free"]],
                "is_local": False, "needs_api_key": False, "configurable": False}

    def status(self, settings: dict) -> dict:
        return {"configured": True, "error": ""}

    def list_languages(self, settings: dict) -> list[str]:
        return sorted(ai.ISO_CODES)

    def translate(self, settings: dict, text: str, src: str, to: str) -> str:
        return ai.free_translate(text, to, src or ai.guess_language(text))


class PluginEngine(Engine):
    """An engine from an installed plugin: every call goes over JSON-RPC (plugins/host.py)."""

    def __init__(self, manager, manifest):
        self.mgr, self.manifest = manager, manifest
        self.provider = PLUGIN_PREFIX + manifest.id
        self.kind = "ai_engine" if "ai_engine" in manifest.kinds else "translator"

    def _call(self, method: str, params: dict | None = None, timeout: float = AI_TIMEOUT_S, settings=None):
        from phraseforge.plugins.host import PluginError, PluginTimeout
        if not self.mgr.is_enabled(self.manifest.id):
            raise ai.AIError(f"the plugin {self.manifest.id} is switched off")
        p = dict(params or {})
        secrets = self.mgr._secrets(self.manifest)
        for name in secrets:                      # a key typed in Settings but not saved yet ("Test")
            typed = (settings or {}).get(f"plugins.secret.{self.manifest.id}.{name}")
            if typed:
                secrets[name] = typed
        p["secrets"] = secrets
        try:
            return self.mgr.process(self.manifest.id).call(method, p, timeout=timeout)
        except PluginTimeout:
            raise ai.AIError(f"plugin {self.manifest.id}: timeout") from None
        except Exception as e:                    # noqa: BLE001 - uninstalled meanwhile, bad answer, ...
            raise ai.AIError(f"plugin {self.manifest.id}: {e}") from None

    def _dict(self, method: str, keys) -> dict:
        res = self._call(method, timeout=10)
        if not isinstance(res, dict):
            raise ai.AIError(f"plugin {self.manifest.id}: {method} did not answer an object")
        return res

    def describe(self) -> dict:
        d = self._dict("describe", DESCRIBE_KEYS)
        d.setdefault("name", self.manifest.name)
        d["provider"] = self.provider
        return d

    def status(self, settings: dict) -> dict:
        return self._dict("status", ("configured", "error"))

    def capabilities(self) -> dict:
        caps = super().capabilities()
        res = self._dict("capabilities", CAPABILITY_KEYS)
        caps.update({k: bool(res.get(k)) for k in CAPABILITY_KEYS})
        return caps

    def settings_schema(self) -> dict:
        return self._dict("settings_schema", ())

    def list_models(self, settings: dict) -> list[str]:
        return [str(x) for x in (self._call("list_models", {"kind": "text"}, timeout=10) or [])]

    def list_languages(self, settings: dict) -> list[str]:
        return [str(x) for x in (self._call("list_languages", timeout=10) or [])]

    @staticmethod
    def _text(res) -> str:
        if isinstance(res, dict) and "text" in res:
            return str(res["text"])
        raise ai.AIError("the plugin answered without text")

    def generate(self, settings: dict, messages: list[dict], params: dict) -> str:
        if self.kind != "ai_engine":
            return super().generate(settings, messages, params)
        clean = {k: v for k, v in params.items() if k in ("model", "system", "max_tokens", "length", "accuracy",
                                                          "variation")}
        return self._text(self._call("generate", {"messages": messages, "params": clean},
                                     timeout=float(params.get("timeout", AI_TIMEOUT_S)), settings=settings))

    def translate(self, settings: dict, text: str, src: str, to: str) -> str:
        if "translator" not in self.manifest.kinds:
            return super().translate(settings, text, src, to)
        return self._text(self._call("translate", {"text": text, "from": src, "to": to}, settings=settings))


BUILTIN: dict[str, Engine] = {p: BuiltinChatEngine(p) for p in ai.DEFAULT_MODELS}
BUILTIN["deepl"] = DeepLEngine()
BUILTIN["free"] = FreeEngine()


def plugin_engines(kind: str | None = None) -> dict[str, PluginEngine]:
    from phraseforge.plugins import manager as pm
    mgr = pm.current()
    if mgr is None:
        return {}
    out = {}
    for pid, m in mgr.installed().items():
        if not ({"ai_engine", "translator"} & set(m.kinds)) or not mgr.is_enabled(pid):
            continue
        if kind is not None and kind not in m.kinds:
            continue
        out[PLUGIN_PREFIX + pid] = PluginEngine(mgr, m)
    return out


def engine(provider: str) -> Engine | None:
    provider = (provider or "").strip().lower()
    if provider.startswith(PLUGIN_PREFIX):
        return plugin_engines().get(provider)
    return BUILTIN.get(provider)


def choices(kind: str) -> list[tuple[str, str]]:
    """(label, provider) of the enabled plugin engines of this kind, for the Settings lists."""
    return [(f"Plugin: {e.manifest.name}", pid) for pid, e in plugin_engines(kind).items()]
