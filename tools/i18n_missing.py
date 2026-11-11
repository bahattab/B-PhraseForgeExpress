"""List UI strings that have no Arabic translation (PRD G-31: the extraction step).

Finds string literals given to the Qt calls that show text (labels, buttons, check boxes,
group boxes, menu actions, window titles, tooltips, placeholders, the settings helpers
_group/_row, message boxes, menu lists, tray notices) in phraseforge/ui and phraseforge/app.py,
and prints those that i18n.lookup() leaves in English. Text built at run time (f-strings) is
listed as a template with {} place-holders: add that template to i18n_ar.py.

    python tools/i18n_missing.py            # list them
    python tools/i18n_missing.py --count    # just the number
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CALLS = {"QLabel", "QPushButton", "QCheckBox", "QRadioButton", "QGroupBox", "QAction", "QToolButton",
         "addAction", "addMenu", "setWindowTitle", "setToolTip", "setPlaceholderText", "setText",
         "setTitle", "_group", "_row", "addTab", "setStatusTip"}
SKIP_PREFIX = ("{#", "http", "#", "<")
# shown as they are on purpose: names, examples of what to type, code
ALLOWED = {
    "© 2026 PhraseForge contributors", "SELECT name AS Description, body AS Content FROM phrases",
    "1234567890-abc.apps.googleusercontent.com", "GOCSPX-...", "\\s+([.,;:!?]) => \\1\n[Arabic]\nي => ی",
    "Microsoft OneNote", "Google Drive", "e.g. G:\\My Drive\\PhraseForge", "keepass.exe", "s",
    "sql01.company.local\\PHRASES", "CONTOSO\\Sales  /  ali  /  *", "MM-DD",
    "PhraseForge v{}", "{} ms", "{}, {}pt", "{} [F3]", "OneNote", "{} failed",
}


def _name(func) -> str:
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


BOXES = {"information", "warning", "question", "critical", "about"}       # QMessageBox.x(parent, title, text)
NOTICES = {"notify", "showMessage"}                                       # (title, text)


def _text(arg) -> str | None:
    """The literal, or the template of an f-string ("Saved to {}"), else None."""
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    if isinstance(arg, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in arg.values)
    return None


def _wanted(s: str) -> bool:
    if any("\u0600" <= c <= "\u06ff" for c in s):       # already Arabic
        return False
    return bool(s.strip()) and any(c.isalpha() for c in s.replace("{}", "")) and not s.startswith(SKIP_PREFIX)


def strings(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _name(node.func)
        if name in BOXES and getattr(getattr(node.func, "value", None), "id", "") == "QMessageBox":
            args, every = node.args[1:3], True
        elif name in NOTICES:
            args, every = node.args[:2], True
        elif name == "menu_with" and len(node.args) > 1 and isinstance(node.args[1], ast.List):
            args = [e.elts[0] for e in node.args[1].elts if isinstance(e, ast.Tuple) and e.elts]
            every = True
        elif name in CALLS:
            args, every = node.args[:2], False
        else:
            continue
        for arg in args:
            s = _text(arg)
            if s is None:
                continue
            if _wanted(s):
                yield s, node.lineno
            if not every:
                break


def missing() -> list[tuple[str, str, int]]:
    from phraseforge.ui import i18n
    files = sorted((ROOT / "phraseforge" / "ui").glob("*.py")) + [ROOT / "phraseforge" / "app.py"]
    out, seen = [], set()
    for f in files:
        if f.name.startswith("i18n"):
            continue
        for s, line in strings(f):
            if s in seen:
                continue
            seen.add(s)
            if i18n.lookup(s) == s and s.strip() != "PhraseForge" and s not in ALLOWED:
                out.append((s, f.relative_to(ROOT).as_posix(), line))
    return out


if __name__ == "__main__":
    rows = missing()
    if "--count" in sys.argv:
        print(len(rows))
    else:
        for s, f, line in rows:
            print(f"{f}:{line}: {s!r}")
        print(f"{len(rows)} strings without Arabic", file=sys.stderr)
