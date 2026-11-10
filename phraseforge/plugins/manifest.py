"""plugin.toml: what a plugin is, what it adds and what it may do (FR-PLG-01).

    id = "hello"                     # lowercase letters, digits, - and _; also the macro namespace
    name = "Hello"
    version = "1.0.0"
    api_version = "1.0"              # PhraseForge plugin API; this PhraseForge speaks 1.x
    kinds = ["macro"]
    entry = "main.py"                # inside the plugin folder
    runtime = "python-subprocess"    # or "exe-subprocess"
    macros = ["greet", "shout"]      # {#hello.greet}, {#hello.shout}

    [permissions]
    network = ["api.example.com"]    # hosts it may reach
    filesystem = []                  # e.g. ["read:user-selected"]
    secrets = ["api_key"]            # values PhraseForge passes in on each call
    clipboard = false
    input = false                    # may press keys / move the mouse

Nothing in the file is run; a manifest with any problem is refused with the reason.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field

API_MAJOR = 1
KINDS = ("ai_engine", "translator", "macro", "importer", "exporter", "trigger_source")
RUNTIMES = ("python-subprocess", "exe-subprocess")
_ID = re.compile(r"[a-z][a-z0-9_-]{0,39}")
_MACRO = re.compile(r"[a-z][a-z0-9_]{0,39}")
_DEVICE = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}
ENGINE_KINDS = ("ai_engine", "translator")
ENGINE_LINE = "receive the text and images you send to AI or translation"


def valid_id(pid: str) -> bool:
    """A plugin id is also a folder name: no Windows device names such as CON or NUL (R104)."""
    return bool(_ID.fullmatch(pid or "")) and pid.split(".", 1)[0] not in _DEVICE


def describe_manifest(m) -> list[str]:
    """What the user is asked to accept: the declared needs, and for an AI or translation
    engine that it receives what is sent to it (R112)."""
    out = list(m.permissions.describe())
    if any(k in getattr(m, "kinds", ()) for k in ENGINE_KINDS):
        out = [x for x in out if x != "no special needs declared"] + [ENGINE_LINE]
    return out
_SEMVER = re.compile(r"\d+\.\d+(?:\.\d+)?(?:[-+][0-9A-Za-z.-]+)?")
_HOST = re.compile(r"(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*")
_SECRET = re.compile(r"[a-z][a-z0-9_]{0,39}")
FS_RIGHTS = ("read:user-selected", "write:user-selected", "read:any", "write:any")


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class Permissions:
    network: tuple[str, ...] = ()
    filesystem: tuple[str, ...] = ()
    secrets: tuple[str, ...] = ()
    clipboard: bool = False
    input: bool = False

    @property
    def privileged(self) -> bool:
        """What the plugin SAYS it needs beyond answering. Not enforced: every plugin runs as a
        program with the user's rights, so the trust gate treats every plugin as privileged
        (security R97); this only decides how the needs are described."""
        return bool(self.network or self.filesystem or self.input)

    def describe(self) -> list[str]:
        out = []
        if self.network:
            out.append("connect to: " + ", ".join(self.network))
        if self.filesystem:
            out.append("files: " + ", ".join(self.filesystem))
        if self.secrets:
            out.append("receive secrets: " + ", ".join(self.secrets))
        if self.clipboard:
            out.append("read and change the clipboard")
        if self.input:
            out.append("press keys and move the mouse")
        # not "nothing": the list is what the plugin declares, nothing enforces it (R97)
        return out or ["no special needs declared"]

    def wider_than(self, old: "Permissions") -> list[str]:
        """What these permissions add to old ([] = nothing new)."""
        out = []
        for name in ("network", "filesystem", "secrets"):
            extra = sorted(set(getattr(self, name)) - set(getattr(old, name)))
            if extra:
                out.append(f"{name}: " + ", ".join(extra))
        for name in ("clipboard", "input"):
            if getattr(self, name) and not getattr(old, name):
                out.append(name)
        return out


@dataclass(frozen=True)
class Manifest:
    id: str
    name: str
    version: str
    api_version: str
    kinds: tuple[str, ...]
    entry: str
    runtime: str
    permissions: Permissions = field(default_factory=Permissions)
    macros: tuple[str, ...] = ()
    description: str = ""


def _str(data, key, required=True) -> str:
    v = data.get(key)
    if v is None:
        if required:
            raise ManifestError(f"{key} is missing")
        return ""
    if not isinstance(v, str) or not v.strip():
        raise ManifestError(f"{key} must be a non-empty text")
    return v.strip()


def _list(data, key, pattern=None, allowed=None) -> tuple[str, ...]:
    v = data.get(key, [])
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ManifestError(f"{key} must be a list of texts")
    out = []
    for x in v:
        x = x.strip().lower() if pattern is _HOST else x.strip()
        if allowed is not None and x not in allowed:
            raise ManifestError(f"{key}: {x!r} is not one of {', '.join(allowed)}")
        if pattern is not None and not pattern.fullmatch(x):
            raise ManifestError(f"{key}: {x!r} is not allowed")
        if x in out:
            raise ManifestError(f"{key}: {x!r} is listed twice")
        out.append(x)
    return tuple(out)


def _bool(data, key) -> bool:
    v = data.get(key, False)
    if not isinstance(v, bool):
        raise ManifestError(f"{key} must be true or false")
    return v


def parse(text: str) -> Manifest:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"plugin.toml is not valid TOML: {e}") from None
    known = {"id", "name", "version", "api_version", "kinds", "entry", "runtime", "permissions", "macros",
             "description", "signature"}
    unknown = sorted(set(data) - known)
    if unknown:
        raise ManifestError(f"unknown key {unknown[0]!r}")
    pid = _str(data, "id")
    if not valid_id(pid):
        raise ManifestError("id may only hold lowercase letters, digits, - and _ (and start with a letter)")
    version = _str(data, "version")
    if not _SEMVER.fullmatch(version):
        raise ManifestError("version must look like 1.2.3")
    api = _str(data, "api_version")
    if not _SEMVER.fullmatch(api):
        raise ManifestError("api_version must look like 1.0")
    if int(api.split(".")[0]) != API_MAJOR:
        raise ManifestError(f"api_version {api} is not supported (this PhraseForge speaks {API_MAJOR}.x)")
    kinds = _list(data, "kinds", allowed=KINDS)
    if not kinds:
        raise ManifestError("kinds must name at least one kind")
    entry = _str(data, "entry").replace("\\", "/")
    parts = [x for x in entry.split("/") if x not in ("", ".")]
    if (entry.startswith("/") or re.match(r"^[A-Za-z]:", entry) or ".." in parts or not parts
            or entry.endswith("/")
            or any(":" in x or x.endswith((".", " ")) or x.split(".", 1)[0].lower() in _DEVICE for x in parts)):
        raise ManifestError("entry must be a file inside the plugin folder")   # also no NUL, x:ads (R104)
    runtime = _str(data, "runtime")
    if runtime not in RUNTIMES:
        raise ManifestError(f"runtime must be one of {', '.join(RUNTIMES)}")
    perms = data.get("permissions", {})
    if not isinstance(perms, dict):
        raise ManifestError("[permissions] must be a table")
    pk = sorted(set(perms) - {"network", "filesystem", "secrets", "clipboard", "input"})
    if pk:
        raise ManifestError(f"unknown permission {pk[0]!r}")
    permissions = Permissions(
        network=_list(perms, "network", _HOST), filesystem=_list(perms, "filesystem", allowed=FS_RIGHTS),
        secrets=_list(perms, "secrets", _SECRET), clipboard=_bool(perms, "clipboard"), input=_bool(perms, "input"))
    macros = _list(data, "macros", _MACRO)
    if "macro" in kinds and not macros:
        raise ManifestError("a macro plugin must list its macros")
    if macros and "macro" not in kinds:
        raise ManifestError('macros are listed but kinds has no "macro"')
    return Manifest(pid, _str(data, "name"), version, api, kinds, entry, runtime, permissions, macros,
                    str(data.get("description", "")))
