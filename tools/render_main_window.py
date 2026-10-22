"""Render PhraseForge main-window states to reference/phraseforge/*.png for comparison
with reference/phraseexpress. Uses a throwaway in-memory database with sample data.

Run: C:\\venvs\\phraseforge\\Scripts\\python.exe tools\\render_main_window.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "reference" / "phraseforge"
OUT.mkdir(parents=True, exist_ok=True)

from PySide6.QtCore import QPoint, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from phraseforge.db import Store  # noqa: E402
from phraseforge.models import Folder, Phrase, Trigger, TriggerKind  # noqa: E402


def sample_store() -> Store:
    s = Store(":memory:")
    agents = s.add_folder(Folder("00 - Agents"))
    inst = s.add_folder(Folder("00 - Install, Add Skill", parent_id=agents.id))
    for name in ("00 - API Keys", "00 - Code", "00 - Design skill", "00 - English", "00 - Prompts",
                 "00 - Research Paper", "00 - Search", "General", "Linux", "System"):
        s.add_folder(Folder(name))
    p = s.add_phrase(Phrase("0 - Install Skill",
                            'Install Skill "",\nName Skill "",\nTrigger Skill by "",\n\n'
                            "After installation, read each installed SKILL.md and complete any required setup,\n\n"
                            "Make Skill Useable for Any Agent,\n\nRefresh Agent Skills Index",
                            folder_id=inst.id, triggers=[Trigger(TriggerKind.AUTOTEXT, "isk#")]))
    s.add_phrase(Phrase('Add Skill "" to Skill ""', "x", folder_id=inst.id))
    for d in ("0 - Management & Science University", "0 - MCP server configuration",
              "0 - Planner to analyze the user's request", "0 - Think Step By Step"):
        s.add_phrase(Phrase(d, d))
    for t in ("own write", "PhraseForge, the PhraseExpress", "add this to the project", "TextExpander"):
        s.add_clipboard(t)
    s.record_use(p.id, chars=300)
    return s, p, inst


def main() -> None:
    app = QApplication(sys.argv)
    from phraseforge.ui import pe_style
    pe_style.apply(app)
    from phraseforge.ui.main_window import MainWindow
    s, p, inst = sample_store()
    w = MainWindow(s)
    w.resize(1600, 900)
    w.show()
    w.select_phrase(p.id)
    app.processEvents()
    shots = []

    def grab(name, widget=None):
        app.processEvents()
        (widget or w).grab().save(str(OUT / f"{name}.png"))
        shots.append(name)

    grab("01_main_phrase_selected")
    w.ribbon.select("view")
    grab("02_ribbon_view")
    w.ribbon.select("help")
    grab("03_ribbon_help")
    w.ribbon.select("phrases")
    for name, menu in (("04_file_menu", w.file_menu), ("14_dropdown_color", w.color_menu),
                       ("16_context_menu_phrase", w.build_context_menu("phrase", p.id)),
                       ("16_context_menu_folder", w.build_context_menu("folder", inst.id))):
        menu.popup(w.mapToGlobal(QPoint(40, 60)))
        app.processEvents()
        grab(name, menu)
        menu.hide()
    w.select_folder(inst.id)
    grab("09_folder_selected")
    w.panel.select("clipboard_cache", None)
    grab("21_view_clipboard_cache")
    w.set_columns(3, save=False)
    w.panel.select("last_used", None)
    grab("21_view_three_columns")
    w.set_columns(2, save=False)
    print("saved:", ", ".join(shots))
    QTimer.singleShot(0, app.quit)
    w.close()


if __name__ == "__main__":
    main()
