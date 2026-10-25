# Evidence & verification report

Status: **draft, 2026-10-25.** The menu capture of the five reference programs has not run yet
(the screenshot session could not start on the user's PC; `tools/capture_menus.ps1` can be run by hand). Their sections below are marked
*pending* until `docs/menus/<app>.md` exists. Nothing here claims a capture or test that did
not run.

## Method and limits

| Source | Used for | Allowed |
|---|---|---|
| UI observation: menus, ribbons, dialogs, tray menus opened through the normal interface, up to 10 levels, screenshots kept locally in `reference/` (gitignored) | menu hierarchy, feature list, visible behavior | yes |
| Public documentation: vendor help pages, Microsoft Win32/OneNote COM docs, documented export formats | APIs and file formats | yes |
| Capture2Text's published source code and docs (open source, GPLv3) | OCR command line, languages | yes, as reference only: PhraseForge (MIT) runs Capture2Text_CLI.exe and copies none of its code |
| Binary analysis (decompile/disassemble with REA, Ghidra, debuggers) of ONENOTE.EXE, onenotecapture.exe, ONENOTEM.EXE, TextExpander.exe, Listary.exe | — | **not done**: the TextExpander, Microsoft and Listary licenses forbid reverse engineering, and the goal is to build similar features, not interoperability |

So there are no pseudocode snippets or call graphs taken from these programs. Every PhraseForge
feature is an original implementation; this report records where each idea came from.

Evidence states: **observed** (seen in the program's UI), **documented** (public docs, file
format or open source), **published, unconfirmed** (from the vendor's public product
information, not yet confirmed by screenshots), **inferred** (design choice, not seen in the
original), **pending** (not captured yet).

## Reference programs

| Program | Capture status | Inventory |
|---|---|---|
| Capture2Text v4.6.3 Arabic | pending | `docs/menus/capture2text.md` |
| OneNote (ONENOTE.EXE) | pending | `docs/menus/onenote.md` |
| OneNote screen clipping (onenotecapture.exe) | pending | `docs/menus/onenotecapture.md` |
| Send to OneNote (ONENOTEM.EXE) | pending | `docs/menus/onenotem.md` |
| TextExpander | pending | `docs/menus/textexpander.md` |
| Listary | pending | `docs/menus/listary.md` |

## Feature ledger

| PhraseForge feature | Modelled on | Evidence | Status | Verification |
|---|---|---|---|---|
| Abbreviation expands to text (autotext triggers, delimiters, case handling) | TextExpander, PhraseExpress | documented (TextExpander public snippet docs; SPEC.md) | implemented | `tests/test_triggers.py`, `tests/test_triggers_advanced.py` |
| Fill-ins (`%filltext%`, `%fillpopup%` … → `{#ask*}` macros) | TextExpander | documented (export format) | implemented | `tests/test_textexpander_import.py` |
| Import TextExpander CSV / `.textexpander` groups | TextExpander | documented (export formats) | implemented | `tests/test_textexpander_import.py` |
| Send clipboard text/picture to OneNote page or Quick Notes | Send to OneNote (ONENOTEM) | documented (OneNote COM API) | implemented | `tests/test_onenote*.py` (fake client) |
| New quick note window (tray, hotkey): Ctrl+Enter sends to OneNote Quick Notes or the default page, Ctrl+S saves as a phrase | Send to OneNote (ONENOTEM) | published, unconfirmed (ONENOTEM's tray menu not captured yet); sending uses the documented OneNote COM API | implemented | `tests/test_quick_note.py` |
| Screen clip to OneNote, or OCR the clip | onenotecapture.exe | documented (starts `onenotecapture.exe`; Capture2Text CLI) | implemented | `tests/test_onenote*.py` |
| Import OneNote pages as phrases | OneNote | documented (OneNote COM `GetHierarchy`/`GetPageContent`) | implemented | `tests/test_onenote.py` |
| Adapt output case to the typed abbreviation (ALL CAPS / Capitalised) | TextExpander, PhraseExpress | published, unconfirmed | already implemented | `tests/test_triggers*.py` |
| Screen OCR to clipboard, any Capture2Text language incl. Arabic (Ctrl+Alt+O) | Capture2Text | documented (Capture2Text CLI options, open source) | already implemented | `tests/test_macros.py::test_ocr` |
| Search files: type name fragments, Enter opens, Ctrl+Enter opens folder, Shift+Enter types path | Listary | published, unconfirmed; exact keys and ranking **pending capture** | implemented | `tests/test_filesearch.py`, `tests/test_filesearch_ui.py` |
| Open Search files by pressing Ctrl twice | Listary | published, unconfirmed | implemented (on by default, Settings > Search files) | `test_double_ctrl_tap`, `test_double_ctrl_opens_file_search` |
| Web search keywords (`g`, `yt`, `wiki`, `maps`, user-defined) | Listary | published, unconfirmed | implemented | `test_web_keywords`, `test_web_keyword_row_opens_url` |
| File index | Listary | inferred: folder walk with `os.scandir`, rebuilt every N minutes. Listary's own indexing method is **unknown** (not observed; no binary analysis). An NTFS MFT/USN index (as documented for the Everything search engine) is a possible later upgrade and needs admin rights | implemented (folder walk) | speed gate below |
| Menu system reorganised after OneNote's ribbon/menu hierarchy | OneNote | pending capture | not started | — |

## Verification gates

| Gate | Check | Result |
|---|---|---|
| P1 text expansion: a trigger word expands to its text | `tests/test_triggers*.py` | pass (Linux, 2026-10-25) |
| P2 file search answers in milliseconds from a local directory | `test_speed_gate_50k_entries_answers_in_milliseconds`: 50,100 entries, median of 5 queries < 50 ms | pass (Linux, 2026-10-25). Manual run on 95,339 real files: index built in 1.7 s, queries took 0.4–21 ms |
| P4 installer | Windows CI: tests, EXE self-test, silent install + self-test + uninstall | pass on windows-latest (run 40166838878, 2026-10-25) |

## Not replicated

To be filled after the menu capture: for each captured menu item, replicated / approximated /
not implemented, with the reason.
