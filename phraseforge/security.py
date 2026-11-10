"""Protection rules that span the app: password-locked folders and untrusted phrases.

Folder passwords
    A folder with a password, and everything below it, is locked until the user
    unlocks it in this session (main window, or the prompt shown when one of its
    phrases is triggered). Locked phrases do not expand without the password, do
    not show in the phrase menu or its search, and never appear as SmartComplete
    suggestions. LOCKS is shared by the main window, the phrase menu and the
    expansion code, so one unlock counts everywhere until PhraseForge exits.

Untrusted phrases
    Phrases that arrive through an import, or that a cloud sync pull added or
    changed, are put in quarantine (Store.quarantine_*). Their privileged macros
    (start programs, open files or web pages, network requests, send mail, write
    files, query databases, change phrases, Windows-key shortcuts, read a file
    from a network share, set variables that other phrases read) do not run
    until the user approves the phrase. A trigger that fires on its own (time,
    window focus, clipboard) never asks: the phrase is skipped and logged.
"""
from __future__ import annotations

import os
import re
import threading

# primary macro name -> what it can do (shown in the approval dialog)
PRIVILEGED: dict[str, str] = {
    "run": "start programs",
    "open": "open files, folders or web pages",
    "web": "open web pages",
    "http": "send or fetch data over the internet",
    "mail": "create or send e-mail",
    "outputfile": "write files",
    "dbquery": "query databases",
    "setphrase": "create or change phrases",
    "key": "press Windows-key shortcuts",
    # a click on the Start button or a dialog's "Run"/"Allow", then typed text and Enter,
    # starts programs just like Win+R (security R43)
    "mouse": "click, move or scroll the mouse in other programs",
    # a value an unapproved phrase leaves behind could become a trusted phrase's
    # {#run {#gettemp x}} argument (security R32); {#set -scope global} below likewise
    "settemp": "change variables other phrases use",
}

# Macros that read the file named by their first argument. Reading a local file is
# harmless, but on Windows opening \\host\share\file connects to that host over SMB
# and sends this user's NTLM credentials, so a network path needs an approved phrase.
FILE_READERS = frozenset({"textfile", "document", "csv", "image", "xls", "xlsfind", "sql", "pastefile",
                          "sound"})
NETWORK_READ = "read files from a network share"
_NETWORK_PATH = re.compile(r"^[\\/]{2}")          # \\host\share, //host/share, \\?\UNC\...
SCOPED_VARS = frozenset({"set", "unset"})          # -scope global (or any scope but local) is shared
_SCOPE = re.compile(r'-scope\s+["\']?([^\s"\'{}]*)')
_FIRST_ARG = re.compile(r'\s*("(?:[^"\\]|\\.)*"|\'[^\']*\'|[^\s"\']+)')


def is_network_path(path: str) -> bool:
    """True for a UNC / network path (after %VAR% expansion, quotes removed)."""
    p = os.path.expandvars((path or "").strip().strip("\"'").strip())
    return bool(_NETWORK_PATH.match(p))


def opens_system_ui(chord: str) -> bool:
    """True if a {#key} chord presses the Windows key (under any of its names: win, lwin,
    windows, meta, super, cmd, lwinkey, vk5b...) or Ctrl+Esc (the Start menu). Either one
    lets typed text start programs (Win+R, Start search + Enter)."""
    from phraseforge.macros.commands import _KEY_ALIASES
    from phraseforge.platform.keys import MODIFIER_ALIASES, key_name_to_vk
    names: list[str] = []
    for part in re.split(r"[+\s,]+", (chord or "").lower()):
        if not part:
            continue
        part = _KEY_ALIASES.get(part, part)
        mod = MODIFIER_ALIASES.get(part)
        if mod:
            names.append(mod)
            continue
        try:
            vk = key_name_to_vk(part)
        except (ValueError, TypeError):
            names.append(part)
            continue
        names.append("win" if vk in (0x5B, 0x5C) else "esc" if vk == 0x1B else part)
    return "win" in names or ("ctrl" in names and "esc" in names)


def privileged_reason(name: str, args: list[str], opts: dict[str, str]) -> str | None:
    """Why the call {#name args opts} needs an approved phrase, or None if it is harmless."""
    if name in FILE_READERS:
        return NETWORK_READ if args and is_network_path(str(args[0])) else None
    if name in ("ai", "translate") and plugin_engine(opts.get("provider", "")):
        return PLUGIN_ENGINE_REASON   # the text and images go to plugin code (security R98)
    if name == "ai":      # {#ai -image file:\\host\share\x.png} reads a network file
        return NETWORK_READ if _ai_network_image(opts.get("image", "")) else None
    if name in SCOPED_VARS:
        return PRIVILEGED["settemp"] if opts.get("scope", "local") not in ("", "local") else None
    reason = PRIVILEGED.get(name)
    if reason is None:
        return None
    if name == "key":     # ordinary keys (enter, tab, ctrl+c) are fine; Win+R and friends are not
        return reason if opens_system_ui(" ".join(args)) else None
    if name == "mail" and not ({"send", "attach"} & set(opts)):
        return None       # only opens a draft for the user to check
    return reason


def _ai_network_image(spec: str) -> bool:
    return any(p.strip().lower().startswith("file:") and is_network_path(p.strip()[5:])
               for p in (spec or "").split("|"))


_AI_IMAGE = re.compile(r'-image\s+("[^"]*"|\S+)')

PLUGIN_REASON = "use plugins that may reach the internet, files or the keyboard"
PLUGIN_ENGINE_REASON = "send text or images to an AI or translation plugin"
_PROVIDER = re.compile(r'-provider\s+("[^"]*"|\S+)', re.IGNORECASE)


def plugin_engine(provider: str) -> bool:
    return (provider or "").strip().strip('"').lower().startswith("plugin:")


def _setting(key: str) -> str:
    """This PC's setting, for the engine a macro without -provider uses."""
    try:
        from phraseforge.plugins import manager as pm
        mgr = pm.current()
        store = getattr(mgr, "store", None) if mgr is not None else None
        return store.setting(key, "") if store is not None else ""
    except Exception:          # noqa: BLE001 - no store: nothing chosen
        return ""


def _whole_call(content: str, start: int) -> str:
    """The text of the macro call that opens at `start`, nested macros included (a nested
    {#clipboard} must not hide a later -provider option)."""
    depth, i = 0, start
    while i < len(content):
        c = content[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return content[start:i + 1]
        i += 1
    return content[start:]


def ai_provider_of(name: str, provider: str) -> str:
    """The engine {#ai}/{#translate} really uses: -provider, else the one chosen in Settings."""
    if provider:
        return provider
    if name == "translate":
        return _setting("translation.provider") or _setting("ai.provider")
    return _setting("ai.provider")


def scan_privileged(content: str) -> list[str]:
    """Reasons for every privileged macro written in `content` (static check used
    to decide whether to ask before expanding). The engine still checks each call
    at run time, which also covers phrases pulled in with {#insert}."""
    from phraseforge.macros.registry import REGISTRY, catalog
    catalog()                                     # make sure all commands are registered
    found: list[str] = []
    # every plugin macro, known or not: a plugin's declared permissions are not enforced, it
    # runs with the user's rights (security R97); an unknown one may be installed later
    if re.search(r"\{#[A-Za-z]\w*(?:-\w+)*\.[A-Za-z_]\w*", content or ""):
        found.append(PLUGIN_REASON)
    for m in re.finditer(r"\{#([A-Za-z][\w]*)([^{}]*)", content or ""):
        if m.group(2).startswith("."):                   # a plugin macro: handled above
            continue
        entry = REGISTRY.get(m.group(1).lower())
        if entry is None:
            continue
        name, rest = entry[0].name, m.group(2)
        if name == "key":
            reason = privileged_reason(name, [rest], {})
        elif name == "mail":
            opts = {o: "" for o in re.findall(r"-(\w+)", rest)}
            reason = privileged_reason(name, [], opts)
        elif name in SCOPED_VARS:
            scope = _SCOPE.search(rest)
            # a scope written as a macro ({#var s}) is only known at run time: ask anyway
            reason = privileged_reason(name, [], {"scope": scope.group(1) or "?"} if scope else {})
        elif name in ("ai", "translate"):
            whole = _whole_call(content, m.start())
            img = _AI_IMAGE.search(whole)
            prov = _PROVIDER.search(whole)
            o = {"image": img.group(1).strip('"')} if img and name == "ai" else {}
            o["provider"] = ai_provider_of(name, prov.group(1).strip('"') if prov else "")
            reason = privileged_reason(name, [], o)
        elif name in FILE_READERS:
            first = _FIRST_ARG.match(rest)
            reason = privileged_reason(name, [first.group(1)] if first else [], {})
        else:
            reason = PRIVILEGED.get(name)
        if reason and reason not in found:
            found.append(reason)
    return found


class FolderLocks:
    """Folders unlocked in this session. Behaves like a set of folder ids."""

    def __init__(self):
        self._ids: set[int] = set()
        self._lock = threading.Lock()

    def __contains__(self, folder_id) -> bool:
        with self._lock:
            return folder_id in self._ids

    def add(self, folder_id: int) -> None:
        with self._lock:
            self._ids.add(folder_id)

    def discard(self, folder_id: int) -> None:
        with self._lock:
            self._ids.discard(folder_id)

    def clear(self) -> None:
        with self._lock:
            self._ids.clear()

    def locked_folder(self, store, folder_id):
        """The outermost locked folder in the chain of `folder_id`, or None."""
        chain = getattr(store, "folder_chain", None)
        if folder_id is None or chain is None:
            return None
        for f in reversed(chain(folder_id)):
            if f.password_hash and f.id not in self:
                return f
        return None

    def is_locked(self, store, folder_id) -> bool:
        return folder_id is not None and self.locked_folder(store, folder_id) is not None

    def try_unlock(self, store, folder, password: str) -> bool:
        """Check `password`; on success remember the folder and upgrade an old hash."""
        from phraseforge.db import hash_password, needs_rehash, verify_password
        if not verify_password(password, folder.password_hash):
            return False
        if needs_rehash(folder.password_hash):
            folder.password_hash = hash_password(password)
            store.update_folder(folder)
        self.add(folder.id)
        return True


def protected(store, folder_id) -> bool:
    """True if `folder_id` or a parent folder has a password (locked or not)."""
    chain = getattr(store, "folder_chain", None)
    return folder_id is not None and chain is not None and any(f.password_hash for f in chain(folder_id))


LOCKS = FolderLocks()
