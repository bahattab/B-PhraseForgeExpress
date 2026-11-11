"""Check GitHub Releases for a newer PhraseForge (Help > Check for updates, and once a day
automatically unless turned off in Settings), and install it when it is signed (FR-APP-05).

Signed updates: the release build signs the setup program (tools/sign_release.py writes
<setup>.exe.sig: {"key", "sig"}, an Ed25519 signature of the file's SHA-256). PhraseForge
downloads both, checks that the key is one of UPDATE_KEYS (built into this program, never
taken from the download) and that the signature matches, and only then offers to run the
setup. Nothing installs without the user's click. While UPDATE_KEYS is empty, or a release
has no signature, PhraseForge only opens the download page, as before.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

RELEASES_API = "https://api.github.com/repos/bahattab/B-PhraseForgeExpress/releases/latest"
RELEASES_PAGE = "https://github.com/bahattab/B-PhraseForgeExpress/releases"
PROJECT_PATH = "/bahattab/B-PhraseForgeExpress"
# base64 Ed25519 public keys allowed to sign releases (see docs/releasing.md)
UPDATE_KEYS: frozenset[str] = frozenset()
MAX_SETUP = 400 * 1024 * 1024
SIG_SUFFIX = ".sig"


class UpdateError(Exception):
    pass


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
    if not re.fullmatch(r"[vV]?\d{1,5}(?:\.\d{1,5}){0,3}", tag):   # shown in dialogs: digits only (R150)
        raise OSError("the latest release has an unexpected tag")
    setup = next((a.get("browser_download_url") for a in data.get("assets") or []
                  if str(a.get("name", "")).lower().endswith(".exe") and "setup" in str(a.get("name", "")).lower()),
                 "")
    sig = next((a.get("browser_download_url") for a in data.get("assets") or []
                if setup and str(a.get("browser_download_url", "")) == setup + SIG_SUFFIX), "")
    return {"version": tag.lstrip("vV"), "url": safe_release_url(data.get("html_url")) or RELEASES_PAGE,
            "name": data.get("name") or tag, "setup_url": safe_release_url(setup),
            "sig_url": safe_release_url(sig)}


def can_install(rel: dict | None, keys=None) -> bool:
    """True when this release can be downloaded, verified and installed from inside PhraseForge."""
    keys = UPDATE_KEYS if keys is None else keys
    return bool(rel and keys and rel.get("setup_url") and rel.get("sig_url"))


def _statement(version: str, name: str, digest_hex: str) -> bytes:
    """What a release signature covers: the version and file name too, so an old signed setup
    cannot be offered as a new version, or under another name."""
    return json.dumps({"app": "PhraseForge", "version": version, "name": name, "sha256": digest_hex},
                      sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_file(path, sig_json: bytes, keys, version: str = "", current: str = "") -> str:
    """Raise UpdateError unless sig_json is a valid signature by one of keys over this file,
    its name and a version. Returns the signed version. With `version`, the signed one must be
    that version; with `current`, it must be newer than the running one."""
    import base64
    from pathlib import Path
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        data = json.loads(sig_json.decode("utf-8"))
        key_b64, sig_b64, signed_version = str(data["key"]), str(data["sig"]), str(data["version"])
        key, sig = base64.b64decode(key_b64, validate=True), base64.b64decode(sig_b64, validate=True)
    except (ValueError, KeyError, TypeError, UnicodeDecodeError, AttributeError):
        raise UpdateError("the signature file cannot be read") from None
    if key_b64 not in keys:
        raise UpdateError("the update is signed by a key this PhraseForge does not trust")
    try:
        Ed25519PublicKey.from_public_bytes(key).verify(
            sig, _statement(signed_version, Path(path).name, _sha256(path)))
    except (InvalidSignature, ValueError):
        raise UpdateError("the downloaded setup does not match its signature") from None
    if version and version_tuple(signed_version) != version_tuple(version):
        raise UpdateError(f"the setup is signed as v{signed_version}, not v{version}")
    if current and not is_newer(signed_version, current):
        raise UpdateError(f"the setup is v{signed_version}, not newer than this PhraseForge")
    return signed_version


def sign_file(path, private_b64: str, version: str) -> bytes:
    """The .sig content for a release file (tools/sign_release.py)."""
    import base64
    from pathlib import Path
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    k = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_b64))
    pub = base64.b64encode(k.public_key().public_bytes(serialization.Encoding.Raw,
                                                       serialization.PublicFormat.Raw)).decode()
    sig = k.sign(_statement(version, Path(path).name, _sha256(path)))
    return json.dumps({"key": pub, "version": version, "sig": base64.b64encode(sig).decode()}).encode()


def _fetch(url: str, dest, limit: int, opener, timeout: float, progress=None, cancelled=lambda: False) -> None:
    if not safe_release_url(url):
        raise UpdateError("the download link is not a release of this project")
    req = urllib.request.Request(url, headers={"User-Agent": "PhraseForge"})
    got = 0
    with opener(req, timeout=timeout) as resp, open(dest, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0) if getattr(resp, "headers", None) else 0
        if total > limit:
            raise UpdateError("the download is larger than expected")
        while True:
            if cancelled():
                raise UpdateError("cancelled")
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            got += len(chunk)
            if got > limit:
                raise UpdateError("the download is larger than expected")
            out.write(chunk)
            if progress:
                progress(got, total)


def download_verified(rel: dict, folder, opener=None, keys=None, progress=None,
                      cancelled=lambda: False, timeout: float = 15, current: str = ""):
    """Download the release's setup and signature into folder and verify them. Returns the
    setup's path; a file that fails the check is deleted. Raises UpdateError."""
    from pathlib import Path
    from urllib.parse import urlsplit
    keys = UPDATE_KEYS if keys is None else keys
    opener = opener or _release_opener().open
    if not can_install(rel, keys):
        raise UpdateError("this release cannot be installed from PhraseForge; use the download page")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    name = Path(urlsplit(rel["setup_url"]).path).name
    if not name.lower().endswith(".exe") or "/" in name or "\\" in name:
        raise UpdateError("unexpected setup file name")
    setup, sig = folder / name, folder / (name + SIG_SUFFIX)
    try:
        _fetch(rel["sig_url"], sig, 64 * 1024, opener, timeout)
        _fetch(rel["setup_url"], setup, MAX_SETUP, opener, timeout, progress, cancelled)
        verify_file(setup, sig.read_bytes(), keys, version=rel.get("version", ""), current=current)
    except BaseException:
        for f in (setup, sig):
            try:
                f.unlink()
            except OSError:
                pass
        raise
    return setup


DOWNLOAD_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")


def _release_opener():
    """urllib opener that follows a redirect only over https to GitHub's download hosts."""
    from urllib.parse import urlsplit

    class Redirects(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            u = urlsplit(newurl)
            if u.scheme != "https" or (u.hostname or "").lower() not in DOWNLOAD_HOSTS:
                raise UpdateError("the download was sent to another site")
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    return urllib.request.build_opener(Redirects)


def safe_release_url(url) -> str:
    """`url` if it is an https link into this project's releases on github.com, else "".
    The update notice opens it with one click, so a changed or spoofed API answer must not be
    able to send the user to another site or a file of someone else's."""
    from urllib.parse import urlsplit
    if not isinstance(url, str) or not url:
        return ""
    try:
        u = urlsplit(url)
    except ValueError:
        return ""
    if u.scheme != "https" or (u.hostname or "").lower() != "github.com" or u.port not in (None, 443):
        return ""
    if u.username or u.password or "\\" in url:
        return ""
    if not u.path.startswith(PROJECT_PATH + "/releases/"):
        return ""
    return url


def check_due(last_iso: str, now=None, hours: float = 24) -> bool:
    """True when the last automatic check is older than `hours` (or never happened)."""
    from datetime import datetime, timedelta
    now = now or datetime.now()
    try:
        return not last_iso or now - datetime.fromisoformat(last_iso) >= timedelta(hours=hours)
    except ValueError:
        return True
