"""Check GitHub Releases for a newer PhraseForge (Help > Check for updates, and once a day
automatically unless turned off in Settings)."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

RELEASES_API = "https://api.github.com/repos/bahattab/B-PhraseForgeExpress/releases/latest"
RELEASES_PAGE = "https://github.com/bahattab/B-PhraseForgeExpress/releases"


def version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:4]) or (0,)


def is_newer(candidate: str, current: str) -> bool:
    return version_tuple(candidate) > version_tuple(current)


def latest_release(timeout: float = 6.0, opener=urllib.request.urlopen) -> dict | None:
    """{"version", "url", "name"} of the latest published release, or None when the
    repository has no release yet. Raises OSError when GitHub cannot be reached."""
    req = urllib.request.Request(RELEASES_API, headers={"Accept": "application/vnd.github+json",
                                                        "User-Agent": "PhraseForge"})
    try:
        with opener(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise OSError(f"GitHub answered {e.code}") from e
    tag = str(data.get("tag_name", ""))
    setup = next((a.get("browser_download_url") for a in data.get("assets") or []
                  if str(a.get("name", "")).lower().endswith(".exe") and "setup" in str(a.get("name", "")).lower()),
                 "")
    return {"version": tag.lstrip("vV"), "url": data.get("html_url") or RELEASES_PAGE,
            "name": data.get("name") or tag, "setup_url": setup or ""}


def check_due(last_iso: str, now=None, hours: float = 24) -> bool:
    """True when the last automatic check is older than `hours` (or never happened)."""
    from datetime import datetime, timedelta
    now = now or datetime.now()
    try:
        return not last_iso or now - datetime.fromisoformat(last_iso) >= timedelta(hours=hours)
    except ValueError:
        return True
