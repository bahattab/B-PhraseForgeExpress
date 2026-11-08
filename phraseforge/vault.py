"""Encryption at rest for the phrase file (PRD G-04, FR-SEC-09).

An encrypted phrase file is never a SQLite file on disk. PhraseForge reads it into memory,
works on the in-memory database and writes it back encrypted a moment after every change
(db.py). File layout:

    b"PFVAULT1"  4-byte header length (big endian)  header (JSON)  12-byte nonce  ciphertext

The whole SQLite database is encrypted with AES-256-GCM under a random 256-bit data key; the
header is authenticated with it (associated data), so it cannot be swapped or edited. The data
key is stored in the header twice, wrapped:

    "dpapi"  by Windows DPAPI: only this Windows user on this PC can unwrap it, so the
             file opens without a question
    "pass"   by a passphrase (scrypt, then AES-256-GCM), optional: lets the file open on
             another PC or after Windows was reinstalled, or is the only way in when the
             user chose "always ask for the passphrase" (then there is no "dpapi" entry)

Outside Windows there is no DPAPI, so a passphrase is required.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sqlite3
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"PFVAULT1"
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 15, 8, 1
FAKE_DPAPI_FOR_TESTS = False          # tests on Linux switch on a stand-in for DPAPI


class VaultError(Exception):
    pass


class NeedPassphrase(VaultError):
    """The file can only be opened with its passphrase."""


class WrongPassphrase(VaultError):
    pass


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _unb64(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def _aes():
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM


def dpapi_available() -> bool:
    return sys.platform == "win32" or FAKE_DPAPI_FOR_TESTS


def _protect(data: bytes) -> bytes:
    if sys.platform == "win32":
        from phraseforge.cloud.secure import protect
        return protect(data)
    if FAKE_DPAPI_FOR_TESTS:
        return b"fake-dpapi:" + bytes(x ^ 0x5A for x in data)
    raise VaultError("Windows data protection is not available here; use a passphrase.")


def _unprotect(data: bytes) -> bytes:
    if sys.platform == "win32":
        from phraseforge.cloud.secure import unprotect
        return unprotect(data)
    if FAKE_DPAPI_FOR_TESTS and data.startswith(b"fake-dpapi:"):
        return bytes(x ^ 0x5A for x in data[len(b"fake-dpapi:"):])
    raise OSError("not protected for this user")


def _kek(passphrase: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=256 * 1024 * 1024, dklen=32)


@dataclass
class Key:
    """The data key and how it is wrapped in the file's header."""
    dek: bytes
    wraps: dict

    @classmethod
    def new(cls, passphrase: str | None = None, use_dpapi: bool = True) -> "Key":
        k = cls(secrets.token_bytes(32), {})
        k.rewrap(passphrase, use_dpapi)
        return k

    def rewrap(self, passphrase: str | None, use_dpapi: bool = True) -> None:
        """Replace the wrapped copies: DPAPI (if wanted and possible) and/or a passphrase."""
        wraps: dict = {}
        if use_dpapi and dpapi_available():
            wraps["dpapi"] = _b64(_protect(self.dek))
        if passphrase:
            salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
            kek = _kek(passphrase, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
            wraps["pass"] = {"salt": _b64(salt), "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P,
                             "nonce": _b64(nonce), "ct": _b64(_aes()(kek).encrypt(nonce, self.dek, b"pf-dek"))}
        if not wraps:
            raise VaultError("A passphrase is required on this PC.")
        self.wraps = wraps

    @property
    def has_passphrase(self) -> bool:
        return "pass" in self.wraps

    @property
    def opens_without_passphrase(self) -> bool:
        return "dpapi" in self.wraps


def is_encrypted(path: str | Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def _split(blob: bytes) -> tuple[bytes, dict, bytes, bytes]:
    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + 4:
        raise VaultError("This is not an encrypted PhraseForge file.")
    (n,) = struct.unpack(">I", blob[len(MAGIC):len(MAGIC) + 4])
    start = len(MAGIC) + 4
    aad = blob[:start + n]
    try:
        header = json.loads(blob[start:start + n].decode("utf-8"))
    except ValueError as e:
        raise VaultError("The encrypted phrase file is damaged.") from e
    body = blob[start + n:]
    return aad, header, body[:12], body[12:]


def header_of(path: str | Path) -> dict:
    return _split(Path(path).read_bytes())[1]


def unlock(header: dict, passphrase: str | None = None) -> Key:
    """The data key from a header: DPAPI first, then the passphrase."""
    wraps = header.get("wraps") or {}
    if passphrase is None and "dpapi" in wraps:
        try:
            return Key(_unprotect(_unb64(wraps["dpapi"])), wraps)
        except (OSError, ValueError):
            pass                              # another Windows user or PC: needs the passphrase
    w = wraps.get("pass")
    if not w:
        raise VaultError("This phrase file was encrypted for another Windows user or PC.")
    if passphrase is None:
        raise NeedPassphrase("This phrase file is protected by a passphrase.")
    kek = _kek(passphrase, _unb64(w["salt"]), int(w["n"]), int(w["r"]), int(w["p"]))
    try:
        dek = _aes()(kek).decrypt(_unb64(w["nonce"]), _unb64(w["ct"]), b"pf-dek")
    except Exception as e:                    # cryptography raises InvalidTag
        raise WrongPassphrase("Wrong passphrase.") from e
    return Key(dek, wraps)


def encrypt(data: bytes, key: Key) -> bytes:
    header = json.dumps({"v": 1, "alg": "AES-256-GCM", "wraps": key.wraps}, sort_keys=True).encode("utf-8")
    aad = MAGIC + struct.pack(">I", len(header)) + header
    nonce = secrets.token_bytes(12)
    return aad + nonce + _aes()(key.dek).encrypt(nonce, data, aad)


def decrypt(blob: bytes, key: Key) -> bytes:
    aad, _header, nonce, ct = _split(blob)
    try:
        return _aes()(key.dek).decrypt(nonce, ct, aad)
    except Exception as e:
        raise VaultError("The encrypted phrase file is damaged or was changed.") from e


def read(path: str | Path, key: Key | None = None, passphrase: str | None = None) -> tuple[bytes, Key]:
    """(SQLite database bytes, key) of an encrypted file."""
    blob = Path(path).read_bytes()
    if key is None:
        key = unlock(_split(blob)[1], passphrase)
    return decrypt(blob, key), key


def write(path: str | Path, data: bytes, key: Key) -> None:
    """Write atomically: a crash leaves the old file or the new one, never half of one."""
    p = Path(path)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(encrypt(data, key))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def no_wal(data: bytes) -> bytes:
    """A database image marked as WAL mode cannot be used in memory: mark it as a rollback journal."""
    if len(data) > 19 and data[18] == 2:
        data = bytearray(data)
        data[18] = data[19] = 1
        data = bytes(data)
    return data


def memory_db(data: bytes) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:", check_same_thread=False)
    con.deserialize(no_wal(data))
    return con


def connect(path: str | Path, key: Key | None = None, passphrase: str | None = None) -> sqlite3.Connection:
    """A connection to an in-memory copy of any phrase file, encrypted or not (read only use)."""
    if is_encrypted(path):
        return memory_db(read(path, key, passphrase)[0])
    return sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)


def wipe(path: str | Path) -> None:
    """Overwrite a plain file before deleting it, so its old pages are not left behind as easily.
    (On SSDs and journaling file systems old copies can survive anyway.)"""
    p = Path(path)
    try:
        size = p.stat().st_size
        with open(p, "r+b") as f:
            chunk = bytes(1 << 16)
            for _ in range(0, size, len(chunk)):
                f.write(chunk)
            f.truncate(size)
            f.flush()
            os.fsync(f.fileno())
        p.unlink()
    except FileNotFoundError:
        pass
