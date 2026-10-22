"""Render popup / stats / about / clipboard / wizard to PNGs in reference/phraseforge/.

Run: C:\\venvs\\phraseforge\\Scripts\\python.exe tools\\render_ui5.py
Uses sample data in a temporary in-memory database (never your real phrases).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "reference" / "phraseforge"
OUT.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication  # noqa: E402

from phraseforge.db import Store  # noqa: E402
from phraseforge.models import Folder, Phrase, Trigger, TriggerKind  # noqa: E402
from phraseforge.ui import pe_style  # noqa: E402

app = QApplication(sys.argv)
pe_style.apply(app)
s = Store(":memory:")
names = ["Agents", "API Keys", "Code", "Design", "English", "Prompts", "Research Paper", "Search",
         "Writing", "عربي", "General", "Linux", "System"]
folders = {n: s.add_folder(Folder(n)) for n in names}
for i, n in enumerate(["Install skill", "Update skill", "Create skill and name it", "Refresh skills index"]):
    s.add_phrase(Phrase(n, "x", folder_id=folders["Agents"].id,
                        triggers=[Trigger(TriggerKind.AUTOTEXT, f"sk{i}#")] if i == 0 else []))
for n in ["Extract pdf file", "Make it portable", "MCP server configuration", "Organize files into subfolders",
          "Planner to analyze the request", "Provide skills, rules, workflows", "Think step by step",
          "Systematic problem solving", "Debug the problem step by step"]:
    s.add_phrase(Phrase(n, "x", triggers=[Trigger(TriggerKind.HOTKEY, "ctrl+alt+1")] if n.startswith("MCP") else []))
for t in ["git status", "https://example.com/docs", "Meeting moved to 3 pm"]:
    s.add_clipboard(t)
p = s.add_phrase(Phrase("Signature", "Best regards", folder_id=folders["General"].id))
s.record_use(p.id, app="outlook.exe", chars=1099588)
s.set_setting("stats.typing_speed", "156")
s.set_setting("stats.hourly_wage", "25")


def save(w, name):
    w.show()
    app.processEvents()
    w.grab().save(str(OUT / name))
    print("saved", name, w.width(), "x", w.height())


from phraseforge.ui.popup import PhrasePopup  # noqa: E402

pop = PhrasePopup(s)
pop.refresh()
pop.move(900, 0)
save(pop, "20_popup_menu.png")
item = next(pop.list.item(i) for i in range(pop.list.count()) if pop.list.item(i).text() == "Agents")
sub = pop.open_submenu(pop, item)
save(sub, "20_popup_submenu.png")
pop.close_from(1)
pop.search.setText("skill")
save(pop, "20_popup_quick_search.png")
pop.hide()

from phraseforge.ui.stats_window import StatsWindow  # noqa: E402
save(StatsWindow(s), "18_dialog_statistics.png")
from phraseforge.ui.about_dialog import AboutDialog  # noqa: E402
save(AboutDialog(), "18_dialog_about.png")
from phraseforge.ui.clipboard_window import ClipboardWindow  # noqa: E402
cw = ClipboardWindow(s)
cw.refresh()
save(cw, "21_clipboard_window.png")
from phraseforge.ui.wizard import FirstRunWizard  # noqa: E402
save(FirstRunWizard(s), "22_first_run_wizard.png")
from phraseforge.ui.icons import _pix  # noqa: E402
_pix(128).save(str(OUT / "00_app_icon.png"))
