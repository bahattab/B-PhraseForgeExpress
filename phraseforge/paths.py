"""Where PhraseForge keeps its data. Override with the PHRASEFORGE_HOME env var."""
from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    base = os.environ.get("PHRASEFORGE_HOME") or os.path.join(
        os.environ.get("APPDATA", str(Path.home())), "PhraseForge"
    )
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return data_dir() / "phrases.db"


def backups_dir() -> Path:
    p = data_dir() / "backups"
    p.mkdir(exist_ok=True)
    return p
