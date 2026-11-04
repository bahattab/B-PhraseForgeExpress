"""One PhraseForge per Windows user and data folder.

The first process owns a named mutex and listens on a local pipe (QLocalServer,
current user only). A second launch finds the mutex, sends its command line to
the first process and exits; the first process then shows its window. Two
installations with different data folders (PHRASEFORGE_HOME, portable copies,
tests) get different names and do not block each other.
"""
from __future__ import annotations

import ctypes
import getpass
import hashlib
import json
import sys
import time

import shiboken6
from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

ERROR_ALREADY_EXISTS = 183
ASFW_ANY = -1


def instance_name(data_dir: str) -> str:
    key = f"{getpass.getuser().lower()}|{str(data_dir).lower()}"
    return "PhraseForge-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _disconnect(*signals) -> None:
    for sig in signals:
        try:
            sig.disconnect()
        except (RuntimeError, TypeError):        # nothing connected
            pass


class SingleInstance(QObject):
    """acquire() -> True in the first process. In a later one, forward(argv) hands over."""
    message = Signal(list)          # argv sent by a later launch

    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self._mutex = None
        self._server: QLocalServer | None = None
        self._sockets: list[QLocalSocket] = []      # connections from later launches

    def acquire(self) -> bool:
        if sys.platform == "win32":
            k32 = ctypes.windll.kernel32
            k32.CreateMutexW.restype = ctypes.c_void_p
            k32.SetLastError(0)
            self._mutex = k32.CreateMutexW(None, False, "Local\\" + self.name)
            if self._mutex and k32.GetLastError() == ERROR_ALREADY_EXISTS:
                k32.CloseHandle(ctypes.c_void_p(self._mutex))
                self._mutex = None
                return False
        if sys.platform != "win32" and self._server_alive():
            return False                                # no mutex here: a live server means another instance
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.UserAccessOption)
        if not server.listen(self.name):
            QLocalServer.removeServer(self.name)        # stale socket file (non-Windows), nobody listens
            if not server.listen(self.name):
                return sys.platform == "win32"          # mutex is ours; run without the pipe
        server.newConnection.connect(self._on_connection)
        self._server = server
        return True

    def _server_alive(self) -> bool:
        sock = QLocalSocket()
        sock.connectToServer(self.name)
        alive = sock.waitForConnected(300)
        sock.abort()
        return alive

    def forward(self, argv: list[str], timeout_s: float = 3.0) -> bool:
        """Send argv to the running instance. Retries while it is still starting up."""
        if sys.platform == "win32":
            ctypes.windll.user32.AllowSetForegroundWindow(ASFW_ANY)   # let it raise its window
        payload = json.dumps(list(argv)).encode("utf-8") + b"\n"
        deadline = time.monotonic() + timeout_s
        while True:
            sock = QLocalSocket()
            sock.connectToServer(self.name)
            if sock.waitForConnected(300):
                sock.write(payload)
                ok = sock.waitForBytesWritten(1000)
                sock.disconnectFromServer()
                return ok
            if time.monotonic() > deadline:
                return False
            time.sleep(0.1)

    def _on_connection(self) -> None:
        while self._server is not None and (sock := self._server.nextPendingConnection()) is not None:
            self._sockets.append(sock)
            buf = bytearray()
            sock.readyRead.connect(lambda s=sock, b=buf: self._read(s, b))
            sock.disconnected.connect(lambda s=sock: self._drop(s))
            if sock.bytesAvailable():
                self._read(sock, buf)

    def _read(self, sock: QLocalSocket, buf: bytearray) -> None:
        buf.extend(bytes(sock.readAll()))
        if not buf.endswith(b"\n"):
            return
        try:
            argv = json.loads(buf.decode("utf-8"))
        except ValueError:
            argv = None
        if isinstance(argv, list):
            self.message.emit([str(a) for a in argv])
        sock.disconnectFromServer()

    # A socket must not keep Python slots once it goes away: if this object is destroyed
    # while a socket's deferred delete is still queued, the next event loop pass crashed
    # the process (access violation on Windows, segfault on Linux).
    def _drop(self, sock: QLocalSocket) -> None:
        if sock in self._sockets:
            self._sockets.remove(sock)
            _disconnect(sock.readyRead, sock.disconnected)
            sock.deleteLater()

    def release(self) -> None:
        """Close the pipe and delete its sockets now, leaving nothing queued behind."""
        for sock in self._sockets:
            if shiboken6.isValid(sock):
                _disconnect(sock.readyRead, sock.disconnected)
                sock.abort()
                shiboken6.delete(sock)
        self._sockets.clear()
        if self._server is not None:
            if shiboken6.isValid(self._server):
                _disconnect(self._server.newConnection)
                self._server.close()
                shiboken6.delete(self._server)
            self._server = None
        if self._mutex and sys.platform == "win32":
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(self._mutex))
            self._mutex = None
