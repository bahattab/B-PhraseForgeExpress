"""Small HTTP helper used by the {#http} macro."""
from __future__ import annotations

import httpx


class NetError(RuntimeError):
    pass


def http_request(method: str, url: str, headers: dict[str, str] | None = None, body: str | None = None,
                 timeout_s: float = 30) -> str:
    if not url.lower().startswith(("http://", "https://")):
        raise NetError("only http(s) URLs are allowed")
    try:
        r = httpx.request(method.upper(), url, headers=headers or {},
                          content=body.encode("utf-8") if body is not None else None,
                          timeout=timeout_s, follow_redirects=True)
    except httpx.HTTPError as e:
        raise NetError(str(e)) from e
    if r.status_code >= 400:
        raise NetError(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.text
