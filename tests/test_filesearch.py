"""File search (Listary-style launcher): matching, ranking, speed gate."""
from phraseforge import filesearch
import os
import statistics
import time

import pytest

from phraseforge.filesearch import FileIndex, parse_roots


def _touch(p):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x")


@pytest.fixture()
def tree(tmp_path):
    for rel in ["Reports/Annual Report 2026.pdf", "Reports/report-draft.docx", "Reports/old/report 2019.pdf",
                "Apps/Notepad++.lnk", "Apps/notes.txt", "Photos/IMG_0001.jpg", "node_modules/report.js",
                ".hidden/report.txt", "Budget.xlsx", "budget notes.txt"]:
        _touch(tmp_path / rel)
    return tmp_path


def _names(hits):
    return [h.name for h in hits]


def test_all_words_must_match_in_any_order(tree):
    ix = FileIndex([str(tree)])
    ix.build()
    assert set(_names(ix.search("2026 report"))) == {"Annual Report 2026.pdf"}
    assert set(_names(ix.search("rep pdf"))) == {"Annual Report 2026.pdf", "report 2019.pdf"}


def test_excluded_and_hidden_folders_are_skipped(tree):
    ix = FileIndex([str(tree)])
    ix.build()
    paths = [h.path for h in ix.search("report")]
    assert not any("node_modules" in p or ".hidden" in p for p in paths)
    ix2 = FileIndex([str(tree)], include_hidden=True)
    ix2.build()
    assert any(".hidden" in h.path for h in ix2.search("report"))


def test_ranking_exact_then_prefix_then_word_then_contains(tree):
    ix = FileIndex([str(tree)])
    ix.build()
    assert _names(ix.search("budget"))[:2] == ["Budget.xlsx", "budget notes.txt"]
    names = _names(ix.search("report"))
    assert names.index("report-draft.docx") < names.index("Annual Report 2026.pdf")
    assert "Reports" in names   # folders are found too


def test_programs_rank_before_documents(tree):
    ix = FileIndex([str(tree)])
    ix.build()
    assert _names(ix.search("note"))[0] == "Notepad++.lnk"


def test_opened_items_rank_higher_and_history_persists(tree, tmp_path):
    hist = tmp_path / "hist.json"
    ix = FileIndex([str(tree)], history_file=hist)
    ix.build()
    pdfs = ix.search("pdf")
    target = [h for h in pdfs if h.name == "report 2019.pdf"][0]
    ix.record_open(target.path)
    ix.record_open(target.path)
    assert ix.search("pdf")[0].name == "report 2019.pdf"
    ix2 = FileIndex([str(tree)], history_file=hist)
    ix2.build()
    assert ix2.search("pdf")[0].name == "report 2019.pdf"


def test_empty_query_and_missing_root(tmp_path):
    ix = FileIndex([str(tmp_path / "missing")])
    ix.build()
    assert len(ix) == 0 and ix.search("x") == [] and ix.search("  ") == []


def test_parse_roots():
    assert parse_roots(' C:\\A \n\n"D:\\B"\n') == ["C:\\A", "D:\\B"]


def test_speed_gate_50k_entries_answers_in_milliseconds(tmp_path):
    """Verification gate P2: results from a local directory within milliseconds."""
    words = ["alpha", "beta", "gamma", "delta", "report", "invoice", "photo", "notes", "budget", "draft"]
    for d in range(100):
        sub = tmp_path / f"dir{d:03d}"
        sub.mkdir()
        for f in range(500):
            (sub / f"{words[f % 10]}_{words[(f // 10) % 10]}_{d}_{f}.txt").touch()
    ix = FileIndex([str(tmp_path)])
    ix.build()
    assert len(ix) == 100 + 50_000
    times = []
    for q in ["invoice", "rep dra", "gamma 42", "zzz-not-there", "photo_notes_7"]:
        t0 = time.perf_counter()
        ix.search(q)
        times.append((time.perf_counter() - t0) * 1000)
    assert statistics.median(times) < 50, times     # milliseconds
    assert ix.search("photo_notes_7_76")[0].name == "photo_notes_7_76.txt"


def test_web_keywords():
    from phraseforge.filesearch import DEFAULT_WEB_KEYWORDS, parse_web_keywords, web_search
    kw = parse_web_keywords(DEFAULT_WEB_KEYWORDS + "\nbad line\nx=no-placeholder\n")
    assert set(kw) == {"g", "yt", "wiki", "maps"}
    assert web_search("g weather riyadh", kw) == ("g", "https://www.google.com/search?q=weather+riyadh")
    assert web_search("G  ", kw) is None and web_search("report 2026", kw) is None


def test_double_ctrl_tap():
    from phraseforge.filesearch import DoubleTap
    t = [0.0]
    d = DoubleTap({0xA2}, window=0.4, clock=lambda: t[0])
    CTRL = 0xA2

    def tap(at):
        t[0] = at
        a = d.feed(CTRL, True)
        b = d.feed(CTRL, False)
        return a or b
    assert not tap(0.0) and tap(0.2)              # two quick taps
    assert not tap(1.0) and not tap(1.6)          # too slow
    t[0] = 2.0
    d.feed(CTRL, True); d.feed(0x43, True); d.feed(0x43, False); d.feed(CTRL, False)   # Ctrl+C
    assert not tap(2.1)                           # Ctrl+C then one tap: not a double tap
    t[0] = 3.0
    d.feed(CTRL, True); d.feed(CTRL, True); d.feed(CTRL, True)   # auto-repeat while held
    d.feed(CTRL, False)
    assert tap(3.2)


# ---- Listary Options features (docs/menus/listary.md)

def _tree(tmp_path):
    for rel in ("docs/report 2026.pdf", "docs/report draft.txt", "pics/report.png",
                "node_modules/report.js", "cache/report.tmp", "important/report.xlsx"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    (tmp_path / "reports").mkdir()
    return tmp_path


def test_filters_by_keyword(tmp_path):
    root = _tree(tmp_path)
    ix = filesearch.FileIndex([str(root)], excludes=())
    ix.build()
    filters = filesearch.parse_filters(f"mine = My filter; ext=txt; in={root / 'docs'}")
    f, words = filesearch.split_filter("doc: report", filters)
    assert f.name == "Document" and words == "report"
    names = {h.name for h in ix.search(words, filt=f)}
    assert names == {"report 2026.pdf", "report draft.txt", "report.xlsx"}
    f, words = filesearch.split_filter("folder:report", filters)
    assert [h.name for h in ix.search(words, filt=f)] == ["reports"]
    f, words = filesearch.split_filter("mine: report", filters)
    assert [h.name for h in ix.search(words, filt=f)] == ["report draft.txt"]
    assert filesearch.split_filter("nofilter: x", filters) == (None, "nofilter: x")


def test_priorities_order_and_skip(tmp_path):
    root = _tree(tmp_path)
    rules = filesearch.parse_priority_rules(
        f"high: {root / 'important'}\nrare: re:^node_modules$\nskip: {root / 'cache'}\nbogus line\nrare: re:[")
    assert len(rules) == 3
    ix = filesearch.FileIndex([str(root)], excludes=(), priority_rules=rules)
    ix.build()
    hits = [h.name for h in ix.search("report")]
    assert hits[0] == "report.xlsx"                 # high first
    assert "report.tmp" not in hits                 # skipped folder is not indexed
    assert hits[-1] == "report.js"                  # inside node_modules (rare): last
    assert filesearch.priority_of(str(root / "x" / "a.txt"), "a.txt", rules) == filesearch.NORMAL


def test_custom_actions_and_commands(tmp_path):
    acts = filesearch.parse_custom_actions('Edit with VS Code = code | "{path}"\nList = cmd.exe | /k dir | {folder}\nbad')
    assert [a.title for a in acts] == ["Edit with VS Code", "List"]
    f = tmp_path / "a b.txt"
    f.write_text("x")
    prog, params, cwd = filesearch.expand_action(acts[0], str(f))
    assert (prog, params, cwd) == ("code", f'"{f}"', str(tmp_path))
    assert filesearch.expand_action(acts[1], str(f))[2] == str(tmp_path)
    assert filesearch.match_commands("ps") == ["psh", "psha"]
    assert filesearch.match_commands("cmd x") == []
    assert "shutdown" not in filesearch.COMMANDS and "reboot" not in filesearch.COMMANDS
