# Evidence & verification report

Status: **2026-10-25, partial capture.**
- The user ran `tools/capture_menus.ps1 -All` on their PC. OneNote: 88 items, 10 levels deep.
  The other five programs gave 0 items because they have no window (tray programs, or
  onenotecapture, which opens and closes at once).
- The user also sent 9 screenshots of Capture2Text's tray menu and Settings pages.
- The raw OneNote capture contained the user's own notebook, section and page names. Those were
  replaced with `<user content>` before committing, and the script now does this by itself.
- Programs whose inventory says *pending* still need tray-menu screenshots.

Earlier attempts to capture from this session failed. Remote sessions could not start in the
PC's registered folder. Screen control allowed only clicks in terminals, so the script could not
be started that way.

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
| Capture2Text v4.6.3 Arabic | **observed**: tray menu and 7 of 9 Settings pages, from the user's screenshots | `docs/menus/capture2text.md` |
| OneNote (ONENOTE.EXE) | **observed**: title bar, Quick Access Toolbar, ribbon tab row, notebook/page panes (88 items, depth 10). The commands inside each tab are not captured yet | `docs/menus/onenote.md` |
| OneNote screen clipping (onenotecapture.exe) | pending (no window) | `docs/menus/onenotecapture.md` |
| Send to OneNote (ONENOTEM.EXE) | pending (tray only) | `docs/menus/onenotem.md` |
| TextExpander | pending (tray only) | `docs/menus/textexpander.md` |
| Listary | **observed**: Options window (General, Appearance, Hotkey, File Search, Actions, Commands) from 16 screenshots; tray menu pending | `docs/menus/listary.md` |

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
| OCR output options: Save to clipboard, show result popup, keep line breaks | Capture2Text tray menu and Settings > Output | observed | implemented (Settings > Screen OCR > Output) | `tests/test_ocr_options.py::test_ocr_modes_log_and_clipboard` |
| Log captures to a file with a format (`${capture}${linebreak}`, plus `${tab}`, `${timestamp}`) | Capture2Text Settings > Output > Logging | observed | implemented | `test_log_format`, `test_ocr_modes_log_and_clipboard` |
| Re-capture last area (hotkey) | Capture2Text Settings > Hotkeys "Re-Capture Last" | observed | implemented (no default key) | `test_ocr_modes_log_and_clipboard`, `test_ocr_hotkeys_map_to_commands` |
| Three quick-access OCR languages, each with a hotkey | Capture2Text Settings > OCR 1 and Hotkeys | observed | implemented (default languages Arabic, English; no default keys) | same tests |
| OCR language menu in the tray icon | Capture2Text tray menu "OCR Language ▸" | observed | implemented (current plus quick-access languages) | `test_tray_language_menu` |
| Find (regex) → Replace rules per OCR language | Capture2Text Settings > Replace | observed | implemented as text rules `find => replace` with `[Language]` sections (Capture2Text uses a table) | `test_replace_rules_global_and_per_language` |
| Search files: type name fragments, Enter opens, Ctrl+Enter opens folder, Shift+Enter types path | Listary | published, unconfirmed (Enter/Shift+Enter keys not in the screenshots) | implemented | `tests/test_filesearch.py`, `tests/test_filesearch_ui.py` |
| Open Search files by pressing Ctrl twice; "When pressing again: Hide" | Listary Options > Hotkey | observed | implemented (Settings > Search files) | implemented (on by default, Settings > Search files) | `test_double_ctrl_tap`, `test_double_ctrl_opens_file_search` |
| Web search keywords (`g`, `yt`, `wiki`, `maps`, user-defined) | Listary | published, unconfirmed | implemented | `test_web_keywords`, `test_web_keyword_row_opens_url` |
| Next / previous result Ctrl+N / Ctrl+P, actions menu Ctrl+O | Listary Options > Hotkey | observed | implemented | `test_actions_menu_commands_and_navigation` |
| Search filters "keyword:" (Folder, File, Document, Picture, Video, Audio) plus user filters with extensions, folder/file choice and "search in" | Listary Options > File Search > Filters | observed (names); the built-in keywords folder/file/doc/pic/video/audio and the extension lists are **inferred** | implemented | `test_filters_by_keyword`, `test_filter_in_window` |
| Priorities: High / Normal / Rarely used / Do not index, by folder or file-name regex, with Listary's default rules | Listary Options > File Search > Priorities | observed | implemented; a folder's priority passes to its contents. The `^[^.]+$` rule is left out because it would push every folder down | `test_priorities_order_and_skip` |
| Actions: Open Containing Folder, Copy, Cut, Copy Path, Copy File Name, custom actions (program, parameter, working folder) | Listary Options > Actions | observed | implemented; hotkey, keyword, scope, silent and run-as-admin per action are not | `test_custom_actions_and_commands`, `test_actions_menu_commands_and_navigation` |
| Command keywords: opt, rebuild, cmd, cmda, psh, psha, uninstall, connections, hosts | Listary Options > Commands | observed | implemented | same tests |
| File index | Listary | inferred: folder walk with `os.scandir`, rebuilt every N minutes. Listary's own indexing method is **unknown** (not observed; no binary analysis). An NTFS MFT/USN index (as documented for the Everything search engine) is a possible later upgrade and needs admin rights | implemented (folder walk) | speed gate below |
| Ribbon "Tools" tab: OneNote group (Send clipboard to OneNote, Screen clipping, New quick note), Capture group (Screen OCR, Sticky Notes), Find group (Search files) | OneNote Insert tab, ONENOTEM and onenotecapture tray tools | the tab row (File, Home, Insert, Draw, History, Review, View, Help, plus a Sticky Notes button) is **observed**; the commands inside OneNote's tabs are not captured yet, so the grouping is still an approximation | implemented (approximated) | `tests/test_ui.py::test_tools_tab_runs_app_commands` |

## Verification gates

| Gate | Check | Result |
|---|---|---|
| P1 text expansion: a trigger word expands to its text | `tests/test_triggers*.py` | pass (Linux, 2026-10-25) |
| P2 file search answers in milliseconds from a local directory | `test_speed_gate_50k_entries_answers_in_milliseconds`: 50,100 entries, median of 5 queries < 50 ms | pass (Linux, 2026-10-25). Manual run on 95,339 real files: index built in 1.7 s, queries took 0.4–21 ms |
| P4 installer | Windows CI: tests, EXE self-test, silent install + self-test + uninstall | pass on windows-latest (run 40166838878, 2026-10-25) |

## Not replicated

Item-by-item status waits for the menu capture. Until then, this list covers the main published
features of each program. It is based on vendor product information, not on screenshots.

| Program | Feature | Status | Reason |
|---|---|---|---|
| OneNote | Notebooks, sections, pages, rich page canvas, inking, audio/video notes | not implemented | PhraseForge is a phrase manager. It reads from and writes to OneNote through its COM API instead of copying the editor |
| OneNote | Ribbon layout | approximated | "Tools" tab groups the OneNote-related commands. Full tab-by-tab parity waits for the capture |
| onenotecapture.exe | Screen clipping to a chosen page | replicated by calling it | PhraseForge starts `onenotecapture.exe`; it can also OCR the clip with Capture2Text |
| ONENOTEM.EXE | Tray icon: New quick note, screen clip, send to OneNote | approximated | Quick note window and tray actions. Its own tray menu and default actions are not captured |
| TextExpander | Snippets, abbreviations, fill-ins, CSV and `.textexpander` import | replicated | See the feature ledger |
| TextExpander | Cloud team sharing, account sign-in, snippet suggestions service | not implemented | Needs TextExpander's online service; PhraseForge has its own optional Google Drive sync |
| Listary | Search files by name, double Ctrl, open folder, web keywords | approximated | See the feature ledger. Ranking and keys may differ from Listary's |
| Listary | Integration into Open/Save dialogs and Explorer (Quick Switch Ctrl+G, "folder jump") | not implemented | Hooks into other programs' file dialogs; the Integration page is not in the screenshots |
| Listary | Commands `..`, mkdir, touch | not implemented | They act on the folder open in Explorer, which Search files does not track |
| Listary | Commands shutdown, reboot | not implemented on purpose | One mistyped Enter would turn off the PC |
| Listary | Preview (Alt+P), Dark theme, network drives in the index, per-action hotkeys and scope | not implemented | Not needed for the work packages; PhraseForge has its own light/dark theme |
| Capture2Text | OCR of a screen region, Arabic and other languages | replicated by calling it | PhraseForge runs `Capture2Text_CLI.exe`; no GPL code copied |
| Capture2Text | Output (clipboard, popup, line breaks, log file), Re-capture last, quick-access languages, tray language menu, Replace rules | replicated | See the feature ledger (observed from screenshots) |
| Capture2Text | Text Line / Forward Text Line / Bubble capture (OCR around the mouse without drawing a box) | not implemented | Needs Capture2Text's own line-finding code; its CLI only takes a box or an image |
| Capture2Text | Whitelist/Blacklist characters, Tesseract config file, scale factor, deskew, trim | not implemented | Capture2Text's own settings already apply when PhraseForge runs its CLI |
| Capture2Text | Translate (Google Translate) and Speech | approximated / not implemented | PhraseForge has `{#translate}` through its AI settings; speech is not implemented |
| Capture2Text | Capture box colours, debug image saving, Call Executable | not implemented | Low value for a phrase manager |
| OneNote | Ribbon tab row, Quick Access Toolbar, Sticky Notes button | observed, partly mirrored | PhraseForge's ribbon has File, Phrases, View, Tools, Help. A Sticky Notes button is in the Tools tab |
