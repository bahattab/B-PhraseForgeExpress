"""One plugin process: JSON-RPC 2.0 over stdin/stdout, one JSON message per line (FR-PLG-02).

The process gets a small environment (no inherited API keys or proxy settings) and its own
folder as working directory. Each call has a time limit; when it runs out the plugin gets a
"$/cancel" notification, two seconds of grace, and is then killed. A dead plugin is started
again on the next call. On Windows the process is put in a job object that kills it with
PhraseForge and caps its memory (default 512 MB).
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from phraseforge.plugins.manifest import Manifest

GRACE_S = 2.0
MEMORY_MB = 512
ENV_KEEP = ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH", "LANG", "PATHEXT", "COMSPEC")


class PluginError(Exception):
    pass


class PluginTimeout(PluginError):
    pass


def command(m: Manifest, folder: Path) -> list[str]:
    entry = str(folder / m.entry)
    if m.runtime == "exe-subprocess":
        return [entry]
    if getattr(sys, "frozen", False):            # the PhraseForge EXE runs Python plugins itself
        return [sys.executable, "--run-plugin", entry]
    return [sys.executable, "-I", "-X", "utf8", entry]


def _env() -> dict:
    env = {k: os.environ[k] for k in ENV_KEEP if k in os.environ}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PHRASEFORGE_PLUGIN_API"] = "1"
    return env


def _windows_job(proc: subprocess.Popen, memory_mb: int) -> object | None:
    """Kill-on-close job with a memory cap (best effort; None when it cannot be made)."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class EXTENDED(ctypes.Structure):
            _fields_ = [("Basic", BASIC), ("Io", IO_COUNTERS), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        job = k32.CreateJobObjectW(None, None)
        info = EXTENDED()
        info.Basic.LimitFlags = 0x2000 | 0x100 | 0x8      # KILL_ON_JOB_CLOSE | PROCESS_MEMORY | ACTIVE_PROCESS
        info.Basic.ActiveProcessLimit = 1                  # no child processes
        info.ProcessMemoryLimit = memory_mb * 1024 * 1024
        k32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info))
        k32.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(int(proc._handle)))
        return job
    except Exception:                                      # noqa: BLE001 - isolation is best effort
        return None


class PluginProcess:
    def __init__(self, manifest: Manifest, folder: str | Path, memory_mb: int = MEMORY_MB):
        self.manifest = manifest
        self.folder = Path(folder)
        self.memory_mb = memory_mb
        self.errors: deque[str] = deque(maxlen=100)        # shown in the Plugins window
        self._proc: subprocess.Popen | None = None
        self._job = None
        self._lock = threading.Lock()                      # one call at a time
        self._replies: queue.Queue = queue.Queue()
        self._next_id = 0

    # ------------------------------------------------------------ process
    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _start(self) -> None:
        flags = 0x08000000 if sys.platform == "win32" else 0       # CREATE_NO_WINDOW
        self._proc = subprocess.Popen(command(self.manifest, self.folder), cwd=str(self.folder), env=_env(),
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      creationflags=flags, bufsize=0)
        self._job = _windows_job(self._proc, self.memory_mb)
        self._replies = queue.Queue()
        proc, replies = self._proc, self._replies
        threading.Thread(target=self._read, args=(proc, replies), daemon=True,
                         name=f"plugin-{self.manifest.id}").start()
        threading.Thread(target=self._drain_stderr, args=(proc,), daemon=True).start()

    def _read(self, proc, replies) -> None:
        for raw in proc.stdout:
            try:
                msg = json.loads(raw.decode("utf-8"))
            except ValueError:
                self._error(f"not JSON: {raw[:200]!r}")
                continue
            if isinstance(msg, dict) and "id" in msg:
                replies.put(msg)
        replies.put(None)                                  # the process ended

    def _drain_stderr(self, proc) -> None:
        for line in proc.stderr:
            self._error(line.decode("utf-8", "replace").rstrip()[:500])

    def _error(self, text: str) -> None:
        self.errors.append(time.strftime("%Y-%m-%d %H:%M:%S ") + text)

    def stop(self) -> None:
        p, self._proc = self._proc, None
        if p is not None and p.poll() is None:
            try:
                p.stdin.close()
                p.wait(1)
            except Exception:                              # noqa: BLE001
                pass
            if p.poll() is None:
                p.kill()
                p.wait(5)

    def _send(self, msg: dict) -> None:
        self._proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
        self._proc.stdin.flush()

    # ------------------------------------------------------------ calls
    def call(self, method: str, params: dict | None = None, timeout: float = 5.0):
        with self._lock:
            if not self.running:
                self._start()
            self._next_id += 1
            rid = self._next_id
            try:
                self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
            except OSError as e:
                self.stop()
                raise PluginError(f"the plugin stopped: {e}") from None
            deadline = time.monotonic() + timeout
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    self._cancel(rid)
                    self._error(f"{method}: no answer in {timeout:g} s, stopped")
                    raise PluginTimeout("timeout")
                try:
                    msg = self._replies.get(timeout=left)
                except queue.Empty:
                    continue
                if msg is None:
                    self.stop()
                    self._error(f"{method}: the plugin ended")
                    raise PluginError("the plugin ended")
                if msg.get("id") != rid:
                    continue                               # a late answer to a cancelled call
                if "error" in msg:
                    err = msg["error"]
                    text = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                    self._error(f"{method}: {text}")
                    raise PluginError(text)
                return msg.get("result")

    def _cancel(self, rid: int) -> None:
        try:
            self._send({"jsonrpc": "2.0", "method": "$/cancel", "params": {"id": rid}})
        except OSError:
            pass
        end = time.monotonic() + GRACE_S
        while time.monotonic() < end:
            try:
                msg = self._replies.get(timeout=max(0.01, end - time.monotonic()))
            except queue.Empty:
                break
            if msg is None or msg.get("id") == rid:
                return                                     # it gave up (or ended) in time
        self.stop()                                        # still busy after the grace period
