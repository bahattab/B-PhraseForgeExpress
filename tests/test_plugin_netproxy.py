"""Per-plugin network filter (FR-PLG-05, T-PLG-05)."""
import socket
import socketserver
import sys
import threading

import pytest

from phraseforge.plugins.netproxy import FilterProxy, parse_connect


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        data = self.request.recv(1024)
        self.request.sendall(b"echo:" + data)


@pytest.fixture
def upstream():
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Echo)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def ask(proxy_port, line: bytes) -> tuple[bytes, socket.socket]:
    s = socket.create_connection(("127.0.0.1", proxy_port), timeout=5)
    s.sendall(line)
    reply = b""
    while b"\r\n\r\n" not in reply:
        chunk = s.recv(1024)
        if not chunk:
            break
        reply += chunk
    return reply, s


def test_parse_connect():
    assert parse_connect(b"CONNECT Api.Example.com.:443 HTTP/1.1\r\nHost: x\r\n\r\n") == ("api.example.com", 443)
    assert parse_connect(b"GET http://x/ HTTP/1.1\r\n\r\n") is None
    assert parse_connect(b"CONNECT x HTTP/1.1\r\n\r\n") is None
    assert parse_connect(b"CONNECT [::1]:443 HTTP/1.1\r\n\r\n") is None
    assert parse_connect(b"\xff\xfe") is None


def test_allowed_host_is_tunnelled(upstream):
    p = FilterProxy("demo", ["localhost"])
    p.ports = frozenset({upstream})
    p.start()
    try:
        reply, s = ask(p.port, f"CONNECT localhost:{upstream} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
        assert reply.startswith(b"HTTP/1.1 200")
        s.sendall(b"hello")
        assert s.recv(1024) == b"echo:hello"
        s.close()
    finally:
        p.stop()


def test_other_hosts_ports_and_plain_http_are_refused(upstream):
    p = FilterProxy("demo", ["api.example.com"])
    p.start()
    try:
        assert ask(p.port, b"CONNECT evil.example.org:443 HTTP/1.1\r\n\r\n")[0].startswith(b"HTTP/1.1 403")
        assert ask(p.port, b"CONNECT api.example.com:22 HTTP/1.1\r\n\r\n")[0].startswith(b"HTTP/1.1 403")
        assert ask(p.port, b"GET http://api.example.com/ HTTP/1.1\r\n\r\n")[0].startswith(b"HTTP/1.1 405")
        assert list(p.denied)[:2] == ["evil.example.org:443", "api.example.com:22"]
    finally:
        p.stop()


def test_no_network_permission_refuses_everything():
    p = FilterProxy("demo", [])
    p.start()
    try:
        assert ask(p.port, b"CONNECT api.example.com:443 HTTP/1.1\r\n\r\n")[0].startswith(b"HTTP/1.1 403")
    finally:
        p.stop()


def test_env_points_every_proxy_variable_at_the_filter():
    p = FilterProxy("demo", [])
    p.start()
    try:
        env = p.env()
        url = f"http://127.0.0.1:{p.port}"
        assert env["HTTPS_PROXY"] == env["https_proxy"] == env["HTTP_PROXY"] == env["ALL_PROXY"] == url
        assert env["NO_PROXY"] == ""
    finally:
        p.stop()


def test_plugin_process_gets_the_proxy(tmp_path):
    """A real plugin process sees the proxy variables and cannot reach an unlisted host."""
    from phraseforge.plugins import manifest as mf
    from phraseforge.plugins.host import PluginProcess
    (tmp_path / "plugin.py").write_text(
        "import json, os, sys, urllib.request\n"
        "for line in sys.stdin:\n"
        "    msg = json.loads(line)\n"
        "    try:\n"
        "        urllib.request.urlopen('https://blocked.example.org/', timeout=5)\n"
        "        res = 'reached'\n"
        "    except Exception as e:\n"
        "        res = 'blocked:' + type(e).__name__\n"
        "    out = {'jsonrpc': '2.0', 'id': msg['id'], 'result': {'proxy': os.environ.get('HTTPS_PROXY'), 'net': res}}\n"
        "    sys.stdout.write(json.dumps(out) + '\\n'); sys.stdout.flush()\n")
    m = mf.parse('id = "nettest"\nname = "N"\nversion = "1.0.0"\napi_version = "1.0"\nentry = "plugin.py"\n'
                 'runtime = "python-subprocess"\nkinds = ["macro"]\nmacros = ["probe"]\n'
                 '[permissions]\nnetwork = ["api.example.com"]\n')
    proc = PluginProcess(m, tmp_path)
    try:
        out = proc.call("probe", {}, timeout=20)
    finally:
        proc.stop()
    assert out["proxy"].startswith("http://127.0.0.1:")
    assert out["net"].startswith("blocked:")
