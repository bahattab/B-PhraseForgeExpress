"""Example "ai_engine" + "translator" plugin. A real engine would call its service here (and
list that host under [permissions] network)."""
import json
import sys


def handle(method, p):
    if method == "describe":
        return {"type": "ai_engine", "provider": "echo-ai", "name": "Echo AI", "urls": [], "is_local": True,
                "needs_api_key": False, "configurable": False}
    if method == "status":
        return {"configured": True, "error": ""}
    if method == "capabilities":
        return {"custom_instructions": True}
    if method == "settings_schema":
        return {"type": "object", "properties": {}}
    if method == "list_models":
        return ["echo-1"]
    if method == "list_languages":
        return ["English", "Arabic"]
    if method == "generate":
        msgs = p.get("messages") or []
        last = msgs[-1]["content"] if msgs else ""
        system = (p.get("params") or {}).get("system", "")
        return {"text": f"echo: {last}" + (" (with instructions)" if system else "")}
    if method == "translate":
        return {"text": f"[{p.get('to')}] {p.get('text')}"}
    raise ValueError(f"unknown method {method}")


for line in sys.stdin:
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    if "id" not in msg:
        continue
    try:
        reply = {"jsonrpc": "2.0", "id": msg["id"], "result": handle(msg.get("method"), msg.get("params") or {})}
    except Exception as e:  # noqa: BLE001
        reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32000, "message": str(e)}}
    sys.stdout.write(json.dumps(reply) + "\n")
    sys.stdout.flush()
