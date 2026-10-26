"""Screen and image OCR through Capture2Text's command-line tool.

Capture2Text is a separate GPLv3 program; we only start its CLI as a process.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

DEFAULT_CLI = r"C:\Program Files\00 - Capture2Text v4.6.3 - Arabic\Capture2Text_CLI.exe"
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW


class OCRError(RuntimeError):
    pass


class Capture2TextOCR:
    def __init__(self, cli_path: str = DEFAULT_CLI, timeout_s: float = 60):
        self.cli_path = cli_path or DEFAULT_CLI
        self.timeout_s = timeout_s

    def available(self) -> bool:
        return Path(self.cli_path).is_file()

    def _run(self, args: list[str]) -> str:
        if not self.available():
            raise OCRError(f"Capture2Text CLI not found: {self.cli_path}")
        # Capture2Text is a Qt5 app: our own Qt 6 env vars (QT_QPA_PLATFORM,
        # QT_PLUGIN_PATH...) would make it load the wrong plugins and crash.
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("QT_", "QML"))}
        try:
            proc = subprocess.run(
                [self.cli_path, *args], capture_output=True, timeout=self.timeout_s,
                cwd=str(Path(self.cli_path).parent), creationflags=_NO_WINDOW, env=env)
        except subprocess.TimeoutExpired as e:
            raise OCRError("Capture2Text timed out") from e
        out = proc.stdout.decode("utf-8", errors="replace")
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace").strip()
            raise OCRError(err or f"Capture2Text exited with code {proc.returncode}")
        return out

    def languages(self) -> list[str]:
        out = self._run(["--show-languages"])
        lines = [l.strip() for l in out.splitlines()]
        return [l for l in lines if l and not l.lower().startswith("installed")]

    def ocr_rect(self, x1: int, y1: int, x2: int, y2: int, language: str = "English",
                 keep_line_breaks: bool = True) -> str:
        if x2 <= x1 or y2 <= y1:
            raise OCRError("Empty capture rectangle")
        args = ["-s", f"{x1} {y1} {x2} {y2}", "-l", language, "--output-format", "${capture}"]
        if keep_line_breaks:
            args.append("-b")
        return self._clean(self._run(args))

    def ocr_image(self, path: str, language: str = "English", keep_line_breaks: bool = True) -> str:
        if not Path(path).is_file():
            raise OCRError(f"Image not found: {path}")
        args = ["-i", path, "-l", language, "--output-format", "${capture}"]
        if keep_line_breaks:
            args.append("-b")
        return self._clean(self._run(args))

    @staticmethod
    def _clean(text: str) -> str:
        return text.replace("\r\n", "\n").strip()


# ---- post-processing (modelled on Capture2Text's Settings > Replace and Output > Logging pages)

def parse_replace_rules(text: str) -> list[tuple[str | None, str, str]]:
    """Rules, one per line: ``regex => replacement``.

    A line ``[Arabic]`` starts a section whose rules apply only when OCR ran in that
    language; rules before any section apply to every language. Blank lines and lines
    starting with ``#`` are ignored. Bad regexes are skipped.
    """
    import re
    rules: list[tuple[str | None, str, str]] = []
    lang: str | None = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            lang = line[1:-1].strip() or None
            continue
        if "=>" not in raw:
            continue
        find, _, repl = raw.partition("=>")
        find, repl = find.strip(), repl.strip()
        if not find:
            continue
        try:
            re.compile(find)
        except re.error:
            continue
        rules.append((lang, find, repl.replace("\\n", "\n").replace("\\t", "\t")))
    return rules


def apply_replacements(text: str, rules, language: str = "") -> str:
    import re
    for lang, find, repl in rules:
        if lang is None or lang.lower() == (language or "").lower():
            text = re.sub(find, repl, text)
    return text


def format_log_entry(text: str, fmt: str = "${capture}${linebreak}", when=None) -> str:
    from datetime import datetime
    when = when or datetime.now()
    return ((fmt or "${capture}${linebreak}")
            .replace("${capture}", text)
            .replace("${linebreak}", "\n")
            .replace("${tab}", "\t")
            .replace("${timestamp}", when.strftime("%Y-%m-%d %H:%M:%S")))


def quick_languages(value: str) -> list[str]:
    """Up to three quick-access languages from 'Arabic, English, ...'."""
    out = []
    for part in (value or "").replace(";", ",").split(","):
        p = part.strip()
        if p and p not in out:
            out.append(p)
    return out[:3]
