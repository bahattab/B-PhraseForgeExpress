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

PhraseForge reads only this file before the user agrees to install the plugin. A plugin that
asks for network, filesystem or input access is treated like `{#run}`: phrases from imports or
sync must be approved on this PC before they can use it. An update that asks for more is
switched off until the user agrees again.

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
