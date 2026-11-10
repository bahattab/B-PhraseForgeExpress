# Writing a PhraseForge plugin

A plugin is a folder (or a `.pfplugin` zip of that folder) with a `plugin.toml` and a program.
See `examples/plugins/hello` for a complete macro plugin.

## plugin.toml

```toml
id = "hello"                 # lowercase; also the macro namespace: {#hello.greet}
name = "Hello"
version = "1.0.0"
api_version = "1.0"
kinds = ["macro"]
entry = "main.py"
runtime = "python-subprocess"   # or "exe-subprocess"
macros = ["greet", "shout"]

[permissions]
network = []        # hosts the plugin connects to
filesystem = []     # read:user-selected, write:user-selected, read:any, write:any
secrets = ["token"] # set in Phrases > Plugins > Set secret; passed in on each call
clipboard = false
input = false
```

PhraseForge reads only this file before the user agrees to install the plugin. **The
permissions are declarations, not limits:** a plugin is a program that runs with the user's
Windows rights, so it can read files and reach the network whatever it declares (a network
proxy and a restricted token are still open, FR-PLG-05). Therefore every plugin macro is
treated like `{#run}`: phrases from imports, sync or libraries must be approved on this PC
before they can use it, and so must `{#ai}` / `{#translate}` when the engine is a plugin.
An update always asks (also when it asks for nothing new) and keeps a switched-off plugin
off; one that asks for more is switched off until the user agrees again. Removing a plugin
removes its secrets. Without `plugins_allowed`, a PC whose policy locks Settings or editing
runs no plugins.

## Protocol

The plugin runs as its own process. PhraseForge writes one JSON-RPC 2.0 request per line to
its stdin and reads one reply per line from its stdout (UTF-8):

```json
{"jsonrpc": "2.0", "id": 1, "method": "macro",
 "params": {"name": "greet", "args": ["Sam"], "opts": {"end": "."}, "secrets": {"token": "..."}}}
{"jsonrpc": "2.0", "id": 1, "result": {"text": "Hello, Sam."}}
```

Errors: `{"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "..."}}` — shown in the
phrase as `[hello.greet: ...]`. A macro call has 5 seconds; then PhraseForge sends
`{"method": "$/cancel", "params": {"id": 1}}`, waits two seconds and stops the process (it is
started again on the next call). Anything written to stderr appears in the Plugins window.
The process gets a minimal environment (no API keys or proxy settings from PhraseForge's own).

## AI and translation engines

A plugin with `kinds = ["ai_engine"]` and/or `["translator"]` appears in Settings > AI and
Settings > Language Translation as "Plugin: <name>". It answers these methods (see
`examples/plugins/echo-ai` and `phraseforge/plugins/engines.py`):

| Method | Answer |
|---|---|
| `describe` | `{type, provider, name, urls, is_local, needs_api_key, configurable}` |
| `status` | `{configured, error}` |
| `capabilities` | booleans: `glossaries, ignored_words, custom_instructions, vision, image_gen, image_edit, usage_stats, model_management` |
| `settings_schema` | a JSON Schema object |
| `list_models`, `list_languages` | lists of names |
| `generate` | params `{messages, params: {model, system, max_tokens}}` → `{text}` |
| `translate` | params `{text, from, to}` → `{text}` |

The API key typed in Settings > AI for a plugin engine is passed as the secret `api_key` (declare
it under `[permissions] secrets`). AI calls have 60 seconds. A plugin that only writes text
(ai_engine) can also be chosen for translation: PhraseForge then asks it with a translation
instruction.

## Signing a plugin

A plugin can carry `plugin.sig`, an Ed25519 signature over every file in it. PhraseForge shows
whether a plugin is signed, and by whom (a short fingerprint), when it asks you to install it.
A plugin whose files no longer match its signature is never installed.

```python
from phraseforge.plugins import signing
private, public = signing.new_key()      # keep the private key secret; publish the public one
signing.sign_folder("my-plugin", private) # writes my-plugin/plugin.sig; sign last, after every change
```

Users trust a publisher by adding its public key, one per line, to the setting
`plugins.trusted_keys` (this PC only). Administrators can list keys in `policy.toml`
(`plugins_trusted_keys = ["..."]`) and set `plugins_require_signature = true` so that only
plugins signed by one of those keys can be installed (then keys in the user's setting do not count). Python caches (`__pycache__`, `*.pyc`) and `.git` are never installed, so they are not signed either.

## Network access

Each plugin process gets `HTTPS_PROXY`, `HTTP_PROXY` and `ALL_PROXY` pointing at its own local
proxy. It only opens HTTPS tunnels (port 443) to the hosts in `permissions.network`; anything
else, and plain HTTP, is refused and listed in the plugin's errors. Use a normal HTTP library
that honours these variables (urllib, requests, httpx). A plugin that opens sockets itself is not
stopped by this: install only plugins you trust.

## Streaming an answer

When PhraseForge can show an answer while it is written, `generate` gets `"stream": true` in
its params. The plugin may then send any number of notifications before its normal reply:

```json
{"jsonrpc": "2.0", "method": "$/progress", "params": {"id": <the request's id>, "text": "next piece"}}
```

The pieces are shown live (Prompt Optimizer). The final reply must still carry the whole text.
Each piece restarts the call's timeout, but a call ends after ten times its timeout in any case,
and after 4 MB of streamed text. `examples/plugins/echo-ai` streams word by word.
