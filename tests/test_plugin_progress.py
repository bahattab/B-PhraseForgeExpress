"""Streamed plugin replies ($/progress, FR-PLG-03)."""
import time

import pytest

from phraseforge.plugins import host as H
from phraseforge.plugins import manifest as mf
from phraseforge.plugins.host import PluginError, PluginProcess, PluginTimeout

SCRIPT = r"""
import json, sys, time
def send(o):
    sys.stdout.write(json.dumps(o) + "\n"); sys.stdout.flush()
for line in sys.stdin:
    m = json.loads(line)
    if "id" not in m:
        continue
    p = m.get("params") or {}
    mode = p.get("mode")
    if mode == "stream":
        send({"jsonrpc": "2.0", "method": "$/progress", "params": {"id": m["id"] - 1, "text": "OLD"}})
        send({"jsonrpc": "2.0", "method": "$/progress", "params": {"id": m["id"], "text": 5}})
        for piece in ("a", "b", "c"):
            send({"jsonrpc": "2.0", "method": "$/progress", "params": {"id": m["id"], "text": piece}})
    elif mode == "slow":
        for _ in range(4):
            time.sleep(0.6)
            send({"jsonrpc": "2.0", "method": "$/progress", "params": {"id": m["id"], "text": "."}})
    elif mode == "flood":
        for _ in range(int(p.get("n", 10))):
            send({"jsonrpc": "2.0", "method": "$/progress", "params": {"id": m["id"], "text": "x" * 1000}})
        time.sleep(5)
    elif mode == "endless":
        while True:
            time.sleep(0.3)
            send({"jsonrpc": "2.0", "method": "$/progress", "params": {"id": m["id"], "text": "."}})
    send({"jsonrpc": "2.0", "id": m["id"], "result": {"text": "done"}})
"""


@pytest.fixture
def proc(tmp_path):
    (tmp_path / "plugin.py").write_text(SCRIPT)
    m = mf.parse('id = "streamer"\nname = "S"\nversion = "1.0.0"\napi_version = "1.0"\nentry = "plugin.py"\n'
                 'runtime = "python-subprocess"\nkinds = ["macro"]\nmacros = ["x"]\n')
    p = PluginProcess(m, tmp_path)
    yield p
    p.stop()


def test_pieces_arrive_in_order_and_only_for_this_call(proc):
    got = []
    assert proc.call("generate", {"mode": "stream"}, timeout=10, on_progress=got.append) == {"text": "done"}
    assert got == ["a", "b", "c"]                  # other call ids and non-text pieces are ignored


def test_no_callback_still_works(proc):
    assert proc.call("generate", {"mode": "stream"}, timeout=10) == {"text": "done"}


def test_each_piece_restarts_the_timeout(proc):
    got = []
    # 4 pieces 0.6 s apart: 2.4 s in all, more than the 1 s timeout, but never 1 s without news
    assert proc.call("generate", {"mode": "slow"}, timeout=1.5, on_progress=got.append) == {"text": "done"}
    assert len(got) == 4


def test_streaming_has_a_hard_end(proc, monkeypatch):
    monkeypatch.setattr(H, "MAX_CALL_FACTOR", 2)
    t = time.monotonic()
    with pytest.raises(PluginTimeout):
        proc.call("generate", {"mode": "endless"}, timeout=1, on_progress=lambda _t: None)
    assert time.monotonic() - t < 8                # 2 s limit + the 2 s cancel grace before a kill


def test_too_much_streamed_text_stops_the_call(proc, monkeypatch):
    monkeypatch.setattr(H, "MAX_STREAM", 5000)
    with pytest.raises(PluginError, match="too much"):
        proc.call("generate", {"mode": "flood", "n": 10}, timeout=10, on_progress=lambda _t: None)


def test_a_failing_display_does_not_end_the_call(proc):
    def boom(_t):
        raise RuntimeError("ui gone")
    assert proc.call("generate", {"mode": "stream"}, timeout=10, on_progress=boom) == {"text": "done"}
