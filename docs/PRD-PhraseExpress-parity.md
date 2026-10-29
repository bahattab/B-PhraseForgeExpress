# PRD — PhraseExpress parity and extension for B-PhraseForgeExpress

| | |
|---|---|
| Target repo | `https://github.com/bahattab/B-PhraseForgeExpress`, gap analysis checked against release **0.5.4** (`b0d84ff`) |
| Reference product | PhraseExpress 18.0.84.0, installed at `C:\Program Files (x86)\PhraseExpress` |
| Date | 2026-10-29 |
| Status | Draft v2 — gap table refreshed for 0.5.4; Phase 0 security items delivered in branch `security-hardening-0.5.4` |
| Method | Static analysis only. No PhraseExpress binary was executed. No PhraseExpress code, assets, keys or text are reproduced here. |

---

## Status note (v2)

Draft v1 was written against an outdated local checkout (about 0.3). The
**gap table in Section 2 is now re-checked against release 0.5.4** with file-level
evidence: column "0.5.4" is the released state, column "After PR" is the state once
branch `security-hardening-0.5.4` is merged. The "PF status" column of the Section
1.2 inventory still reflects the older checkout; where it disagrees with Section 2,
**Section 2 wins**. Features 0.5.4 has that v1 did not know about are listed in
Section 1.5.

---

## 0. Evidence model and how to read this document

Every claim about PhraseExpress (PE) carries a tag:

| Tag | Meaning | Source |
|---|---|---|
| **[C-EXE]** | Confirmed: string, import, RTTI name, DFM form or embedded SQL seen in `phraseexpress.exe` | Section 0.2 |
| **[C-DLL]** | Confirmed: export, import or string seen in a companion DLL/EXE | Section 0.2 |
| **[C-DATA]** | Confirmed: structure observed in `%APPDATA%\PhraseExpress` files (structure only, no values) | Section 0.2 |
| **[I]** | Inferred from confirmed evidence; must be validated before the requirement is closed | — |
| **[U]** | Unknown; listed in Section 10 | — |
| **[REPO]** | Observed in the PhraseForge (PF) working tree, with file:line where useful | — |

This is the claim discipline from LeanREA (seen/inferred/unknown) and REA (evidence authority + confidence), plus AMA's requirement-traceability rule: each FR maps to a test ID (Section 7). A static string being present does not prove the feature is reachable or enabled in this build (LeanREA: "not found ≠ absent; static ≠ runtime").

### 0.1 Assumptions

- A1. Running PE for behavioural capture was **not done**. Every PE timing/behaviour number in this PRD is [I] until a capture harness (Section 7.6) confirms it. Behavioural parity tests that need PE ground truth are marked `needs-PE-capture`.
- A2. PE's `.pexdb` files are SQLCipher-encrypted [C-DATA]. No decryption was attempted, and this PRD does not require it (see D3, Section 8).
- A3. The PF test venv is `C:\venvs\phraseforge` (Python 3.14, 64-bit). The PF results quoted here come from a run on 2026-10-29.
- A4. The reference repos were read through the GitHub API, not cloned or executed.

### 0.2 What was analysed

| Artifact | Technique | Notes |
|---|---|---|
| `phraseexpress.exe` (155 MB, x86) | PE header/section/import parse, ASCII+UTF-16 string extraction with offsets, Delphi unit-name scan, DFM resource decode (295 forms), embedded SQL extraction (35 scripts, 4 dialects) | Raw extracts were saved in the session scratchpad (`re_exe\`, `re_exe_dump\`). Copy them into `docs/evidence/` if they must be kept. |
| `pexkey.dll`, `pexmsol.dll`, `pexlang.dll`, `Plugins\*.dll`, `pexUpdateService.exe`, `pexinst.exe`, `sqlcipher.dll`, `hunspelldll.dll`, OpenSSL DLLs, `mailconfig.dat`, `dict\` | pefile export/import tables, string extraction, capstone call-site disassembly (hook types, posted message IDs) | REA's decompiler back ends (Ghidra/IDA) were not configured, so there is no pseudocode. |
| `%APPDATA%\PhraseExpress\*` | Read-only copies: header bytes, entropy, page/journal sizing, XML element tree | Phrase content, keys, tokens and personal values were deliberately not read or recorded. |
| PF repo | Full source read, test run | 434 tests: 414 passed before a hang in a full run; all pass when the suite is split in two (Section 7.1). |
| AMA, LeanREA, REA | GitHub API read | Section 0.3 |

### 0.3 Techniques drawn from the reference repositories

| Repo | License | What this PRD uses |
|---|---|---|
| **REA** (`morluto/rea`, MIT; its MCP server is installed locally as `mcp__rea__*`) | MIT | (1) Evidence records with authority/confidence/limitations, hence the tag scheme above. (2) An **unknowns registry** (`record_unknown`/`verify_unknown_resolution`); Section 10 is written to be loaded into it. (3) The **reconstruction obligation ledger** (`build_reconstruction_obligation_ledger`, `verify_reconstruction`, `evaluate_reconstruction_coverage`) is the acceptance framework: each FR is an obligation, closed only by a passing test bound to the implementing commit. (4) Recon order: imports/exports, then resources, then strings and xrefs, then decompile. (5) A Frida plan for runtime confirmation (Section 7.6). Limits: REA's SQLite inspector cannot read SQLCipher; its native process/UI capture is Linux/macOS only, so Windows needs our own harness; 32-bit PE support depends on the installed REA version. |
| **LeanREA** (`aicodeking/leanrea`, MIT) | MIT | CLI-first recon checklist: identify by magic bytes, cheap inventory before decompiling, slice output, work on copies, open SQLite read-only with its `-wal`. Its "minimal reimplementation, then differential test with the same inputs and outputs" rule is the basis of the behavioural tests (Section 7.3). |
| **AMA** (`bahattab/AMA`, private, no license; owned by the user) | none | Governance, not RE: claim states (VERIFIED / SUPPORTED INFERENCE / ASSUMPTION / UNKNOWN), a requirement-traceability matrix, risk and assumption registers, and acceptance gates per phase (Section 6). |

None of the three provides Delphi-specific recovery (IDR, DFM/VMT/RTTI) or SQLCipher handling. The DFM forms were decoded with a custom script, and Delphi RTTI names came from string scans.

---

## 1. Feature inventory of PhraseExpress 18.0.84

### 1.1 Binary roles

| Binary | Arch | Role | Key evidence |
|---|---|---|---|
| `phraseexpress.exe` 18.0.84 | x86 | Everything else: UI, phrase DB, triggers (except raw key capture), macro engine, output, sync, AI host, importers. Delphi 13 VCL with DevExpress, TRichView, FireDAC, Indy/ICS, WebView2. Authenticode-signed. | [C-EXE] compiler string "Embarcadero Delphi for Win32 compiler version 37.0"; `.rsrc` 113.75 MB (81 MB RCDATA icon sprites, 27.6 MB DevExpress skins); 295 DFM forms |
| `pexkey.dll` 18.0.22 | x86 | Global low-level keyboard + mouse hook on its own thread; keeps a key buffer; auto-caps fixes; keyboard blocking. Posts `WM_USER+n` messages to the main window `TpexMWnd4`. | [C-DLL] exports `SetHook, RemoveHook, SetHookFunctionsActive, BlockKeyboard, GetBlockState, ResetKeyBuffer, SetAutoState, SetAutoFirstCaps, SetAutoFixDoubleCaps, SetAutoFixAllCaps, GetThreadID`; disassembly shows `SetWindowsHookExW(13)` (WH_KEYBOARD_LL) and `(14)` (WH_MOUSE_LL); PostMessage 0x401–0x416, SendMessage 0x433/0x434 for a 16-slot key buffer |
| `pexmsol.dll` 1.0.2 | **x64** (the only x64 binary) | Outlook COM add-in (Add-in Express for VCL). Sends the current mail's context as XML to `TpexMWnd4`. | [C-DLL] `DllRegisterServer/DllGetClassObject`; TypeLib "PhraseExpressForOutlook"; `<olmail>` XML with from/to/cc/bcc/subject/body/htmlbody/rtfbody/attachments and contact fields. Transport (WM_COPYDATA?) is [U-07]. |
| `pexlang.dll` | x86 | UI string table, English + German, 523 RT_STRING blocks with per-language ID offsets | [C-DLL] manifest string `English|100:$09;Deutsch|5100:$07;` |
| `Plugins\{anthropic,openrouter,ollama,gpt4all}.dll` | x86 | AI/translation engine plugins sharing one C-style export ABI (Section 1.4) | [C-DLL] export tables |
| `pexUpdateService.exe` 18.0.1 | x86 | Windows service. Takes a downloaded installer from `%WINDIR%\Temp\PhraseExpressTemp\`, verifies its Authenticode signature against a pinned signer, installs it silently, then relaunches the app in the user's session. | [C-DLL] `Global\PhraseExpressUpdateEvent`, `WTSQueryUserToken`/`CreateProcessAsUserW`; `updatelog.txt` [C-DATA] |
| `pexinst.exe` | x86 | Restart / restart-elevated helper | [C-DLL] `ShellExecute "runas"`, `-restart`, `-restartadmin` |
| `sqlcipher.dll` 3.39.4 | x86 | Encrypted SQLite engine for local phrase files | [C-DLL] `sqlite3_key(_v2)`, `sqlite3_rekey(_v2)`; [C-EXE] FireDAC `page_size=4096`, `LockingMode=EXCLUSIVE`, `cipher_profile` |
| `hunspelldll.dll` 1.3.2 + `dict\` (9 languages) | x86 | Spell checking in the phrase editor via TRichView | [C-DLL] |
| `libeay32/ssleay32` 1.0.2u and `libcrypto-3/libssl-3` 3.6.4 | x86 | TLS: legacy Indy needs 1.0.x; newer paths use 3.x | [C-DLL] [I] |
| `mailconfig.dat` | — | ZIP holding one WinZip-AES-encrypted `mailconfig.xml`, probably an SMTP/IMAP provider auto-config database | [C-DLL] structure; content [I] |

Single-instance and IPC objects [C-EXE]: `Global\PhraseExpressMutex`, `Global\PhraseExpressEvent`, `Global\PexRunEvent`, `Global\PhraseExpressUpdateEvent`; named pipes; UDP discovery; the `pex://` URL protocol.

### 1.2 Feature inventory

*PF status below reflects the ~0.3 checkout; see Section 2 for 0.5.4.* Legend for **PF status**: ✅ reproduced · 🟡 partial · ❌ missing · ➕ PF-only. "Partial" means PF has the feature but lacks options PE shows.

#### A. Phrase store and organisation

| # | PE feature | How PE does it (evidence) | PF status |
|---|---|---|---|
| A1 | Tree of phrase files → folders → phrases, all held in one `data` table (GUID id, pid, datatype, pos, color, icon, desc, allowed/declined apps, timing, paste target, hint, tag, comment, trigger BLOB) | [C-EXE] SQLite DDL `CREATE TABLE data(...)` | ✅ `db.py:40-72` (integer IDs, separate folders/phrases tables) |
| A2 | Multiple phrase files at once (local, network, URL, FTP, SQL server, cloud folder), each with its own password and sync settings | [C-EXE] `files` table: `localpath, networkpath, urlpath, ftppath, sqlpath, filetype, doudp, syncdate`; [C-DATA] `PhraseFile/Data/phrases/file*` | ❌ one DB per profile |
| A3 | **Levels**: per-language/variant content for each phrase (`phrases` is UNIQUE(id, lid)), with level hotkeys; `{#setlevel}` | [C-EXE] tables `levels(lid,hk,desc,abbr)`, `datalevels`, `taglevels` | ❌ |
| A4 | Content formats per phrase: plain, RTF, HTML, RTF-diff, view mode; embedded files and images (`embfiles`); OLE/Word objects | [C-EXE] `phrases(plain, rtf, html, rtf1, rtfd, lang, viewmode)`, `embfiles(fid,id,lid,type,data,filename)` | 🟡 text and HTML only, images via HTML; no RTF, no embedded files table |
| A5 | Tags (tags, datatags, taglevels) | [C-EXE] | ✅ `phrase_tags` |
| A6 | Comments on phrases (per user) | [C-EXE] `comments(cid,id,uid,lid,flag,…,text)` | ❌ (PF has a single `notes` field) |
| A7 | Version history for items, phrases and files, written by DB triggers; retention by count and by days | [C-EXE] `datahistory, phraseshistory, historyfiles`; `options(historynum, historydays)` | 🟡 `phrase_history` snapshots, no retention policy |
| A8 | Trash / deleted items with restore path | [C-EXE] `deleteditems`, `data.restorepath` | ❌ deletes are hard |
| A9 | Template folders, phrase links | [C-EXE] `folders.istemplate`; TExtendedFrame [I] | ❌ |
| A10 | Folder text prefix/suffix added to every phrase (`ltextadd`, `rtextadd`) | [C-EXE] | ❌ |
| A11 | Folder sort options (two keys, direction, mode) | [C-EXE] `sortfield/dir/mode, sortfield2/dir2` | 🟡 manual `sort` only |
| A12 | **Dynamic folders**: phrase lists filled live from Excel, CSV, SQL (Firebird/MSSQL/MySQL/Access/SQLite) with field mapping and a cache | [C-EXE] `folders(constr, querystr, fieldmap, cachedyndata, cachedate)`; TDyn*SettingsFrame | ❌ (PF has only `{#xls*}`/`{#sql}` macros) |
| A13 | "Floats": phrases placed on the desktop as windows | [C-EXE] `floats(id,uid,x,y,width,height)` | ➕ sticky-notes integration is the nearest equivalent; ❌ parity |
| A14 | Per-item ACLs: users, workgroups, domains, with rights | [C-EXE] `datausers, dataworkgroups, datadomains, editusers` | ❌ |
| A15 | Usage statistics per user; typing speed and hourly-rate savings | [C-EXE] `userstats`; separate stats DB; TStatsForm | ✅ `usage_log`, `stats_window.py` |
| A16 | Phrase-file encryption at rest (SQLCipher) | [C-DLL] [C-DATA] every `.pexdb` has 8.00 bits/byte entropy and no SQLite header | ❌ plaintext SQLite |
| A17 | Password protection for phrase files, checked on start, open, expand or view (`passcheck` modes) | [C-EXE] `files.password, passcheck`; TPassDlg, TPassEditDlg | 🟡 unsalted SHA-256 folder lock that gates only the tree UI (`db.py:109`); expansion and popup bypass it |
| A18 | Macro text in phrases stored encrypted in the DB | [C-EXE] `UPDENCRYPTPLAINMACROS … WHERE plain LIKE '%{#%'` | ❌ |
| A19 | Clipboard cache and "last used" stored as their own phrase files | [C-DATA] `clipboard.pexdb`, `lastused.pexdb` | ✅ functionally (`clipboard` table, Last Used node) |

#### B. Triggers

| # | PE feature | Evidence | PF status |
|---|---|---|---|
| B1 | Autotext with word position end / middle / entire / beginning | [C-EXE] TTriggerAtextSectionFrame | ✅ `autotext.py` |
| B2 | Execution timing: as detected, manual confirmation, on typing pause, **on fast typing only** | [C-EXE] trigger timing strings; `data.timingtype, timinginterval` | 🟡 immediate/confirm/pause/continue; no "fast typing only" |
| B3 | Delimiter classes for prefix and postfix: All, Standard, Letters, Numbers, Enter, Tab, Space, Point, Comma, Custom, Refine; "remove trailing char"; global `CharsBefore/CharsAfter/SentenceDelimiters` | [C-EXE] TExpertDlg; [C-DATA] `Expert/*` | 🟡 Default/None/Space/Enter/Tab/Punct/AnyNonLetter; no per-class Letters/Numbers/Point/Comma/Custom |
| B4 | Global autotext prefix | [C-DATA] `Expert/GlobalPrefix` | ❌ |
| B5 | Block and resend Enter/Tab (route Enter) | [C-DATA] `DoRouteEnter` | ✅ "route Enter/Tab" |
| B6 | Unwanted-autotext detection and threshold (auto-skip after repeated undo) | [C-DATA] `AutoSkip, SkipAtextThreshold` | 🟡 undo within 10 s (`manager.py:410`), no learned auto-skip |
| B7 | Skip-next-autotext hotkey | [C-EXE] `SkipHotkey` | 🟡 a pause command exists; no one-shot skip |
| B8 | SmartComplete (suffix tree, refine from N chars) | [C-EXE] `SuffixTreeU` | ✅ `manager.py:395,587`, `smartcomplete_tip.py` |
| B9 | RegEx autotext, with presets: email, URL, ISBN, IPv4, IPv6, MAC, time | [C-EXE] | 🟡 regex yes, presets no |
| B10 | Hotkey triggers through `RegisterHotKey` plus a hook-based path | [C-EXE] imports RegisterHotKey; [C-DLL] LL hook | ✅ hook-matched only (`hotkeys.py:56`) |
| B11 | Window trigger (application focus) | [C-EXE] TTriggerAppSectionFrame | ✅ |
| B12 | Time trigger plus scheduled tasks `Tasks/Task0–9` | [C-EXE], [C-DATA] | 🟡 daily/every-N only; no task list UI |
| B13 | Clipboard trigger and RegEx clipboard trigger | [C-EXE] | ✅ |
| B14 | Allowed/declined apps per item and globally; per-app output method (`AppMethods`) | [C-DATA] | ✅ |
| B15 | Auto-caps fixes (first caps, double caps, all caps), done inside the hook DLL | [C-DLL] `SetAutoFirstCaps/FixDoubleCaps/FixAllCaps` | ✅ `manager.py:567` |
| B16 | Keyboard blocking during output | [C-DLL] `BlockKeyboard`; [C-EXE] `BlockInput` | 🟡 `set_busy` suspends triggers but does not block user keystrokes |
| B17 | Mouse LL hook to reset the key buffer on click | [C-DLL] WH_MOUSE_LL | ✅ buffer resets on clicks (`autotext.py:36`); verify the mechanism |

#### C. Input capture, caret and output

| # | PE feature | Evidence | PF status |
|---|---|---|---|
| C1 | LL keyboard hook in a dedicated DLL thread, posting to the UI | [C-DLL] | ✅ ctypes `WH_KEYBOARD_LL` on its own thread (`keyboard_hook.py`), but the callback runs Python under the GIL (risk R1) |
| C2 | Key-by-key output with selectable method (VK_PACKET vs SendKey) | [C-DATA] `KeyByKeyPasteMethod` | ✅ vk_packet / unicode / scancode (`sendinput.py:77`) |
| C3 | Clipboard paste with formats, clipboard backup and restore, and delays `FocusDelay, SimKeyDelay, RestoreClbDelay, PlainClbDelay2, RndDelay` | [C-DATA] | ✅ except `RndDelay` (randomised typing delay) ❌ |
| C4 | Force focus before output | [C-DATA] `ForceFocus` | 🟡 |
| C5 | Caret position for the popup via MSAA (`AccessibleObjectFromWindow`, `DoACC`), `GetCaretPos` and `GetGUIThreadInfo`; `CaretPositionMode` | [C-EXE] imports oleacc | 🟡 GetGUIThreadInfo only (`windows.py:117`); fails in Chromium/Electron and WPF |
| C6 | Paste targets: current app, a specific window, clipboard, file, email | [C-EXE] TPasteTargetFrame, `data.pastetarget, pasteparams` | ✅ `output_target.py:41` |
| C7 | Elevation handling: `pexinst -restartadmin` | [C-DLL] | ❌ silently fails in elevated windows (UIPI) |
| C8 | Session awareness (`WTSRegisterSessionNotification`), RDP guest install | [C-EXE] | ❌ |
| C9 | Text-to-speech (SAPI) | [C-EXE] `SAPI.SpVoice` | ❌ |
| C10 | Keyboard layout switch/convert (`{#setlayout}`, `{#convertlayout}`) | [C-EXE] | 🟡 `{#setlanguage}`; no convert-layout |

#### D. Macros

PE macro names [C-EXE, from the macro name table], compared with PF's 151 commands [REPO `macros/README.md`]. PF has the same overall syntax (`{#name … -opt value}`), but parameter names and some semantics differ. Rows marked **compat** need an alias or translator so that phrases imported from PE run unchanged (FR-MAC-01).

| PE group | PE macros | PF equivalent | Status |
|---|---|---|---|
| Input / forms | input, form, formtext, formseparator, formeditbox, formmemo, formcheckbox, formradiogroup, formcombobox, formcalendar, formphrasecombo, formnum, formslider, formgroup, formcheckcombo, forminput, formvalue; field validation (Anything, Email, URL, File path, Folder, Letters, Numbers, Text, Custom), `-required`, group visibility, button IDs | input, form, formedit, formmemo, formcombo, formcheckbox, formradio, formdate, formnumber, formlabel, formseparator, formslider, formphrases, formenum, formvalue | 🟡 compat names; **formgroup, formcheckcombo, validation presets and required fields are missing** |
| Clipboard | clipboard, insertclipboard, setclipboard, flushclipboardcache | clipboard, clipboardhistory, setclipboard | 🟡 flushclipboardcache missing |
| Phrase / output | insert, setphrase, output, outputall, pasteoptions, setlevel, autotext, qstext, setqstext, embed, embedfile, embfile, pastefile, cursor, contents | insert, setphrase, pastefile, pastemethod, cursor, outputfile | 🟡 output/outputall/setlevel/qstext/embed/contents missing |
| Date / time | date, time, datetime (`-f` Delphi format tokens d…dddddd, mmmm, yy, hh, nn, ss, am/pm; `-d`, `-w`), calendar, datecalc, timecalc | date, time, datetime, timestamp, datecalc, timecalc, datepick | 🟡 compat: Delphi format tokens (`nn` = minutes) must map to PF format |
| Logic / vars | cond (`-if -then -else -case`), check, loop (`-count`), setvar (`-value`), settemp, gettemp, calc, explode, numlist (`-style -level -start`), asc | if/elseif/else, loop, foreach, set, var, unset, calc, ascii | 🟡 compat: cond→if, check; **explode, numlist, settemp/gettemp missing** |
| Strings | length, substr, trim, trimleft, trimright, replace, lowercase, uppercase, lowercasefirst, uppercasefirst, lowercaseword, uppercaseword, autocase, decstr, lastchars, regexget, regexpos, regexrep, regexcount, urlencode, urldecode, randomtext, textempty, checktext, headfootfilled, prefix, postfix, parse | upper, lower, title, ucfirst, lcfirst, ucwords, lcwords, trim, ltrim, rtrim, replace, regexreplace, regexget, substr, length, urlencode, urldecode, randomtext… | 🟡 compat names; **autocase, decstr, lastchars, regexpos, regexcount, textempty, checktext, headfootfilled, prefix, postfix, parse missing** |
| Files | textfile, imgfile, wordfile, rtffile, htmlfile, insertfile, opendlg, savedlg, docgen, dictionary (`-deffilename`) | textfile, image, document, fileselect, filesave, docgen | 🟡 dictionary missing |
| System | run, open, openfolder, focus, getfocus, getwindowtitle, waitfor, sleep, msgbox, balloon, sound, mouseposition, mousex, mousey, mousewheel, pexversion, lastpos, mail, dban, adldap | run, open, focus, windowtitle, waitfor, sleep, message, notify, mouse, mail, ad | 🟡 mousex/mousey/mousewheel/mouseposition/sound/getfocus/dban missing; `licensekey` is out of scope |
| Keyboard layout | setlayout, getlayout, convertlayout | setlanguage | 🟡 |
| **Macro recorder** | macrorecorder, mouserecorder, mrkey, mrwheel, mrsleep, mrmousemove, mrchars (`.mrf` files) | — | ❌ |
| Office / data | extractcell, extractxml (`-xpath`), getxlscol, getxlsrow, extractxlscol, extractxlsrow, **olmaildata**, ddemacro, ddeset, sql (`-connectionstring -query -fieldseparator -rowseparator`) | xls, xlsfind, xlsfindcol, xlsfindrow, xml, sql, dbquery, outlook | 🟡 olmaildata (needs Outlook context) and DDE missing |
| Web / AI | url, httprequest (`-url -post`), bitly, twitter, translate (`-fromlang -tolang -glossary`), langdetect, deepl (`-query`), openai (`-input -preset`) | http, web, ai, translate | 🟡 langdetect, deepl missing; bitly/twitter are obsolete APIs and out of scope |
| Gender | detectgender, findname, mtgenderswitch | gender | 🟡 |
| Keys | `{#CTRL …}`-style nestable modifiers, ENTER…F12, LEFT/RIGHT `-count n`, mouse buttons, numpad, media keys | key, enter, tab, …, f1–f12 | 🟡 compat: nestable modifier blocks, `-count`, media/numpad keys |
| Engine | macros encrypted at rest; macro syntax checking (`Edit/CheckSyntax`) | AST parser; errors written as `[name: error]` | 🟡 no syntax checker in the editor |

#### E. UI and workflow

| # | PE feature | Evidence | PF status |
|---|---|---|---|
| E1 | Ribbon main window (192 actions), tree, multi-column phrase list (`UI/PhraseCol*0–15`) | [C-EXE] TpexMWnd4 DFM | ✅ `ribbon.py`, `tree_panel.py` |
| E2 | Rich editor with spell check, tables, images, find/replace, character map, font dialog, DOCX/Markdown/HTML import/export | [C-EXE] TFrmRV*, TRichForm | 🟡 HTML QTextEdit, no spell check, no Markdown/DOCX |
| E3 | Popup menu, QuickKeys, QuickSearch (inline, case, subfolders, Quick Jump), repeat last output, dark mode, ~20 colours | [C-DATA] `Popup/*`, `Search/*` | ✅ `popup.py` (verify Quick Jump and repeat-last) |
| E4 | Clipboard cache window with auto-collect, dedupe, plain-only, trim | [C-DATA] `ClipCache/*` | ✅ |
| E5 | Autotext learning (word graph + corrections, `words.pal`), learns from Outlook, AutoCorrect | [C-DATA] words.pal is an encrypted ZIP; [C-EXE] `<connections><corrections>` | 🟡 sentence-repeat learner, AutoComplete word learner |
| E6 | First-start wizard, bubble help, tray hints | [C-EXE] | ✅ wizard, tray |
| E7 | Settings dialog | [C-EXE] TSettingsForm | ✅ 26 pages |
| E8 | Print / print preview | [C-EXE] | ✅ `main_dialogs.py` |
| E9 | Duplicate finder / removal | [C-EXE] TDelDupConfDlg | ❌ |
| E10 | Backup: count retention, compare file versions, restore, optimise/vacuum | [C-EXE] TFileBackupDlg, TFileCompareDlg, TOptimizeDlg | 🟡 backup and restore; no compare, no vacuum UI |
| E11 | UI languages EN/DE | [C-DLL] pexlang | ➕ EN/AR, but only ~64 strings translated |
| E12 | Event sounds (6) | [C-DATA] `DoSound0–5` | ✅ `sounds.py` |
| E13 | Toast notifications (WinRT) | [C-EXE] `RoActivateInstance` [I] | 🟡 tray balloon |
| E14 | Admin lockdown via machine-wide `C:\ProgramData\PhraseExpress\config.xml` (`ConfigDisabled, EditDisabled, DoStats`) | [C-DATA] | ❌ |
| E15 | CLI switches (Section 3.9) and portable mode | [C-EXE] | ❌ (only the `PHRASEFORGE_HOME` env var) |

#### F. Integration, sync, network

| # | PE feature | Evidence | PF status |
|---|---|---|---|
| F1 | Cloud-folder sync: Dropbox, OneDrive, Google Drive, iCloud | [C-EXE] | ✅ folder remote + Google Drive OAuth (`cloud/sync.py`) |
| F2 | **Change-set sync** ("hub", `.pexdbhub`, `.pexdbupd`) with tombstones, synced-change log, sync users, master client | [C-EXE] `syncedchanges, synclog, deleteditems`; TSyncUsersDlg | ❌ PF syncs whole snapshots with a keep-mine/keep-theirs choice |
| F3 | Client-server: MS SQL Server, MySQL, Firebird back ends; UDP server discovery | [C-EXE] four DDL dialects; `ListenUDPPort` | ❌ |
| F4 | LDAP/AD and Microsoft Entra ID (OAuth v2 + Graph `me, memberOf, users, groups`) for identity and ACLs | [C-EXE]; [C-DATA] `AzureAD/*` | ❌ (PF has `{#ad}` lookups only) |
| F5 | Outlook add-in that supplies mail context | [C-DLL] pexmsol | ❌ |
| F6 | Mail sending: mailto, MAPI, Outlook OLE, Gmail | [C-DATA] `MailMode` | 🟡 mailto + Outlook COM |
| F7 | Proxy with auto-detect (WinHTTP) | [C-EXE] | 🟡 manual proxy (`net.py`) |
| F8 | Auto-update through a signed-installer service | [C-DLL] | ❌ |
| F9 | Microsoft Office COM, DDE | [C-EXE] | 🟡 COM through macros |

#### G. AI and translation

| # | PE feature | Evidence | PF status |
|---|---|---|---|
| G1 | Built-in OpenAI engine: chat, images, image edits; presets (Instruction, Length, Accuracy, Variation, Model); text-info and answer instructions | [C-EXE] api.openai.com/v1; [C-DATA] `AIPresets/*` | 🟡 text chat only |
| G2 | **Plugin engines** (Anthropic, OpenRouter, Ollama, GPT4All) behind a common ABI with capability discovery | [C-DLL] Section 1.4 | 🟡 providers hard-coded in `ai.py:98` |
| G3 | Translation: DeepL (free/pro), AI engines; glossaries (name, fromlang, tolang, dict), ignored words; language detection | [C-EXE]; [C-DATA] `Translation/*` | 🟡 AI translation + glossary; no DeepL, no langdetect |
| G4 | Vision (GenerateTextFromImage), image generation/edit (OpenRouter) | [C-DLL] | ❌ |
| G5 | Local models: Ollama model pull/delete with progress; GPT4All through a Python bridge | [C-DLL] | 🟡 Ollama chat only |
| G6 | Usage/balance stats per engine | [C-DLL] `GetEngineUsageStats` | ❌ |

#### H. Import / export

| PE importers [C-EXE] | PF |
|---|---|
| TextExpander (incl. 5+), Texter, AutoHotkey (`.ahk`), Breevy, ShortHand, ShortKeys, GhostTyper, Direct Access, InstantText, Word AutoCorrect/AutoText, Outlook, Excel, CSV, SQL, folder structure; extensions `.textexpander .texter .ahk .glo .spf .gtx .dta` | ✅ TextExpander, CSV, JSON, txt folder · ➕ OneNote, Sticky Notes · ❌ everything else |
| PE exporters: HTML, CSV, XML, Word, Excel, Android, TextExpander | ✅ JSON, CSV, txt · ❌ HTML/XML/Word/Excel/TextExpander |
| Native PE formats `.pxp .px3 .pxa .pexdb .pexdbupd .pexdbhub .pexmigration .pal .mrf` | ❌ none (see D3) |

#### I. Present in PF but not in PE (keep)

Screen OCR via Capture2Text, OneNote import/send/clip, Windows Sticky Notes import, Google Drive OAuth with DPAPI-protected token, Arabic UI and right-to-left layout, AST-sandboxed calculator, chip-style macro display in the editor, typing-speed test.

### 1.3 Data files of the installed instance

| File | Format [C-DATA] | Notes |
|---|---|---|
| `config.xml` | `<xml><pexconfig>` → one element per key, text values (0/1, ints, TDateTime floats, `|`-lists) | Key tree in Appendix B. Secrets (`*APIKey`, `AzureAD/*Token`) sit in this file [C-DATA]; whether they are obfuscated is [U-05]. |
| `*.pexdb` | SQLCipher, 4096-byte pages, rollback journal (`-journal` = 512 + n·4104 bytes) | Schema known from the embedded DDL (Appendix A); key derivation is [U-01]. |
| `words.pal`, `mailconfig.dat` | ZIP with a WinZip-AES-encrypted entry | — |
| `updates.xml` | Version channels (new/major/minor/experimental/beta) per install type (standard/usb) | — |
| `PhraseExpressBackup\<base>_<6hex>_Local\<dd_MM_yy hh-mm-ss AMPM>.pexdb.bak` | Byte copy of the encrypted pexdb; retention `BackupCountSQL`; AM/PM marker follows the locale | — |
| `C:\ProgramData\PhraseExpress\config.xml` | Machine-wide lockdown and licensing | — |

### 1.4 PE AI plugin ABI (reconstructed interface contract)

All four DLLs are x86 Delphi with plain exports [C-DLL]. **Common exports (31):** `Init, GetEngineType, GetEngineDescription, GetEngineProviderName, GetEngineProviderWebURL, GetEngineProviderHelpURL, GetIsLocal, GetIsConfigurable, GetIsConfigured, GetNeedsAPIKey, GetLastEngineError, CheckConnection, ConfigurePython, SetProgressCallback, CancelExecTask, GetSupportedSettings, GetSupportedModelIDs, GetSupportedModelNames, GetSupportedLanguageIDs, GetSupportedLanguageNames, GetSupportsGlossaries, GetSupportsIgnoredWords, GetSupportsCustomInstructions, UpdateGlosaary, TranslateText, GenerateText, AddSystemInput, AddInput, StartComplexAction, ExecComplexAction` plus Delphi helper exports.

**Optional exports, probed by name:** `SetAPIKey, Configure, GetHasExtAuth, GetSupportsTranslationModelSelection, GetSupportedImageModelIDs/Names, GenerateImage, EditImage, GetEngineUsageStats, CancelConfigurationTask, GetIsNeededAppInstalled, GetOptsUI, SetOptsValues, GetEngineConfigDescription`.

Semantics: Params is a `Key=Value` list (Model, MaxTokens, Temperature, Top_k, Instruction, IgnoreTags, glossary) [I]. `GetSupportedSettings` returns a CSV of the abstract knobs `Length, Accuracy, Variation, Model` [C-DLL]. The host maps them to provider fields (Length→max_tokens, Variation→temperature, Accuracy→top_p/top_k/penalty) [C-DLL]. `GetOptsUI` returns a small XML form descriptor [C-DLL]. There is no ABI version export, so capability is detected by which exports exist [I]. The exact calling convention and string types (Delphi `string` vs `PWideChar`) are [U-03]. **PF will not load these DLLs** (D2); the contract is used only as the model for PF's own plugin interface (FR-PLG-*).

### 1.5 PhraseForge 0.5.4 features not in PhraseExpress (keep)

Built-in OCR (Windows.Media.Ocr, Capture2Text-style modes, optional Mistral OCR, PDF/image to Markdown) ·
built-in desktop sticky notes and a Microsoft Sticky Notes importer · quick-note window (send to OneNote or
save as phrase) · OneNote COM send/read and `{#onenote}` · Prompt Tower, Prompt Optimizer, Boost-prompt
hotkey (`{#promptboost}`) · AI engines Gemini, OpenCode Zen, Kilo Code, GPT4All, Mistral, DeepL and free
translate · Listary-style "Search files" launcher · DOCX/PDF export with Arabic RTL · TextExpander, macOS
Text Replacements and PhraseExpress-CSV exchange · HTML→RTF clipboard output · full Arabic RTL UI, Arabic
user guide, Hijri dates · Windows installer, portable EXE, GitHub update check · Google sign-in with a
built-in or own OAuth client.

---

## 2. Gap analysis

Priority: **M** must-have (core parity, or a security defect), **S** should-have, **N** nice-to-have. Complexity: S ≤ 3 dev-days, M ≤ 2 weeks, L ≤ 6 weeks, XL > 6 weeks.

| ID | Gap | Priority | Complexity | FR | 0.5.4 | After PR |
|---|---|---|---|---|---|---|
| G-01 | Secrets stored in plain text and uploaded by sync | M (sec) | S | FR-SEC-01..03 | partial: 8 AI keys DPAPI-sealed and kept out of sync (`db.py` SECRET_SETTINGS); `net.proxy_password` plain and synced | closed: proxy password sealed and device-only; plain values from old versions or restored backups are sealed and wiped from the file |
| G-02 | Macro trust model for imported/synced phrases (`{#run}`, `{#http}`, `{#sql}`, `{#mail -send}`; time/app triggers) | M (sec) | M | FR-SEC-04/05 | open | closed: imported phrases and phrases a sync pull adds or changes are quarantined per PC; their privileged macros (`run, open, web, http, mail -send, outputfile, dbquery, setphrase`, Win-key chords) ask Run once / Always allow / Do not run, automatic triggers skip them; engine blocks them at run time, also through `{#insert}` (`security.py`) |
| G-03 | Folder password: unsalted SHA-256, UI-only gate | M | M | FR-SEC-07/08 | open (`db.py` hash_password) | closed: salted scrypt (old hashes upgraded on unlock); locked folders ask for the password before any expansion, are hidden from the phrase menu and its search, never feed SmartComplete, and cannot be read through `{#insert}`; one unlock per session counts everywhere (`security.LOCKS`) |
| G-04 | Encryption at rest for the phrase DB | S | M | FR-SEC-09 | open | open |
| G-05 | Hook callback runs Python under the GIL | M | M | FR-INP-01..03 | open (`keyboard_hook.py`) | open (P1) |
| G-06 | UIPI / elevated-window handling | M | S | FR-INP-04 | open | open (P1) |
| G-07 | MSAA/UIA caret fallback | S | M | FR-INP-05 | open (GetGUIThreadInfo only) | open |
| G-08 | Single-instance guard + argv hand-over | M | S | FR-APP-01 | open | closed: mutex + user-only local pipe per data folder |
| G-09 | CLI switches, portable mode | S | M | FR-APP-02/03 | partial: `--self-test`, `--minimized`, portable EXE, `PHRASEFORGE_HOME`; portable EXE still writes %APPDATA% | partial |
| G-10 | Trigger options (fast-typing-only, global prefix, delimiter classes, regex presets in trigger editor, skip-next, learned auto-skip, key blocking, random delay) | M | M | FR-TRG-01..07 | partial: modes immediate/confirm/pause/continue; regex presets only in macro dialog | partial |
| G-11 | Missing macros + PE macro-syntax layer | M | L | FR-MAC-01..06 | partial: a few PE aliases (insertclipboard, formeditbox, formcombobox, msgbox, embed, imgfile, openfolder, openai); no translator; explode, numlist, settemp/gettemp, autocase, regexpos/count, setlevel, output, langdetect, sound, mouse x/y missing | partial |
| G-12 | Form validation, required, formgroup, checkcombo | M | M | FR-MAC-04 | partial: `{#input -syntax}` presets and required; no formgroup/checkcombo | partial |
| G-13 | Plugin system | M | L | FR-PLG-01..08 | open (engines hard-coded in `ai.py`) | open (P4) |
| G-14 | AI parity (vision, image gen, Ollama pull, usage, DeepL, langdetect) | S | M | FR-AI-01..05 | partial: 8 providers + DeepL + language guess; no vision/image/pull/usage | partial |
| G-15 | Import from PhraseExpress | M | M | FR-IMP-01..03 | partial: CSV/TXT/TSV with header aliases; encrypted .pexdb/.pxp detected and refused with instructions; no XML, no macro translation | partial |
| G-16 | Other importers/exporters | S | M | FR-IMP-04/05 | partial: TextExpander, macOS plist, PE CSV, DOCX/PDF; no Texter/AHK/Breevy/Word AutoCorrect, no HTML/XML/XLSX export | partial |
| G-17 | Levels (language variants), hotkeys, `{#setlevel}` | S | L | FR-DAT-01 | partial: `phrase_versions(phrase_id, lang)` + active-language setting; no level hotkeys/`{#setlevel}` | partial |
| G-18 | Trash, comments, templates, links, folder prefix/suffix, multi-key sort | S | M | FR-DAT-02..05 | partial: folder abbreviation prefix, bulk sort | partial |
| G-19 | Multiple mounted phrase libraries | S | L | FR-DAT-06 | open | open |
| G-20 | Spell check | S | M | FR-EDT-01 | open | open |
| G-21 | RTF, embedded files, Markdown/DOCX into editor | N | M | FR-EDT-02 | partial: RTF clipboard output | partial |
| G-22 | Dynamic folders | S | L | FR-DYN-01/02 | open | open |
| G-23 | Macro recorder | N | L | FR-REC-01 | open | open |
| G-24 | Change-set sync | S | L | FR-SYN-01..04 | open (whole snapshot) | open |
| G-25 | Multi-user server, ACLs, directory identity | N | XL | FR-SYN-05 | open | open |
| G-26 | Outlook context | N | M | FR-OL-01 | partial: `{#outlook field}` via COM | partial |
| G-27 | Duplicate finder, backup compare, vacuum | N | S | FR-UI-01 | partial: bulk remove duplicates | partial |
| G-28 | Admin lockdown policy file | N | S | FR-APP-04 | open | open |
| G-29 | Auto-update | N | M | FR-APP-05 | partial: GitHub release check + setup link | partial |
| G-30 | SAPI, layout conversion, mouse/sound macros | N | S | FR-MAC-05 | open | open |
| G-31 | Full UI localisation | S | M | FR-UI-02 | partial: ~1000-string Arabic table, RTL | partial |
| G-32 | Full test suite hangs in one run (order-dependent Qt state) | M (quality) | S | FR-QA-01 | open: stalls at `test_ui.py::test_theme_icons_tray` | closed: leftover windows deleted after each test |
| G-33 | Session awareness (lock, RDP) | N | S | FR-INP-06 | open | open |
| G-34 | `{#http}` can reach localhost/LAN/metadata addresses (incl. via redirect) | M (sec) | S | FR-SEC-06 | open | closed: blocked by default, setting to allow |

PE evidence for each gap: Section 1.2. Also open in 0.5.4: `test_filesearch.py::test_speed_gate_50k_entries_answers_in_milliseconds` (median < 50 ms) fails on slower machines.

Out of scope by decision: licensing/activation, the vendor update server protocol, bit.ly/Twitter macros, DDE (`ddemacro/ddeset`, revisit on demand), Firebird/MySQL back ends, and the "AI for a fee" vendor proxy.

---

## 3. Clone requirements

Format: **FR-ID — statement.** *Acceptance:* testable criteria. *Test:* ID in Section 7. Requirements tagged `needs-PE-capture` must also match a recorded PE behaviour trace before they close.

### 3.1 Security (do first)

- **FR-SEC-01 — Secrets are stored DPAPI-protected (CurrentUser scope), never in plain text.** Applies to every settings key matching `ai.*key*`, `ai.*token*`, `net.proxy_password`, `cloud.*token*`, and any plugin-declared secret.
  *Acceptance:* (a) after setting a key, `SELECT value FROM settings` contains no substring of the key; (b) on a fresh DB the key round-trips through the UI; (c) a DB copied to another Windows user cannot decrypt it and the UI shows "re-enter key". *Test:* T-SEC-01.
- **FR-SEC-02 — Secrets and device-local settings are excluded from every sync upload, cloud backup and export.** *Acceptance:* the uploaded snapshot (or change set) contains none of the FR-SEC-01 keys; `export_dict()` omits them unless the user passes `include_secrets=True` and enters a password used to encrypt the export with AES-GCM. *Test:* T-SEC-02.
- **FR-SEC-03 — Migration.** On the first start of schema v3, existing plaintext secrets are encrypted in place, and the old rows are overwritten and the DB vacuumed. *Acceptance:* after migration, `strings phraseforge.db` finds no former key. *Test:* T-SEC-03.
- **FR-SEC-04 — Phrase trust levels.** Each phrase has `origin ∈ {local, imported, synced, plugin}` and `trusted_hash` (SHA-256 of its content when last approved). *Acceptance:* a phrase whose content hash ≠ `trusted_hash` and whose origin ≠ local cannot run privileged macros (FR-SEC-05) until it is approved. Editing a phrase locally re-approves it. *Test:* T-SEC-04.
- **FR-SEC-05 — Privileged macros** (`run, open` with non-http targets, `http` to non-public or user-unapproved hosts, `sql`/`dbquery` with write statements or ODBC, `outputfile`, `mail -send`, `ad`, plugin calls flagged privileged) require approval on first use for each (phrase, content hash). A trigger that fires without user input (time, app focus, clipboard) **never** shows an approval prompt; it skips execution and logs it. *Acceptance:* an imported phrase with `{#run calc.exe}` fired by a time trigger does not start calc and writes a log entry; the same phrase fired by its hotkey shows one approval dialog. *Test:* T-SEC-05.
- **FR-SEC-06 — `{#http}` blocks link-local, loopback and RFC1918 targets by default** (setting `net.allow_private_hosts=false`), after DNS resolution (DNS-rebinding safe: connect to the resolved IP). *Test:* T-SEC-06.
- **FR-SEC-07 — Folder/file passwords use Argon2id** (fallback scrypt; parameters stored with the hash, salt ≥ 16 bytes). *Acceptance:* the stored hash format is `$argon2id$…`; legacy SHA-256 hashes are upgraded on the next successful unlock. *Test:* T-SEC-07.
- **FR-SEC-08 — Password check modes, matching PE `passcheck`:** `on_start`, `on_open`, `on_expand`, `on_view`. *Acceptance:* with `on_expand`, an autotext trigger inside a locked folder shows the unlock prompt before any characters are deleted or typed; a wrong password leaves the typed abbreviation untouched; unlock lasts for the session or N minutes (setting). The popup and SmartComplete hide locked phrases' content. *Test:* T-SEC-08.
- **FR-SEC-09 — Optional DB encryption at rest** (D4): whole-DB encryption with a random 256-bit key wrapped by DPAPI, plus an optional user passphrase. *Acceptance:* the DB file has no `SQLite format 3` header and no plaintext phrase substring; open/close latency ≤ 150 ms more than unencrypted for a 10k-phrase DB. *Test:* T-SEC-09, P-04.

### 3.2 Input core

- **FR-INP-01 — The hook callback must not execute Python.** A native hook module (C or Rust, built as `pfhook.dll`, x64 + x86) installs `WH_KEYBOARD_LL` and `WH_MOUSE_LL` on its own thread, writes events (vk, scan, flags, time, injected flag, extra-info) to a lock-free SPSC ring buffer, and returns `CallNextHookEx` immediately, except for keys the host has synchronously armed for suppression (hotkey chords, routed Enter/Tab). *Acceptance:* p99 callback time ≤ 50 µs measured by an in-DLL QPC histogram; the hook survives a 30-s GIL stall induced in Python (Python thread holding the GIL in a busy loop) with no lost events and no hook removal. *Test:* T-INP-01, P-01.
- **FR-INP-02 — Suppression decisions are made in native code** from a compiled table pushed by Python (hotkey chords, route-Enter flag, "block all keys" during output), so suppression never waits on Python. *Acceptance:* a hotkey chord is swallowed, including its key-up, while Python is stalled. *Test:* T-INP-02.
- **FR-INP-03 — Self-injection filtering** by a magic `dwExtraInfo`, retaining the current `INJECT_MAGIC` contract [REPO]. A per-setting option chooses whether input injected by other programs is fed to the matcher. *Test:* T-INP-03.
- **FR-INP-04 — UIPI handling.** When the foreground process has a higher integrity level than PF, PF shows a single tray notice "Cannot type into elevated window <exe>" with a "Restart PhraseForge as administrator" action, using a small launcher equivalent to `pexinst -restartadmin`. *Acceptance:* with an elevated Notepad focused, typing an autotext gives the notice and nothing is half-deleted. *Test:* T-INP-04 (manual + integration).
- **FR-INP-05 — Caret location chain:** GetGUIThreadInfo → MSAA `AccessibleObjectFromWindow(OBJID_CARET)` → UIA `TextPattern2.GetCaretRange`/`GetBoundingRectangles` → mouse position. Setting `popup.caret_mode ∈ {auto, caret, mouse, center}`. *Acceptance:* the popup appears within 30 px of the caret in Notepad, Word, Chrome, VS Code and a WPF app; falls back without exceptions. *Test:* T-INP-05.
- **FR-INP-06 — Session events:** suspend hooks on workstation lock or session disconnect; resume on unlock. *Test:* T-INP-06.

### 3.3 Triggers

- **FR-TRG-01 — Timing mode `fast_typing_only`:** fire only if the abbreviation's inter-key intervals are all ≤ `trigger.fast_ms` (default 150 ms [I]). *Acceptance:* the same abbreviation typed at 300 ms per key does not fire. `needs-PE-capture` for the default. *Test:* T-TRG-01.
- **FR-TRG-02 — Global autotext prefix** (`triggers.global_prefix`, e.g. `#`): when set, autotext triggers match only if they are preceded by the prefix, and the prefix is deleted along with the abbreviation. *Test:* T-TRG-02.
- **FR-TRG-03 — Delimiter classes** for leading and trailing: All, Standard (the global set), Letters, Numbers, Enter, Tab, Space, Point, Comma, Custom (user string), as a multi-select per trigger. *Acceptance:* table-driven tests over every class × leading/trailing. *Test:* T-TRG-03.
- **FR-TRG-04 — Regex presets** in the trigger editor: email, URL, ISBN-10/13, IPv4, IPv6, MAC, time (HH:MM[:SS]). Each preset ships with positive and negative fixtures. *Test:* T-TRG-04.
- **FR-TRG-05 — Skip-next hotkey** (one-shot: the next autotext match is ignored) and **learned auto-skip**: if a given trigger is undone ≥ `triggers.skip_threshold` times (default 3) within 7 days in the same app, it is auto-disabled for that app, with a tray notice and a one-click restore. *Test:* T-TRG-05.
- **FR-TRG-06 — Keyboard blocking during output:** user keystrokes during output are buffered by the native hook and replayed after output finishes (default), or discarded (setting). *Acceptance:* typing "xyz" during a 2-s typed expansion yields expansion+"xyz" in order. *Test:* T-TRG-06.
- **FR-TRG-07 — Scheduled tasks list:** time triggers gain weekday masks, date ranges and "run once"; there is a Tasks view listing every time-triggered item and its next run. *Test:* T-TRG-07.

### 3.4 Macros

- **FR-MAC-01 — PE syntax compatibility layer.** A pure function `pe_compat.translate(text) -> (pf_text, warnings)` maps PE macro names and parameters to PF equivalents: alias table (e.g. `cond→if`, `uppercase→upper`, `lowercasefirst→lcfirst`, `insertclipboard→clipboardhistory`, `formeditbox→formedit`, `formradiogroup→formradio`, `formcombobox→formcombo`, `formcalendar→formdate`, `msgbox→message`, `balloon→notify`, `httprequest→http`, `openai→ai`), parameter renames (`-f`→`-format` with Delphi format-token conversion: `nn`→minutes, `mmmm`→month name, `dddddd`→long date…), key blocks (`{#CTRL {#SHIFT a}}`), and `-count`. Untranslatable macros are kept verbatim in a `{#pe_unsupported …}` wrapper, which prints a visible marker when expanded. *Acceptance:* a corpus of ≥ 200 PE-syntax samples (written by hand from the observed macro and parameter vocabulary; no PE phrase content copied) translates with 0 parser errors; each translated sample expands to the expected golden output. *Test:* T-MAC-01.
- **FR-MAC-02 — Missing string/logic macros:** `autocase, decstr, lastchars, regexpos, regexcount, textempty, checktext, headfootfilled, prefix, postfix, parse, explode, numlist, settemp, gettemp, flushclipboardcache, dictionary, langdetect`. Each has a spec entry in `macros/README.md` with ≥ 3 golden tests. Semantics not determinable from static evidence are [U-04]; implement PF-defined semantics and mark them `compat: approximate`. *Test:* T-MAC-02.
- **FR-MAC-03 — Output/phrase macros:** `output, outputall, setlevel, qstext/setqstext, embed/embedfile, contents, getfocus, mousex, mousey, mouseposition, mousewheel, sound`. *Test:* T-MAC-03.
- **FR-MAC-04 — Form validation:** every input field supports `-required` and `-validate {anything|email|url|filepath|folder|letters|numbers|text|regex:<pattern>}`; OK stays disabled while any field is invalid; new field types `formgroup` (collapsible group with visibility bound to a checkbox) and `formcheckcombo`. *Acceptance:* a Qt offscreen test sets invalid values and asserts the OK button state and the error text. *Test:* T-MAC-04.
- **FR-MAC-05 — System extras:** `{#speak text -voice -rate}` (SAPI via COM), `{#convertlayout -from -to}` (re-maps text typed in the wrong keyboard layout using `VkKeyScanEx`/`ToUnicodeEx` tables). *Test:* T-MAC-05.
- **FR-MAC-06 — Editor syntax check:** the phrase editor marks unknown macros, unbalanced blocks and bad options inline, using the same parser as the engine. *Test:* T-MAC-06.

### 3.5 Plugins

- **FR-PLG-01 — Plugin package format.** A plugin is a directory or `.pfplugin` zip containing `plugin.toml` with: `id, name, version, api_version (semver), kinds = ["ai_engine"|"translator"|"macro"|"importer"|"exporter"|"trigger_source"], entry, runtime = "python-subprocess"|"exe-subprocess", permissions = {network = ["api.example.com"], filesystem = ["read:user-selected"], secrets = ["api_key"], clipboard = false, input = false}`, plus an optional detached signature. *Acceptance:* a malformed manifest is rejected with a specific error, and no code runs. *Test:* T-PLG-01.
- **FR-PLG-02 — Isolation:** every third-party plugin runs **out of process**. It is spawned with a restricted token (low integrity; job object with kill-on-close, memory cap of 512 MB by default, no child processes unless permitted) and talks JSON-RPC 2.0 over stdio. The host enforces a per-call timeout (default 60 s for AI, 5 s for macros) and cancellation (`$/cancel`, then kill after a 2-s grace period). *Acceptance:* a plugin that loops forever is killed and the expansion reports `[plugin: timeout]`; host memory is unaffected. *Test:* T-PLG-02.
- **FR-PLG-03 — Capability contract for `ai_engine` / `translator`**, modelled on PE's ABI (Section 1.4) but expressed as RPC methods: `describe() → {type, provider, urls, is_local, needs_api_key, configurable}`, `status() → {configured, error}`, `check_connection()`, `settings_schema() → JSON Schema` (replaces `GetOptsUI`), `list_models(kind)`, `list_languages()`, `capabilities() → {glossaries, ignored_words, custom_instructions, vision, image_gen, image_edit, usage_stats, model_management}`, `generate(messages, params, images?)` with streaming `$/progress`, `translate(text, from, to, glossary?, ignore_tags?)`, `generate_image`, `edit_image`, `usage()`, `models.pull/delete` (local engines). Abstract knobs `length, accuracy, variation, model` map to provider parameters inside the plugin. *Acceptance:* a conformance test suite (`tests/plugin_conformance/`) passes for every bundled engine. *Test:* T-PLG-03.
- **FR-PLG-04 — Secrets are injected per call** by the host from the FR-SEC-01 store, only for secrets the manifest declares. A plugin never reads the PF DB. *Test:* T-PLG-04.
- **FR-PLG-05 — Network permission enforcement (best effort):** the host passes `HTTPS_PROXY` pointing to a local filtering proxy that allows only the manifest's hosts. Plugins that bypass the proxy are a documented residual risk; first-party plugins are reviewed. *Test:* T-PLG-05.
- **FR-PLG-06 — Bundled first-party engines** are migrated from `ai.py` into plugins: openai, anthropic, openrouter, ollama (incl. pull/delete with progress), deepl. First-party plugins may run in-process (`runtime="builtin"`) only if they ship in the PF package and pass the same conformance suite. *Test:* T-PLG-03.
- **FR-PLG-07 — Macro plugins** register `{#ns.name}` commands (namespaced, so they cannot shadow built-ins); their arguments arrive already expanded; they return a text, actions or error result. Privileged-macro rules (FR-SEC-05) apply when the manifest requests `input`, `filesystem` or non-allowlisted `network`. *Test:* T-PLG-06.
- **FR-PLG-08 — Plugin manager UI:** install from file, enable/disable, show permissions and requests, show the last 100 RPC errors. Installing shows the permission diff and needs explicit consent; updates that widen permissions need consent again. *Test:* T-PLG-07.

### 3.6 AI and translation

- **FR-AI-01 — Preset model parity:** preset = {name, instruction, length, accuracy, variation, model, engine}; the PE preset serialisation (`|`-separated, `~pipe~` escape [C-DLL]) is importable through FR-IMP-01 when a user supplies PE's config. *Test:* T-AI-01.
- **FR-AI-02 — Vision:** `{#ai -image clipboard|file:<path>|region}` sends an image to engines whose `capabilities.vision` is true; otherwise `[ai: engine has no vision]`. *Test:* T-AI-02.
- **FR-AI-03 — Image generation** `{#aiimage -prompt -model -size}` → image action pasted as an image. *Test:* T-AI-03.
- **FR-AI-04 — DeepL engine** (free/pro endpoint chosen by key suffix `:fx`), glossary sync to DeepL glossaries, ignored words wrapped in XML tags that are preserved. *Test:* T-AI-04 (against a recorded mock).
- **FR-AI-05 — `{#langdetect text}`** returns an ISO-639-1 code, using an offline detector (pure-Python n-gram model) with optional engine fallback. *Test:* T-AI-05.

### 3.7 Data model v3

Schema v3 migration requirements (one migration, reversible through the pre-migration backup):

- **FR-DAT-00 — Stable GUIDs:** every folder, phrase and trigger gains `uid TEXT UNIQUE` (UUIDv7), plus `modified_hlc` (hybrid logical clock) and `deleted_at`. This is required by sync (FR-SYN) and import de-duplication. *Acceptance:* migration of a 10k-phrase v2 DB completes in < 5 s and preserves every row, verified by `export_dict` equality before and after, ignoring new columns. *Test:* T-DAT-00.
- **FR-DAT-01 — Levels:** table `levels(id, name, abbr, hotkey)`; `phrase_content(phrase_id, level_id, content, format)` UNIQUE(phrase_id, level_id); there is an active level per session, with fallback to the default level when a phrase has no content for the active level. `{#setlevel name}` switches. The editor has a level tab strip, and "Translate to level…" uses FR-AI translation. *Acceptance:* expansion picks the active level's content; a missing level falls back to the default; the popup shows level badges. *Test:* T-DAT-01.
- **FR-DAT-02 — Trash:** a delete sets `deleted_at` and records the original parent; the Trash node lists items; restore puts them back in the original folder or root; purge happens after N days (default 30). *Test:* T-DAT-02.
- **FR-DAT-03 — Comments** per phrase (author, time, text, resolved flag), separate from `notes`. *Test:* T-DAT-03.
- **FR-DAT-04 — Template folders:** folder flag `is_template`; "New phrase" inside a template folder's descendant pre-fills from the template; templates are hidden from triggers and the popup. **Phrase links:** a phrase whose content is `{#insert -uid X}` and that is flagged `is_link` is shown with a link icon and follows edits to X. *Test:* T-DAT-04.
- **FR-DAT-05 — Folder prefix/suffix text** (`text_before`, `text_after`, macro-enabled) is applied to every phrase in the folder subtree at expansion time; multi-key sorting (two fields + direction). *Test:* T-DAT-05.
- **FR-DAT-06 — Multiple mounted phrase libraries:** the personal DB plus 0..n additional libraries (local file, shared folder), each with read-only/read-write mode, its own password check mode and its own sync config; the tree shows them as roots. *Acceptance:* a read-only library rejects edits with a visible reason; triggers from all mounted libraries work, with conflict precedence "personal > first-mounted". *Test:* T-DAT-06.

### 3.8 Import / export

- **FR-IMP-01 — PhraseExpress import (export-based; D3 option B).** PF imports the files PE itself writes when the user exports from PE (CSV, XML, HTML [C-EXE: exporters exist]) and the user's `config.xml` (AI presets, glossaries, delimiter settings, excluded apps, hotkeys; secrets are **not** imported automatically, and the user is told to re-enter them). Folder tree, descriptions, plain/HTML content, autotext and hotkeys are mapped; macros go through FR-MAC-01. The import report lists every unsupported macro and option. *Acceptance:* blocked until the user supplies sample PE export files for each format ([U-02]); then a round-trip fixture made from those samples imports with 0 data loss for supported fields. *Test:* T-IMP-01.
- **FR-IMP-02 — Imported items get `origin="imported"`** (FR-SEC-04) and the tag `phraseexpress`, and are placed under a new root folder by default. *Test:* T-IMP-02.
- **FR-IMP-03 — Native `.pxp`/`.pexdb` import is out of scope** unless [U-01]/[U-02] are resolved by a lawful route (Section 8): e.g. PE offers a documented plaintext export of these files, or a user decrypts their own files using PE itself. If such a route exists, the import adapter reads a decrypted SQLite copy mapped through Appendix A. *Test:* —
- **FR-IMP-04 — Additional importers:** Word AutoCorrect (`.acl` via Word COM, or the Word export), AutoHotkey hotstrings (`::abbr::text` incl. options `*`, `?`, `C`, `O`, `R`), Texter (`.texter`), Breevy, ShortKeys (CSV/text exports). Each is a separate `importer` plugin with fixtures. *Test:* T-IMP-04.
- **FR-IMP-05 — Exporters:** HTML (printable, collapsible tree), XML (documented PF schema), DOCX, XLSX (one row per phrase), TextExpander CSV. *Test:* T-IMP-05.

### 3.9 Application shell

- **FR-APP-01 — Single instance:** named mutex `Local\PhraseForge-<user SID>`; a second launch forwards argv over a named pipe `\\.\pipe\PhraseForge-<SID>` (ACL: current user only) and exits with code 0. *Test:* T-APP-01.
- **FR-APP-02 — CLI** (subset of PE's switches [C-EXE], PF naming):
  - `--portable` / `--home <dir>` — all data and settings under the app folder or `<dir>`; no registry writes.
  - `--minimized`, `--hidden`, `--no-hook`, `--no-clipboard`, `--readonly`, `--shutdown` (ask the running instance to exit).
  - `--import <file>`, `--open <libfile>`, `--exec <uid|description>`, `--edit <uid>`.
  - `--debug`, `--log-file <path>`.
  - URL protocol `phraseforge://exec/<uid>` (opt-in registration).
  *Acceptance:* each switch has an integration test driving a real process. *Test:* T-APP-02.
- **FR-APP-03 — Portable mode** never writes to `%APPDATA%` or HKCU (verified with a ProcMon trace filter in CI-on-Windows, or a registry/file snapshot diff). *Test:* T-APP-03.
- **FR-APP-04 — Admin policy file** `%ProgramData%\PhraseForge\policy.toml` (read-only to users): `settings_locked`, `editing_disabled`, `stats_enabled`, `plugins_allowed = [...]`, `macros_disabled = [...]`. *Test:* T-APP-04.
- **FR-APP-05 — Update check** (opt-in): query GitHub Releases for the repo; download only Authenticode-signed (or minisign-signed) artifacts; verify before running; never auto-install without consent. No privileged service (an extension decision; Section 5). *Test:* T-APP-05.

### 3.10 Editor, dynamic folders, recorder, sync, Outlook, misc

- **FR-EDT-01 — Spell check** with Hunspell (via `spylls` pure-Python or `cyhunspell`/`hunspell` binding; D6 in Section 10), using dictionaries from LibreOffice dictionaries (licensed per dictionary; **not** copied from PE's `dict\`). Red underline, suggestions menu, per-phrase language from its level. *Acceptance:* a misspelt word is underlined within 300 ms of typing in a 5k-word phrase. *Test:* T-EDT-01.
- **FR-EDT-02 — Content formats:** add Markdown import/export and DOCX import (python-docx → HTML); keep HTML as the canonical rich format; RTF is pasted as CF_RTF generated from HTML when the target app prefers RTF (setting). *Test:* T-EDT-02.
- **FR-DYN-01 — Dynamic folder** = folder with `source ∈ {csv, xlsx, sqlite, odbc}`, `connection`, `query`, `field_map {description, content, autotext}`, `cache_ttl`. Children are virtual phrases (not stored), refreshed on open or TTL; they work in the popup and search, not as autotext unless `field_map.autotext` is set and the item count is ≤ 5000. *Acceptance:* 1000 CSV rows appear in the popup within 500 ms (cached); an ODBC source requires privileged approval (FR-SEC-05). *Test:* T-DYN-01.
- **FR-DYN-02 — Credentials for dynamic sources** live in the FR-SEC-01 store. *Test:* T-DYN-02.
- **FR-REC-01 — Macro recorder:** records keys (as text runs plus special keys), mouse clicks (screen and window-relative), wheel and delays into a PF macro block (`{#key}`, `{#mouse}`, `{#sleep}`); there is a stop hotkey and an option to strip idle time > N ms. *Acceptance:* recording "Win+R notepad Enter, type hello" and replaying it reproduces the result in a clean session. *Test:* T-REC-01 (interactive integration).
- **FR-SYN-01 — Change-set sync:** each mutation appends `{uid, entity, op, fields, hlc, device}` to a local `changes` log; sync exchanges change files through the remote (folder / Google Drive), applies remote changes in HLC order, field-level last-writer-wins, and tombstones deletions. *Acceptance:* two devices editing different fields of the same phrase offline converge to a merge with both edits; editing the same field converges to the higher HLC and keeps the loser in phrase history. *Test:* T-SYN-01.
- **FR-SYN-02 — Compaction:** a snapshot plus changes after it; changes older than the oldest device's acknowledged HLC are compacted. *Test:* T-SYN-02.
- **FR-SYN-03 — End-to-end encryption** of the sync payload (XChaCha20-Poly1305) with a sync passphrase shared by the user across devices. The cloud provider sees ciphertext only. *Test:* T-SYN-03.
- **FR-SYN-04 — Backward compatibility:** the existing snapshot sync remains readable for one release, with automatic upgrade to change-set mode once all known devices report v3. *Test:* T-SYN-04.
- **FR-SYN-05 — Shared team libraries (nice-to-have):** a shared folder library (FR-DAT-06) with change-set sync and per-library roles (reader/editor) enforced by encrypting the write key; no SQL Server back end. *Test:* T-SYN-05.
- **FR-OL-01 — Outlook context:** `{#olmail -field from|fromname|to|cc|subject|body|htmlbody|attachments}` reads the active Inspector/Explorer item through Outlook COM at expansion time (no add-in required; D7). *Acceptance:* with a mail open, `{#olmail -field subject}` returns its subject; with Outlook closed it returns an empty string and logs a warning, without starting Outlook. *Test:* T-OL-01 (COM fake + manual).
- **FR-UI-01 — Maintenance tools:** duplicate finder (same content hash or same autotext), DB vacuum/integrity check, backup diff (added/removed/changed phrases between two backups). *Test:* T-UI-01.
- **FR-UI-02 — Localisation:** every user-visible string goes through Qt `tr()`; Arabic and English `.ts` files cover ≥ 95 % of strings; a lint test fails on new untranslated literals in `ui/`. *Test:* T-UI-02.
- **FR-QA-01 — The full test suite runs in one process in < 3 min** with `QT_QPA_PLATFORM=offscreen`, using a session-scoped QApplication fixture and per-test widget teardown; a `pytest-timeout` of 60 s per test. *Test:* CI.

---

## 4. Extension opportunities (beyond parity; not in clone scope)

| ID | Extension | Rationale |
|---|---|---|
| X-01 | **Per-phrase usage analytics with privacy budget**: local-only, with an "expansions saved N keystrokes" dashboard | PE has stats; PF can do better without sending data anywhere |
| X-02 | **Semantic search** in the popup (local embedding model through an ai_engine plugin) | Large libraries; fuzzy recall |
| X-03 | **Context-aware suggestions**: rank phrases by foreground app + window title + time of day | Builds on `usage_log(app)` |
| X-04 | **Phrase-as-code**: libraries stored as a git-friendly folder of TOML/Markdown files with two-way sync | Team review, diffs, PRs |
| X-05 | **LLM-assisted macro authoring** ("describe the form you need" → macro text, validated by the parser) | Lowers the macro learning curve |
| X-06 | **OCR → phrase** and image-to-text through vision engines | Extends PF's OCR lead |
| X-07 | **Cross-platform core** (macOS via CGEventTap, Linux via libinput/uinput) behind the same `platform` interface | PE is Windows-only |
| X-08 | **Sandboxed WASM macro plugins** (wasmtime-py) as a lighter isolation tier than subprocesses | Fast, deterministic macro plugins |
| X-09 | **Accessibility**: screen-reader announcement of expansions; high-contrast popup | — |
| X-10 | **Secret-redacting clipboard history** (detect tokens/card numbers by pattern; don't store) | Privacy |
| X-11 | **TSF text service** for apps where synthetic input is unreliable (D1 option C) | Robust IME-grade insertion |
| X-12 | **MCP server** exposing phrase search/insert to AI agents (read-only by default) | Integrates with agent tooling |

---

## 5. Architecture

### 5.1 Component breakdown (target)

```
phraseforge/
  app/               process shell: single instance, CLI, policy, lifecycle, update check
  core/              models, store (SQLite/SQLCipher), migrations, HLC, change log, secrets (DPAPI)
  input/             native pfhook.dll (C/Rust) + Python ring-buffer reader, hotkey table compiler
  triggers/          matcher (autotext/regex/smartcomplete), timed/app/clipboard sources, dispatch
  macros/            parser, engine, built-in commands, pe_compat translator, trust gate
  output/            executor (type/paste/actions), clipboard, caret locator, UIPI check, targets
  plugins/           manifest loader, RPC host, sandbox (job object, restricted token, proxy), registry
  plugins_builtin/   ai_openai, ai_anthropic, ai_openrouter, ai_ollama, tr_deepl, imp_*, exp_*
  sync/              change-set engine, remotes (folder, gdrive), E2E crypto, legacy snapshot reader
  integrations/      ocr, onenote, stickynotes, outlook, spell
  ui/                Qt windows (unchanged layout; talks to core through services only)
```

Rules: `core`, `macros`, `triggers` (matcher), `sync` and `pe_compat` stay pure Python with no Qt and no Win32, so they can be unit-tested in isolation. Win32 stays in `input`, `output` and `integrations`. The UI never touches SQLite directly.

### 5.2 Data flow — expansion

```
pfhook.dll (hook thread)
  │  KBDLLHOOKSTRUCT → ring buffer   (suppression decided natively from compiled table)
  ▼
input.reader (Python thread)  → char via ToUnicodeEx(fg layout) → triggers.matcher
  ▼                                                    │ match(phrase uid, trigger, groups)
triggers.dispatch (worker thread) ── locks? ── trust gate (FR-SEC-04/05) ── password gate (FR-SEC-08)
  ▼
macros.engine.expand(content@active level, ctx) ──► host services (forms → Qt thread via queued call;
  │                                                 plugins → RPC host; clipboard; files)
  ▼ actions[]
output.executor: arm native "block keys" → erase abbreviation → type/paste → cursor → restore clipboard
                 → disarm → replay buffered user keys (FR-TRG-06) → usage_log + change log
```

### 5.3 Plugin loading and isolation

Startup scans `<data>/plugins/*` and `<app>/plugins_builtin/*`, validates the manifest (FR-PLG-01), checks policy (`plugins_allowed`), then registers capabilities **lazily**: a plugin process starts on first use and shuts down after 10 minutes idle. The RPC host owns a job object per plugin. Secrets are injected per call. Results are size-capped (default 1 MB text, 20 MB image).

**Decision D2 — plugin model**

| Option | Description | Pros | Cons |
|---|---|---|---|
| A. In-process Python entry points | `importlib.metadata` entry points loaded into the PF process | Simplest, fastest calls, easy debugging | No isolation: a plugin can read the DB and secrets, hook input, or crash or hang the UI. Unacceptable for a tool that sees every keystroke. |
| **B. Out-of-process JSON-RPC (recommended)** | Subprocess per plugin, stdio JSON-RPC, job object + low-integrity token + allowlist proxy | Crash/hang isolation, an enforceable permission model, language-agnostic (exe plugins possible), mirrors PE's capability-probing ABI as explicit methods | Process start latency (~150–400 ms cold; mitigated by lazy start and keep-alive), packaging Python for plugins (use PF's own interpreter with `-I -S` and a per-plugin `site-packages`) |
| C. Load PE's native plugin DLLs through a 32-bit bridge | x86 host process exposing PE's export ABI | Instant reuse of the four engines | Proprietary DLLs (EULA; cannot redistribute); x86-only Delphi ABI with unknown string conventions [U-03]; no benefit over B, since the providers' public HTTP APIs are simple. **Rejected.** |

Recommendation: **B**, with a `builtin` fast path for first-party engines that pass the same conformance tests.

### 5.4 Decision D1 — system-wide text expansion on Windows

| Option | Description | Pros | Cons |
|---|---|---|---|
| A. Status quo: ctypes `WH_KEYBOARD_LL` with a Python callback | Current PF | No native build | The callback needs the GIL. A GC pause, a long Qt slot or a blocking import > `LowLevelHooksTimeout` (default ~1000 ms on Win10/11 [I]; the value is configurable) causes system-wide key lag. Windows 7+ can silently remove the hook after repeated timeouts. Cannot guarantee FR-INP-01. |
| **B. Native hook DLL in process + ring buffer (recommended)** | `pfhook.dll` (≈500 LOC C/Rust) owns the hook thread; suppression table and key-block in native code; Python polls with a wait handle | Matches PE's architecture (`pexkey.dll` [C-DLL]); deterministic µs-level callback; keeps all logic in Python | Native build (x64 + arm64) in CI; signed binary recommended so AV heuristics don't flag a keyboard hook |
| C. TSF text input processor / UIA `ValuePattern` insertion | Register as a TSF TIP or insert text through UIA | Text insertion works with IME and is not keystroke-synthetic | TSF TIPs must be COM DLLs loaded into every app (complex, per-arch, AV-sensitive); UIA insertion is unsupported in many controls. Does not replace keystroke observation for autotext. Reserve as X-11. |

Recommendation: **B** for capture and suppression; keep SendInput/clipboard for output; add C later as an optional output path. Mitigation for elevated windows: FR-INP-04 (no uiAccess, because signing plus a secure install location adds a lot of complexity; revisit later).

### 5.5 Decision D4 — encryption at rest

| Option | Pros | Cons |
|---|---|---|
| **A. SQLCipher (`sqlcipher3` binding) with a DPAPI-wrapped random key (recommended if wheels exist)** | Whole-DB encryption, matching PE's approach [C-DLL]; transparent to queries | Python 3.14 Windows wheel availability is [U-08]; may need building from source in CI |
| B. Field-level AES-GCM (content, notes, macros) in normal SQLite | Pure Python (`cryptography`); no native dependency | Metadata (descriptions, triggers) still in plaintext unless also encrypted, which breaks SQL search (needs an in-memory index) |
| C. Rely on BitLocker/EFS | Zero work | Not under app control; backups and sync copies are exposed |

Recommendation: **A**, falling back to **B** for content and notes if [U-08] blocks. Secrets are always handled by FR-SEC-01, regardless of the option chosen.

### 5.6 Decision D5 — sync

| Option | Pros | Cons |
|---|---|---|
| A. Keep whole-snapshot sync (current) | Done; simple | Conflicts are all-or-nothing; data loss risk by user choice; the full DB is uploaded each time |
| **B. Change-set log + HLC + tombstones (recommended)** | Mirrors PE's hub/syncedchanges design [C-EXE]; field-level merge; small payloads; works over dumb storage (folder/Drive) | More code; compaction logic; clock-skew handling (HLC solves ordering, not intent) |
| C. Central server (SQL Server/Postgres) | Real-time multi-user, ACLs | Infrastructure for users; PE's server is a separate commercial product; out of scope for parity |

### 5.7 Decision D3 — PhraseExpress data compatibility

| Option | Pros | Cons |
|---|---|---|
| A. Decrypt `.pexdb` with the key material embedded in PE | Full fidelity | Uses vendor key material obtained by reverse engineering to defeat an access control; legal exposure (anti-circumvention law; EULA). The key was deliberately not extracted or recorded. **Rejected.** |
| **B. Import PE's own exports (CSV/XML/HTML) + `config.xml` (recommended)** | Lawful interoperability using user-initiated exports; plaintext | Fidelity depends on what PE exports (triggers/macros/levels may be lost) [U-02] |
| C. Automate PE's export UI (pywinauto) from PF's import wizard | One-click for users who still have PE installed | Brittle against PE UI changes; still bounded by B's fidelity |

### 5.8 Decision D6 — Outlook context

| Option | Pros | Cons |
|---|---|---|
| **A. Query Outlook COM at expansion time (recommended)** | No add-in install; PF already uses Outlook COM | Outlook security prompts in some configurations; requires classic Outlook (new Outlook has no COM) |
| B. Ship a COM add-in (like `pexmsol.dll`) | Push-based context; works when the mail window isn't active | x64 COM DLL, registration, Office trust centre; high maintenance |
| C. Microsoft Graph | Works with new Outlook / web | Needs Entra app registration and OAuth; only server-side mail, not the draft being edited |

---

## 6. Implementation plan

Each phase ends with an AMA-style acceptance gate: all FR tests green, performance budgets met, the unknowns touched by the phase updated in the registry (Section 10), and a short decision record committed under `docs/decisions/`.

| Phase | Scope | Depends on | Exit gate | Risks → mitigations |
|---|---|---|---|---|
| **P0 — Baseline & hardening** (1–2 wk) | Commit the current working tree in reviewable chunks; FR-QA-01 (test hang); FR-SEC-01..03, 06, 07; FR-APP-01; perf harness (Section 7.4) with baseline numbers | — | 434+ tests pass in one run; no plaintext secrets; baseline latency recorded | Large uncommitted diff → split commits by module before any refactor. DPAPI loss on profile reset → explain re-entry in the UI. |
| **P1 — Input core** (2–3 wk) | `pfhook.dll` + ring buffer (FR-INP-01..03), keyboard block + replay (FR-TRG-06), UIPI (FR-INP-04), caret chain (FR-INP-05), session events | P0 | P-01..P-03 budgets met; hook survives a 30-s GIL stall | Native build in CI (GitHub Actions windows-latest, MSVC) → prebuilt artifact checked by hash. AV false positives → sign the DLL, publish its hash, VirusTotal check in the release checklist. |
| **P2 — Data model v3** (2–3 wk) | FR-DAT-00..05, FR-SEC-04/05 trust model, FR-SEC-08 password modes, trash, comments, levels (storage + expansion; UI minimal) | P0 | Migration test on synthetic 10k/50k DBs; rollback from backup tested | Migration corrupts user data → mandatory pre-migration backup + dry-run mode + `export_dict` equality check. |
| **P3 — Macro parity** (3–4 wk) | FR-MAC-01..06, trigger options FR-TRG-01..05, 07 | P2 (levels, trust) | Compat corpus 100 % parsed; golden tests per macro | Unknown PE semantics [U-04] → mark `compat: approximate`, then confirm with a capture when available. |
| **P4 — Plugin platform & AI** (3–4 wk) | FR-PLG-01..08, migrate providers, FR-AI-01..05 | P0 (secrets), P2 (trust) | Conformance suite green for 5 engines; kill/timeout tests | Subprocess cold start → lazy start + keep-alive; measure P-05. Sandbox gaps (network bypass) → document; first-party review; future AppContainer. |
| **P5 — Import/export** (2 wk + waiting on samples) | FR-IMP-01 (after user samples), 02, 04, 05 | P3 (pe_compat), P4 (importer plugins) | Fixture round trips | [U-02] PE export fidelity → request samples early (in P0) so the work isn't blocked. |
| **P6 — Editor & content** (2–3 wk) | FR-EDT-01/02, FR-DYN-01/02, FR-OL-01, FR-UI-01, FR-UI-02 | P2, P4 | Spell latency budget; dynamic folder budget | Hunspell binding on Py3.14 [U-08] → `spylls` fallback (slower; budget allows it). |
| **P7 — Sync v2** (3–4 wk) | FR-SYN-01..04, FR-DAT-06 (multi-library) | P2 (uids, HLC) | Convergence property tests (Section 7.2) | Divergent replicas → property-based tests with random op interleavings; keep the legacy snapshot reader for one release. |
| **P8 — Shell & optional** (2 wk) | FR-APP-02..05, FR-REC-01, FR-MAC-05, FR-SYN-05 | P1, P7 | Portable no-write audit | Recorder replay flakiness → treat it as a best-effort feature; integration test only. |

Critical path: P0 → P1 → P2 → P3 → P5. P4 can start after P2 in parallel with P3; P6 and P7 can run in parallel after P2.

---

## 7. Testing and quality

### 7.1 Current baseline [REPO]

434 tests over core, IO, learning, cloud sync (two simulated PCs), macros, macro UI, triggers (incl. advanced), platform, output services, editor, popup, settings, UI, OneNote, Sticky Notes and the TextExpander import. A full single run hung at `tests/test_ui.py::test_theme_icons_tray` (stack in `app.setPalette`, `pe_style.py:142`) after 414 passes; split runs pass 434/434. FR-QA-01 fixes this first.

### 7.2 Unit and property tests (per feature)

| Area | Tests |
|---|---|
| Matcher | Table-driven: word position × delimiter class × case mode × prefix; Hypothesis: random keystroke streams never produce a match whose deleted span ≠ the abbreviation length |
| pe_compat | Golden corpus (FR-MAC-01); Hypothesis: `translate` is idempotent on PF-native text; never raises |
| Macros | ≥ 3 golden tests per command; fuzz the parser with random braces (no hang > 100 ms, no exceptions other than `MacroSyntaxError`) |
| Trust gate | Matrix origin × trigger kind × macro privilege → {run, prompt, skip} |
| Secrets | DPAPI round trip; cross-user failure (run under a second local account in an integration job) |
| Store/migration | v2 → v3 on synthetic DBs (1k/10k/50k); `export_dict` equality; idempotent re-run |
| Sync | Hypothesis state machine: 2–4 replicas, random ops/partitions/clock skew → all replicas converge to an identical `export_dict`; no resurrection of tombstoned items |
| Plugins | Manifest validation; RPC framing (partial reads, oversize messages); timeout/kill; permission diff on update |

### 7.3 Integration and behavioural tests

- **Windows integration job** (self-hosted or windows-latest runner with an interactive desktop session): launch PF with `--home <tmp>`, open Notepad and a WPF test app and a Chromium-based page (local HTML), type through `SendInput` from the harness (tagged with a different `dwExtraInfo`), and assert the final text through UIA `ValuePattern`. Covers autotext in each delimiter mode, hotkeys, paste vs type, cursor positioning, forms (driven through UIA), clipboard restore (verify that all original formats are restored).
- **Elevated window test** (manual checklist + scripted where the runner allows UAC-less elevation).
- **Differential tests against PE** (`needs-PE-capture`, optional, LeanREA method): the same keystroke script is replayed into a test app with PE active (on a machine where the user runs PE under its license) and with PF active; compare final text, deleted-char count and timing distributions. A behaviour diff becomes either a fix or a documented deviation.

### 7.4 Performance budgets (measured by the `bench/` harness, p50/p95/p99 over 1000 runs)

| ID | Metric | Budget |
|---|---|---|
| P-01 | Hook callback duration (native, QPC histogram) | p99 ≤ 50 µs; max ≤ 1 ms |
| P-02 | Keystroke → matcher decision (Python) | p95 ≤ 2 ms |
| P-03 | Trigger → first output char, 40-char plain phrase, typed | p95 ≤ 30 ms |
| P-04 | Trigger → paste complete, 2 KB HTML phrase | p95 ≤ 150 ms (excl. user-configured delays) |
| P-05 | Plugin RPC round trip (warm), cold start | warm p95 ≤ 5 ms; cold ≤ 500 ms |
| P-06 | Popup open with 10k phrases | ≤ 120 ms |
| P-07 | Idle CPU / RAM | < 0.5 % CPU; < 150 MB RSS with no plugin processes |
| P-08 | Added system-wide input latency (typing in Notepad with PF vs without) | Δ p95 ≤ 1 ms |

### 7.5 Security checks

- Input handling: no keystroke data is written to logs at any log level (test: grep logs after a typing session); learner skips password fields (`windows.py:149`), with a test using a UIA `IsPassword` control.
- Clipboard history excludes `ExcludeClipboardContentFromMonitorProcessing` and `CanIncludeInClipboardHistory=0` formats (password managers set these), and skips concealed-format clipboard items.
- Macro sandbox: `safe_calc` AST whitelist fuzzing; `{#run}` arguments are passed as an argv list, never through a shell; `{#sql}` is read-only unless privileged approval was given; `{#textfile}`/`{#outputfile}` resolve paths with symlinks resolved and are confined to user-approved roots for imported/synced phrases.
- Plugin loading: manifest-only parsing before execution; plugins run with `python -I -S` (no CWD imports, as in the scratchpad rule for untrusted code); restricted token; job object; signature check for third-party plugins when `policy.plugins_require_signature=true`.
- No data leakage: sync payload E2E-encrypted (FR-SYN-03); a network egress test asserts that PF makes no outbound connections with all integrations disabled (`net` monitor in the integration job); crash reports are local only.
- Dependency audit: `pip-audit` in CI; pinned hashes in `requirements.lock`.
- Static analysis: `bandit` (no `shell=True`, no `eval`, no `pickle`, which the current code already satisfies [REPO]) and `ruff`.
- Native DLL: built with `/guard:cf /Qspectre /DYNAMICBASE /HIGHENTROPYVA`; fuzz the ring-buffer reader.

### 7.6 PE behaviour capture plan (to resolve `needs-PE-capture` and the unknowns)

The user runs PE, under their own license, on a test machine:

1. **API Monitor / Frida** (REA's `instrument_with_frida`, Windows support experimental): trace `SendInput` (counts, flags, inter-event gaps), `SetClipboardData`/`GetClipboardData` order, `SetWindowsHookExW`, and `PostMessageW` from pexkey to `TpexMWnd4`. Record timing defaults (FocusDelay, SimKeyDelay, RestoreClbDelay) as evidence.
2. **ProcMon:** file and registry writes in portable vs normal mode; config write timing.
3. **UI capture:** pywinauto/UIA dumps of trigger and form dialogs (REA's native UI capture is macOS-only).
4. Import each capture as an REA evidence bundle (`import_evidence_bundle`) and resolve the matching unknown (`verify_unknown_resolution`).

Not to be traced: `sqlite3_key` and any licensing code path (Section 8).

---

## 8. Legal and licensing note

*Not legal advice; get counsel review before any public release that claims PE compatibility.*

1. **PhraseExpress is proprietary software** by Bartels Media GmbH (Authenticode signer [C-EXE]). Its EULA was not reviewed for this PRD [U-09]; it very likely restricts reverse engineering, decompilation and redistribution. Under the EU Software Directive (2009/24/EC, Art. 5(3) observation and Art. 6 interoperability decompilation) and US 17 U.S.C. §1201(f), limited analysis for interoperability is generally permitted. Those exceptions are narrow. This PRD keeps to observing interfaces, names, file structures and behaviour.
2. **Clean-room rule.** PF code must be written from this PRD and from public documentation, **not** from decompiled PE code. No PE code, decompiled pseudocode, DFM layouts, icon sprites, skins, sounds, UI strings (pexlang), help text, or the embedded SQL scripts may be copied into PF. Schema and macro *names* are facts used for interoperability. PF defines its own schema (Section 3.7). The macro-name alias table in `pe_compat` is an interoperability mapping. Keep analysis notes (this PRD's evidence) separate from implementation commits. Ideally, implementers of interoperability-sensitive parts (pe_compat, importers) work only from this PRD.
3. **Encryption and key material.** PE contains a hard-coded default database key and a license token [C-DLL]. They were **not** extracted, recorded or used, and must never be. Decrypting `.pexdb` with vendor key material risks violating anti-circumvention law. Interoperability is through user-initiated exports (D3 option B).
4. **Licensing/activation** code paths are out of scope and must not be analysed further.
5. **Bundled third-party components** in PE (DevExpress, TRichView, TMS, FireDAC, madExcept, Add-in Express) are commercial; nothing from them is reused. Open components PE ships (Hunspell, OpenSSL, SQLCipher community edition) must be obtained from upstream under their own licenses (Hunspell MPL/LGPL/GPL tri-license; OpenSSL Apache-2.0; SQLCipher BSD-style), not copied from PE's folder. **Dictionaries** must come from upstream (e.g. LibreOffice dictionaries), checking each dictionary's own license (some are GPL, which affects bundling with MIT PF: ship them as separate downloads).
6. **Plugins:** PE's plugin DLLs must not be loaded, bundled or redistributed (D2 option C rejected).
7. **Trademarks:** "PhraseExpress" and "TextExpander" are third-party marks. Use them only descriptively ("imports from PhraseExpress exports"); no logos or look-alike branding. The README already has a disclaimer [REPO]; keep it.
8. **Reference repos:** REA and LeanREA are MIT (attribution required if code or text is reused); AMA has no license and is owned by the user. This PRD reuses methods only.
9. **PF's own license:** MIT [REPO]. New dependencies must be MIT/BSD/Apache/LGPL-compatible. PySide6 (LGPL) is already used dynamically. Avoid GPL dependencies in the core; Capture2Text stays an external, optional executable [REPO].

---

## 9. Requirements traceability (summary)

| Gap | FRs | Tests | Phase |
|---|---|---|---|
| G-01, G-02, G-03 | FR-SEC-01..08 | T-SEC-01..08 | P0, P2 |
| G-04 | FR-SEC-09 | T-SEC-09, P-04 | P2 |
| G-05..G-07, G-33 | FR-INP-01..06 | T-INP-01..06, P-01..03, P-08 | P1 |
| G-08, G-09, G-28, G-29 | FR-APP-01..05 | T-APP-01..05 | P0, P8 |
| G-10 | FR-TRG-01..07 | T-TRG-01..07 | P1, P3 |
| G-11, G-12, G-30 | FR-MAC-01..06 | T-MAC-01..06 | P3, P8 |
| G-13, G-14 | FR-PLG-01..08, FR-AI-01..05 | T-PLG-01..07, T-AI-01..05, P-05 | P4 |
| G-15, G-16 | FR-IMP-01..05 | T-IMP-01..05 | P5 |
| G-17..G-19 | FR-DAT-00..06 | T-DAT-00..06 | P2, P7 |
| G-20, G-21 | FR-EDT-01..02 | T-EDT-01..02 | P6 |
| G-22 | FR-DYN-01..02 | T-DYN-01..02 | P6 |
| G-23 | FR-REC-01 | T-REC-01 | P8 |
| G-24, G-25 | FR-SYN-01..05 | T-SYN-01..05 | P7, P8 |
| G-26 | FR-OL-01 | T-OL-01 | P6 |
| G-27, G-31 | FR-UI-01..02 | T-UI-01..02 | P6 |
| G-32 | FR-QA-01 | CI | P0 |

---

## 10. Ambiguities and unknowns (load into the REA unknowns registry)

| ID | Unknown | Why it matters | Resolution route |
|---|---|---|---|
| U-01 | SQLCipher key derivation / cipher settings of `.pexdb` | Native file import | **Do not resolve by RE** (Section 8). Only via a vendor-documented export. |
| U-02 | What PE's CSV/XML/HTML exports contain (triggers? macros? levels? folders?) | FR-IMP-01 fidelity | The user exports a small synthetic library from PE in each format and adds it to `tests/fixtures/pe_exports/` |
| U-03 | Exact plugin ABI calling convention and string types | Only relevant if D2-C were chosen (it is not) | None needed |
| U-04 | Exact semantics of macros without visible parameter docs (`autocase, decstr, explode, parse, headfootfilled, qstext, check, numlist` styles…) | FR-MAC-02/03 compat fidelity | PE's public online macro documentation (allowed: public docs) + behaviour capture |
| U-05 | Whether `config.xml` secrets (`*APIKey`, AzureAD tokens) are obfuscated or plaintext | Importing settings, and a security note for users migrating | Inspect the user's own file manually; never import secrets automatically |
| U-06 | Default timing values (FocusDelay, SimKeyDelay, RestoreClbDelay, pause timing, fast-typing threshold) | Behavioural parity defaults | Capture plan 7.6 step 1, or read the user's `config.xml` values for their own machine |
| U-07 | Transport between `pexmsol.dll` and the main window (WM_COPYDATA?) | Only relevant for D6-B (not chosen) | None needed |
| U-08 | Availability of `sqlcipher3` and Hunspell bindings for Python 3.14 on Windows | D4, FR-EDT-01 | Spike in P0: `pip download` for cp314 win_amd64 |
| U-09 | PhraseExpress EULA terms on analysis/interoperability | Legal posture | The user reads the EULA shipped with the installer; counsel review before release |
| U-10 | Whether the PE "hub" sync uses field-level or row-level merge | D5 design reference only | Not required; PF defines its own semantics |
| U-11 | `words.pal` learning model semantics (connections/backconnections/ends) | Learner parity (E5) | Treat as inspiration only; PF keeps its own learner |
| U-12 | `LowLevelHooksTimeout` effective default on the target Windows builds | D1 risk sizing | Read `HKCU\Control Panel\Desktop\LowLevelHooksTimeout` on test machines; test with an induced stall |
| U-13 | Whether PE's "Window" trigger matches by title, class, exe, or a mix | FR parity of B11 | Capture 7.6 step 3 |
| U-14 | Whether the "SQL" macro dialog maps to a `{#sql}` macro (only the dialog form was observed) | Macro compat | Public docs |

Ambiguities in this PRD itself:
- PF currently uses integer IDs. Moving to UUIDv7 (FR-DAT-00) touches every module, but is required for sync and import; the alternative (keep ints, add a uid column only for sync) is accepted if P2 estimates overrun.
- The "fast typing only" threshold, the auto-skip threshold and the unlock duration defaults are PF choices until U-06 resolves.

---

## Appendix A — PE schema (structure reference only; PF does not copy it)

From the embedded SQLite DDL [C-EXE]: `data, folders, files, levels, datalevels, phrases (UNIQUE id,lid), vars(value,inc), embfiles, floats, users, workgroups, domains, datausers, dataworkgroups, datadomains, editusers, options(version,historynum,historydays,syncver), datahistory, phraseshistory, historyfiles, userstats (UNIQUE id,uid), tags, datatags, taglevels, comments, deleteditems, syncedchanges, synclog`. A separate stats DB holds `USERS, FILES, DESCRIPTIONS, ACTIONS`, and a users DB holds `serials, users`. The same DDL exists in Firebird, MSSQL and MySQL dialects. Column lists are in Section 1.2 A.

## Appendix B — PE `config.xml` key areas (names only)

`PhraseFile/*` (files, sync, backup) · `General/*` (shortcuts, sounds, updates, proxy, UDP) · `Popup/*` · `Search/*` · `Expert/*` (apps, delimiters, prefix, delays, paste method, clipboard backup, auto caps) · `Auto/*` · `AutoLearn/*` · `LastText/*` · `ClipCache/*` · `AI/*`, `AIPresets/*`, `AIBuiltInPresets/*` · `Translation/*` (engine, ignore words, glossaries) · `AzureAD/*` · `Edit/*` (spell dictionary, syntax check) · `MainWindow/*`, `UI/*` · dialog geometry flags · `Statistics/*` · `Tasks/Task0–9` · `Network/*` · `Hidden/*` · machine-wide `ProgramData` config for lockdown.

## Appendix C — PE command-line switches observed [C-EXE]

Portable/user: `-portable -portablemultiuser -PortableApps -user= -configfile=` · lifecycle: `-shutdown -programshutdown -noexit -hidden -nowizard -nosettings` · data: `-import= -open= -openmig= -varsfile= -addrun= -addfolder= -embfile= -exec= -execid= -editid= -exportfile= -textexpanderexport -print -resetstat -pwd=` · behaviour: `-noedit -readonly -nohook -noeventhook -noclb -template -varman -sqlhistory -filterpopup -cleanexp -root -dropbox -url -ftp -dictionary= -editdictionary -noshutdownblock` · debug: `-debug -filedebug -memdebug -logcount= -drawcaret -focusrect` · network: `-proxyname/pass/addr/port=` · URL protocol `pex://`. (Update and license switches are omitted on purpose.)
