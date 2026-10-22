"""Regenerate the '## Commands' section of phraseforge/macros/README.md from the registry."""
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from phraseforge.macros.registry import REGISTRY, catalog  # noqa: E402

readme = ROOT / "phraseforge" / "macros" / "README.md"
head = readme.read_text(encoding="utf-8").split("## Commands")[0]
aliases = defaultdict(list)
for name, (info, _fn) in REGISTRY.items():
    if name != info.name:
        aliases[info.name].append(name)
groups = defaultdict(list)
for info in catalog():
    groups[info.category].append(info)
out = [head.rstrip() + "\n", "## Commands\n"]
for cat, infos in groups.items():
    out.append(f"\n### {cat}\n\n| Command | Syntax | Description |\n|---|---|---|")
    for i in infos:
        al = f" (aliases: {', '.join(sorted(aliases[i.name]))})" if aliases[i.name] else ""
        esc = lambda s: s.replace("|", "\\|")
        out.append(f"| `{i.name}`{al} | `{esc(i.syntax)}` | {esc(i.description)} |")
out.append("\nEvery command also accepts `-caption \"Name\"`: the label shown on the macro chip in the editor "
           "(set by the macro dialogs' Name field); it does not change the output.\n")
readme.write_text("\n".join(out) + "\n", encoding="utf-8")
print(sum(len(v) for v in groups.values()), "commands")
