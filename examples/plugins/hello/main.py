"""Example PhraseForge macro plugin: JSON-RPC 2.0, one JSON message per line on stdin/stdout.

PhraseForge sends {"method": "macro", "params": {"name", "args", "opts", "secrets"}} and
expects {"result": {"text": "..."}} or {"error": {"code": ..., "message": "..."}}.
"$/cancel" notifications ask the plugin to stop the call with that id.
"""
import json
import sys
import time


def handle(method, params):
    if method == "describe":
        return {"name": "Hello", "macros": ["greet", "shout", "secret_len"]}
    if method != "macro":
        raise ValueError(f"unknown method {method}")
    name, args, opts = params.get("name"), params.get("args", []), params.get("opts", {})
    if name == "greet":
        return {"text": f"Hello, {' '.join(args) or 'world'}{opts.get('end', '!')}"}
    if name == "shout":
        return {"text": " ".join(args).upper()}
    if name == "secret_len":
        return {"text": str(len(params.get("secrets", {}).get("token", "")))}
    if name == "hang":                      # used by the tests: never answers
        while True:
            time.sleep(1)
    raise ValueError(f"unknown macro {name}")


for line in sys.stdin:
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    if "id" not in msg:                     # a notification such as $/cancel
        continue
    try:
        reply = {"jsonrpc": "2.0", "id": msg["id"], "result": handle(msg.get("method"), msg.get("params") or {})}
    except Exception as e:                  # noqa: BLE001
        reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32000, "message": str(e)}}
    sys.stdout.write(json.dumps(reply) + "\n")
    sys.stdout.flush()
