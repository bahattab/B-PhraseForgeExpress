"""Render every macro dialog to reference/phraseforge/macro_<kind>.png and check its macro text.

Usage: C:\\venvs\\phraseforge\\Scripts\\python.exe tools/render_macro_dialogs.py [kind ...]
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

from phraseforge.ui import pe_style  # noqa: E402
from phraseforge.ui.macro_dialog_kit import MacroDialog  # noqa: E402
from phraseforge.ui.macro_specs import SPECS  # noqa: E402
from phraseforge.ui.macro_ui import parse_token  # noqa: E402

app = QApplication(sys.argv[:1])
pe_style.apply(app)
out = ROOT / "reference" / "phraseforge"
out.mkdir(parents=True, exist_ok=True)
kinds = sys.argv[1:] or list(SPECS)
problems = 0
for kind in kinds:
    s = SPECS[kind]
    if s.direct:
        print(f"{kind:24} direct  {s.build({})}")
        continue
    d = MacroDialog(s)
    d.adjustSize()
    d.show()
    app.processEvents()
    d.grab().save(str(out / f"macro_{kind}.png"))
    text = d.build_text()
    ok = text.startswith("{#") and (parse_token(text) is not None or text.endswith(("{#endif}", "{#endloop}", "{#endform}")))
    problems += not ok
    print(f"{kind:24} {d.width()}x{d.height()}  {'OK ' if ok else 'BAD'} {text[:90]}")
    d.close()
print("problems:", problems)
