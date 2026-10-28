"""Prompt Tower: build AI prompts from many files of a project (context for coding agents).

PhraseForge's own implementation of the workflow of the "Prompt Tower" VS Code extension
(github.com/backnotprop/prompt-tower). No code was taken from it (it is AGPL-3.0); the
behaviour was described from its public documentation and settings, see
docs/PROMPT_TOWER_SPEC.md:

- pick files of a folder with checkboxes; .gitignore, .towerignore and a built-in list of
  folders that never belong in a prompt (.git, node_modules, build output...) are skipped
- the prompt = prefix text + project tree + one block per file + suffix text, shaped by
  templates with placeholders ({fileContent}, {rawFilePath}, {projectTree}, {blocks}...)
- live token estimate, warning for big files, optional removal of comments
- saved prompt sets ("templates": folder, files, prefix, suffix, format) and a history of
  prefix/suffix texts

This module has no Qt code so it can be tested on its own.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------- output format
DEFAULT_BLOCK = '<file name="{fileNameWithExtension}" path="{rawFilePath}">\n{fileContent}\n</file>'
DEFAULT_TREE = "<project_tree>\n{projectTree}\n</project_tree>\n"
DEFAULT_WRAPPER = "<context>\n{treeBlock}<project_files>\n{blocks}\n</project_files>\n</context>"
MARKDOWN_BLOCK = "### {rawFilePath}\n```{fileExtension}\n{fileContent}\n```"
MARKDOWN_TREE = "## Project tree\n```\n{projectTree}\n```\n"
MARKDOWN_WRAPPER = "{treeBlock}\n## Files\n\n{blocks}"

TREE_TYPES = ("full", "directories", "selected", "none")   # what the project tree shows


@dataclass
class OutputFormat:
    block: str = DEFAULT_BLOCK
    separator: str = "\n"
    trim_blank_lines: bool = True
    tree_type: str = "full"              # one of TREE_TYPES
    tree_sizes: bool = False
    tree_template: str = DEFAULT_TREE
    wrapper: str = DEFAULT_WRAPPER       # "" = no wrapper (blocks only)

    @classmethod
    def markdown(cls) -> "OutputFormat":
        return cls(block=MARKDOWN_BLOCK, separator="\n\n", tree_template=MARKDOWN_TREE, wrapper=MARKDOWN_WRAPPER)

    @classmethod
    def from_dict(cls, d: dict | None) -> "OutputFormat":
        f = cls()
        for k, v in (d or {}).items():
            if hasattr(f, k):
                setattr(f, k, v)
        if f.tree_type not in TREE_TYPES:
            f.tree_type = "full"
        return f


# ---------------------------------------------------------------- ignore rules
# Never useful in a prompt (version control, dependencies, build output, caches, binaries).
ALWAYS_IGNORE = [
    ".git/", ".svn/", ".hg/", ".vs/", ".idea/", ".vscode/", "__pycache__/", ".mypy_cache/",
    ".pytest_cache/", ".ruff_cache/", ".tox/", ".venv/", "venv/", "env/", "node_modules/",
    "bower_components/", "vendor/", "dist/", "build/", "out/", "target/", "bin/", "obj/",
    ".next/", ".nuxt/", ".gradle/", "coverage/", ".cache/", ".DS_Store", "Thumbs.db",
    "*.pyc", "*.pyo", "*.class", "*.o", "*.obj", "*.dll", "*.exe", "*.so", "*.dylib",
    "*.lock", "package-lock.json", "*.min.js", "*.min.css", "*.map", "*.log", "*.tmp",
    "*.zip", "*.7z", "*.rar", "*.gz", "*.tar", "*.png", "*.jpg", "*.jpeg", "*.gif", "*.bmp",
    "*.ico", "*.webp", "*.pdf", "*.mp3", "*.mp4", "*.wav", "*.avi", "*.mov", "*.ttf", "*.otf",
    "*.woff", "*.woff2", "*.db", "*.sqlite", "*.sqlite3",
]


class IgnoreRules:
    """A practical subset of .gitignore syntax: '#' comments, '!' negation, trailing '/'
    for folders only, leading '/' (or a '/' inside) to anchor at the root, '*', '?', '[]'
    and '**'. Later rules win, like in git."""

    def __init__(self, patterns: list[str] | None = None):
        self.rules: list[tuple[bool, bool, bool, re.Pattern]] = []   # (negate, dir_only, anchored, regex)
        for p in patterns or []:
            self.add(p)

    def add(self, line: str) -> None:
        line = line.rstrip("\n").rstrip()
        if not line or line.startswith("#"):
            return
        negate = line.startswith("!")
        if negate:
            line = line[1:]
        dir_only = line.endswith("/")
        line = line.strip("/") if dir_only else line
        anchored = line.startswith("/") or "/" in line.rstrip("/")
        line = line.lstrip("/")
        if line.startswith("**/"):
            line, anchored = line[3:], False
        self.rules.append((negate, dir_only, anchored, re.compile(_glob_to_regex(line))))

    def add_file(self, path: Path) -> None:
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                self.add(line)
        except OSError:
            pass

    def ignored(self, rel: str, is_dir: bool) -> bool:
        """rel: path relative to the root with '/' separators."""
        rel = rel.strip("/")
        name = rel.rsplit("/", 1)[-1]
        result = False
        for negate, dir_only, anchored, rx in self.rules:
            if dir_only and not is_dir:
                continue
            if rx.fullmatch(rel if anchored else name) or (not anchored and rx.fullmatch(rel)):
                result = not negate
        return result


def _glob_to_regex(pat: str) -> str:
    out, i = [], 0
    while i < len(pat):
        c = pat[i]
        if pat.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if pat.startswith("/**", i) and i + 3 == len(pat):
            out.append("/.*")
            i += 3
            continue
        if pat.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = pat.find("]", i + 1)
            if j == -1:
                out.append(re.escape(c))
            else:
                body = pat[i + 1:j].replace("\\", "\\\\")
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append(f"[{body}]")
                i = j
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


# ---------------------------------------------------------------- scanning
@dataclass
class Entry:
    rel: str            # "src/app.py" (always '/')
    is_dir: bool
    size: int = 0


def load_rules(root: Path, use_gitignore: bool = True, extra: str = "") -> IgnoreRules:
    rules = IgnoreRules(ALWAYS_IGNORE)
    if use_gitignore:
        rules.add_file(root / ".gitignore")
    rules.add_file(root / ".towerignore")
    for line in (extra or "").splitlines():
        rules.add(line)
    return rules


def scan(root: str | Path, rules: IgnoreRules | None = None, max_entries: int = 20000) -> list[Entry]:
    """Files and folders under root (sorted: folders first, then names), ignore rules applied.
    Nested .gitignore files are not read (only the root's), like most prompt tools."""
    root = Path(root)
    rules = rules or load_rules(root)
    out: list[Entry] = []

    def walk(d: Path, prefix: str) -> None:
        try:
            items = sorted(os.scandir(d), key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))
        except OSError:
            return
        for e in items:
            if len(out) >= max_entries:
                return
            is_dir = e.is_dir(follow_symlinks=False)
            rel = f"{prefix}{e.name}"
            if e.is_symlink() or rules.ignored(rel, is_dir):
                continue
            if is_dir:
                out.append(Entry(rel, True))
                walk(Path(e.path), rel + "/")
            else:
                try:
                    size = e.stat(follow_symlinks=False).st_size
                except OSError:
                    size = 0
                out.append(Entry(rel, False, size))
    walk(root, "")
    return out


def is_binary(data: bytes) -> bool:
    return b"\x00" in data[:4096]


def read_text(path: Path) -> str | None:
    """File text (UTF-8, then the Windows code page as fallback); None for binary files."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if is_binary(data):
        return None
    for enc in ("utf-8-sig", "cp1256", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


# ---------------------------------------------------------------- comments
_HASH = {".py", ".sh", ".bash", ".rb", ".pl", ".r", ".yaml", ".yml", ".toml", ".ps1", ".cfg", ".ini", ".conf"}
_SLASH = {".js", ".jsx", ".ts", ".tsx", ".java", ".c", ".h", ".cpp", ".hpp", ".cc", ".cs", ".go", ".rs",
          ".swift", ".kt", ".kts", ".scala", ".php", ".dart", ".css", ".scss", ".less", ".m", ".mm"}
_STRING = r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'|`(?:\\.|[^`\\])*`'


def remove_comments(text: str, ext: str) -> str:
    """Remove comments (strings are kept). Unknown file types are returned unchanged."""
    ext = ext.lower()
    if ext in _SLASH:
        rx = re.compile(_STRING + r"|//[^\n]*|/\*.*?\*/", re.S)
    elif ext in _HASH:
        rx = re.compile(r'"""(?:.|\n)*?"""|\'\'\'(?:.|\n)*?\'\'\'|' + _STRING + r"|#[^\n]*")
    elif ext in {".html", ".htm", ".xml", ".svg", ".vue"}:
        rx = re.compile(r"<!--.*?-->", re.S)
    elif ext == ".sql":
        rx = re.compile(_STRING + r"|--[^\n]*|/\*.*?\*/", re.S)
    else:
        return text

    def keep(m: re.Match) -> str:
        s = m.group(0)
        if s.startswith(("//", "/*", "#", "<!--", "--")):
            return "\n" * s.count("\n") if s.startswith(("/*", "<!--")) else ""
        return s
    out = rx.sub(keep, text)
    out = "\n".join(l.rstrip() for l in out.splitlines())
    return re.sub(r"\n{3,}", "\n\n", out)


# ---------------------------------------------------------------- tokens
def estimate_tokens(text: str) -> int:
    """Approximate token count for GPT/Claude/Gemini style tokenizers (about 4 characters per
    token for English and code, about 2 per token for Arabic and other non-Latin scripts).
    It is an estimate, not an exact count."""
    if not text:
        return 0
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    other = len(text) - ascii_chars
    return max(1, round(ascii_chars / 4 + other / 2))


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024 or unit == "MB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}MB"


# ---------------------------------------------------------------- building the prompt
def project_tree(entries: list[Entry], selected: set[str], tree_type: str = "full", sizes: bool = False,
                 root_name: str = "") -> str:
    """ASCII tree (├── └──) of the folder, of its folders only, or of the selected files only."""
    if tree_type == "selected":
        keep = set()
        for rel in selected:
            parts = rel.split("/")
            keep.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
        items = [e for e in entries if e.rel in keep]
    elif tree_type == "directories":
        items = [e for e in entries if e.is_dir]
    else:
        items = list(entries)
    children: dict[str, list[Entry]] = {}
    for e in items:
        parent = e.rel.rsplit("/", 1)[0] if "/" in e.rel else ""
        children.setdefault(parent, []).append(e)
    lines = [f"{root_name}/"] if root_name else []

    def draw(parent: str, indent: str) -> None:
        kids = children.get(parent, [])
        for i, e in enumerate(kids):
            last = i == len(kids) - 1
            name = e.rel.rsplit("/", 1)[-1] + ("/" if e.is_dir else "")
            if sizes and not e.is_dir:
                name += f" ({human_size(e.size)})"
            lines.append(f"{indent}{'└── ' if last else '├── '}{name}")
            if e.is_dir:
                draw(e.rel, indent + ("    " if last else "│   "))
    draw("", "")
    return "\n".join(lines)


def format_block(template: str, rel: str, root: Path, content: str, trim: bool = True) -> str:
    if trim:
        content = content.strip("\n")
        content = re.sub(r"^(?:[ \t]*\n)+", "", content)
    name = rel.rsplit("/", 1)[-1]
    stem, dot, ext = name.rpartition(".")
    values = {
        "{fileNameWithExtension}": name,
        "{fileName}": stem if dot else name,
        "{fileExtension}": ext if dot else "",
        "{rawFilePath}": "/" + rel,
        "{filePath}": "/" + rel,
        "{fullPath}": str(root / rel),
    }
    out = template
    for k, v in values.items():
        out = out.replace(k, v)
    return out.replace("{fileContent}", content)     # last: file text may contain "{...}"


@dataclass
class Result:
    text: str
    tokens: int
    files: int
    skipped: list[str] = field(default_factory=list)      # unreadable / binary files


def build_prompt(root: str | Path, selected: list[str], fmt: OutputFormat | None = None, prefix: str = "",
                 suffix: str = "", remove_comment_lines: bool = False, entries: list[Entry] | None = None,
                 now: datetime | None = None) -> Result:
    """The full prompt: prefix, wrapper(tree + file blocks), suffix."""
    root = Path(root).resolve()
    fmt = fmt or OutputFormat()
    entries = entries if entries is not None else scan(root)
    selected = [s for s in selected if s]
    blocks, skipped = [], []
    for rel in selected:
        text = read_text(root / rel)
        if text is None:
            skipped.append(rel)
            continue
        if remove_comment_lines:
            text = remove_comments(text, os.path.splitext(rel)[1])
        blocks.append(format_block(fmt.block, rel, root, text, fmt.trim_blank_lines))
    body = fmt.separator.join(blocks)
    tree_block = ""
    if fmt.tree_type != "none":
        tree = project_tree(entries, set(selected), fmt.tree_type, fmt.tree_sizes, root.name)
        tree_block = fmt.tree_template.replace("{projectTree}", tree)
    if fmt.wrapper:
        stamp = (now or datetime.now()).isoformat(timespec="seconds")
        out = fmt.wrapper
        for k, v in {"{treeBlock}": tree_block, "{timestamp}": stamp, "{fileCount}": str(len(blocks)),
                     "{workspaceRoot}": str(root), "{githubIssues}": "", "{githubPRs}": ""}.items():
            out = out.replace(k, v)
        out = out.replace("{blocks}", body)
    else:
        out = (tree_block + "\n" if tree_block else "") + body
    parts = [p for p in (prefix.strip(), out.strip("\n"), suffix.strip()) if p]
    text = "\n\n".join(parts)
    return Result(text, estimate_tokens(text), len(blocks), skipped)


# ---------------------------------------------------------------- saved sets and history
@dataclass
class PromptSet:
    """A saved prompt template: folder, chosen files, texts before/after, and format."""
    name: str
    root: str = ""
    files: list[str] = field(default_factory=list)
    prefix: str = ""
    suffix: str = ""
    remove_comments: bool = False
    format: dict = field(default_factory=dict)


class TowerStore:
    """Prompt sets and prefix/suffix history, kept in PhraseForge's settings table."""
    SETS, HISTORY = "prompttower.sets", "prompttower.history"
    HISTORY_MAX = 20

    def __init__(self, store):
        self.store = store

    def _load(self, key: str, default):
        try:
            v = json.loads(self.store.setting(key, "") or "null")
        except ValueError:
            v = None
        return v if isinstance(v, type(default)) else default

    def sets(self) -> list[PromptSet]:
        out = []
        for d in self._load(self.SETS, []):
            if isinstance(d, dict) and d.get("name"):
                out.append(PromptSet(**{k: v for k, v in d.items() if k in PromptSet.__dataclass_fields__}))
        return out

    def get(self, name: str) -> PromptSet | None:
        return next((s for s in self.sets() if s.name.lower() == (name or "").strip().lower()), None)

    def save(self, s: PromptSet) -> None:
        items = [x for x in self.sets() if x.name.lower() != s.name.lower()] + [s]
        self.store.set_setting(self.SETS, json.dumps([asdict(x) for x in items], ensure_ascii=False))

    def delete(self, name: str) -> None:
        items = [x for x in self.sets() if x.name.lower() != name.lower()]
        self.store.set_setting(self.SETS, json.dumps([asdict(x) for x in items], ensure_ascii=False))

    def history(self, kind: str) -> list[str]:
        return [x for x in self._load(self.HISTORY, {}).get(kind, []) if isinstance(x, str)]

    def remember(self, kind: str, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        h = self._load(self.HISTORY, {})
        items = [text] + [x for x in h.get(kind, []) if x != text]
        h[kind] = items[:self.HISTORY_MAX]
        self.store.set_setting(self.HISTORY, json.dumps(h, ensure_ascii=False))


def build_from_set(s: PromptSet) -> Result:
    """{#prompttower "name"}: the prompt of a saved set, read from the files as they are now."""
    root = Path(s.root)
    if not s.root or not root.is_dir():
        raise FileNotFoundError(f"Prompt Tower folder not found: {s.root}")
    rules = load_rules(root)
    entries = scan(root, rules)
    present = {e.rel for e in entries if not e.is_dir}
    files = [f for f in s.files if f in present]
    return build_prompt(root, files, OutputFormat.from_dict(s.format), s.prefix, s.suffix,
                        s.remove_comments, entries)


# Chat sites the prompt can be opened in (the prompt is on the clipboard; paste with Ctrl+V).
CHAT_SITES = {
    "ChatGPT": "https://chatgpt.com/",
    "Claude": "https://claude.ai/new",
    "Gemini": "https://gemini.google.com/app",
    "Google AI Studio": "https://aistudio.google.com/prompts/new_chat",
}
