"""Render PhraseForge's QPainter app icon to packaging/build/phraseforge.ico.

The icon is drawn in code (phraseforge/ui/icons.py), so the .ico used for the
EXE and the installer is generated at build time instead of being committed.
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from phraseforge.ui.icons import _pix  # noqa: E402

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def main() -> int:
    app = QApplication.instance() or QApplication([])  # noqa: F841 - needed for QPixmap
    out = ROOT / "packaging" / "build" / "phraseforge.ico"
    out.parent.mkdir(parents=True, exist_ok=True)
    images = []
    for s in SIZES:
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        _pix(s).save(buf, "PNG")
        images.append(Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA"))
    big = images[-1]
    big.save(out, format="ICO", sizes=[(s, s) for s in SIZES],
             append_images=images[:-1])
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
