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
MAX_LINE = 16 * 1024 * 1024        # one JSON-RPC message (R108)
MAX_STREAM = 4 * 1024 * 1024       # bytes a call may stream through $/progress
PIECE_COST = 64                    # counted per piece on top of its bytes, so 4 MB is also ~65k pieces
MAX_CALL_FACTOR = 10               # a streaming call ends after timeout * this, however lively
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
    # bytecode only from a private cache: a .pyc planted in the plugin's __pycache__ is never run (R118)
    return [sys.executable, "-I", "-X", "utf8", "-X", f"pycache_prefix={_pycache_dir()}", entry]


_PYCACHE: list[str] = []


def _pycache_dir() -> str:
    """A private folder (mkdtemp: new, this user only) made once per PhraseForge process."""
    if not _PYCACHE:
        import tempfile
        _PYCACHE.append(tempfile.mkdtemp(prefix="pf-pycache-"))
    return _PYCACHE[0]


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
        # the results are checked: a plugin that is not in its job runs without the limits (R110)
        if not job or not k32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info),
                                                      ctypes.sizeof(info)) \
                or not k32.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(int(proc._handle))):
            if job:
                k32.CloseHandle(wintypes.HANDLE(job))
            return None
        return job
    except Exception:                                      # noqa: BLE001
        return None


def _close_job(job) -> None:
    if job and sys.platform == "win32":
        try:
            import ctypes
            ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(job))
        except Exception:                                  # noqa: BLE001
            pass


class PluginProcess:
    def __init__(self, manifest: Manifest, folder: str | Path, memory_mb: int = MEMORY_MB, sandbox: bool = True):
        self.manifest = manifest
        self.folder = Path(folder)
        self.memory_mb = memory_mb
        self.errors: deque[str] = deque(maxlen=100)        # shown in the Plugins window
        self._proc: subprocess.Popen | None = None
        self._job = None
        self._lock = threading.Lock()                      # one call at a time
        self._replies: queue.Queue = queue.Queue()
        self._next_id = 0
        self._proxy = None                                 # netproxy.FilterProxy (FR-PLG-05)
        self.sandbox = sandbox                             # Windows: run at Low integrity (sandbox.py)

    # ------------------------------------------------------------ process
    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _start(self) -> None:
        flags = 0x08000000 if sys.platform == "win32" else 0       # CREATE_NO_WINDOW
        from phraseforge.plugins.netproxy import FilterProxy
        if self._proxy is None:                             # only the manifest's hosts are reachable
            self._proxy = FilterProxy(self.manifest.id, self.manifest.permissions.network, self._error)
            self._proxy.start()
        _close_job(self._job)                               # a restart: the old job's handle (R110)
        self._job = None
        env = dict(_env(), **self._proxy.env())
        # the frozen EXE runs plugins itself: its bytecode cache must be made by this (Medium)
        # process, not in the sandbox's writable temp, where one plugin could plant code for another
        env["PHRASEFORGE_PYCACHE"] = _pycache_dir()
        args = command(self.manifest, self.folder)
        if self.sandbox and sys.platform == "win32":
            from phraseforge.plugins import sandbox
            low_tmp = str(sandbox.low_temp_dir())
            env.update(TEMP=low_tmp, TMP=low_tmp)
            try:
                self._proc, self._job = sandbox.launch(args, str(self.folder), env,
                                                       lambda p: _windows_job(p, self.memory_mb))
            except Exception as e:                     # noqa: BLE001 - fail closed: never run it outside the sandbox
                self._error(f"the plugin could not be started in its sandbox: {e}")
                raise PluginError(f"the plugin could not be started in its sandbox: {e}") from None
        else:
            self._proc = subprocess.Popen(args, cwd=str(self.folder), env=env,
                                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                          creationflags=flags)
            self._job = _windows_job(self._proc, self.memory_mb)
            if sys.platform == "win32" and self._job is None:     # never run outside its job (R110)
                self.stop()
                self._error("the plugin could not be started in its limited job")
                raise PluginError("the plugin could not be started in its limited job")
        self._replies = queue.Queue()
        proc, replies = self._proc, self._replies
        threading.Thread(target=self._read, args=(proc, replies), daemon=True,
                         name=f"plugin-{self.manifest.id}").start()
        threading.Thread(target=self._drain_stderr, args=(proc,), daemon=True).start()

    def _read(self, proc, replies) -> None:
        try:
            while True:
                raw = proc.stdout.readline(MAX_LINE + 1)   # bounded: a reply without an end grew forever (R108)
                if not raw:
                    break
                if len(raw) > MAX_LINE:
                    self._error(f"a reply longer than {MAX_LINE // (1024 * 1024)} MB: the plugin was stopped")
                    proc.kill()
                    break
                try:
                    msg = json.loads(raw.decode("utf-8"))
                except Exception:                          # noqa: BLE001 - ValueError, RecursionError, ...
                    self._error(f"not JSON: {raw[:200]!r}")
                    continue
                if isinstance(msg, dict) and ("id" in msg or msg.get("method") == "$/progress"):
                    replies.put(msg)
        except Exception as e:                             # noqa: BLE001 - the reader must not die silently
            self._error(f"reading the plugin failed: {e}")
        replies.put(None)                                  # the process ended

    def _drain_stderr(self, proc) -> None:
        try:
            while True:
                line = proc.stderr.readline(4096)          # bounded too (R108)
                if not line:
                    break
                self._error(line.decode("utf-8", "replace").rstrip()[:500])
        except Exception:                                  # noqa: BLE001
            pass

    def _error(self, text: str) -> None:
        self.errors.append(time.strftime("%Y-%m-%d %H:%M:%S ") + text)

    @property
    def blocked_hosts(self) -> list[str]:
        """Connections the network filter refused (newest last)."""
        return list(self._proxy.denied) if self._proxy else []

    def stop(self) -> None:
        proxy, self._proxy = self._proxy, None
        if proxy is not None:
            proxy.stop()
        p, self._proc = self._proc, None
        job, self._job = self._job, None
        if p is not None and p.poll() is None:
            try:
                p.stdin.close()
                p.wait(1)
            except Exception:                              # noqa: BLE001
                pass
            if p.poll() is None:
                p.kill()
                p.wait(5)
        _close_job(job)                                    # one handle per start, not leaked (R110)

    def _send(self, msg: dict) -> None:
        proc = self._proc
        if proc is None:
            raise OSError("the plugin was stopped")
        try:
            proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
            proc.stdin.flush()
        except (ValueError, AttributeError) as e:          # stopped from another thread meanwhile
            raise OSError(str(e)) from None

    # ------------------------------------------------------------ calls
    def call(self, method: str, params: dict | None = None, timeout: float = 5.0, on_progress=None):
        """on_progress(text): called for each {"method": "$/progress", "params": {"id": <this
        call's id>, "text": "..."}} the plugin sends before its answer (streamed AI replies).
        Each piece restarts the timeout, up to timeout * MAX_CALL_FACTOR in all."""
        if not self._lock.acquire(timeout=timeout):        # another call still waits on it
            raise PluginTimeout("busy")
        try:
            return self._call(method, params, timeout, on_progress)
        finally:
            self._lock.release()

    def _call(self, method: str, params: dict | None, timeout: float, on_progress=None):
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
        hard_end = time.monotonic() + timeout * MAX_CALL_FACTOR
        streamed = 0
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
            if msg.get("method") == "$/progress":
                pp = msg.get("params") if isinstance(msg.get("params"), dict) else {}
                text = pp.get("text")
                if pp.get("id") != rid or not isinstance(text, str) or on_progress is None:
                    continue           # an earlier call, not text, or a call that did not ask to stream (R123)
                streamed += len(text.encode("utf-8", "replace")) + PIECE_COST   # many tiny pieces count too (R125)
                if streamed > MAX_STREAM:
                    self._cancel(rid)
                    self._error(f"{method}: streamed more than {MAX_STREAM // (1024 * 1024)} MB, stopped")
                    raise PluginError("the plugin sent too much text")
                try:
                    on_progress(text)
                except Exception:                      # noqa: BLE001 - a display error must not end the call
                    pass
                if text:                               # an empty piece is no progress (R123)
                    deadline = min(time.monotonic() + timeout, hard_end)
                continue
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
