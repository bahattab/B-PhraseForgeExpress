# PhraseForge — specification

PhraseForge is an original Windows text expander with the feature set of
PhraseExpress. No PhraseExpress code, assets, or licensing logic is reused.
The feature list comes from inspecting the shipped program (window/dialog
names, database layout, macro names); the design and code here are our own.

Stack: Python 3.14, PySide6 (Qt 6), SQLite, ctypes for Win32 hooks.
Run: `.venv\Scripts\python -m phraseforge`. Tests: `.venv\Scripts\python -m pytest`.

## Features found in PhraseExpress (what we cover)

| Area | PhraseExpress evidence (dialog/form names) | PhraseForge module |
|---|---|---|
| Phrase tree: folders, phrases, tags, descriptions | TPHRASEFRAME, TFOLDERFRAME, TADDTAGDLG, TMORETAGSFORM | `db`, `ui.main_window` |
| Triggers: autotext, hotkey, app, regex, clipboard, clipboard-regex, time | TTRIGGER*SECTIONFRAME (7 kinds) | `triggers` |
| Popup menu / quick search | TSEARCHDROPDOWNWND, TDROPLISTFORM | `ui.popup` |
| Output by typing or paste | TPASTEOPTSFORM, TPASTETARGETFRAME | `platform.output` |
| Macros (≈60) | TMACRODLG* | `macros` |
| Fill-in forms (edit, memo, combo, checkbox, radio, date) | TMACRODLGFORM, TMACRODLGSUPERFORM, TFORMULAR | `macros` + `ui.forms` |
| Variables, conditions, loops | TMACRODLGSET, TSETVARFORM, TCONDDLG, TMACRODLGLOOP | `macros` |
| Date/time calc, calculator, random | TMACRODLGDATECALC, TMACRODLGTIMECALC, TCALCDLG, TMACRODLGRNDTEXT | `macros` |
| Run program, open file/folder/URL, wait, keys, mouse | TRUNFORM, TURLFORM, TSLEEPFORM, TSIMKEYFORM, TSIMMOUSEFORM, TMACRODLGWAITFOR | `macros` |
| Text files, Excel, XML, SQL, HTTP, regex extract | TMACRODLGXLS, TMACRODLGEXTRACTXML, TMACRODLGSQL, TMACRODLGHTTP, TMACRODLGREGEXGET | `macros` |
| AI (OpenAI, Anthropic, Ollama, OpenRouter), translate | TMACRODLGOPENAI, TOAISETTINGSWND, Plugins/*.dll | `macros.ai` |
| Clipboard history/cache | TCLIPBOARDFORM, TMACRODLGINSERTCLB | `clipboard_history` |
| Autotext learning / suggestions | TLEARNDLG, TLEARNSOURCEDLG, TREMWORDSDLG | `learning` |
| Spell check (Hunspell dictionaries) | TFRMRVSPELL, dict/*.dic | optional, `ui.editor` |
| Rich text phrases | TRICHFORM, TFRMRV* | `ui.editor` (HTML) |
| Statistics | TSTATSFORM, userstats table | `db`, `ui.stats` |
| History / undo of edits | THISTORYDLG, phraseshistory table | `db` |
| Import/export, backup/restore | TTXTIMPORTDLG, TGRIDIMPORTDLG, TFILEBACKUPDLG, TRESTOREBACKUPDLG | `io_formats` |
| Settings, first-start wizard, tray | TSETTINGSFORM, TFIRSTSTARTWIZDLG, TTRAYHINTDLG | `ui.settings`, `app` |
| Excluded apps, password-protected folders | TIGNOREDLG, TPASSDLG | `db`, `triggers` |

| Screen OCR (extra, built in: Windows OCR engine) | — (user request) | `ocr`, `ui.region_select`, `{#ocr}` macro |
| Sticky notes (extra, built in) | — (user request) | `ui.sticky_notes`, `stickynotes`, `{#stickynote}` macro |

### Built-in screen OCR
Text recognition runs inside PhraseForge with the Windows OCR engine
(`Windows.Media.Ocr`, through the `winrt-*` Python bindings). No other program
is started; Capture2Text is not needed and none of its code is used.

- `ocr.WindowsOCR(scale, whitelist, blacklist)`: `recognize(png, lang)` returns
  lines with word boxes; `ocr_png`, `ocr_image`, `ocr_at(png, x, y, mode)` with
  mode `line` / `forward` / `bubble`; `languages()` lists the OCR languages
  installed in Windows (Arabic needs the Arabic language added in Windows).
- Small captures are enlarged (automatic or 1-4x) and padded before reading.
- Capture2Text-style options: quick-access languages, re-capture last area,
  text line / forward text line / bubble capture around the mouse pointer,
  character whitelist/blacklist, replace rules, log file, clipboard, notification.
- UI: a full-screen translucent overlay lets the user drag a rectangle
  (`ui.region_select`), returned in physical screen pixels.
- Macro `{#ocr -lang Arabic -linebreaks}` asks for a region and inserts the text;
  `{#ocrfile path -lang English}` OCRs an image file.
- Global hotkey (default Ctrl+Alt+O): OCR region -> clipboard, with a tray notice.

### Built-in sticky notes
`ui.sticky_notes` (windows, list, manager) and the `sticky_notes` table. Notes
are frameless desktop windows: seven colours, rich text, always on top, autosave,
position restore at start-up, search, delete, save as phrase, and a read-only
import of the Microsoft Sticky Notes file (`stickynotes.read_notes`).

### TextExpander compatibility
TextExpander's license forbids reverse engineering, so it was NOT inspected
with REA. Compatibility is built from TextExpander's public snippet docs and
its export formats. Snippets live in TextExpander's cloud; on this PC there are
only logs, so users export a group (CSV or `.textexpander`) and import it.

- `importers.textexpander.import_any(store, path)` -> ImportReport
  (CSV `abbreviation,content,label` or `.textexpander` plist with `snippetsTE2`).
- Converts macros: date/time tokens (`%Y %m %d %A %H %M %p`...), date math
  `%@+1D`, `%clipboard`, `%|` cursor, `%key:tab%`, `%snippet:abbr%`,
  `%filltext/fillarea/fillpopup/fillpart/filldate%` -> `{#ask*}` macros that ask
  once per name and reuse the value, like TextExpander fill-ins.
- Imported snippets get an IMMEDIATE autotext trigger (TextExpander's default),
  the tag `textexpander`, and one folder per group. Script snippets are kept as
  text with a warning.

Out of scope for now: multi-user server sync, LDAP, licensing, Outlook MAPI mail.

## Package layout

```
phraseforge/
  __main__.py          entry point -> app.main()
  app.py               wires everything; tray; owns the Qt event loop   (integration)
  models.py            dataclasses (core)
  db.py                SQLite store (core)
  host.py              interfaces between modules (core)
  paths.py             data directory (core)
  macros/              macro parser + engine + all macro commands       (agent A)
  platform/            Win32 keyboard hook, send input, clipboard, window info (agent B)
  triggers/            autotext matcher, hotkey manager, trigger dispatch (agent B)
  clipboard_history.py clipboard watcher + history                       (agent B)
  learning.py          repeated-text detector -> suggestions             (agent B)
  io_formats.py        import/export JSON, CSV, plain text, backup       (agent A)
  ui/                  all Qt windows                                    (agent C)
tests/
```

## Macro syntax

Commands are written `{#name args}` and may nest:
`{#upper {#clipboard}}`.

- Positional arguments are separated by spaces. Use quotes for spaces: `{#input "Your name"}`.
- Options: `-key value`. Example: `{#date -format "yyyy-MM-dd" -offset +3d}`.
- Block commands are closed with `{#end<name>}`:
  `{#if {#var x} == "a"}yes{#else}no{#endif}`,
  `{#loop 3}line {#loopindex}\n{#endloop}`.
- A literal `{` is written `{{`.

Full command list: see `phraseforge/macros/README.md` (written by agent A).

## Execution model

1. A trigger fires for a phrase (`triggers` -> `host.ExpansionRequest`).
2. `macros.MacroEngine.expand(content, ctx)` returns a list of `host.Action`s
   (text, keys, cursor marker, sleep, paste-html, etc.). The engine is pure and
   calls `host.HostServices` for anything interactive (forms, clipboard, run...).
3. `platform.output.OutputExecutor` performs the actions in the focused app:
   erases the typed abbreviation, types or pastes the text, then moves the cursor
   to `{#cursor}`.
