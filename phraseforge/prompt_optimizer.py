"""Prompt Optimizer: a conversation that turns a vague idea into a precise prompt.

PhraseForge's version of the "AI Prompt Optimizer" VS Code extension
(https://github.com/mhemdan/ai-prompt-optimizer, MIT): the assistant asks clarifying
questions when the request is vague and ends with an "Optimized Prompt:" section the user
copies; templates with {{variables}} start common tasks; the project's languages and
frameworks are added as context; answers are cached for an hour.

The extension's own system prompt contains unfinished placeholders ("[Previous guidelines
remain the same...]"), so PhraseForge uses its own complete instruction with the same
contract (the "Optimized Prompt:" marker). No Qt code here.
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

MARKER = "Optimized Prompt:"

SYSTEM_PROMPT = """You are an AI prompt optimizer. You help people write precise, effective prompts for AI \
coding assistants and chat assistants (for example Cursor, Claude Code, Copilot, ChatGPT). Requests can be \
feature implementation, bug fixes, code explanations, code reviews, writing or research tasks.

How to work:
1. If the request is vague or misses information that changes the result (goal, audience, tech stack, \
inputs and outputs, constraints, examples), ask at most 3 short clarifying questions, then stop and wait \
for the answers. Do not ask again about things the user already said.
2. When you have enough information (or the user says to continue), write the final prompt.
3. The final prompt must come after a line that is exactly "Optimized Prompt:". Everything after that \
line is copied by the user, so put nothing after the prompt.
4. The optimized prompt is self-contained and specific: the task, the context, requirements and \
constraints as lists, the expected output format, and how to check the result. Use the structure that \
fits the task, for example:
   - Feature: "Create [what] with the following specifications:" then Core features, Technical \
requirements, Constraints, Deliverables.
   - Bug fix: "Debug and fix [issue] with the following approach:" then Problem analysis (current and \
expected behaviour, steps to reproduce), Investigation, Fix requirements, Tests.
   - Explanation: "Explain [code or concept] with focus on:" then Structure, Key logic, Examples.
5. Write in the user's language (Arabic if the user writes Arabic). Keep placeholders in curly braces, \
such as {#clipboard}, exactly as written."""

CACHE_TTL_S = 60 * 60


def extract_optimized(reply: str) -> str:
    """The part of the reply after the last "Optimized Prompt:" line ("" when there is none)."""
    m = list(re.finditer(r"(?im)^[\s>*#_\"`]*optimized prompt\s*:[ \t*_`]*", reply or ""))
    if not m:
        return ""
    out = reply[m[-1].end():].strip()
    if out.startswith('"') and out.endswith('"') and len(out) > 1:
        out = out[1:-1].strip()
    return out


# ---------------------------------------------------------------- templates
@dataclass
class Template:
    id: str
    name: str
    description: str
    text: str                      # with {{variable}} placeholders

    @property
    def variables(self) -> list[str]:
        seen: list[str] = []
        for v in re.findall(r"\{\{\s*(\w+)\s*\}\}", self.text):
            if v not in seen:
                seen.append(v)
        return seen

    def fill(self, values: dict[str, str]) -> str:
        return re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: values.get(m.group(1), "").strip() or "(not specified)",
                      self.text)


BUILTIN_TEMPLATES = [
    Template("api-endpoint", "API endpoint", "Create an API endpoint with specific functionality",
             "Create an API endpoint that:\n- Method: {{method}}\n- Path: {{path}}\n- Functionality: "
             "{{functionality}}\n- Authentication: {{auth}}\n- Response format: {{response}}\n\nConsider:\n"
             "- Input validation\n- Error handling\n- Rate limiting\n- Security best practices"),
    Template("database-model", "Database model", "Create a database model with relationships",
             "Create a database model for:\n- Entity: {{entity}}\n- Properties: {{properties}}\n- Relationships: "
             "{{relationships}}\n- Constraints: {{constraints}}\n\nInclude:\n- Indexes\n- Validation rules\n"
             "- Migration approach"),
    Template("ui-component", "UI component", "Build a user-interface component",
             "Build a {{framework}} component named {{name}} that:\n- Purpose: {{purpose}}\n- Props / inputs: "
             "{{inputs}}\n- States and interactions: {{states}}\n\nRequirements:\n- Accessible (keyboard, screen "
             "readers, right-to-left text)\n- Responsive layout\n- Unit tests"),
    Template("bug-fix", "Bug fix", "Find and fix a bug",
             "Fix this bug:\n- What happens: {{actual}}\n- What should happen: {{expected}}\n- Steps to reproduce: "
             "{{steps}}\n- Error message or log: {{error}}\n\nFind the root cause before changing code, keep the fix "
             "small, and add a test that fails without the fix."),
    Template("code-review", "Code review", "Review code for problems",
             "Review the following code for correctness, security, performance and readability.\n- Language / "
             "framework: {{language}}\n- What the code should do: {{purpose}}\n\nList problems by severity, with "
             "the line and a concrete fix for each.\n\n{{code}}"),
]


def parse_templates(raw: str) -> list[Template]:
    """User templates (setting promptopt.templates): JSON list of {name, description, text}."""
    try:
        data = json.loads(raw or "[]")
    except ValueError:
        return []
    out = []
    for i, d in enumerate(data if isinstance(data, list) else []):
        if isinstance(d, dict) and d.get("name") and d.get("text"):
            out.append(Template(str(d.get("id") or f"user-{i}"), str(d["name"]), str(d.get("description", "")),
                                str(d["text"])))
    return out


# ---------------------------------------------------------------- project context
EXT_LANG = {".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript",
            ".java": "Java", ".kt": "Kotlin", ".cs": "C#", ".cpp": "C++", ".cc": "C++", ".c": "C", ".h": "C/C++",
            ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP", ".swift": "Swift", ".dart": "Dart",
            ".vue": "Vue", ".svelte": "Svelte", ".sql": "SQL", ".html": "HTML", ".css": "CSS", ".scss": "SCSS"}
JS_FRAMEWORKS = {"react": "React", "next": "Next.js", "vue": "Vue", "nuxt": "Nuxt", "svelte": "Svelte",
                 "@angular/core": "Angular", "express": "Express", "@nestjs/core": "NestJS", "electron": "Electron",
                 "react-native": "React Native", "tailwindcss": "Tailwind CSS", "jest": "Jest", "vitest": "Vitest"}
PY_FRAMEWORKS = {"django": "Django", "flask": "Flask", "fastapi": "FastAPI", "pyside6": "PySide6 (Qt)",
                 "pyqt5": "PyQt5", "pytest": "pytest", "pandas": "pandas", "numpy": "NumPy", "torch": "PyTorch",
                 "tensorflow": "TensorFlow", "sqlalchemy": "SQLAlchemy", "streamlit": "Streamlit"}


@dataclass
class ProjectContext:
    name: str = ""
    languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)

    def describe(self) -> str:
        if not (self.languages or self.frameworks):
            return ""
        parts = [f"Project: {self.name}"] if self.name else []
        if self.languages:
            parts.append("Languages: " + ", ".join(self.languages))
        if self.frameworks:
            parts.append("Frameworks and libraries: " + ", ".join(self.frameworks))
        return "\n".join(parts)


def analyze_project(root: str | Path, max_files: int = 3000) -> ProjectContext:
    """Main languages (by file count) and frameworks (package.json, requirements.txt,
    pyproject.toml) of a folder. Folders that never matter (node_modules, .git...) are skipped."""
    from phraseforge.prompttower import load_rules, scan
    root = Path(root)
    ctx = ProjectContext(root.name)
    if not root.is_dir():
        return ctx
    counts: Counter = Counter()
    for e in scan(root, load_rules(root), max_entries=max_files):
        if not e.is_dir:
            lang = EXT_LANG.get(Path(e.rel).suffix.lower())
            if lang:
                counts[lang] += 1
    ctx.languages = [l for l, _ in counts.most_common(4)]
    found: list[str] = []
    try:
        pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
        deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
        found += [v for k, v in JS_FRAMEWORKS.items() if k in deps]
    except (OSError, ValueError, AttributeError):
        pass
    py_text = ""
    for name in ("requirements.txt", "pyproject.toml", "setup.cfg"):
        try:
            py_text += (root / name).read_text(encoding="utf-8", errors="replace").lower() + "\n"
        except OSError:
            pass
    found += [v for k, v in PY_FRAMEWORKS.items() if re.search(rf"(?m)(^|[\s\"'\[,]){re.escape(k)}\b", py_text)]
    ctx.frameworks = list(dict.fromkeys(found))
    return ctx


def system_prompt(context: str = "") -> str:
    if not context:
        return SYSTEM_PROMPT
    return SYSTEM_PROMPT + "\n\nThe user's project (use it to make the prompt specific):\n" + context


# ---------------------------------------------------------------- conversation + cache
class ReplyCache:
    """Answers for identical conversations, kept for an hour (like the extension's cache)."""

    def __init__(self, ttl_s: float = CACHE_TTL_S, max_entries: int = 100, clock=time.monotonic):
        self.ttl, self.max, self.clock = ttl_s, max_entries, clock
        self.data: dict[str, tuple[float, str]] = {}

    @staticmethod
    def key(settings: dict, history: list[dict], system: str) -> str:
        return json.dumps([settings.get("ai.provider", ""), settings.get("ai.model", ""), system, history],
                          ensure_ascii=False, sort_keys=True)

    def get(self, k: str) -> str | None:
        hit = self.data.get(k)
        if hit and self.clock() - hit[0] < self.ttl:
            return hit[1]
        self.data.pop(k, None)
        return None

    def put(self, k: str, reply: str) -> None:
        if len(self.data) >= self.max:
            self.data.pop(next(iter(self.data)))
        self.data[k] = (self.clock(), reply)


_CACHE = ReplyCache()


class Conversation:
    def __init__(self, settings: dict[str, str], context: str = "", chat_fn=None, cache: ReplyCache | None = None):
        self.settings = settings
        self.context = context
        self.history: list[dict] = []
        self.cache = _CACHE if cache is None else cache
        if chat_fn is None:
            from phraseforge import ai

            def chat_fn(history, system):
                return ai.chat(settings, history, system=system, raw_system=True, max_tokens=2000)
        self.chat_fn = chat_fn

    def send(self, text: str, use_cache: bool = True) -> str:
        text = (text or "").strip()
        if not text:
            raise ValueError("empty message")
        self.history.append({"role": "user", "content": text})
        system = system_prompt(self.context)
        k = ReplyCache.key(self.settings, self.history, system)
        reply = self.cache.get(k) if use_cache else None
        if reply is None:
            try:
                reply = self.chat_fn(list(self.history), system)
            except Exception:
                self.history.pop()                 # let the user try the same message again
                raise
            self.cache.put(k, reply)
        self.history.append({"role": "assistant", "content": reply})
        return reply

    def optimized(self) -> str:
        """The newest optimized prompt in the conversation ("" if none yet)."""
        for m in reversed(self.history):
            if m["role"] == "assistant":
                out = extract_optimized(m["content"])
                if out:
                    return out
        return ""
