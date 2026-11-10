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
MAX_CONNECTIONS = 16        # open tunnels per plugin; more are refused
HEADER_DEADLINE_S = 10      # the whole CONNECT request must arrive within this
SEND_TIMEOUT_S = 30         # a send that cannot finish within this ends the tunnel
MAX_PENDING = 64            # connections still sending their CONNECT line


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


def _send(sock, data: bytes) -> None:
    try:
        sock.sendall(data)
    except OSError:
        pass


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        proxy: FilterProxy = self.server.owner            # type: ignore[attr-defined]
        client = self.request
        if not proxy._pending.acquire(blocking=False):
            return                                        # too many half-sent requests: just close
        proxy._track(client, True)
        try:
            try:
                head = self._read_head(client)
            finally:
                proxy._pending.release()
            if head is None:
                return
            if not proxy.authorized(head):                # only the plugin knows the token (R120)
                _send(client, b"HTTP/1.1 407 Proxy authentication required\r\n"
                              b"Proxy-Authenticate: Basic realm=\"PhraseForge\"\r\nContent-Length: 0\r\n\r\n")
                return
            if not proxy._slots.acquire(blocking=False):
                _send(client, b"HTTP/1.1 503 Too many connections\r\nContent-Length: 0\r\n\r\n")
                return
            try:
                self._serve(proxy, client, head)
            finally:
                proxy._slots.release()
        finally:
            proxy._track(client, False)

    @staticmethod
    def _read_head(client) -> bytes | None:
        import time
        deadline = time.monotonic() + HEADER_DEADLINE_S
        head = b""
        try:
            while b"\r\n\r\n" not in head and len(head) < MAX_HEADER:
                left = deadline - time.monotonic()
                if left <= 0:
                    return None
                client.settimeout(left)
                chunk = client.recv(1024)
                if not chunk:
                    return None
                head += chunk
        except OSError:
            return None
        return head

    def _serve(self, proxy, client, head: bytes) -> None:
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
            addr = (host, port) if proxy.allow_local else _public_address(host, port)
            if addr is None:                          # an allowed name that points inside (R121)
                client.sendall(b"HTTP/1.1 403 Host resolves to a local address\r\nContent-Length: 0\r\n\r\n")
                proxy.denied.append(f"{host}:{port} (local address)")
                return
            upstream = socket.create_connection(addr, timeout=CONNECT_TIMEOUT_S)   # the address checked
        except OSError:
            client.sendall(b"HTTP/1.1 502 Could not connect\r\nContent-Length: 0\r\n\r\n")
            return
        proxy._track(upstream, True)
        rest = head.split(b"\r\n\r\n", 1)[1]
        try:
            client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            if rest:
                upstream.sendall(rest)
            _pipe(client, upstream)
        finally:
            proxy._track(upstream, False)
            upstream.close()


def _public_address(host: str, port: int):
    """The first internet address of host, or None when it only resolves to this PC, the local
    network, link-local (169.254.x, cloud metadata) or other reserved ranges."""
    import ipaddress
    for family, _t, _p, _c, sa in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
        ip = ipaddress.ip_address(sa[0].split("%")[0])
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
        if ip.is_global:
            return sa[:2]
    return None


def _pipe(a: socket.socket, b: socket.socket) -> None:
    # a peer that stops reading must not hold the slot forever (R120)
    a.settimeout(SEND_TIMEOUT_S)
    b.settimeout(SEND_TIMEOUT_S)
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
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self._pending = threading.BoundedSemaphore(MAX_PENDING)
        import secrets
        self.token = secrets.token_urlsafe(24)      # in the plugin's proxy URL only
        self.allow_local = False                    # tests tunnel to a server on this PC
        self._open: set[socket.socket] = set()
        self._open_lock = threading.Lock()

    def _track(self, sock: socket.socket, add: bool) -> None:
        with self._open_lock:
            (self._open.add if add else self._open.discard)(sock)

    def authorized(self, head: bytes) -> bool:
        import base64
        import hmac
        want = b"Basic " + base64.b64encode(f"pf:{self.token}".encode())
        for line in head.split(b"\r\n")[1:]:
            name, sep, value = line.partition(b":")
            if sep and name.strip().lower() == b"proxy-authorization":
                return hmac.compare_digest(value.strip(), want)
        return False

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
        with self._open_lock:                 # end open tunnels too, not only new connections
            socks, self._open = list(self._open), set()
        for sk in socks:
            try:
                sk.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sk.close()
            except OSError:
                pass

    def env(self) -> dict[str, str]:
        url = f"http://pf:{self.token}@127.0.0.1:{self.port}"
        out = {}
        for name in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"):
            out[name] = out[name.lower()] = url
        out["NO_PROXY"] = out["no_proxy"] = ""
        return out
