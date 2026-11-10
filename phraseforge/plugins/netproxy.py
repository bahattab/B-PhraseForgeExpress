"""Per-plugin network filter (PRD FR-PLG-05, best effort).

Each plugin process gets HTTPS_PROXY / HTTP_PROXY / ALL_PROXY pointing at its own local proxy
on 127.0.0.1. The proxy opens a tunnel (HTTP CONNECT) only to a host the manifest lists in
permissions.network, so a plugin that uses the system's normal HTTP libraries cannot reach
anything else. A plugin with no network permission gets a proxy that refuses everything.

Limits (documented residual risk): a plugin that ignores the proxy variables and opens sockets
itself is not stopped; first-party plugins are reviewed. Only CONNECT tunnels (HTTPS and any
TLS protocol) are offered: plain-HTTP requests are refused, so nothing a plugin sends travels
unencrypted through PhraseForge.
"""
from __future__ import annotations

import logging
from collections import deque
import select
import socket
import socketserver
import threading

log = logging.getLogger(__name__)

ALLOWED_PORTS = frozenset({443})
CONNECT_TIMEOUT_S = 15
IDLE_TIMEOUT_S = 300
MAX_HEADER = 8192


def parse_connect(head: bytes) -> tuple[str, int] | None:
    """('api.example.com', 443) from b'CONNECT api.example.com:443 HTTP/1.1...', else None."""
    try:
        line = head.split(b"\r\n", 1)[0].decode("ascii")
    except UnicodeDecodeError:
        return None
    parts = line.split()
    if len(parts) != 3 or parts[0].upper() != "CONNECT" or not parts[2].startswith("HTTP/1."):
        return None
    host, sep, port = parts[1].rpartition(":")
    if not sep or not port.isdigit() or not host or host.startswith("["):
        return None
    return host.lower().rstrip("."), int(port)


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        proxy: FilterProxy = self.server.owner            # type: ignore[attr-defined]
        client = self.request
        client.settimeout(CONNECT_TIMEOUT_S)
        head = b""
        try:
            while b"\r\n\r\n" not in head and len(head) < MAX_HEADER:
                chunk = client.recv(1024)
                if not chunk:
                    return
                head += chunk
        except OSError:
            return
        target = parse_connect(head)
        if target is None:
            client.sendall(b"HTTP/1.1 405 Only CONNECT is allowed\r\nContent-Length: 0\r\n\r\n")
            proxy.denied.append(head.split(b"\r\n", 1)[0][:120].decode("latin-1"))
            return
        host, port = target
        if not proxy.allows(host, port):
            client.sendall(b"HTTP/1.1 403 Host not allowed by the plugin's permissions\r\nContent-Length: 0\r\n\r\n")
            proxy.denied.append(f"{host}:{port}")
            if proxy.on_denied:
                proxy.on_denied(f"network: blocked {host}:{port} (not in the plugin's permissions)")
            log.info("plugin %s: blocked connection to %s:%d", proxy.plugin_id, host, port)
            return
        try:
            upstream = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT_S)
        except OSError:
            client.sendall(b"HTTP/1.1 502 Could not connect\r\nContent-Length: 0\r\n\r\n")
            return
        rest = head.split(b"\r\n\r\n", 1)[1]
        try:
            client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            if rest:
                upstream.sendall(rest)
            _pipe(client, upstream)
        finally:
            upstream.close()


def _pipe(a: socket.socket, b: socket.socket) -> None:
    a.settimeout(None)
    b.settimeout(None)
    socks = [a, b]
    while True:
        ready, _, _ = select.select(socks, [], [], IDLE_TIMEOUT_S)
        if not ready:
            return
        for s in ready:
            try:
                data = s.recv(65536)
            except OSError:
                return
            if not data:
                return
            try:
                (b if s is a else a).sendall(data)
            except OSError:
                return


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = False


class FilterProxy:
    def __init__(self, plugin_id: str, hosts: tuple[str, ...] | list[str], on_denied=None):
        self.plugin_id = plugin_id
        self.hosts = frozenset(h.lower().rstrip(".") for h in hosts)
        self.ports = ALLOWED_PORTS
        self.on_denied = on_denied           # called with "host:port" for each refused tunnel
        self.denied: deque[str] = deque(maxlen=100)          # what was refused (shown with the plugin's errors)
        self._server: _Server | None = None

    def allows(self, host: str, port: int) -> bool:
        return port in self.ports and host.lower().rstrip(".") in self.hosts

    def start(self) -> int:
        self._server = _Server(("127.0.0.1", 0), _Handler)
        self._server.owner = self                       # type: ignore[attr-defined]
        threading.Thread(target=self._server.serve_forever, daemon=True,
                         name=f"plugin-proxy-{self.plugin_id}").start()
        return self.port

    @property
    def port(self) -> int:
        return self._server.server_address[1] if self._server else 0

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def env(self) -> dict[str, str]:
        url = f"http://127.0.0.1:{self.port}"
        out = {}
        for name in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"):
            out[name] = out[name.lower()] = url
        out["NO_PROXY"] = out["no_proxy"] = ""
        return out
