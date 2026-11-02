"""HTTP helper for the {#http} macro, plus the proxy from Settings > Network.

configure(settings) is called at start and after Settings closes. It sets the
proxy used by every httpx call in PhraseForge (net, ai) and the HTTP(S)_PROXY
environment variables that the Google Drive client (httplib2/requests) honours.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import quote

import httpcore
import httpx


class NetError(RuntimeError):
    pass


_proxy: str | None = None
# {#http} may not reach this PC, the local network or link-local/metadata addresses
# unless Settings > Network allows it: a phrase imported or synced from elsewhere
# must not be able to probe the LAN or call local services.
_allow_private = False


# 100.64.0.0/10 (RFC 6598, carrier-grade NAT) is not "private" to Python's ipaddress, but it
# holds Tailscale hosts and some cloud metadata services (100.100.100.200).
_SHARED_SPACE = ipaddress.ip_network("100.64.0.0/10")


def is_private_ip(address: str) -> bool:
    """True for a loopback/private/link-local/reserved/multicast/unspecified address."""
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified or ip in _SHARED_SPACE)


def is_private_host(host: str) -> bool:
    """True if `host` is, or resolves to, a loopback/private/link-local/reserved address."""
    host = (host or "").strip("[]")
    try:
        addrs = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except (socket.gaierror, UnicodeError):
        return False      # unresolvable here (e.g. only the proxy can resolve it): httpx reports it
    return any(is_private_ip(a) for a in addrs)


def _blocked(host: str) -> NetError:
    return NetError(f"blocked: {host} is a local or private address (allow it in Settings > Network)")


def public_addresses(host: str, port: int) -> list[tuple]:
    """Resolve `host` once and return its socket addresses, or raise NetError if any of them is
    local/private. The caller must connect to one of these addresses and not resolve again: a
    DNS-rebinding server can give a public address to a first lookup and 127.0.0.1 to a second."""
    host = (host or "").strip("[]")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as e:
        raise NetError(f"cannot resolve {host}: {e}") from e
    if any(is_private_ip(info[4][0]) for info in infos):
        raise _blocked(host)
    return infos


class _PinnedBackend(httpcore.NetworkBackend):
    """httpcore network backend for {#http}: checks the addresses it connects to.

    httpx resolves the host itself when it connects, so checking the name beforehand
    (`_guard`) cannot stop DNS rebinding. Here the lookup, the check and the connection use
    the same addresses. TLS still verifies the certificate against the host name, because
    httpcore passes the URL's host as the server name, not the address we connect to."""

    def __init__(self, resolve=public_addresses):
        self._inner = httpcore.SyncBackend()
        self._resolve = resolve

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if _allow_private:
            return self._inner.connect_tcp(host, port, timeout=timeout, local_address=local_address,
                                           socket_options=socket_options)
        last: Exception | None = None
        for info in self._resolve(host, port):
            address = info[4][0]
            try:
                return self._inner.connect_tcp(address, port, timeout=timeout, local_address=local_address,
                                               socket_options=socket_options)
            except httpcore.ConnectError as e:      # try the next checked address
                last = e
        raise last or httpcore.ConnectError(f"no address for {host}")

    def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise NetError("unix sockets are not allowed")

    def sleep(self, seconds: float) -> None:
        self._inner.sleep(seconds)


def pinned_transport(resolve=public_addresses, **kwargs) -> httpx.HTTPTransport:
    """An httpx transport whose connections go only to addresses `resolve` checked."""
    t = httpx.HTTPTransport(**kwargs)
    pool = getattr(t, "_pool", None)
    if not isinstance(pool, httpcore.ConnectionPool):
        # httpx changed its internals: refuse rather than fall back to an unchecked connection
        raise NetError("network check unavailable in this httpx version")
    t._pool = httpcore.ConnectionPool(
        ssl_context=pool._ssl_context, max_connections=pool._max_connections,
        max_keepalive_connections=pool._max_keepalive_connections, keepalive_expiry=pool._keepalive_expiry,
        http1=pool._http1, http2=pool._http2, retries=pool._retries, local_address=pool._local_address,
        uds=pool._uds, socket_options=pool._socket_options, network_backend=_PinnedBackend(resolve))
    return t


def _guard(request: httpx.Request) -> None:
    """Runs before the first request and before every redirect. With a proxy this name check is
    all PhraseForge can do (the proxy resolves the name); without one, the pinned transport also
    checks the address actually connected to."""
    if not _allow_private and is_private_host(request.url.host):
        raise _blocked(request.url.host)


def proxy_url(settings: dict[str, str]) -> str | None:
    """'http://user:pass@server:port' from net.proxy_* settings, or None."""
    server = (settings.get("net.proxy_server") or "").strip()
    if not server:
        return None
    if "://" not in server:
        server = "http://" + server
    scheme, rest = server.split("://", 1)
    rest = rest.rstrip("/")
    port = (settings.get("net.proxy_port") or "").strip()
    if port and ":" not in rest.split("@")[-1]:
        rest = f"{rest}:{port}"
    user = (settings.get("net.proxy_user") or "").strip()
    if user:
        pw = settings.get("net.proxy_password") or ""
        rest = f"{quote(user, safe='')}:{quote(pw, safe='')}@{rest}"
    return f"{scheme}://{rest}"


def configure(settings: dict[str, str]) -> None:
    global _proxy, _allow_private
    _proxy = proxy_url(settings)
    _allow_private = (settings.get("net.allow_private_hosts") or "0") == "1"
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        if _proxy:
            os.environ[var] = _proxy
        else:
            os.environ.pop(var, None)


def current_proxy() -> str | None:
    return _proxy


def client_kwargs() -> dict:
    return {"proxy": _proxy} if _proxy else {}


def http_request(method: str, url: str, headers: dict[str, str] | None = None, body: str | None = None,
                 timeout_s: float = 30) -> str:
    if not url.lower().startswith(("http://", "https://")):
        raise NetError("only http(s) URLs are allowed")
    try:
        extra = client_kwargs() if _proxy else {"transport": pinned_transport()}
        first = httpx.URL(url)
        own = [h for h in (headers or {})]

        def same_site_headers(request: httpx.Request) -> None:
            # httpx drops Authorization on a redirect to another host but keeps the rest
            # (x-api-key, cookies...): a redirect must not carry the phrase's headers away.
            if (request.url.scheme, request.url.host, request.url.port) != (first.scheme, first.host, first.port):
                for h in own:
                    request.headers.pop(h, None)

        with httpx.Client(timeout=timeout_s, follow_redirects=True,
                          event_hooks={"request": [_guard, same_site_headers]}, **extra) as c:
            r = c.request(method.upper(), url, headers=headers or {},
                          content=body.encode("utf-8") if body is not None else None)
    except httpx.HTTPError as e:
        raise NetError(str(e)) from e
    if r.status_code >= 400:
        raise NetError(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.text
