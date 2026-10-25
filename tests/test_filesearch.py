"""File search (Listary-style launcher): matching, ranking, speed gate."""
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
