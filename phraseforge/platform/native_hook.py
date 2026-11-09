"""Keyboard hook backed by pfhook.dll (native/pfhook/pfhook.c), PRD FR-INP-01/02.

The DLL runs the WH_KEYBOARD_LL callback in native code, so a busy Python (garbage
collection, a slow Qt slot) can no longer make every key on the PC lag or get the hook
removed by Windows. A Python thread here reads the DLL's queue and answers each key
within a short budget. Keys Python did not answer in time reach the program and are
reported with KeyEvent.late; the trigger manager adjusts for them.

make_keyboard_hook() picks this hook when the DLL loads and falls back to the Python
hook (keyboard_hook.KeyboardHook) otherwise.
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
from ctypes import wintypes as wt
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

DLL_NAME = "pfhook.dll"
EXPECTED_VERSION = 1

ST_DOWN, ST_INJECTED, ST_EXTENDED, ST_WAITED, ST_NATIVE = 0x01, 0x02, 0x04, 0x08, 0x10
M_SHIFT, M_CTRL, M_ALT, M_WIN = 1, 2, 4, 8
WHEN_ALWAYS, WHEN_DEGRADED = 1, 2
MOD_BITS = {"shift": M_SHIFT, "ctrl": M_CTRL, "alt": M_ALT, "win": M_WIN}

DEFAULT_BUDGET_MS = 40


class PFEvent(ctypes.Structure):
    _fields_ = [("seq", ctypes.c_uint32), ("vk", ctypes.c_uint32), ("scan", ctypes.c_uint32),
                ("flags", ctypes.c_uint32), ("time", ctypes.c_uint32), ("mods", ctypes.c_uint32),
                ("status", ctypes.c_uint32), ("nchars", ctypes.c_uint32), ("chars", ctypes.c_wchar * 8)]


class PFRule(ctypes.Structure):
    _fields_ = [("vk", ctypes.c_uint32), ("mods", ctypes.c_uint32), ("when", ctypes.c_uint32)]


class PFStats(ctypes.Structure):
    _fields_ = [("events", ctypes.c_uint64), ("waited", ctypes.c_uint64), ("timeouts", ctypes.c_uint64),
                ("dropped", ctypes.c_uint64), ("native_swallowed", ctypes.c_uint64),
                ("late_replies", ctypes.c_uint64), ("max_us", ctypes.c_uint32), ("p99_us", ctypes.c_uint32),
                ("degraded", ctypes.c_uint32), ("running", ctypes.c_uint32), ("hist", ctypes.c_uint32 * 32)]


def mods_to_bits(mods) -> int:
    return sum(bit for name, bit in MOD_BITS.items() if name in mods)


def bits_to_mods(bits: int) -> set[str]:
    return {name for name, bit in MOD_BITS.items() if bits & bit}


def _candidates() -> list[Path]:
    here = Path(__file__).resolve().parent
    out = [here / DLL_NAME]
    base = getattr(sys, "_MEIPASS", None)            # PyInstaller
    if base:
        out += [Path(base) / "phraseforge" / "platform" / DLL_NAME, Path(base) / DLL_NAME]
    return out


_lib = None
_lib_error = ""


def load_library():
    """The DLL with its function signatures set, or None (see library_error())."""
    global _lib, _lib_error
    if _lib is not None:
        return _lib
    if os.name != "nt":
        _lib_error = "not Windows"
        return None
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        _lib_error = "pfhook.dll is built for 64-bit Python only"
        return None
    path = next((p for p in _candidates() if p.is_file()), None)
    if path is None:
        _lib_error = f"{DLL_NAME} not found"
        return None
    try:
        lib = ctypes.CDLL(str(path))
        lib.pf_version.restype = ctypes.c_int
        if lib.pf_version() != EXPECTED_VERSION:
            _lib_error = f"{DLL_NAME} version {lib.pf_version()} (expected {EXPECTED_VERSION})"
            return None
        lib.pf_set_options.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_size_t]
        lib.pf_set_options.restype = None
        lib.pf_set_rules.argtypes = [ctypes.POINTER(PFRule), ctypes.c_int]
        lib.pf_set_rules.restype = ctypes.c_int
        lib.pf_start.argtypes = []
        lib.pf_start.restype = wt.DWORD
        lib.pf_stop.argtypes = []
        lib.pf_stop.restype = None
        lib.pf_next.argtypes = [ctypes.POINTER(PFEvent), wt.DWORD]
        lib.pf_next.restype = ctypes.c_int
        lib.pf_reply.argtypes = [ctypes.c_uint32, ctypes.c_int]
        lib.pf_reply.restype = ctypes.c_int
        lib.pf_stats.argtypes = [ctypes.POINTER(PFStats)]
        lib.pf_stats.restype = None
    except (OSError, AttributeError) as e:
        _lib_error = f"{DLL_NAME}: {e}"
        return None
    _lib = lib
    _lib_error = ""
    return lib


def library_error() -> str:
    return _lib_error


class NativeKeyboardHook:
    """Same interface as keyboard_hook.KeyboardHook: on_key(KeyEvent) -> True swallows the key.
    Extra: set_rules() (hotkey chords the DLL swallows by itself while Python is late) and stats()."""

    native = True

    def __init__(self, on_key: Callable, pass_foreign_injected: bool = True,
                 budget_ms: int = DEFAULT_BUDGET_MS, lib=None):
        self.on_key = on_key
        self.pass_foreign_injected = pass_foreign_injected
        self.budget_ms = budget_ms
        self._lib = lib if lib is not None else load_library()
        if self._lib is None:
            raise OSError(library_error() or f"{DLL_NAME} not available")
        self._thread: threading.Thread | None = None
        self._running = False
        self._rules: list[tuple[int, int, int]] = []

    # ---------------------------------------------------------------- control
    def start(self) -> None:
        if self._running:
            return
        from phraseforge.platform._win32 import INJECT_MAGIC
        self._lib.pf_set_options(int(self.budget_ms), 1 if self.pass_foreign_injected else 0, INJECT_MAGIC)
        self._push_rules()
        err = self._lib.pf_start()
        if err:
            raise OSError(f"pfhook: SetWindowsHookEx failed (error {err})")
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, name="pf-native-hook-reader", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._lib.pf_stop()
        if self._thread:
            self._thread.join(3)
        self._thread = None

    @property
    def running(self) -> bool:
        return self._running and bool(self._thread and self._thread.is_alive())

    def set_rules(self, rules) -> None:
        """rules: iterable of (vk, modifier names, when) with when WHEN_ALWAYS or WHEN_DEGRADED."""
        self._rules = [(int(vk), mods_to_bits(mods), int(when)) for vk, mods, when in rules]
        self._push_rules()

    def _push_rules(self) -> None:
        arr = (PFRule * max(1, len(self._rules)))()
        for i, (vk, mods, when) in enumerate(self._rules):
            arr[i].vk, arr[i].mods, arr[i].when = vk, mods, when
        self._lib.pf_set_rules(arr, len(self._rules))

    def stats(self) -> dict:
        s = PFStats()
        self._lib.pf_stats(ctypes.byref(s))
        return {"events": s.events, "waited": s.waited, "timeouts": s.timeouts, "dropped": s.dropped,
                "native_swallowed": s.native_swallowed, "late_replies": s.late_replies,
                "max_us": s.max_us, "p99_us": s.p99_us, "degraded": bool(s.degraded),
                "running": bool(s.running)}

    # ---------------------------------------------------------------- reader
    def event_from(self, raw: PFEvent):
        from phraseforge.platform.keyboard_hook import KeyEvent, finish_char
        from phraseforge.platform import keys as K
        down = bool(raw.status & ST_DOWN)
        char = None
        if down and raw.nchars and raw.vk not in K.MODIFIER_VKS:
            char = finish_char(raw.vk, raw.chars[:raw.nchars])
        return KeyEvent(vk=raw.vk, scan=raw.scan, char=char, down=down,
                        injected=bool(raw.status & ST_INJECTED), modifiers=bits_to_mods(raw.mods),
                        extended=bool(raw.status & ST_EXTENDED),
                        late=not (raw.status & ST_WAITED) and not (raw.status & ST_NATIVE),
                        native=bool(raw.status & ST_NATIVE))

    def handle(self, raw: PFEvent) -> None:
        """One queued event: ask on_key and answer the DLL if it is waiting."""
        swallow = False
        try:
            swallow = bool(self.on_key(self.event_from(raw)))
        except Exception:      # never leave the DLL waiting because of an error
            log.exception("keyboard hook callback failed")
        if raw.status & ST_WAITED and not self._lib.pf_reply(raw.seq, 1 if swallow else 0):
            # never the key itself: one key per stall built a log of what was typed (R93)
            log.debug("a key was answered after the %d ms budget; it was passed on", self.budget_ms)

    def _read_loop(self) -> None:
        raw = PFEvent()
        while self._running:
            r = self._lib.pf_next(ctypes.byref(raw), 250)
            if r < 0:
                break
            if r == 0:
                continue
            self.handle(raw)


def make_keyboard_hook(on_key: Callable, pass_foreign_injected: bool = True, prefer_native: bool = True,
                       budget_ms: int = DEFAULT_BUDGET_MS):
    """The native hook when pfhook.dll loads, else the Python hook. PHRASEFORGE_HOOK=python forces the latter."""
    if prefer_native and os.environ.get("PHRASEFORGE_HOOK", "").lower() != "python":
        try:
            return NativeKeyboardHook(on_key, pass_foreign_injected, budget_ms)
        except OSError as e:
            log.info("native keyboard hook not used: %s", e)
    from phraseforge.platform.keyboard_hook import KeyboardHook
    return KeyboardHook(on_key, pass_foreign_injected)
