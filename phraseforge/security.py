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
    files, query databases, change phrases, Windows-key shortcuts) do not run
    until the user approves the phrase. A trigger that fires on its own (time,
    window focus, clipboard) never asks: the phrase is skipped and logged.
"""
from __future__ import annotations

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
}


def privileged_reason(name: str, args: list[str], opts: dict[str, str]) -> str | None:
    """Why the call {#name args opts} needs an approved phrase, or None if it is harmless."""
    reason = PRIVILEGED.get(name)
    if reason is None:
        return None
    if name == "key":     # ordinary keys (enter, tab, ctrl+c) are fine; Win+R and friends are not
        chord = " ".join(args).lower()
        return reason if re.search(r"\b(l|r)?win\b", chord) else None
    if name == "mail" and not ({"send", "attach"} & set(opts)):
        return None       # only opens a draft for the user to check
    return reason


def scan_privileged(content: str) -> list[str]:
    """Reasons for every privileged macro written in `content` (static check used
    to decide whether to ask before expanding). The engine still checks each call
    at run time, which also covers phrases pulled in with {#insert}."""
    from phraseforge.macros.registry import REGISTRY, catalog
    catalog()                                     # make sure all commands are registered
    found: list[str] = []
    for m in re.finditer(r"\{#([A-Za-z][\w]*)([^{}]*)", content or ""):
        entry = REGISTRY.get(m.group(1).lower())
        if entry is None:
            continue
        name, rest = entry[0].name, m.group(2)
        if name == "key":
            reason = privileged_reason(name, [rest], {})
        elif name == "mail":
            opts = {o: "" for o in re.findall(r"-(\w+)", rest)}
            reason = privileged_reason(name, [], opts)
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
