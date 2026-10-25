"""Fast local file and program search ("Search files", Listary-style launcher).

Evidence basis (see docs/EVIDENCE.md): Listary is a keyword launcher. You type
fragments of a file or program name, results appear as you type, and Enter opens
the result. This is an original implementation built on public Python/Windows
APIs (os.scandir, os.startfile). It does not use any code from Listary.

How it stays fast:
- The index keeps every name lower-cased in ONE newline-separated string, so a
  query uses str.find (C speed) to jump from match to match instead of looping
  over every entry in Python. Offsets map back to entries through bisect.
- All query words must appear in the name, in any order ("rep 2026 pdf").
- Ranking: exact name > name starts with the query > a word starts with it >
  contained anywhere; then programs/shortcuts first, often-opened items, and
  shorter names.
"""
from __future__ import annotations

import bisect
import json
import logging
import os
import re
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

log = logging.getLogger(__name__)

DEFAULT_EXCLUDES = frozenset({
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".venv", "venv", "$recycle.bin",
    "system volume information", "windows", "winsxs", ".cache", ".tox", "site-packages",
})
PROGRAM_EXTS = frozenset({".exe", ".lnk", ".url", ".appref-ms", ".bat", ".cmd", ".msc"})
MAX_ENTRIES = 3_000_000
_WORD_SEP = re.compile(r"[\s_\-.()\[\]]+")


def default_roots() -> list[str]:
    """Start menus, Desktop, Documents, Downloads (the folders people launch from)."""
    env = os.environ
    home = Path.home()
    cands = [
        Path(env.get("APPDATA", home / "AppData/Roaming")) / "Microsoft/Windows/Start Menu",
        Path(env.get("PROGRAMDATA", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu",
        home / "Desktop", home / "Documents", home / "Downloads", home / "OneDrive",
    ]
    return [str(p) for p in cands if p.is_dir()]


@dataclass(frozen=True)
class Hit:
    path: str
    name: str
    is_dir: bool
    score: tuple


# ---- priorities (observed: Listary Options > File Search > Priorities, docs/menus/listary.md)
HIGH, NORMAL, RARE, SKIP = 0, 1, 2, 3
PRIORITY_WORDS = {"high": HIGH, "normal": NORMAL, "rare": RARE, "skip": SKIP}

# Listary's default rules as seen in the user's screenshot. Folder rules use environment
# variables; "re:" rules are regular expressions on the file name.
DEFAULT_PRIORITY_RULES = r"""normal: %APPDATA%\Microsoft\Internet Explorer
normal: %APPDATA%\Microsoft\Windows
normal: %ProgramData%\Microsoft\Windows\Start Menu
rare: %SystemDrive%\Windows.old
rare: %SystemDrive%\$WINDOWS.~BT
rare: %SystemDrive%\$Windows.~WS
rare: %ProgramData%
rare: %SystemRoot%
rare: %USERPROFILE%\AppData
rare: %ProgramW6432%
rare: %ProgramFiles(x86)%
rare: re:^\.
rare: re:^~
rare: re:^node_modules$
rare: re:^\$"""


@dataclass(frozen=True)
class PriorityRule:
    priority: int
    folder: str = ""                     # normalised lower-case path prefix
    regex: "re.Pattern | None" = None    # matched against the file name


def parse_priority_rules(text: str) -> list[PriorityRule]:
    """Lines 'high|normal|rare|skip: <folder>' or '...: re:<regex>'. Unknown lines are skipped."""
    rules: list[PriorityRule] = []
    for line in (text or "").splitlines():
        word, sep, target = line.strip().partition(":")
        prio = PRIORITY_WORDS.get(word.strip().lower())
        target = target.strip()
        if not sep or prio is None or not target:
            continue
        if target.lower().startswith("re:"):
            try:
                rules.append(PriorityRule(prio, regex=re.compile(target[3:], re.IGNORECASE)))
            except re.error:
                continue
        else:
            folder = os.path.expandvars(target)
            if "%" in folder:            # variable not defined on this PC
                continue
            rules.append(PriorityRule(prio, folder=os.path.normcase(os.path.normpath(folder)).rstrip("\\/")))
    return rules


def priority_of(path: str, name: str, rules: list[PriorityRule], inherited: int = NORMAL) -> int:
    """A name regex wins; then the longest matching folder rule; then the parent folder's
    priority (so everything inside a "rare" node_modules folder is rare too)."""
    for r in rules:
        if r.regex is not None and r.regex.search(name):
            return r.priority
    best, best_len = inherited, -1
    low = os.path.normcase(os.path.normpath(path))
    for r in rules:
        if r.folder and len(r.folder) > best_len and (low == r.folder or low.startswith(r.folder + os.sep)):
            best, best_len = r.priority, len(r.folder)
    return best


# ---- search filters (observed: Options > File Search > Filters, "Type keyword: to use search filters")
@dataclass(frozen=True)
class SearchFilter:
    keyword: str
    name: str
    exts: frozenset = frozenset()     # empty = any extension
    folders: bool = True
    files: bool = True
    search_in: str = ""               # only results under this folder


_EXT = {
    "doc": "doc docx odt rtf txt md pdf xls xlsx ods csv ppt pptx odp",
    "pic": "jpg jpeg png gif bmp tif tiff webp heic svg ico",
    "video": "mp4 mkv avi mov wmv webm flv m4v mpg mpeg",
    "audio": "mp3 wav flac aac ogg m4a wma opus",
}
# Names are Listary's; the keywords themselves are not visible in the screenshot (inferred).
DEFAULT_FILTERS = {
    "folder": SearchFilter("folder", "Folder", files=False),
    "file": SearchFilter("file", "File", folders=False),
    "doc": SearchFilter("doc", "Document", frozenset(_EXT["doc"].split()), folders=False),
    "pic": SearchFilter("pic", "Picture", frozenset(_EXT["pic"].split()), folders=False),
    "video": SearchFilter("video", "Video", frozenset(_EXT["video"].split()), folders=False),
    "audio": SearchFilter("audio", "Audio", frozenset(_EXT["audio"].split()), folders=False),
}


def parse_filters(text: str) -> dict[str, SearchFilter]:
    """Built-in filters plus user lines: 'keyword = Name; ext=pdf,docx; in=C:\\Docs; folders=0; files=1'."""
    out = dict(DEFAULT_FILTERS)
    for line in (text or "").splitlines():
        key, sep, rest = line.strip().partition("=")
        key = key.strip().lower().rstrip(":")
        if not sep or not key or " " in key:
            continue
        parts = [p.strip() for p in rest.split(";")]
        name, opts = parts[0] or key, {}
        for p in parts[1:]:
            k, _, v = p.partition("=")
            opts[k.strip().lower()] = v.strip()
        exts = frozenset(e.strip().lstrip(".").lower() for e in opts.get("ext", "").replace(" ", ",").split(",") if e.strip())
        out[key] = SearchFilter(key, name, exts, opts.get("folders", "1") != "0",
                                opts.get("files", "1") != "0", opts.get("in", ""))
    return out


def split_filter(query: str, filters: dict[str, SearchFilter]) -> tuple[SearchFilter | None, str]:
    """'doc: report 2026' -> (Document filter, 'report 2026'). Also 'doc:report'."""
    head, sep, rest = query.strip().partition(":")
    if sep and head.strip().lower() in filters and " " not in head.strip():
        return filters[head.strip().lower()], rest.strip()
    return None, query


class FileIndex:
    def __init__(self, roots: Iterable[str] | None = None, excludes: Iterable[str] = DEFAULT_EXCLUDES,
                 include_hidden: bool = False, history_file: Path | None = None,
                 priority_rules: list[PriorityRule] | None = None):
        self.roots = [r for r in (roots if roots is not None else default_roots()) if r]
        self.priority_rules = priority_rules or []
        self.excludes = {e.lower() for e in excludes}
        self.include_hidden = include_hidden
        self._lock = threading.Lock()
        self._blob = ""                 # "\n" + "\n".join(lower names) + "\n"
        self._starts: list[int] = []    # offset of each name inside _blob
        self._paths: list[str] = []
        self._names: list[str] = []
        self._dirs: bytearray = bytearray()
        self._prio: bytearray = bytearray()
        self.built_at = 0.0
        self.build_seconds = 0.0
        self.building = False
        self._history_file = history_file
        self._opens: dict[str, int] = self._load_history()

    # ------------------------------------------------------------ indexing
    def __len__(self) -> int:
        return len(self._paths)

    def build(self, on_done: Callable[["FileIndex"], None] | None = None) -> None:
        """Walk the roots and swap in the new index (blocking; see build_async)."""
        t0 = time.perf_counter()
        self.building = True
        names: list[str] = []
        paths: list[str] = []
        dirs = bytearray()
        prio = bytearray()
        rules = self.priority_rules
        seen: set[str] = set()
        stack = [(r, NORMAL) for r in self.roots if os.path.isdir(r)]
        while stack and len(paths) < MAX_ENTRIES:
            top, top_prio = stack.pop()
            try:
                with os.scandir(top) as it:
                    for e in it:
                        name = e.name
                        low = name.lower()
                        if not self.include_hidden and name.startswith("."):
                            continue
                        try:
                            is_dir = e.is_dir(follow_symlinks=False)
                        except OSError:
                            continue
                        if is_dir and (low in self.excludes or e.is_symlink()):
                            continue
                        if not self.include_hidden and sys.platform == "win32" and _hidden(e):
                            continue
                        p = e.path
                        key = p.lower()
                        if key in seen:
                            continue
                        seen.add(key)
                        pr = priority_of(p, name, rules, top_prio) if rules else NORMAL
                        if pr == SKIP:
                            continue
                        names.append(name)
                        paths.append(p)
                        dirs.append(1 if is_dir else 0)
                        prio.append(pr)
                        if is_dir:
                            stack.append((p, pr))
            except OSError:
                continue
        starts: list[int] = []
        pos = 1
        for n in names:
            starts.append(pos)
            pos += len(n) + 1
        blob = "\n" + "\n".join(n.lower().replace("\n", " ") for n in names) + "\n"
        with self._lock:
            self._blob, self._starts, self._paths, self._names, self._dirs = blob, starts, paths, names, dirs
            self._prio = prio
        self.built_at = time.time()
        self.build_seconds = time.perf_counter() - t0
        self.building = False
        log.info("file index: %d entries in %.2fs", len(paths), self.build_seconds)
        if on_done:
            on_done(self)

    def build_async(self, on_done: Callable[["FileIndex"], None] | None = None) -> threading.Thread:
        t = threading.Thread(target=self.build, args=(on_done,), name="file-index", daemon=True)
        t.start()
        return t

    # ------------------------------------------------------------ search
    def search(self, query: str, limit: int = 50, filt: SearchFilter | None = None) -> list[Hit]:
        words = [w for w in query.lower().replace("\n", " ").split() if w]
        if not words:
            return []
        with self._lock:
            blob, starts, paths, names, dirs = self._blob, self._starts, self._paths, self._names, self._dirs
            prio = self._prio
        if not starts:
            return []
        lead = max(words, key=len)          # rarest-looking word drives the scan
        others = [w for w in words if w is not lead]
        q = " ".join(words)
        found: dict[int, None] = {}
        i = blob.find(lead)
        while i != -1:
            k = bisect.bisect_right(starts, i) - 1
            if k not in found:
                name = blob[starts[k]: starts[k] + len(names[k])]
                if all(w in name for w in others):
                    found[k] = None
            nxt = starts[k + 1] if k + 1 < len(starts) else len(blob)
            i = blob.find(lead, max(i + 1, nxt))
        hits = []
        under = os.path.normcase(os.path.normpath(filt.search_in)) if filt and filt.search_in else ""
        for k in found:
            name = names[k]
            low = name.lower()
            if filt is not None:
                if (dirs[k] and not filt.folders) or (not dirs[k] and not filt.files):
                    continue
                if filt.exts and (dirs[k] or os.path.splitext(low)[1].lstrip(".") not in filt.exts):
                    continue
                if under and not os.path.normcase(paths[k]).startswith(under + os.sep):
                    continue
            stem = os.path.splitext(low)[0]
            if low == q or stem == q:
                rank = 0
            elif low.startswith(q):
                rank = 1
            elif all(any(part.startswith(w) for part in _WORD_SEP.split(low)) for w in words):
                rank = 2
            else:
                rank = 3
            program = os.path.splitext(low)[1] in PROGRAM_EXTS
            pr = prio[k] if k < len(prio) else NORMAL
            score = (pr, rank, 0 if program else 1, -self._opens.get(paths[k].lower(), 0), len(name), low)
            hits.append(Hit(paths[k], name, bool(dirs[k]), score))
        hits.sort(key=lambda h: h.score)
        return hits[:limit]

    # ------------------------------------------------------------ history
    def record_open(self, path: str) -> None:
        key = path.lower()
        self._opens[key] = self._opens.get(key, 0) + 1
        self._save_history()

    def _load_history(self) -> dict[str, int]:
        if not self._history_file or not self._history_file.is_file():
            return {}
        try:
            data = json.loads(self._history_file.read_text(encoding="utf-8"))
            return {str(k): int(v) for k, v in data.items()}
        except (OSError, ValueError, AttributeError):
            return {}

    def _save_history(self) -> None:
        if not self._history_file:
            return
        try:
            top = dict(sorted(self._opens.items(), key=lambda kv: -kv[1])[:2000])
            self._history_file.write_text(json.dumps(top), encoding="utf-8")
        except OSError:
            log.warning("could not save file search history", exc_info=True)


def _hidden(entry: os.DirEntry) -> bool:
    try:
        attrs = entry.stat(follow_symlinks=False).st_file_attributes  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        return False
    return bool(attrs & 0x2 or attrs & 0x4)   # FILE_ATTRIBUTE_HIDDEN | SYSTEM


DEFAULT_WEB_KEYWORDS = (
    "g=https://www.google.com/search?q={q}\n"
    "yt=https://www.youtube.com/results?search_query={q}\n"
    "wiki=https://en.wikipedia.org/w/index.php?search={q}\n"
    "maps=https://www.google.com/maps/search/{q}"
)


def parse_web_keywords(text: str) -> dict[str, str]:
    """'g=https://...{q}' lines -> {'g': url template}. Lines without {q} or '=' are skipped."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, url = line.strip().partition("=")
        key = key.strip().lower()
        if sep and key and " " not in key and "{q}" in url:
            out[key] = url.strip()
    return out


def web_search(query: str, keywords: dict[str, str]) -> tuple[str, str] | None:
    """'g weather riyadh' -> ('g', 'https://www.google.com/search?q=weather+riyadh')."""
    from urllib.parse import quote_plus
    key, _, rest = query.strip().partition(" ")
    tpl = keywords.get(key.lower())
    if not tpl or not rest.strip():
        return None
    return key.lower(), tpl.replace("{q}", quote_plus(rest.strip()))


class DoubleTap:
    """Detect a modifier key pressed twice on its own (Listary-style "double Ctrl").

    Feed every key event; returns True on the second clean tap. A tap is a press
    and release with no other key in between; both taps must fall within `window` s.
    """

    def __init__(self, vks: set[int], window: float = 0.4, clock: Callable[[], float] = time.monotonic):
        self.vks, self.window, self.clock = vks, window, clock
        self._down = False
        self._clean = False
        self._last_tap = -1.0

    def feed(self, vk: int, down: bool) -> bool:
        if vk not in self.vks:
            self._clean = False
            self._last_tap = -1.0
            self._down = False
            return False
        if down:
            if not self._down:          # ignore auto-repeat
                self._down, self._clean = True, True
            return False
        was_clean, self._down = self._down and self._clean, False
        if not was_clean:
            return False
        now = self.clock()
        if self._last_tap >= 0 and now - self._last_tap <= self.window:
            self._last_tap = -1.0
            return True
        self._last_tap = now
        return False


def parse_roots(text: str) -> list[str]:
    return [line.strip().strip('"') for line in text.splitlines() if line.strip()]


def open_path(path: str) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        import subprocess
        subprocess.Popen(["xdg-open", path])


def open_folder(path: str) -> None:
    """Open the containing folder with the item selected (Explorer /select)."""
    if sys.platform == "win32":
        import subprocess
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    else:
        open_path(os.path.dirname(path))


# ---- actions on a result (observed: Options > Actions, Ctrl+O in the search window)
BUILTIN_ACTIONS = ("open", "folder", "copy", "cut", "copy_path", "copy_name")
ACTION_TITLES = {
    "open": "Open", "folder": "Open Containing Folder", "copy": "Copy", "cut": "Cut",
    "copy_path": "Copy Path to Clipboard", "copy_name": "Copy File Name to Clipboard",
}


@dataclass(frozen=True)
class CustomAction:
    title: str
    program: str
    parameter: str = '"{path}"'
    workdir: str = ""


def parse_custom_actions(text: str) -> list[CustomAction]:
    """Lines 'Title = program | parameter | working directory'.

    {path} is the full path, {folder} its folder, {name} the file name.
    Example: 'Edit with VS Code = code | "{path}"'."""
    out = []
    for line in (text or "").splitlines():
        title, sep, rest = line.strip().partition("=")
        if not sep or not title.strip() or not rest.strip():
            continue
        parts = [p.strip() for p in rest.split("|")]
        out.append(CustomAction(title.strip(), parts[0], parts[1] if len(parts) > 1 and parts[1] else '"{path}"',
                                parts[2] if len(parts) > 2 else ""))
    return out


def expand_action(action: CustomAction, path: str) -> tuple[str, str, str]:
    """-> (program, parameters, working directory) with the placeholders filled in."""
    folder = path if os.path.isdir(path) else os.path.dirname(path)
    fill = lambda t: t.replace("{path}", path).replace("{folder}", folder).replace("{name}", os.path.basename(path))
    return fill(action.program), fill(action.parameter), fill(action.workdir) or folder


def run_custom_action(action: CustomAction, path: str) -> None:
    import shlex
    import subprocess
    prog, params, cwd = expand_action(action, path)
    args = [prog] + (shlex.split(params, posix=False) if params else [])
    args = [a[1:-1] if len(a) > 1 and a[0] == a[-1] == '"' else a for a in args]
    subprocess.Popen(args, cwd=cwd if os.path.isdir(cwd) else None)


# ---- keyword commands (observed: Options > Commands). Only safe ones are offered;
# shutdown and reboot from Listary's list are left out on purpose.
COMMANDS = {
    "opt": "Options (PhraseForge settings)",
    "rebuild": "Rebuild index",
    "cmd": "Command Prompt",
    "cmda": "Command Prompt (Admin)",
    "psh": "PowerShell",
    "psha": "PowerShell (Admin)",
    "uninstall": "Uninstall a Program",
    "connections": "Network Connections",
    "hosts": "Edit Hosts",
}


def match_commands(query: str) -> list[str]:
    q = query.strip().lower()
    if not q or " " in q:
        return []
    return [k for k in COMMANDS if k.startswith(q)]


def shell_execute(program: str, params: str = "", admin: bool = False, cwd: str | None = None) -> None:
    """Start a program through the Windows shell ("runas" asks for admin rights)."""
    if sys.platform != "win32":
        import subprocess
        subprocess.Popen([program] + ([params] if params else []))
        return
    import ctypes
    ctypes.windll.shell32.ShellExecuteW(None, "runas" if admin else "open", program, params or None,
                                        cwd or os.path.expanduser("~"), 1)


def run_command(key: str) -> bool:
    """Run a keyword command. "opt" and "rebuild" are handled by the window; returns False for them."""
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    if key in ("cmd", "cmda"):
        shell_execute("cmd.exe", admin=key == "cmda")
    elif key in ("psh", "psha"):
        shell_execute("powershell.exe", admin=key == "psha")
    elif key == "uninstall":
        shell_execute("control.exe", "appwiz.cpl")
    elif key == "connections":
        shell_execute("control.exe", "ncpa.cpl")
    elif key == "hosts":
        shell_execute("notepad.exe", os.path.join(sysroot, "System32", "drivers", "etc", "hosts"), admin=True)
    else:
        return False
    return True
