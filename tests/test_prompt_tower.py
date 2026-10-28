"""Prompt Tower: AI prompts built from project files (phraseforge/prompttower.py, ui/prompt_tower.py)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from phraseforge import prompttower as pt  # noqa: E402


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "myapp"
    (root / "src" / "utils").mkdir(parents=True)
    (root / "node_modules" / "lib").mkdir(parents=True)
    (root / "logs").mkdir()
    (root / "src" / "main.py").write_text('# start\nprint("# not a comment")  # trailing\n', encoding="utf-8")
    (root / "src" / "utils" / "helpers.js").write_text("// helper\nexport const x = 1; /* doc */\n")
    (root / "README.md").write_text("# My app\n\nمرحبا\n", encoding="utf-8")
    (root / "node_modules" / "lib" / "index.js").write_text("junk")
    (root / "logs" / "run.log").write_text("log")
    (root / "secret.env").write_text("KEY=1")
    (root / "image.bin").write_bytes(b"\x00\x01\x02")
    (root / ".gitignore").write_text("*.env\nlogs/\n")
    (root / ".towerignore").write_text("*.bin\n")
    return root


def test_ignore_rules_follow_gitignore_syntax():
    r = pt.IgnoreRules(["*.log", "/build/", "!keep.log", "docs/**/*.tmp", "**/cache/", "# comment", ""])
    assert r.ignored("a.log", False) and r.ignored("deep/x/a.log", False)
    assert not r.ignored("x/keep.log", False)                     # negation wins (later rule)
    assert r.ignored("build", True) and not r.ignored("build", False)   # folder-only rule
    assert r.ignored("docs/a/b/c.tmp", False) and not r.ignored("other/c.tmp", False)
    assert r.ignored("x/y/cache", True)


def test_scan_skips_ignored_and_dependency_folders(project):
    rels = [e.rel for e in pt.scan(project)]
    assert "src/main.py" in rels and "README.md" in rels and "src/utils/helpers.js" in rels
    for gone in ("node_modules", "logs/run.log", "secret.env", "image.bin", "logs"):
        assert gone not in rels
    assert rels.index("src") < rels.index("README.md")          # folders first


def test_project_tree_types(project):
    entries = pt.scan(project)
    full = pt.project_tree(entries, set(), "full", root_name="myapp")
    assert full.splitlines()[0] == "myapp/" and "│   ├── utils/" in full and "└── " in full
    dirs = pt.project_tree(entries, set(), "directories")
    assert "main.py" not in dirs and "src/" in dirs
    sel = pt.project_tree(entries, {"src/main.py"}, "selected", sizes=True)
    assert "README.md" not in sel and "main.py (" in sel and "utils" not in sel


def test_build_prompt_xml_with_prefix_suffix_and_tokens(project):
    res = pt.build_prompt(project, ["src/main.py", "README.md"], prefix="Fix the bug.", suffix="Answer in Arabic.")
    t = res.text
    assert t.startswith("Fix the bug.\n\n<context>\n<project_tree>\nmyapp/")
    assert '<file name="main.py" path="/src/main.py">\n# start' in t and "</project_files>\n</context>" in t
    assert t.endswith("Answer in Arabic.") and res.files == 2 and res.tokens > 10
    assert "مرحبا" in t


def test_markdown_format_custom_placeholders_and_binary_skip(project):
    fmt = pt.OutputFormat.markdown()
    fmt.tree_type = "none"
    res = pt.build_prompt(project, ["src/utils/helpers.js", "image.bin"], fmt)
    assert res.text.startswith("## Files") and "### /src/utils/helpers.js\n```js\n" in res.text
    assert res.skipped == ["image.bin"] and res.files == 1
    fmt = pt.OutputFormat(block="[{fileName}|{fileExtension}] {fileContent}", wrapper="{fileCount}:{blocks}",
                          tree_type="none")
    out = pt.build_prompt(project, ["README.md"], fmt).text
    assert out.startswith("1:[README|md] # My app")
    # a file that contains a placeholder is not expanded again
    (project / "t.txt").write_text("{rawFilePath} {blocks}")
    out = pt.build_prompt(project, ["t.txt"], pt.OutputFormat(tree_type="none")).text
    assert "{rawFilePath} {blocks}" in out


def test_remove_comments_keeps_strings():
    py = pt.remove_comments('# start\nprint("# not a comment")  # trailing\n', ".py")
    assert py.strip() == 'print("# not a comment")'
    js = pt.remove_comments('var s = "//x"; // c\n/* m\n*/ y', ".js")
    assert 'var s = "//x";' in js and "/*" not in js and "y" in js
    assert pt.remove_comments("# title", ".md") == "# title"           # unknown type: unchanged


def test_token_estimate():
    assert pt.estimate_tokens("") == 0
    assert pt.estimate_tokens("a" * 400) == 100
    assert pt.estimate_tokens("م" * 100) == 50


def test_saved_prompts_history_and_macro(project, tmp_path):
    from phraseforge.db import Store
    from phraseforge.macros import registry
    import phraseforge.macros.commands_extra  # noqa: F401 - registers the macros
    store = Store(tmp_path / "pt.db")
    ts = pt.TowerStore(store)
    ts.save(pt.PromptSet("Review", str(project), ["src/main.py", "gone.py"], "Review this:", "Thanks"))
    ts.save(pt.PromptSet("Other"))
    assert [s.name for s in ts.sets()] == ["Review", "Other"] and ts.get("review").prefix == "Review this:"
    res = pt.build_from_set(ts.get("Review"))                 # missing files are left out
    assert res.files == 1 and res.text.startswith("Review this:")
    ts.delete("Other")
    assert [s.name for s in ts.sets()] == ["Review"]
    for t in ("a", "b", "a"):
        ts.remember("prefix", t)
    assert ts.history("prefix") == ["a", "b"] and ts.history("suffix") == []

    class Host:
        pass
    host = Host()
    host.store = store

    class RT:
        pass
    rt = RT()
    rt.host = host
    fn = registry.REGISTRY["prompttower"][1]
    assert fn is not None
    assert fn(rt, ["Review"], {}).startswith("Review this:")
    with pytest.raises(registry.MacroError):
        fn(rt, ["Nope"], {})
    store.close()


def test_window_end_to_end(project, tmp_path):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from phraseforge.db import Store
    from phraseforge.ui.prompt_tower import PromptTowerWindow
    store = Store(tmp_path / "w.db")
    w = PromptTowerWindow(store)
    w.quiet = True
    assert w.open_folder(str(project))
    w.set_selected(["src/main.py", "README.md"])
    assert sorted(w.selected_files()) == ["README.md", "src/main.py"]
    w.prefix.setPlainText("Explain the code.")
    w._update_tokens()
    assert "2 files selected" in w.tokens.text()
    text = w.copy_prompt()
    assert QApplication.clipboard().text() == text and text.startswith("Explain the code.")
    assert store.setting("prompttower.recent")
    w.filter.setText("helpers")
    visible = [i.data(0, 0x0100) for i in w._iter_items() if not i.isHidden()]
    assert "src/utils/helpers.js" in visible and "README.md" not in visible
    w.no_comments.setChecked(True)
    w._select(w.fmt_combo, "markdown")
    w.save_set("Explain")
    w.set_selected([])
    w.prefix.setPlainText("")
    assert w.load_set("Explain")
    assert sorted(w.selected_files()) == ["README.md", "src/main.py"] and w.prefix.toPlainText() == "Explain the code."
    assert w.fmt_combo.currentData() == "markdown" and w.no_comments.isChecked()
    assert pt.TowerStore(store).history("prefix") == ["Explain the code."]
    got = []
    w.save_as_phrase.connect(lambda d, t: got.append((d, t)))
    w._save_as_phrase()
    assert got and got[0][0] == "Prompt: Explain" and got[0][1].startswith("Explain the code.")
    w.close()
    store.close()
