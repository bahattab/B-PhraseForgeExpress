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

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

ERROR_ALREADY_EXISTS = 183
ASFW_ANY = -1


def instance_name(data_dir: str) -> str:
    key = f"{getpass.getuser().lower()}|{str(data_dir).lower()}"
    return "PhraseForge-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


class SingleInstance(QObject):
    """acquire() -> True in the first process. In a later one, forward(argv) hands over."""
    message = Signal(list)          # argv sent by a later launch

    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self._mutex = None
        self._server: QLocalServer | None = None

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
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.UserAccessOption)
        if not server.listen(self.name):
            QLocalServer.removeServer(self.name)        # stale socket file (non-Windows)
            if not server.listen(self.name):
                return sys.platform == "win32"          # mutex is ours; run without the pipe
        server.newConnection.connect(self._on_connection)
        self._server = server
        return True

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
            buf = bytearray()

            def read(s=sock, b=buf):
                b.extend(bytes(s.readAll()))
                if b.endswith(b"\n"):
                    try:
                        argv = json.loads(b.decode("utf-8"))
                    except ValueError:
                        argv = None
                    if isinstance(argv, list):
                        self.message.emit([str(a) for a in argv])
                    s.disconnectFromServer()

            sock.readyRead.connect(read)
            sock.disconnected.connect(sock.deleteLater)
            if sock.bytesAvailable():
                read()

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        if self._mutex and sys.platform == "win32":
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(self._mutex))
            self._mutex = None
