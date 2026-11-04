"""Run a shared-database sync: connect, check the tables, sync the mirror, disconnect.
One sync at a time per store; the app's timer and the Sync now button both use this."""
from __future__ import annotations

import logging
import threading
import time

from phraseforge.shared.connect import connect
from phraseforge.shared.mirror import Mirror, SyncResult
from phraseforge.shared.server import SharedError

log = logging.getLogger(__name__)

_LOCKS: dict[int, threading.Lock] = {}


def _lock(store) -> threading.Lock:
    return _LOCKS.setdefault(id(store), threading.Lock())


def enabled(store) -> bool:
    return store.setting("shared.enabled", "0") == "1"


def interval_s(store) -> int:
    try:
        return max(15, int(store.setting("shared.interval", "60") or 60))
    except ValueError:
        return 60


def sync(store, connectors: dict | None = None) -> SyncResult | None:
    """Sync now. None when another sync is still running."""
    lock = _lock(store)
    if not lock.acquire(blocking=False):
        return None
    try:
        server = connect(store.setting, connectors)
        try:
            if not server.ready():
                raise SharedError("The shared database has no PhraseForge tables yet. An administrator "
                                  "creates them with \"Create tables\" in the Shared database settings.")
            res = Mirror(store, server, store.setting("shared.root_name", "Shared") or "Shared").sync()
        finally:
            server.close()
        store.set_setting("shared.last_sync", time.strftime("%Y-%m-%d %H:%M:%S"))
        log.info("shared database sync as %s: %s", res.user, res.summary())
        return res
    finally:
        lock.release()


def create_tables(store, connectors: dict | None = None) -> str:
    """Set up the tables (administrator). Returns the login used."""
    server = connect(store.setting, connectors)
    try:
        server.ensure_schema()
        return server.user()
    finally:
        server.close()


def test_connection(store, connectors: dict | None = None) -> tuple[str, bool]:
    """(login the server sees, whether the tables exist)."""
    server = connect(store.setting, connectors)
    try:
        return server.user(), server.ready()
    finally:
        server.close()
