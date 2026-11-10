"""Installed plugins on this PC: which are on, what they were allowed, calling them
(FR-PLG-04, FR-PLG-07, FR-PLG-08).

Settings (all of this PC only, see db.DEVICE_SETTING_PREFIXES):
  plugins.enabled            JSON list of plugin ids switched on
  plugins.granted.<id>       the permissions the user accepted (an update that asks for more
                             is switched off until accepted again)
  plugins.secret.<id>.<name> a secret the plugin declared, sealed like the API keys
The administrator's policy (plugins_allowed) can restrict which ids may run.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict
from pathlib import Path

from phraseforge import paths, policy
from phraseforge.plugins import install as inst
from phraseforge.plugins.host import PluginError, PluginProcess, PluginTimeout
from phraseforge.plugins.manifest import Manifest, Permissions

log = logging.getLogger(__name__)
MACRO_TIMEOUT_S = 5.0


def default_root() -> Path:
    return paths.data_dir() / "plugins"


def _perm_json(p: Permissions) -> str:
    return json.dumps({k: list(v) if isinstance(v, tuple) else v for k, v in asdict(p).items()}, sort_keys=True)


def _perm_from(js: str) -> Permissions | None:
    try:
        d = json.loads(js)
        return Permissions(**{k: tuple(v) if isinstance(v, list) else v for k, v in d.items()})
    except (ValueError, TypeError):
        return None


class PluginManager:
    def __init__(self, store, root: str | Path | None = None):
        self.store = store
        self.root = Path(root) if root is not None else default_root()
        self._procs: dict[str, PluginProcess] = {}
        self._lock = threading.Lock()
        self.load_errors: dict[str, str] = {}

    # ------------------------------------------------------------ what is installed
    def installed(self) -> dict[str, Manifest]:
        out, self.load_errors = {}, {}
        if not self.root.is_dir():
            return out
        for d in sorted(self.root.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            try:
                m = inst.inspect(d)
            except Exception as e:        # noqa: BLE001 - one broken plugin must not break all (R103)
                self.load_errors[d.name] = str(e)
                continue
            if m.id == d.name:
                out[m.id] = m
        return out

    def _enabled_ids(self) -> list[str]:
        try:
            v = json.loads(self.store.setting("plugins.enabled", "[]") or "[]")
        except ValueError:
            return []
        return [x for x in v if isinstance(x, str)]

    def granted(self, pid: str) -> Permissions | None:
        return _perm_from(self.store.setting(f"plugins.granted.{pid}", ""))

    def allowed_by_policy(self, pid: str) -> bool:
        pol = policy.current()
        allowed = pol.plugins_allowed
        if allowed is None:
            # a locked-down PC without an allow-list runs no plugins: they are programs (R102)
            return not (pol.settings_locked or pol.editing_disabled)
        return "*" in allowed or pid in allowed

    def is_enabled(self, pid: str) -> bool:
        m = self.installed().get(pid)
        if m is None or pid not in self._enabled_ids() or not self.allowed_by_policy(pid):
            return False
        g = self.granted(pid)
        return g is not None and not m.permissions.wider_than(g)

    # ------------------------------------------------------------ changes
    def preview(self, src) -> tuple[Manifest, list[str]]:
        """The manifest of a package and what it asks for beyond the installed version."""
        from phraseforge.plugins.manifest import ENGINE_KINDS, ENGINE_LINE, describe_manifest
        m = inst.inspect(src)
        g = self.granted(m.id)
        if g is None:
            return m, describe_manifest(m)
        new = m.permissions.wider_than(g)
        old = self.installed().get(m.id)
        if any(k in m.kinds for k in ENGINE_KINDS) and not (old and any(k in old.kinds for k in ENGINE_KINDS)):
            new.append(ENGINE_LINE)                     # it becomes an AI/translation engine (R112)
        return m, new

    def trusted_keys(self) -> frozenset[str]:
        """Publisher keys this PC trusts: Settings (plugins.trusted_keys) plus the policy's."""
        from phraseforge.plugins import signing
        pol = policy.current()
        if pol.plugins_require_signature:     # the administrator decides who is trusted, not the user
            return pol.plugins_trusted_keys
        return signing.trusted_keys(self.store.setting("plugins.trusted_keys", "")) | pol.plugins_trusted_keys

    def signature(self, src):
        """signing.Signature of a package, shown with the consent question."""
        return inst.signature(src, self.trusted_keys())

    def install(self, src, accept: bool, expected: Manifest | None = None) -> Manifest:
        """Install after the user accepted the permissions (accept must be True)."""
        if not accept:
            raise PermissionError("the plugin's permissions were not accepted")
        m = inst.inspect(src)
        if expected is not None and m != expected:
            raise PermissionError("the plugin changed after it was shown: install it again")   # R99
        if not self.allowed_by_policy(m.id):
            raise PermissionError("your administrator does not allow this plugin")
        was = self.installed().get(m.id)
        keep_off = was is not None and m.id not in self._enabled_ids()   # switched off by the user (R101)
        self.stop(m.id)
        inst.install(src, self.root, self.trusted_keys(), policy.current().plugins_require_signature)
        self.store.set_setting(f"plugins.granted.{m.id}", _perm_json(m.permissions))
        self.set_enabled(m.id, not keep_off)
        return m

    def set_enabled(self, pid: str, on: bool) -> None:
        ids = [x for x in self._enabled_ids() if x != pid] + ([pid] if on else [])
        self.store.set_setting("plugins.enabled", json.dumps(ids))
        if not on:
            self.stop(pid)

    def remove(self, pid: str) -> None:
        self.set_enabled(pid, False)
        inst.uninstall(pid, self.root)
        self.store.set_setting(f"plugins.granted.{pid}", "")
        # its secrets go too: another package with the same id must not receive them (R107)
        with self.store.lock, self.store.conn:
            self.store.conn.execute("DELETE FROM settings WHERE key LIKE ? ESCAPE '\\'",
                                    (f"plugins.secret.{pid.replace('_', chr(92) + '_')}.%",))

    def set_secret(self, pid: str, name: str, value: str) -> None:
        m = self.installed().get(pid)
        if m is None or name not in m.permissions.secrets:
            raise PluginError(f"{pid} does not declare a secret named {name}")
        self.store.set_setting(f"plugins.secret.{pid}.{name}", value)

    def _secrets(self, m: Manifest) -> dict[str, str]:
        """Only what the manifest declares (FR-PLG-04)."""
        return {n: self.store.setting(f"plugins.secret.{m.id}.{n}", "") for n in m.permissions.secrets}

    # ------------------------------------------------------------ processes
    def process(self, pid: str) -> PluginProcess:
        with self._lock:
            p = self._procs.get(pid)
            if p is None:
                m = self.installed()[pid]
                p = self._procs[pid] = PluginProcess(m, self.root / pid)
            return p

    def stop(self, pid: str) -> None:
        with self._lock:
            p = self._procs.pop(pid, None)
        if p is not None:
            p.stop()

    def stop_all(self) -> None:
        with self._lock:
            ids = list(self._procs)
        for pid in ids:
            self.stop(pid)

    def errors(self, pid: str) -> list[str]:
        p = self._procs.get(pid)
        return list(p.errors) if p is not None else []

    # ------------------------------------------------------------ macros
    def macro_manifest(self, pid: str, name: str) -> Manifest | None:
        m = self.installed().get(pid)
        if m is None or name not in m.macros or not self.is_enabled(pid):
            return None
        return m

    def call_macro(self, pid: str, name: str, args: list[str], opts: dict[str, str],
                   timeout: float = MACRO_TIMEOUT_S) -> str:
        m = self.macro_manifest(pid, name)
        if m is None:
            raise PluginError("no such plugin macro, or the plugin is switched off")
        try:
            res = self.process(pid).call("macro", {"name": name, "args": args, "opts": opts,
                                                   "secrets": self._secrets(m)}, timeout=timeout)
        except PluginTimeout:
            raise
        if isinstance(res, dict) and "text" in res:
            return str(res["text"])
        if isinstance(res, str):
            return res
        raise PluginError("the plugin answered without text")


_current: PluginManager | None = None


def current() -> PluginManager | None:
    return _current


def set_current(m: PluginManager | None) -> None:
    global _current
    _current = m
