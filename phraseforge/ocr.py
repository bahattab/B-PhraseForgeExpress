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
