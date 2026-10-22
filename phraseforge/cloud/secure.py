"""Encrypt small secrets (the Google sign-in token) with Windows DPAPI.

Only the same Windows user on the same PC can decrypt. Pure ctypes, no pywin32.
On other platforms the data is stored as-is (PhraseForge is Windows-only today).
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

_ENTROPY = b"PhraseForge.cloud.v1"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _take(blob: _Blob) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob.pbData)


def protect(data: bytes) -> bytes:
    if sys.platform != "win32":
        return data
    out = _Blob()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(_blob(data)), "PhraseForge", ctypes.byref(_blob(_ENTROPY)),
        None, None, 0x1, ctypes.byref(out))  # CRYPTPROTECT_UI_FORBIDDEN
    if not ok:
        raise OSError("CryptProtectData failed")
    return _take(out)


def unprotect(data: bytes) -> bytes:
    if sys.platform != "win32":
        return data
    out = _Blob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(_blob(data)), None, ctypes.byref(_blob(_ENTROPY)),
        None, None, 0x1, ctypes.byref(out))
    if not ok:
        raise OSError("CryptUnprotectData failed (token belongs to another user or PC)")
    return _take(out)
