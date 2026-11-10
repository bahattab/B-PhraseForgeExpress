"""Plugin signatures (PRD FR-PLG-01 "optional detached signature").

A signed plugin carries plugin.sig next to plugin.toml:

    {"key": "<base64 Ed25519 public key>", "sig": "<base64 signature>"}

The signature covers a digest of every other file in the package (relative path and SHA-256,
sorted), so changing, adding or removing any file breaks it. Which publishers to trust is the
user's (Settings value plugins.trusted_keys, one base64 key per line, this PC only) or the
administrator's (policy plugins_require_signature).

States: "unsigned", "trusted" (valid, key trusted), "untrusted" (valid, unknown key) and
"invalid" (plugin.sig present but wrong, or a file changed): an invalid plugin is never installed.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

SIG_FILE = "plugin.sig"
_SKIP_DIRS = {"__pycache__", ".git"}


@dataclass(frozen=True)
class Signature:
    state: str                 # unsigned | trusted | untrusted | invalid
    key: str = ""              # base64 public key that signed it
    reason: str = ""

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.key) if self.key else ""


def fingerprint(key_b64: str) -> str:
    """Short form shown to people: first 16 hex digits of SHA-256 of the key, in groups of 4."""
    h = hashlib.sha256(base64.b64decode(key_b64)).hexdigest()[:16]
    return " ".join(h[i:i + 4] for i in range(0, 16, 4))


def digest(files: dict[str, bytes]) -> bytes:
    """files: {relative posix path: content}. plugin.sig itself is left out."""
    lines = [f"{p}\0{hashlib.sha256(data).hexdigest()}\n" for p, data in sorted(files.items()) if p != SIG_FILE]
    return hashlib.sha256("".join(lines).encode("utf-8")).digest()


def folder_files(folder: str | Path) -> dict[str, bytes]:
    folder = Path(folder)
    out = {}
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in files:
            if name.endswith(".pyc"):
                continue
            p = Path(root) / name
            out[p.relative_to(folder).as_posix()] = p.read_bytes()
    return out


def new_key() -> tuple[str, str]:
    """(private, public) base64 Ed25519 keys for a plugin author."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    k = Ed25519PrivateKey.generate()
    priv = k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                           serialization.NoEncryption())
    pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(priv).decode(), base64.b64encode(pub).decode()


def sign_folder(folder: str | Path, private_b64: str) -> str:
    """Write plugin.sig for the plugin in folder; returns the public key."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    k = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_b64))
    pub = base64.b64encode(k.public_key().public_bytes(serialization.Encoding.Raw,
                                                       serialization.PublicFormat.Raw)).decode()
    sig = base64.b64encode(k.sign(digest(folder_files(folder)))).decode()
    (Path(folder) / SIG_FILE).write_text(json.dumps({"key": pub, "sig": sig}), encoding="utf-8")
    return pub


def trusted_keys(text: str) -> frozenset[str]:
    return frozenset(line.strip() for line in (text or "").splitlines() if line.strip() and not line.startswith("#"))


def verify(files: dict[str, bytes], trusted: frozenset[str] | set[str] = frozenset()) -> Signature:
    raw = files.get(SIG_FILE)
    if raw is None:
        return Signature("unsigned")
    try:
        data = json.loads(raw.decode("utf-8"))
        key_b64, sig_b64 = str(data["key"]), str(data["sig"])
        key, sig = base64.b64decode(key_b64, validate=True), base64.b64decode(sig_b64, validate=True)
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        return Signature("invalid", reason="plugin.sig cannot be read")
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        Ed25519PublicKey.from_public_bytes(key).verify(sig, digest(files))
    except (InvalidSignature, ValueError):
        return Signature("invalid", key_b64, "the files do not match the signature")
    return Signature("trusted" if key_b64 in trusted else "untrusted", key_b64)
