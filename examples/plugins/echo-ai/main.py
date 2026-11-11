"""Example "ai_engine" + "translator" plugin. A real engine would call its service here (and
list that host under [permissions] network)."""
import base64
import json
import sys

# a 1x1 transparent PNG: a real engine would return the picture its service made
PIXEL = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA"
         "60e6kgAAAABJRU5ErkJggg==")


def handle(method, p):
    if method == "describe":
        return {"type": "ai_engine", "provider": "echo-ai", "name": "Echo AI", "urls": [], "is_local": True,
                "needs_api_key": False, "configurable": False}
    if method == "status":
        return {"configured": True, "error": ""}
    if method == "capabilities":
        return {"custom_instructions": True, "image_gen": True, "usage_stats": True, "model_management": True}
    if method == "settings_schema":
        return {"type": "object", "properties": {}}
    if method == "list_models":
        return ["echo-image-1"] if p.get("kind") == "image" else ["echo-1"]
    if method == "list_languages":
        return ["English", "Arabic"]
    if method == "generate":
        msgs = p.get("messages") or []
        last = msgs[-1]["content"] if msgs else ""
        system = (p.get("params") or {}).get("system", "")
        text = f"echo: {last}" + (" (with instructions)" if system else "")
        if (p.get("params") or {}).get("stream"):          # stream it word by word first
            for word in text.split(" "):
                progress(CURRENT_ID, word + " ")
        return {"text": text, "usage": {"input_tokens": len(last.split()), "output_tokens": len(text.split())}}
    if method == "generate_image":
        return {"image": PIXEL, "usage": {"input_tokens": len(str(p.get("prompt", "")).split()), "output_tokens": 0}}
    if method == "pull_model":
        for step in ("pulling manifest", "downloading 50%", "downloading 100%", "verifying"):
            progress(CURRENT_ID, step)
        return {}
    if method == "translate":
        return {"text": f"[{p.get('to')}] {p.get('text')}"}
    raise ValueError(f"unknown method {method}")


CURRENT_ID = None


def progress(call_id, piece):
    """Send part of an answer before the answer itself ($/progress, shown live by PhraseForge)."""
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "method": "$/progress",
                                 "params": {"id": call_id, "text": piece}}) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    if "id" not in msg:
        continue
    CURRENT_ID = msg["id"]
    try:
        reply = {"jsonrpc": "2.0", "id": msg["id"], "result": handle(msg.get("method"), msg.get("params") or {})}
    except Exception as e:  # noqa: BLE001
        reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32000, "message": str(e)}}
    sys.stdout.write(json.dumps(reply) + "\n")
    sys.stdout.flush()
