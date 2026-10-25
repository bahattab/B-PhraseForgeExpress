# Evidence & verification report

Status: **2026-10-25, partial capture.**
- The user ran `tools/capture_menus.ps1 -All` on their PC. OneNote: 88 items, 10 levels deep.
  The other five programs gave 0 items because they have no window (tray programs, or
  onenotecapture, which opens and closes at once).
- The user also sent 9 screenshots of Capture2Text's tray menu and Settings pages, 26 of Listary's
  Options window and 45 of TextExpander (tray, menus, Preferences, web dashboard).
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
| PhraseExpress Free 18.0.84f (phraseexpress.exe), the main model | **observed** by screen control (view only): ribbon tabs File/Phrases/View/Help, File menu, folder context menu 3 levels deep, all 20 Settings pages. tray and popup menus from the user's screenshots; tray click behaviour from the published help | `docs/menus/phraseexpress.md` |
| Capture2Text v4.6.3 Arabic | **observed**: tray menu and 7 of 9 Settings pages, from the user's screenshots | `docs/menus/capture2text.md` |
| OneNote (ONENOTE.EXE) | **observed**: title bar, Quick Access Toolbar, ribbon tab row, notebook/page panes (88 items, depth 10). The commands inside each tab are not captured yet | `docs/menus/onenote.md` |
| OneNote screen clipping (onenotecapture.exe) | pending (no window) | `docs/menus/onenotecapture.md` |
| Send to OneNote (ONENOTEM.EXE) | pending (tray only) | `docs/menus/onenotem.md` |
| TextExpander 8.4.8 | **observed**: tray menu, menu bar, group and snippet editors, all six Preferences pages and the web dashboard, from 45 screenshots | `docs/menus/textexpander.md` |
| Listary | **observed**: all Options pages except About, from 26 screenshots; tray menu pending | `docs/menus/listary.md` |

## Feature ledger

| PhraseForge feature | Modelled on | Evidence | Status | Verification |
|---|---|---|---|---|
| Settings tree: Features, Hotkeys, Display, Sounds, Phrase File/Database, AI text processing (Custom presets, Custom instructions), Language Translation (Ignored words, Glossaries), Network, Phrase Menu (Appearance, Hotkeys, Quick Search), AutoComplete, Expert Options (Text Insertion, Delays, Phrase Formatting) | PhraseExpress 18 Settings | observed (2026-10-25); before that, documented from the manual | already implemented with the same pages and options; PhraseForge adds Backup & Sync, Screen OCR, OneNote, Search files, Program exclusions | `tests/test_settings_dialog.py` |
| Folder menu > Bulk edit: Remove duplicates; Descriptions / Phrase contents / Autotexts: Prefix, Append, Strip trailing/leading spaces, Upper/lower case first letter, UPPERCASE, lowercase; Generate descriptions; Convert to plain text | PhraseExpress 18 folder context menu | observed | implemented (Generate for contents and autotexts, Change font and Convert to RTF are not) | `tests/test_bulk_edit.py` |
| Folder menu > Sort: Description, Description length, Date created, Date modified, Last used, Times used | PhraseExpress 18 folder context menu | observed (list cut off at the screen edge) | implemented | `tests/test_bulk_edit.py` |
| Tray icon clicks: left click opens the phrase menu, double click the main window, Ctrl+click pauses, Alt+click opens settings | PhraseExpress Windows help (doc/ui) | **published, not confirmed by screenshots** | implemented: Ctrl/Alt/double click as published; plain left click opens the main window unless "Left click on the tray icon opens the phrase menu" is on (Settings > Features) | `tests/test_phraseexpress_tray.py` |
| Tray menu: About, Language selection, Enabled in "<program used last>", Open, Settings, Exit | PhraseExpress 18 tray icon | **observed** (user screenshot) | implemented: Language selection (English/Arabic) and the per-program "Enabled in" toggle (adds/removes the program in Program exclusions) added; About, Open, Settings, Quit were already there. "Register for professional use" not replicated (PhraseForge has no paid edition) | `tests/test_phraseexpress_tray.py` |
| New phrase dialog "Enter additional information for the new phrase...": Description, trigger rows with the 8 types and 4 execution modes, (+) add menu, Execute only in specific programs, Save in folder + "Select target folder..." | PhraseExpress 18 | **observed** (user screenshots) | implemented (`NewPhraseInfoDialog`), shown after the Create new phrase hotkey and the phrase menu "New phrase..." when the Display setting is on | `tests/test_phraseexpress_tray.py` |
| AI engines Deepl / OpenAI / Anthropic (Claude) / GPT4All / Ollama / OpenRouter; translation page API key | PhraseExpress 18 AI text processing and Language Translation | **observed** (user screenshots) | implemented: GPT4All (local OpenAI-format server) for AI and translation, DeepL API for translation (ignored words kept with tag handling), API key box on the translation page | `tests/test_phraseexpress_settings.py` |
| AI Presets dialog with per-preset Model (Auto) and Reset to defaults | PhraseExpress 18 Custom presets | **observed** | implemented; `{#ai -preset}` uses the preset's model | `tests/test_phraseexpress_settings.py` |
| New Glossary: Name, Source language, Target language | PhraseExpress 18 Glossaries | **observed** | implemented; a glossary with languages applies only to matching translations (DeepL uses ignored words only, not glossaries) | `tests/test_phraseexpress_settings.py` |
| Phrase menu contents (12 column orders), Sort by Length / Last use, 6 menu positions, 6 fallback positions, QuickKey modifier Win and keys None | PhraseExpress 18 Phrase Menu and its Hotkeys page | **observed** | implemented (column order in the popup rows, drag the title band to set the fixed position) | `tests/test_phraseexpress_settings.py` |
| Phrase output format Auto / RTF & HTML / RTF only / HTML only; key-by-key VK_Packet / SendKey; Show phrase language buttons | PhraseExpress 18 | **observed** | approximated: PhraseForge offers Auto / Plain text / Rich text / HTML and its own key sending; no phrase language versions, so no language buttons | - |
| Phrase menu: wordmark band with search and pin, scroll arrows, folders sorted by name with Clipboard Cache and Last Used among them, then phrases, "New phrase..." footer; number keys 1-9 (published) | PhraseExpress 18 popup | **observed** (user screenshot); number keys from the published help | already implemented in the popup | `tests/test_popup.py` |
| Ribbon File / Phrases / View / Help with Migration Assistant, Import/Export, Two/Three columns, Flat list, Statistics | PhraseExpress 18 main window | observed | already implemented (PhraseForge ribbon: File, Phrases, View, Tools, Help) | `tests/test_ui.py` |
| Abbreviation expands to text (autotext triggers, delimiters, case handling) | TextExpander, PhraseExpress | documented (TextExpander public snippet docs; SPEC.md) | implemented | `tests/test_triggers.py`, `tests/test_triggers_advanced.py` |
| Fill-ins (`%filltext%`, `%fillpopup%` … → `{#ask*}` macros) | TextExpander | documented (export format) | implemented | `tests/test_textexpander_import.py` |
| Import TextExpander CSV / `.textexpander` groups | TextExpander | documented (export formats) | implemented | `tests/test_textexpander_import.py` |
| Import macOS Text Replacements (`.plist`, shortcut → phrase) | TextExpander web Import/Export, "Supported formats" | observed (format list); the file layout is Apple's documented export | implemented (Phrases > Import > TextExpander / macOS) | `test_import_macos_text_replacements_plist` |
| Statistics: phrases expanded and time saved from a typing speed | TextExpander web Statistics (Words Per Minute 50, Snippets Expanded, Time Saved, Daily Activity) | observed | already implemented (Statistics window; speed set in characters per minute, default 180 ≈ 36 words per minute) | `tests/test_ui.py` |
| Send clipboard text/picture to OneNote page or Quick Notes | Send to OneNote (ONENOTEM) | documented (OneNote COM API) | implemented | `tests/test_onenote*.py` (fake client) |
| New quick note window (tray, hotkey): Ctrl+Enter sends to OneNote Quick Notes or the default page, Ctrl+S saves as a phrase | Send to OneNote (ONENOTEM) | published, unconfirmed (ONENOTEM's tray menu not captured yet); sending uses the documented OneNote COM API | implemented | `tests/test_quick_note.py` |
| Screen clip to OneNote, or OCR the clip | onenotecapture.exe | documented (starts `onenotecapture.exe`; Capture2Text CLI) | implemented | `tests/test_onenote*.py` |
| Import OneNote pages as phrases | OneNote | documented (OneNote COM `GetHierarchy`/`GetPageContent`) | implemented | `tests/test_onenote.py` |
| Adapt output case to the typed abbreviation (ALL CAPS / Capitalised) | TextExpander snippet editor "Case: Adapt to Case of Abbreviation" | observed | already implemented | `tests/test_triggers*.py` |
| Expansion modes: immediately / at delimiter keep / at delimiter abandon; delimiter set; restore clipboard; play sound; expand only in / except some programs | TextExpander Preferences > Expansion | observed | already implemented, set per phrase (trailing delimiter "None", "Default", "Remove trailing delimiter") and in Settings (delimiters, sounds, program restrictions); TextExpander sets the mode once for all snippets | `tests/test_triggers*.py` |
| Folder abbreviation prefix, inherited by subfolders | TextExpander Group Settings > Group prefix | observed | implemented (folder editor field "Abbreviation prefix") | `tests/test_textexpander_features.py` |
| Reminder: "you have an autotext for this" when a phrase is typed out in full | TextExpander Preferences > Suggestions "Notify me of the abbreviation when I type a snippet that already exists" | observed | implemented (on by default, Settings > AutoComplete; at most once per 5 minutes per phrase; skipped in password fields, for phrases with macros and texts under 8 characters) | `tests/test_textexpander_features.py` |
| Suggest phrases from typing habits | TextExpander Preferences > Suggestions | observed | already implemented ("Suggest entered sentences"); kept on this PC only | `tests/test_learning.py` |
| Hotkeys: Open, Enable/Disable expansion, New phrase, New phrase from clipboard, Edit last used phrase, inline search | TextExpander Preferences > Hotkeys | observed | implemented (Settings > Hotkeys; no default keys except the existing popup search); "Edit last used" opens the last expanded phrase | `tests/test_textexpander_features.py` |
| Tray items New phrase from clipboard, Edit last used phrase | TextExpander tray menu | observed | implemented | `test_tray_has_clipboard_and_edit_last_items` |
| Duplicate, sort, preview, print groups, Find | TextExpander File / View / Edit menus | observed | already implemented in the main window (Duplicate, Sort, Preview, Print, search) | `tests/test_ui.py` |
| Screen OCR to clipboard, any Capture2Text language incl. Arabic (Ctrl+Alt+O) | Capture2Text | documented (Capture2Text CLI options, open source) | already implemented | `tests/test_macros.py::test_ocr` |
| OCR output options: Save to clipboard, show result popup, keep line breaks | Capture2Text tray menu and Settings > Output | observed | implemented (Settings > Screen OCR > Output) | `tests/test_ocr_options.py::test_ocr_modes_log_and_clipboard` |
| Log captures to a file with a format (`${capture}${linebreak}`, plus `${tab}`, `${timestamp}`) | Capture2Text Settings > Output > Logging | observed | implemented | `test_log_format`, `test_ocr_modes_log_and_clipboard` |
| Re-capture last area (hotkey) | Capture2Text Settings > Hotkeys "Re-Capture Last" | observed | implemented (no default key) | `test_ocr_modes_log_and_clipboard`, `test_ocr_hotkeys_map_to_commands` |
| Three quick-access OCR languages, each with a hotkey | Capture2Text Settings > OCR 1 and Hotkeys | observed | implemented (default languages Arabic, English; no default keys) | same tests |
| OCR language menu in the tray icon | Capture2Text tray menu "OCR Language ▸" | observed | implemented (current plus quick-access languages) | `test_tray_language_menu` |
| Find (regex) → Replace rules per OCR language | Capture2Text Settings > Replace | observed | implemented as text rules `find => replace` with `[Language]` sections (Capture2Text uses a table) | `test_replace_rules_global_and_per_language` |
| Search files: type name fragments, Enter opens, Ctrl+Enter opens folder, Shift+Enter types path | Listary | published, unconfirmed (Enter/Shift+Enter keys not in the screenshots) | implemented | `tests/test_filesearch.py`, `tests/test_filesearch_ui.py` |
| Open Search files by pressing Ctrl twice; "When pressing again: Hide" | Listary Options > Hotkey | observed | implemented (Settings > Search files) | implemented (on by default, Settings > Search files) | `test_double_ctrl_tap`, `test_double_ctrl_opens_file_search` |
| Web search keywords: Listary's list (g, wiki, so, bing, b, gmail, twitter, youtube, maps, amazon, ebay, imdb, facebook) plus yt and user-defined | Listary Options > Web Search | observed (keywords and titles); the URLs are the sites' public search addresses | implemented | `test_web_keywords`, `test_web_keyword_row_opens_url` |
| Next / previous result Ctrl+N / Ctrl+P, actions menu Ctrl+O | Listary Options > Hotkey | observed | implemented | `test_actions_menu_commands_and_navigation` |
| Search filters "keyword:" (Folder, File, Document, Picture, Video, Audio) plus user filters with extensions, folder/file choice and "search in" | Listary Options > File Search > Filters | observed (names); the built-in keywords folder/file/doc/pic/video/audio and the extension lists are **inferred** | implemented | `test_filters_by_keyword`, `test_filter_in_window` |
| Priorities: High / Normal / Rarely used / Do not index, by folder or file-name regex, with Listary's default rules | Listary Options > File Search > Priorities | observed | implemented; a folder's priority passes to its contents. The `^[^.]+$` rule is left out because it would push every folder down | `test_priorities_order_and_skip` |
| Actions: Open Containing Folder, Copy, Cut, Copy Path, Copy File Name, custom actions (program, parameter, working folder) | Listary Options > Actions | observed | implemented; hotkey, keyword, scope, silent and run-as-admin per action are not | `test_custom_actions_and_commands`, `test_actions_menu_commands_and_navigation` |
| Command keywords: opt, rebuild, cmd, cmda, psh, psha, uninstall, connections, hosts | Listary Options > Commands | observed | implemented | same tests |
| Custom commands: keyword + text → program with `{query}` (default example: notepad) | Listary Options > Commands > Custom Command | observed | implemented; hotkey, scope, silent, run as admin per command are not | `test_custom_commands_and_web_list`, `test_custom_command_row_and_favorites` |
| Favourite folders shown before typing | Listary Options > Menu | observed | approximated: a flat list in Search files; Listary's submenus, separators and commands inside the menu are not | `test_custom_command_row_and_favorites` |
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
| TextExpander | Cloud team sharing, account sign-in, Public groups, web dashboard (Members, Teams, Snippet Requests, Statistics) | not implemented | Needs TextExpander's online service; PhraseForge has its own optional Google Drive sync and local statistics |
| TextExpander | Quick actions (Ctrl+Shift+/) | not implemented | The screenshots show only the hotkey, not what the panel offers |
| TextExpander | Import ShortHand `.txt`, Instant Text `.glo`, Google Sheets `.html` | not implemented | Their file layouts are not published; guessing them could import wrong text |
| PhraseExpress | SQL server database, User Manager, Access rights, phrase file synchronization, Manage languages, Translate, Pin to desktop (Demo items in the Free edition) | not implemented / shown disabled | Multi-user server features; PhraseForge uses one local SQLite file plus optional Google Drive sync |
| PhraseExpress | Import from MS Word AutoCorrect / Autotext / Outlook emails, Export as e-mail attachment | not implemented | Need Office automation; PhraseForge imports TextExpander, macOS, OneNote and its own JSON |
| PhraseExpress | Phrase contents caching options, SQL network options, update checker, beta channel | not implemented | PhraseForge reads phrases from SQLite on demand and has no auto-updater |
| TextExpander | Snippet Activity log per person, Snippet Requests, Members, Teams | not implemented | Team features of TextExpander's online service |
| TextExpander | Web account pages: organization settings (idle timeout, staff access, TextExpander AI, publish snippets to the web, sharing controls), Billing, Single sign-on, Profile, e-mail notifications, password | not implemented | Account and billing pages of the online service; PhraseForge has no account. Its AI features use the user's own provider key |
| TextExpander | One global expansion mode; "Scan typing for suggestions" per program; Appearance fonts for snippet display; update check frequency and beta channel | approximated / not implemented | PhraseForge sets the mode per phrase and uses one editor font setting; it has no update checker |
| Listary | Search files by name, double Ctrl, open folder, web keywords | approximated | See the feature ledger. Ranking and keys may differ from Listary's |
| Listary | Integration into File Explorer, Open/Save dialogs and 14 file managers (Quick Switch Ctrl+G) | not implemented | Needs hooks inside other programs' windows; out of scope for this version |
| Listary | Web search suggestion providers and per-site icons | not implemented | Would send what you type to a suggestion server while typing |
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
