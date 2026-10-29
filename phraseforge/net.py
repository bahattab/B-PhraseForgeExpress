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

import httpx


class NetError(RuntimeError):
    pass


_proxy: str | None = None
# {#http} may not reach this PC, the local network or link-local/metadata addresses
# unless Settings > Network allows it: a phrase imported or synced from elsewhere
# must not be able to probe the LAN or call local services.
_allow_private = False


def is_private_host(host: str) -> bool:
    """True if `host` is, or resolves to, a loopback/private/link-local/reserved address."""
    host = (host or "").strip("[]")
    try:
        addrs = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except (socket.gaierror, UnicodeError):
        return False      # unresolvable here (e.g. only the proxy can resolve it): httpx reports it
    for a in addrs:
        ip = ipaddress.ip_address(a.split("%", 1)[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return True
    return False


def _guard(request: httpx.Request) -> None:
    """Runs before the first request and before every redirect."""
    if not _allow_private and is_private_host(request.url.host):
        raise NetError(f"blocked: {request.url.host} is a local or private address "
                       "(allow it in Settings > Network)")


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
        with httpx.Client(timeout=timeout_s, follow_redirects=True, event_hooks={"request": [_guard]},
                          **client_kwargs()) as c:
            r = c.request(method.upper(), url, headers=headers or {},
                          content=body.encode("utf-8") if body is not None else None)
    except httpx.HTTPError as e:
        raise NetError(str(e)) from e
    if r.status_code >= 400:
        raise NetError(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.text
