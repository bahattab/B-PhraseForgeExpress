# PRD — PhraseExpress parity and extension for B-PhraseForgeExpress

| | |
|---|---|
| Target repo | `https://github.com/bahattab/B-PhraseForgeExpress`, inventory and gap analysis checked against release **0.6.5** (`aae8e89`; 0.6.4 is `c100c2e`) and 0.6.6 (#30, #32, #28, #33 and the R19 fix); 0.6.7 adds the R20–R42 fixes and #34 |
| Reference product | PhraseExpress 18.0.84.0, installed at `C:\Program Files (x86)\PhraseExpress` |
| Date | 2026-11-04 (v6, v5) · 2026-11-02 (v4) · 2026-10-30 (v3) · 2026-10-29 (v1, v2) |
| Status | Draft v6 — 0.6.4, 0.6.5, 0.6.6 (#30, #32, #28, #33, R19) 0.6.7 (review fixes R20–R42, #34) 0.6.8 (review fixes R43–R62) 0.6.9 (review fixes R63–R75, #38) and 0.6.11 (review fixes R76–R96) recorded: review fixes R12–R18 (Section 7.5.1), spell check and document import from a parallel session, spell latency budget P-09, U-08 Hunspell part resolved (the frozen EXE does not load a dictionary in its self-test yet). v5: security work of 0.6.1–0.6.3 recorded (G-34 closed, red-team review R1–R11, Section 7.5.1); trust-model storage recorded as decision D7; PE export routes from the vendor documentation (U-15) |
| Method | Static analysis only. No PhraseExpress binary was executed. No PhraseExpress code, assets, keys or text are reproduced here. |

---

## Status note (v6)

v6 records releases **0.6.4** and **0.6.5** (both 2026-11-04). 0.6.4 shipped the two feature PRs merged from a parallel session after 0.6.3, plus the fixes from reviewing #7. 0.6.5 carries the fixes from reviewing those two PRs and one more parallel-session PR (#27). Section 1.2 is unchanged.

| Release | PR | Change |
|---|---|---|
| 0.6.4 | #24, #26, #25 | #24 spell check (FR-EDT-01, G-20 partial). #26 import of Word, RTF, Excel and image files with PE's four file-import options: copy, link, open, line by line (`importers/files.py`; G-16 moves forward inside "partial"). The `{#document}` macro now uses #26's RTF reader. #25: review of #7, R12 (lost delimiter) and R13 (locked phrase names) |
| 0.6.5 | #29, #27 | #27 (parallel session, merged before #29): phrase export as RTF (G-16) and phrase suggestions from sentences repeated in sent e-mail, from Outlook Sent Items or `.eml`/`.mbox` files (`mail_analysis.py`, row E5). #27 has not had a security review yet. #29: review of #24 and #26, R14–R18. **R14** (High, older than both PRs): the file-reading macros reached network shares without approval, which on Windows sends the user's NTLM credentials to the host. A network path now needs an approved phrase. R15: spelling suggestions moved off the UI thread (a long Arabic word froze the editor for 9–30 s). R16: RTF with any code page. R17: DTD refusal in any encoding. R18: synced spell settings cannot name a file |
| 0.6.6 | #30, #32, #28, #33, #31 | #30 (parallel session): **G-28 closed**: `%ProgramData%\PhraseForge\policy.toml` (`policy.py`) locks Settings or editing, turns statistics off, disables named macros and forces settings; an unreadable file fails closed. Also an e-mail signature manager (`signatures.py`: a Signatures folder with footers shown between dates and random quotes, `{#signature}`, export to Outlook's signature folder); PE has one [EVIDENCE.md], no Section 1.2 row. #32 (parallel session): **G-25 open → partial**, stage 1 of a shared phrase database on SQL Server or PostgreSQL (`shared/`): revision counter, optimistic concurrency, conflict copies, soft deletes; per-folder permissions are stage 2. Neither PR has had a security review. One item from #32, R19 (Section 7.5.1), is fixed in 0.6.6 (#31). #28 (parallel session): PE macros explode, numlist, settemp/gettemp, autocase, regexpos/count, setlevel, langdetect and others (G-11 moves forward), and form checks `-required`/`-validate` on every field (**G-12 closed**). #33 (parallel session): shared database stage 2, folder permissions and change history (**G-25 closed** as "done" in its row). #28 and #33 have not had a security review |
| 0.6.7 | #34, this PR | #34 (parallel session): macro recorder (keys and mouse clicks recorded as a phrase); it has not had a security review. This PR: security review of #27, #28, #30, #32 and #33, findings **R20–R42** (Section 7.5.1), all fixed. Seven were High: a mailed `{#run}` became a trusted phrase (R20); the signature preview and Outlook export ran an unapproved signature's `{#outputfile}` (R21); "Not saved" copies of shared phrases lost their quarantine (R22); the setup docs let every database user make themselves administrator (R23, docs fixed; the permissions stay client-side, see R23); `{#sound}` and `-validate filepath/folder` opened network paths (R24, R25); `{#insert "N"}` checked a different phrase than it ran (R26, older than these PRs) |
| 0.6.8 | #35, #36, #38, this PR | #35 dynamic folders (phrases from files, folders, SQLite/ODBC queries) and #36 change-set sync (merge edits from two PCs) went out in 0.6.7 with #34; #38 (parallel session) encrypts the phrase file at rest (AES-256, DPAPI and/or passphrase) and has not had a full security review. This PR: security review of #34, #35 and #36, findings **R43–R62** (Section 7.5.1), all fixed. High: `{#mouse}` was not privileged, so an unapproved phrase could click Start or a dialog's Run button and type a command (R43, older than #34); SQL triggers in a pulled copy survived `restore_from` and could turn quarantine off for good (R44, older than #36) |
| 0.6.9 | #39, #41, this PR | #39 (trash, template folders, comments) and #41 (end-to-end encryption of what sync uploads, with a sync passphrase) came from a parallel session and have not had a security review. This PR: security review of #38 (phrase file encryption), findings **R63–R75** (Section 7.5.1), all fixed or, where noted, documented. High: changing the passphrase kept the data key, so an older copy (old passphrase or DPAPI entry) still opened the current file and "ask every start" could be bypassed (R63); backups made before encryption stayed plain although the dialog said they were encrypted (R64) |
| 0.6.10 | #44 | P1 started: native keyboard hook `pfhook.dll` (G-05 partial: keyboard part of FR-INP-01..03), windows that run as administrator (**G-06 done**, FR-INP-04), hook paused while the PC is locked or a Remote Desktop session is disconnected (**G-33 done**, FR-INP-06). Not yet security-reviewed |
| 0.6.11 | this PR | Security review of #39, #41, #42 and #44–#51 (five reviewers, every finding reproduced again before it was fixed), findings **R76–R96** (Section 7.5.1). High: a pulled folder that reused the library root's row id was taken for the library and deleted on unmount (R76); the trash gave back an old approval although a sync had changed the folder (R78); folder text or an output target from a sync or import ran unapproved in phrases created in or moved into that folder later (R79). Folders now have their own trust state (`folder_quarantine`) |
| 0.6.12 | this PR | FR-TRG-06: keys typed while PhraseForge types a phrase are held back by `pfhook.dll` and replayed after it (or dropped), which closes the last open item of G-10. Not yet security-reviewed |
| 0.6.13 | #58 | Security review of #52 and #53 (plugins), three reviewers, every finding reproduced again before it was fixed: findings **R97–R113** (Section 7.5.1). Medium: a plugin's declared permissions are not enforced, yet a plugin declaring none ran from unapproved phrases and was described as able to do "nothing" (R97); `{#ai}` / `{#translate}` with a plugin engine sent the clipboard, images and files to plugin code from unapproved phrases, also with the plugin's macros disabled by the administrator (R98). Now every plugin macro, and AI/translation through a plugin engine, needs an approved phrase |
| 0.6.14 | this PR | Security review of #55 (AI vision, `{#aiimage}`, Ollama downloads, usage) and of #59 (DeepL glossaries), #61 (plugin network filter and signatures) and #62 (streamed plugin replies): findings **R114–R129** (Section 7.5.1). Medium: an unapproved phrase made paid images with no prompt, 1000 in one `{#loop}` (R114). Now `{#aiimage}` needs an approved phrase and makes at most 4 images per phrase; at most 8 images and 20 MB go with one `{#ai}`; the Ollama download survives a bad server; `plugins_require_signature` also stops installed plugins that are unsigned or changed, and a planted `.pyc` is never run (R118); the plugin proxy needs a per-plugin password and refuses local addresses (R120, R121); `$/progress` no longer extends calls that did not stream (R123); DeepL glossaries are cached per session and never delete one another (R126) |

Gap count at 0.6.7: as at 0.6.6 (the fixes close no gap and reopen none). Gap count at 0.6.5: unchanged since v5, **6 of 34 closed**, 15 partial, 13 open. At 0.6.6: **9 closed** (G-28, G-12, G-25), **14 partial**, **11 open**. R14 extends the closed gap G-02 (FR-SEC-05) and does not reopen it: the gap was "privileged macros run from untrusted phrases", and reading a network share was a privileged action the list did not name.

Evidence for v6 [REPO]: 0.6.4 published with all three assets (Setup, portable, win64 zip; CI green on `c0208d4`, including the frozen-EXE self-test and silent install/uninstall); 0.6.5 on `4c477a8` (PR #29); `pytest --collect-only` 860 tests in 58 files; red-team suite 78 cases. Each R14–R18 case fails on 0.6.4 (17 of 18; the 18th is a control: local files need no approval). Timing for R15 measured with the LibreOffice `ar` dictionary on Linux: menu open ≤ 0.42 s for the worst word, against 30.4 s before.

---

## Status note (v5)

v5 records releases **0.6.1–0.6.3** (2026-11-02 to 2026-11-04) and `main` after 0.6.3. Most of it is security work. Two feature PRs came from a parallel session and were merged into `main` on 2026-11-04: #7 (multiple-choice autotext, inside the 0.6.3 release) and #24 (spell check, after 0.6.3; it updated rows E2 and G-20 itself). Section 1.2 is otherwise as in v4.

| Release | PR | Change |
|---|---|---|
| 0.6.1 | #21 | **G-34 closed**: `{#http}` connects only to an address it resolved and checked (pinned httpcore backend), so DNS rebinding no longer works without a proxy |
| 0.6.2 | #22 | Red-team review of 0.6.1, findings R1–R9 fixed (Section 7.5.1): output target "Specific program" on imported/synced phrases, `{#key}` Win-key aliases and Ctrl+Esc, synced/opened device settings (AI base URLs, proxy, paths, file-search commands), secrets in settings exports, URLs in the log, password-manager clipboard content, cross-host redirect headers, CGNAT range, XML depth |
| 0.6.3 | #23, #7 | R10: synced/imported `{#var}` values send the phrases that read them back for approval; R11: the update notice opens only this project's GitHub release links. #7: when several phrases share one autotext, a "Select phrase" menu opens at the cursor; if only one of them is allowed in the current program it expands directly (`popup.py`, trigger manager). Not mapped to a Section 1.2 row: whether PE behaves the same way is not in the static evidence [U] |
| `main` after 0.6.3 | #24 | Spell check in the phrase editor (FR-EDT-01): underline, suggestions, add/ignore, Hunspell dictionaries through `spylls`, downloaded from LibreOffice (`spell.py`, `ui/spell_ui.py`). G-20 open → partial |

Gap count on `main`: **6 of 34 closed** (G-34 added), 15 partial (G-20 added by #24), 13 open. The trust gate grew beyond FR-SEC-04's wording (fingerprints instead of `trusted_hash`, device-only settings); decision D7 (Section 5.9) records the design as built.

Evidence for v5 [REPO]: `main` at `af02529` (0.6.3 plus #24); `registry.catalog()` 153 commands; `db.py` 16 tables; Arabic table 1,298 entries; `pytest --collect-only` 829 tests in 57 files (816 in 56 at the 0.6.3 tag); Windows CI green on every merged head (#21, #22, #23) including the frozen-EXE self-test and silent install/uninstall.

---

## Status note (v4)

v4 brings the **PhraseForge (PF)** columns up to release **0.6.0** (`6c4904f`). Only the rows that releases 0.5.7–0.6.0 changed were re-checked against the code; every other PF row is carried over from v3 (0.5.6) unchanged. PhraseExpress (PE) binary claims are still those of v2.

What changed in PF since v3:

| Release | PR | Changes relevant to this PRD |
|---|---|---|
| 0.5.7 | #17 | Sync through the Google Drive for desktop folder without sign-in: `cloud/drive_folder.py` finds "My Drive" on the streaming drive, a translated name or a mirrored profile folder (F1) |
| 0.5.8–0.5.9 | #18 | Automatic sync every N minutes (default 7, user-selectable), at start, on exit and 60 s after an edit (F1) · Settings no longer refreshes the Google token on the UI thread · customizable quick toolbar: show, hide, move, add any Tools command (E1) · drag and drop between the phrase list and the folder tree (E1) · OCR to clipboard copies on the UI thread and verifies the copy · OCR of PDF/images without a cloud key (Qt PDF text layer, Windows OCR for scanned pages) · Prompt Optimizer answers only in English or Arabic · OneNote: import a `.one` file, export a folder to a new OneNote section, publish a page/section/notebook to PDF/DOCX/XPS/MHT/ONE/ONEPKG · phrase export to HTML and MHT (E2, H) · PhraseExpress import of `.txt` files (one phrase per file, several at once, or a folder tree) and of XML; text files read as UTF-8, UTF-16 or the ANSI code page (G-15) · fix: File import of one `.txt` imported every `.txt` in its folder tree |
| 0.6.0 | #19 | Visual audit: input borders 3.45:1 and placeholder text 5.1:1 (WCAG 1.4.11 / 1.4.3), filled primary buttons, menu buttons styled like push buttons, one icon palette, translated list headers and breadcrumb in Arabic (E11, G-31) |

**New PE evidence (v4).** PhraseExpress's own online manual (`phraseexpress.com/doc/managing-phrases/export/` and `/doc/phrase-files/export/`, read through web search on 2026-11-01; the site itself was not reachable from the session) says PE exports **text one phrase at a time** ("no file format could save all meta data"), and exports a whole folder only as a **phrase file** (`.pexdb`, encrypted). It documents no CSV or XML export. The user confirmed this on their install: the export choices are text or `.pexdb`. This conflicts with the exporter names found in the binary ([C-EXE], Section 1.2 H); the conflict is logged as U-15. FR-IMP-01 is rewritten around the per-phrase text export.

Evidence for v4 [REPO]: release 0.6.0 (`6c4904f`); `registry.catalog()` still 153 commands; `db.py` still 16 tables; Arabic table 1,277 entries; `pytest --collect-only`: 750 tests; Windows CI (`windows-build.yml`, run 90) passed the full suite, the frozen-EXE self-test and the silent install/uninstall test on `6c4904f`.

---

## Status note (v3)

v3 re-checks every **PhraseForge (PF)** claim against release **0.5.6** (`d03986c`). PhraseExpress (PE) claims are carried over from v2 unchanged: they come from the static analysis done on the user's Windows machine, and the v3 session had no access to `C:\Program Files (x86)\PhraseExpress`, so it did not re-verify them.

Changes from v2:

- **Section 1.2:** the "PF status" column now reflects 0.5.6. File names are authoritative. Line numbers carried over from v1 point to an older checkout and may have moved.
- **Section 2:** the two columns "0.5.4" and "After PR" are merged into one column, "0.5.6". The PR that v2 called "After PR" was merged as #15 and released as 0.5.5.
- **New finding, G-34 reopened as partial:** `net.is_private_host` resolves the host name, and httpx then resolves it again when it connects. A DNS-rebinding server can answer the second lookup with a private address. FR-SEC-06 ("connect to the resolved IP") is therefore not met yet.
- **Section 6:** phase status column added. **Section 7.1:** baseline updated to 663 passed, 18 skipped, in one process.

Evidence for v3 [REPO]: `grep` over `phraseforge/`, `macros.registry.catalog()` (153 commands, 169 names with aliases), `db.py` DDL (16 tables), and a full `pytest` run on Linux with `QT_QPA_PLATFORM=offscreen` on 2026-10-30: 663 passed, 18 skipped, 4 min 18 s.

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

*PF status below reflects release 0.6.0 for the rows changed since v3 (marked "0.5.7+"/"0.5.8+"/"0.5.9+"/"0.6.0"), and 0.5.6 for the rest.* Legend for **PF status**: ✅ reproduced · 🟡 partial · ❌ missing · ➕ PF-only. "Partial" means PF has the feature but lacks options PE shows.

#### A. Phrase store and organisation

| # | PE feature | How PE does it (evidence) | PF status |
|---|---|---|---|
| A1 | Tree of phrase files → folders → phrases, all held in one `data` table (GUID id, pid, datatype, pos, color, icon, desc, allowed/declined apps, timing, paste target, hint, tag, comment, trigger BLOB) | [C-EXE] SQLite DDL `CREATE TABLE data(...)` | ✅ `db.py` (integer IDs, separate folders/phrases tables; 16 tables in all) |
| A2 | Multiple phrase files at once (local, network, URL, FTP, SQL server, cloud folder), each with its own password and sync settings | [C-EXE] `files` table: `localpath, networkpath, urlpath, ftppath, sqlpath, filetype, doudp, syncdate`; [C-DATA] `PhraseFile/Data/phrases/file*` | ❌ one DB per profile |
| A3 | **Levels**: per-language/variant content for each phrase (`phrases` is UNIQUE(id, lid)), with level hotkeys; `{#setlevel}` | [C-EXE] tables `levels(lid,hk,desc,abbr)`, `datalevels`, `taglevels` | 🟡 `phrase_versions(phrase_id, lang)` + `phrase.active_language` setting; no level hotkeys, no `{#setlevel}` |
| A4 | Content formats per phrase: plain, RTF, HTML, RTF-diff, view mode; embedded files and images (`embfiles`); OLE/Word objects | [C-EXE] `phrases(plain, rtf, html, rtf1, rtfd, lang, viewmode)`, `embfiles(fid,id,lid,type,data,filename)` | 🟡 text and HTML only, images via HTML; no RTF, no embedded files table |
| A5 | Tags (tags, datatags, taglevels) | [C-EXE] | ✅ `phrase_tags` |
| A6 | Comments on phrases (per user) | [C-EXE] `comments(cid,id,uid,lid,flag,…,text)` | ❌ (PF has a single `notes` field) |
| A7 | Version history for items, phrases and files, written by DB triggers; retention by count and by days | [C-EXE] `datahistory, phraseshistory, historyfiles`; `options(historynum, historydays)` | 🟡 `phrase_history` snapshots, no retention policy |
| A8 | Trash / deleted items with restore path | [C-EXE] `deleteditems`, `data.restorepath` | ❌ deletes are hard (no `deleted_at`, no Trash node in 0.5.6) |
| A9 | Template folders, phrase links | [C-EXE] `folders.istemplate`; TExtendedFrame [I] | ❌ |
| A10 | Folder text prefix/suffix added to every phrase (`ltextadd`, `rtextadd`) | [C-EXE] | 🟡 per-folder **abbreviation** prefix only; no content prefix/suffix |
| A11 | Folder sort options (two keys, direction, mode) | [C-EXE] `sortfield/dir/mode, sortfield2/dir2` | 🟡 manual `sort` only |
| A12 | **Dynamic folders**: phrase lists filled live from Excel, CSV, SQL (Firebird/MSSQL/MySQL/Access/SQLite) with field mapping and a cache | [C-EXE] `folders(constr, querystr, fieldmap, cachedyndata, cachedate)`; TDyn*SettingsFrame | ❌ (PF has only `{#xls*}`/`{#sql}` macros) |
| A13 | "Floats": phrases placed on the desktop as windows | [C-EXE] `floats(id,uid,x,y,width,height)` | ➕ sticky-notes integration is the nearest equivalent; ❌ parity |
| A14 | Per-item ACLs: users, workgroups, domains, with rights | [C-EXE] `datausers, dataworkgroups, datadomains, editusers` | ❌ |
| A15 | Usage statistics per user; typing speed and hourly-rate savings | [C-EXE] `userstats`; separate stats DB; TStatsForm | ✅ `usage_log`, `stats_window.py` |
| A16 | Phrase-file encryption at rest (SQLCipher) | [C-DLL] [C-DATA] every `.pexdb` has 8.00 bits/byte entropy and no SQLite header | ❌ plaintext SQLite |
| A17 | Password protection for phrase files, checked on start, open, expand or view (`passcheck` modes) | [C-EXE] `files.password, passcheck`; TPassDlg, TPassEditDlg | 🟡 salted scrypt (`db.py` `hash_password`); a locked folder asks for the password before any expansion and is hidden from the popup, SmartComplete and `{#insert}` (`security.LOCKS`); no per-file `passcheck` modes |
| A18 | Macro text in phrases stored encrypted in the DB | [C-EXE] `UPDENCRYPTPLAINMACROS … WHERE plain LIKE '%{#%'` | ❌ |
| A19 | Clipboard cache and "last used" stored as their own phrase files | [C-DATA] `clipboard.pexdb`, `lastused.pexdb` | ✅ functionally (`clipboard` table, Last Used node) |

#### B. Triggers

| # | PE feature | Evidence | PF status |
|---|---|---|---|
| B1 | Autotext with word position end / middle / entire / beginning | [C-EXE] TTriggerAtextSectionFrame | ✅ `autotext.py` |
| B2 | Execution timing: as detected, manual confirmation, on typing pause, **on fast typing only** | [C-EXE] trigger timing strings; `data.timingtype, timinginterval` | 🟡 `models.EXEC_MODES` = immediate/confirm/pause/continue; no "fast typing only" |
| B3 | Delimiter classes for prefix and postfix: All, Standard, Letters, Numbers, Enter, Tab, Space, Point, Comma, Custom, Refine; "remove trailing char"; global `CharsBefore/CharsAfter/SentenceDelimiters` | [C-EXE] TExpertDlg; [C-DATA] `Expert/*` | 🟡 `models.DELIMITER_CHOICES` = Default/None/Space/Enter/Tab/Punctuation/Any non-letter; no Letters/Numbers/Point/Comma/Custom |
| B4 | Global autotext prefix | [C-DATA] `Expert/GlobalPrefix` | ❌ |
| B5 | Block and resend Enter/Tab (route Enter) | [C-DATA] `DoRouteEnter` | ✅ "route Enter/Tab" |
| B6 | Unwanted-autotext detection and threshold (auto-skip after repeated undo) | [C-DATA] `AutoSkip, SkipAtextThreshold` | 🟡 undo within 10 s (`manager.py:410`), no learned auto-skip |
| B7 | Skip-next-autotext hotkey | [C-EXE] `SkipHotkey` | 🟡 a pause command exists; no one-shot skip |
| B8 | SmartComplete (suffix tree, refine from N chars) | [C-EXE] `SuffixTreeU` | ✅ `manager.py:395,587`, `smartcomplete_tip.py` |
| B9 | RegEx autotext, with presets: email, URL, ISBN, IPv4, IPv6, MAC, time | [C-EXE] | 🟡 regex yes; presets only in the macro dialog, not in the trigger editor |
| B10 | Hotkey triggers through `RegisterHotKey` plus a hook-based path | [C-EXE] imports RegisterHotKey; [C-DLL] LL hook | ✅ hook-matched only (`hotkeys.py:56`) |
| B11 | Window trigger (application focus) | [C-EXE] TTriggerAppSectionFrame | ✅ |
| B12 | Time trigger plus scheduled tasks `Tasks/Task0–9` | [C-EXE], [C-DATA] | 🟡 daily/every-N only; no task list UI |
| B13 | Clipboard trigger and RegEx clipboard trigger | [C-EXE] | ✅ |
| B14 | Allowed/declined apps per item and globally; per-app output method (`AppMethods`) | [C-DATA] | ✅ |
| B15 | Auto-caps fixes (first caps, double caps, all caps), done inside the hook DLL | [C-DLL] `SetAutoFirstCaps/FixDoubleCaps/FixAllCaps` | ✅ `manager.py:567` |
| B16 | Keyboard blocking during output | [C-DLL] `BlockKeyboard`; [C-EXE] `BlockInput` | ✅ 0.6.12: `pfhook.dll` holds the user's keys back during output and replays them after (or drops them), Settings > Text Insertion |
| B17 | Mouse LL hook to reset the key buffer on click | [C-DLL] WH_MOUSE_LL | ✅ buffer resets on clicks (`autotext.py:36`); verify the mechanism |

#### C. Input capture, caret and output

| # | PE feature | Evidence | PF status |
|---|---|---|---|
| C1 | LL keyboard hook in a dedicated DLL thread, posting to the UI | [C-DLL] | ✅ ctypes `WH_KEYBOARD_LL` on its own thread (`keyboard_hook.py`), but the callback runs Python under the GIL (risk R1) |
| C2 | Key-by-key output with selectable method (VK_PACKET vs SendKey) | [C-DATA] `KeyByKeyPasteMethod` | ✅ vk_packet / unicode / scancode (`sendinput.py:77`) |
| C3 | Clipboard paste with formats, clipboard backup and restore, and delays `FocusDelay, SimKeyDelay, RestoreClbDelay, PlainClbDelay2, RndDelay` | [C-DATA] | ✅ except `RndDelay` (randomised typing delay) ❌ |
| C4 | Force focus before output | [C-DATA] `ForceFocus` | 🟡 |
| C5 | Caret position for the popup via MSAA (`AccessibleObjectFromWindow`, `DoACC`), `GetCaretPos` and `GetGUIThreadInfo`; `CaretPositionMode` | [C-EXE] imports oleacc | 🟡 GetGUIThreadInfo only (`platform/windows.py`), no MSAA/UIA fallback; fails in Chromium/Electron and WPF [I] |
| C6 | Paste targets: current app, a specific window, clipboard, file, email | [C-EXE] TPasteTargetFrame, `data.pastetarget, pasteparams` | ✅ `output_target.py:41` |
| C7 | Elevation handling: `pexinst -restartadmin` | [C-DLL] | ❌ silently fails in elevated windows (UIPI) |
| C8 | Session awareness (`WTSRegisterSessionNotification`), RDP guest install | [C-EXE] | ❌ |
| C9 | Text-to-speech (SAPI) | [C-EXE] `SAPI.SpVoice` | ❌ |
| C10 | Keyboard layout switch/convert (`{#setlayout}`, `{#convertlayout}`) | [C-EXE] | 🟡 `{#setlanguage}`; no convert-layout |

#### D. Macros

PE macro names [C-EXE, from the macro name table], compared with PF's 153 commands (169 names with aliases, `registry.catalog()` in 0.5.6) [REPO `macros/README.md`]. PF has the same overall syntax (`{#name … -opt value}`), but parameter names and some semantics differ. Rows marked **compat** need an alias or translator so that phrases imported from PE run unchanged (FR-MAC-01).

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
| E1 | Ribbon main window (192 actions), tree, multi-column phrase list (`UI/PhraseCol*0–15`) | [C-EXE] TpexMWnd4 DFM | ✅ `ribbon.py`, `tree_panel.py`; 0.5.8+: customizable quick toolbar (`ui/quick_toolbar.py`), drag and drop of phrases and folders between list and tree |
| E2 | Rich editor with spell check, tables, images, find/replace, character map, font dialog, DOCX/Markdown/HTML import/export | [C-EXE] TFrmRV*, TRichForm | 🟡 HTML QTextEdit, spell check (G-20, partial); DOCX/PDF/HTML/MHT **export** (`documents.py`, HTML/MHT 0.5.9+); no DOCX/Markdown import into the editor |
| E3 | Popup menu, QuickKeys, QuickSearch (inline, case, subfolders, Quick Jump), repeat last output, dark mode, ~20 colours | [C-DATA] `Popup/*`, `Search/*` | ✅ `popup.py` (verify Quick Jump and repeat-last) |
| E4 | Clipboard cache window with auto-collect, dedupe, plain-only, trim | [C-DATA] `ClipCache/*` | ✅ |
| E5 | Autotext learning (word graph + corrections, `words.pal`), learns from Outlook, AutoCorrect | [C-DATA] words.pal is an encrypted ZIP; [C-EXE] `<connections><corrections>` | 🟡 sentence-repeat learner, AutoComplete word learner, learning from sent mail (Outlook Sent Items or .eml/.mbox, `mail_analysis.py`) |
| E6 | First-start wizard, bubble help, tray hints | [C-EXE] | ✅ wizard, tray |
| E7 | Settings dialog | [C-EXE] TSettingsForm | ✅ 26 pages |
| E8 | Print / print preview | [C-EXE] | ✅ `main_dialogs.py` |
| E9 | Duplicate finder / removal | [C-EXE] TDelDupConfDlg | 🟡 Bulk edit > Remove duplicates per folder (`bulk_edit.remove_duplicates`); no library-wide finder |
| E10 | Backup: count retention, compare file versions, restore, optimise/vacuum | [C-EXE] TFileBackupDlg, TFileCompareDlg, TOptimizeDlg | 🟡 backup and restore; `VACUUM` runs only after sealing secrets and on sync snapshots; no compare, no vacuum UI |
| E11 | UI languages EN/DE | [C-DLL] pexlang | ➕ EN/AR with right-to-left layout; 1,277-entry Arabic table (`ui/i18n.py` + `ui/i18n_ar.py`); 0.6.0 translated the remaining list headers and breadcrumb; no `.ts` pipeline |
| E12 | Event sounds (6) | [C-DATA] `DoSound0–5` | ✅ `sounds.py` |
| E13 | Toast notifications (WinRT) | [C-EXE] `RoActivateInstance` [I] | 🟡 tray balloon |
| E14 | Admin lockdown via machine-wide `C:\ProgramData\PhraseExpress\config.xml` (`ConfigDisabled, EditDisabled, DoStats`) | [C-DATA] | ✅ `%ProgramData%\PhraseForge\policy.toml` (G-28) |
| E15 | CLI switches (Section 3.9) and portable mode | [C-EXE] | 🟡 `--self-test`, `--minimized`, argv handed to the running instance (`single_instance.py`), portable EXE, `PHRASEFORGE_HOME`; no other switches |

#### F. Integration, sync, network

| # | PE feature | Evidence | PF status |
|---|---|---|---|
| F1 | Cloud-folder sync: Dropbox, OneDrive, Google Drive, iCloud | [C-EXE] | ✅ folder remote + Google Drive OAuth (`cloud/sync.py`); 0.5.7+: finds the Google Drive for desktop folder (`cloud/drive_folder.py`); 0.5.8+: automatic sync on an interval (default 7 min), at start, on exit and after edits |
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
| G1 | Built-in OpenAI engine: chat, images, image edits; presets (Instruction, Length, Accuracy, Variation, Model); text-info and answer instructions | [C-EXE] api.openai.com/v1; [C-DATA] `AIPresets/*` | 🟡 text chat only (no vision or image calls in `ai.py`) |
| G2 | **Plugin engines** (Anthropic, OpenRouter, Ollama, GPT4All) behind a common ABI with capability discovery | [C-DLL] Section 1.4 | 🟡 nine providers hard-coded in `ai.py` (OpenAI, Anthropic, OpenRouter, Gemini, OpenCode Zen, Kilo Code, DeepL, Ollama, GPT4All); no plugin interface |
| G3 | Translation: DeepL (free/pro), AI engines; glossaries (name, fromlang, tolang, dict), ignored words; language detection | [C-EXE]; [C-DATA] `Translation/*` | 🟡 AI and DeepL translation + glossary; heuristic `ai.guess_language` for the source language; no `{#langdetect}` macro |
| G4 | Vision (GenerateTextFromImage), image generation/edit (OpenRouter) | [C-DLL] | ❌ |
| G5 | Local models: Ollama model pull/delete with progress; GPT4All through a Python bridge | [C-DLL] | 🟡 Ollama and GPT4All chat through their local APIs; no model pull/delete |
| G6 | Usage/balance stats per engine | [C-DLL] `GetEngineUsageStats` | ❌ |

#### H. Import / export

| PE importers [C-EXE] | PF |
|---|---|
| TextExpander (incl. 5+), Texter, AutoHotkey (`.ahk`), Breevy, ShortHand, ShortKeys, GhostTyper, Direct Access, InstantText, Word AutoCorrect/AutoText, Outlook, Excel, CSV, SQL, folder structure; extensions `.textexpander .texter .ahk .glo .spf .gtx .dta` | ✅ TextExpander (CSV, `.textexpander`, macOS plist), CSV, JSON, txt folder · PhraseExpress: per-phrase `.txt` (one or many files, or a folder tree; 0.5.9+), CSV/TSV, XML (0.5.9+, schema not yet checked against a real file) · ➕ OneNote (running notebooks and `.one` files, 0.5.9+), Sticky Notes · ❌ everything else |
| PE exporters: HTML, CSV, XML, Word, Excel, Android, TextExpander [C-EXE names]. **The vendor manual documents only per-phrase text export and phrase-file (`.pexdb`) export (U-15).** | ✅ JSON, CSV, txt, PhraseExpress CSV, TextExpander CSV, macOS plist, DOCX, PDF, HTML, MHT (0.5.9+) · ➕ OneNote section and OneNote Publish (0.5.9+) · ❌ XML/Excel |
| Native PE formats `.pxp .px3 .pxa .pexdb .pexdbupd .pexdbhub .pexmigration .pal .mrf` | ❌ none (see D3) |

#### I. Present in PF but not in PE (keep)

Screen OCR via Capture2Text, OCR of PDFs and images on the PC (0.5.8+), OneNote import/send/clip and `.one` exchange (0.5.9+), Windows Sticky Notes import, Google Drive OAuth with DPAPI-protected token, Arabic UI and right-to-left layout, AST-sandboxed calculator, chip-style macro display in the editor, typing-speed test.

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

### 1.5 PhraseForge features not in PhraseExpress (keep; 0.5.6 list plus 0.5.7–0.6.0 additions)

Built-in OCR (Windows.Media.Ocr, Capture2Text-style modes, optional Mistral OCR, PDF/image to Markdown) ·
built-in desktop sticky notes and a Microsoft Sticky Notes importer · quick-note window (send to OneNote or
save as phrase) · OneNote COM send/read and `{#onenote}` · Prompt Tower, Prompt Optimizer, Boost-prompt
hotkey (`{#promptboost}`) · AI engines Gemini, OpenCode Zen, Kilo Code, GPT4All, Mistral, DeepL and free
translate · Listary-style "Search files" launcher · DOCX/PDF export with Arabic RTL · TextExpander, macOS
Text Replacements and PhraseExpress-CSV exchange · HTML→RTF clipboard output · full Arabic RTL UI, Arabic
user guide, Hijri dates · Windows installer, portable EXE, GitHub update check · Google sign-in with a
built-in or own OAuth client · Tools ribbon tab that mirrors every tray-menu command (0.5.6) · sync through the
Google Drive for desktop folder without sign-in (0.5.7) · OCR of PDFs and images without a cloud key, OneNote
`.one` import/export and Publish, HTML/MHT phrase export, customizable quick toolbar (0.5.8–0.5.9).

---

## 2. Gap analysis

Priority: **M** must-have (core parity, or a security defect), **S** should-have, **N** nice-to-have. Complexity: S ≤ 3 dev-days, M ≤ 2 weeks, L ≤ 6 weeks, XL > 6 weeks.

| ID | Gap | Priority | Complexity | FR | Status in 0.6.0 (rows not marked changed: as in 0.5.6) |
|---|---|---|---|---|---|
| G-01 | Secrets stored in plain text and uploaded by sync | M (sec) | S | FR-SEC-01..03 | **closed** (0.5.5): proxy password sealed and device-only; plain values from old versions or restored backups are sealed and wiped from the file |
| G-02 | Macro trust model for imported/synced phrases (`{#run}`, `{#http}`, `{#sql}`, `{#mail -send}`; time/app triggers) | M (sec) | M | FR-SEC-04/05 | **closed** (0.5.5): imported phrases and phrases a sync pull adds or changes are quarantined per PC; their privileged macros (`run, open, web, http, mail -send, outputfile, dbquery, setphrase`, Win-key chords; since 0.6.5 also any file-reading macro whose path is a network share, R14) ask Run once / Always allow / Do not run, automatic triggers skip them; engine blocks them at run time, also through `{#insert}` (`security.py`) |
| G-03 | Folder password: unsalted SHA-256, UI-only gate | M | M | FR-SEC-07/08 | **closed** (0.5.5): salted scrypt (old hashes upgraded on unlock); locked folders ask for the password before any expansion, are hidden from the phrase menu and its search, never feed SmartComplete, and cannot be read through `{#insert}`; one unlock per session counts everywhere (`security.LOCKS`) |
| G-04 | Encryption at rest for the phrase DB | S | M | FR-SEC-09 | done: `vault.py`, Settings > Phrase File/Database > Encryption. AES-256-GCM over the whole SQLite image (header authenticated), random 256-bit data key wrapped by DPAPI and/or a passphrase (scrypt N=2^15); "ask at every start" stores no DPAPI copy. The store works on an in-memory database and writes the file atomically about a second after changes and on exit; WAL files and the old plain file are overwritten before removal. Local backups and the sync base are encrypted with the same key. Measured: 10k phrases open+close +21 ms. Not covered: the uploaded sync copy (FR-SYN-03), Save As copies, `learning` counts |
| G-05 | Hook callback runs Python under the GIL | M | M | FR-INP-01..03 | partial, **0.6.10**: `pfhook.dll` (`native/pfhook/pfhook.c`, built by the workflow with MSVC, x64) runs `WH_KEYBOARD_LL` on its own native thread and queues events in an SPSC ring; Python (`platform/native_hook.py`) answers each key within a 40 ms budget, after which the key passes and the hook stops waiting until Python catches up ("degraded"); hotkey chords and disabled Caps Lock are swallowed natively from a rule table (FR-INP-02); late keys are flagged and the trigger manager erases the extra character instead; self-injection filter kept (FR-INP-03). In-DLL QPC histogram (p99, max) in `stats()` and the self-test. Python hook kept as fallback (`input.native_hook`, `PHRASEFORGE_HOOK=python`). Left: `WH_MOUSE_LL` (recorder), x86 build, P-01 measured on a desktop runner |
| G-06 | UIPI / elevated-window handling | M | S | FR-INP-04 | done, **0.6.10**: `platform/session.window_elevated` compares the foreground process' integrity level with ours (a token we may not read counts as elevated); once per program a tray notice "Cannot type into an administrator window" whose click restarts PhraseForge elevated (`ShellExecute runas`, `--after-exit <pid>` waits for the old copy); expansions aimed at such a window are skipped, so nothing is half-typed |
| G-07 | MSAA/UIA caret fallback | S | M | FR-INP-05 | open (GetGUIThreadInfo only) |
| G-08 | Single-instance guard + argv hand-over | M | S | FR-APP-01 | **closed** (0.5.5): mutex + user-only local pipe per data folder. 0.5.6 fixed two defects in it: sockets left alive after shutdown crashed the next Qt event loop, and on Linux a second launch took over the running instance's pipe (#14) |
| G-09 | CLI switches, portable mode | S | M | FR-APP-02/03 | partial, **FR-APP-03 done**: portable mode (`paths.py`) for the portable EXE (by its name), a `portable.ini` next to the program, `--portable` or `PHRASEFORGE_PORTABLE=1`; data in `PhraseForgeData` next to the program; no `%APPDATA%` or HKCU writes: the Run key (Start with Windows) and Outlook export/default are refused with a message, the Settings checkbox is disabled; checked by a write audit test (APPDATA stays empty). FR-APP-02 **done in #51** (`cli.py`): `--portable`, `--home`, `--minimized`, `--hidden`, `--no-hook`, `--no-clipboard`, `--readonly`, `--debug`, `--log-file`, `--self-test`; actions handed to a running copy: `--shutdown`, `--import`, `--open` (read-only library), `--exec`, `--edit` (uid, id or description); `phraseforge://exec/<uid>` links (opt-in `--register-url`, refused in portable mode; a link always asks before inserting). Not done: a ProcMon trace on a real Windows run |
| G-10 | Trigger options (fast-typing-only, global prefix, delimiter classes, regex presets in trigger editor, skip-next, learned auto-skip, key blocking, random delay) | M | M | FR-TRG-01..07 | **done (0.6.12)**, earlier partial **changed in #47 and #48**: fast-typing-only per autotext (`autotext.fast_ms`), global prefix (`autotext.global_prefix`), delimiter classes (All, Letters, Numbers, Point, Comma, `Custom:<chars>`, combined with `+`), regex presets with fixtures in the trigger editor (`triggers/regex_presets.py`), Skip-next hotkey, learned auto-skip per program (`triggers/autoskip.py`); time triggers take weekdays, a date range, "once" and a random delay (`triggers/schedule.py`: `08:30 days=mon,fri from=… to=… random=10 once`), with a Schedule dialog in the trigger editor and File > Scheduled tasks listing each next run (FR-TRG-07). **0.6.12:** key blocking during output (FR-TRG-06): `pf_block_begin`/`pf_block_end` in `pfhook.dll` hold the user's keys back (in order, up to 512, at most `output.block_max_s` = 10 s) while PhraseForge types and replay them afterwards marked `PFRR`, so the trigger layer sees them as typing; `output.block_keys` = replay (default) / discard (key releases of keys held before output are still sent, so nothing stays pressed) / off; the Python hook does the same as a fallback. **All of FR-TRG-01..07 now done** |
| G-11 | Missing macros + PE macro-syntax layer | M | L | FR-MAC-01..06 | partial, **changed in 0.6.6**: added explode, numlist, settemp/gettemp, autocase, lastchars, textempty, prefix, postfix, regexpos, regexcount, setlevel, langdetect (offline), mousex/mousey/mouseposition, sound (compat: approximate, see `macros/README.md`). **#49** added contents, dictionary, parse, decstr, checktext, headfootfilled (compat: approximate). **#50** added the PE syntax translator (`macros/pe_compat.py`, FR-MAC-01: aliases, key blocks, `-count`, Delphi date formats, `{#pe_unsupported}` for the rest; 212-sample corpus) and runs it on every PhraseExpress import. output/outputall/qstext/setqstext stay unsupported: PhraseExpress's public manual (checked 2026-11-10: /doc/macros/, /doc/macros/output, docs14 macro.htm) does not document them, so imports keep them as `{#pe_unsupported}` |
| G-12 | Form validation, required, formgroup, checkcombo | M | M | FR-MAC-04 | **closed** (0.6.6): every form field takes `-required` and `-validate` (anything, email, url, filepath, folder, letters, numbers, integer, text, date, time, phone, `regex:`); OK stays disabled and the first problem is shown until all visible fields pass; `{#formgroup}`…`{#formgroupend}` with a checkbox that shows/hides its fields (closed groups output nothing); `{#formcheckcombo}` |
| G-13 | Plugin system | M | L | FR-PLG-01..08 | partial, **stage 1 in #52** (`phraseforge/plugins/`): plugin.toml manifest checked before anything runs (FR-PLG-01); safe install from a folder or `.pfplugin` zip; out-of-process JSON-RPC over stdio with per-call timeout, `$/cancel`, kill after grace, restart, Windows job object (kill-on-close, 512 MB, no child processes), minimal environment (FR-PLG-02); declared secrets only (FR-PLG-04); `{#<id>.<macro>}` macro plugins, privileged ones blocked in unapproved phrases (FR-PLG-07); Phrases > Plugins with consent and permission diff on update, last 100 errors (FR-PLG-08); policy `plugins_allowed`. **Stage 2 in #53** (`plugins/engines.py`): one engine contract (describe, status, capabilities, settings_schema, list_models, list_languages, generate, translate) for built-in and plugin engines (FR-PLG-03); the bundled engines (OpenAI, Anthropic, OpenRouter, Gemini, OpenCode Zen, Kilo Code, Ollama, GPT4All, DeepL, MyMemory) are `builtin` engines behind that contract (FR-PLG-06, wrapping `ai.py`); plugin engines are chosen as `plugin:<id>` in Settings > AI / Language Translation; conformance suite `tests/plugin_conformance/`. **Stage 3:** per-plugin network filter (FR-PLG-05, `plugins/netproxy.py`: HTTPS CONNECT only to manifest hosts on port 443, blocked hosts in the plugin's error list); Ed25519 plugin signatures (`plugins/signing.py`: `plugin.sig` covers every file, shown at consent, an invalid signature is never installed, trusted keys in `plugins.trusted_keys` or the policy, policy `plugins_require_signature`). Streamed replies (`$/progress` pieces before the answer, shown live in the Prompt Optimizer; each piece restarts the timeout, hard end at 10× timeout, 4 MB cap). Built-in engines stream too (OpenAI-compatible SSE, Anthropic SSE, Ollama NDJSON; GPT4All answers in one piece; `tests/test_ai_streaming.py`). Still open: image/vision/usage/model pull methods for plugin engines, restricted token / low integrity (R97: until then a plugin can still read the user's files and bypass the proxy) |
| G-14 | AI parity (vision, image gen, Ollama pull, usage, DeepL, langdetect) | S | M | FR-AI-01..05 | partial: vision (`-image`), `{#aiimage}` (OpenAI/Gemini), Ollama model download, per-PC usage counts, DeepL glossary sync done; PE preset import open (needs a real PE config.xml: field order is unverified) |
| G-15 | Import from PhraseExpress | M | M | FR-IMP-01..03 | partial, **changed in 0.5.9**: per-phrase `.txt` (PE's documented text export: one file = one phrase, name = description; several files at once; a folder tree keeps its sub-folders), CSV/TXT/TSV tables, XML (layout guessed, no real PE sample yet); encrypted `.pexdb/.pexdbhub/.pxp` refused with instructions for the text route; macros translated by `macros/pe_compat.py` since #50; triggers are lost in the text route (U-15) |
| G-16 | Other importers/exporters | S | M | FR-IMP-04/05 | partial, **changed in 0.5.9, 0.6.4 and 0.6.5**: TextExpander, macOS plist, PE CSV, DOCX/RTF/PDF/HTML/MHT export (RTF export: #27, in 0.6.5), OneNote section export and Publish; 0.6.4 (#26): DOCX/RTF/XLSX/image **import** with PE's four options (copy, link, open, line by line; `importers/files.py`; the Excel column mapping is ours, PE's is not published; 0.6.5 hardened the RTF and DOCX readers, R16/R17); no Texter/AHK/Breevy/Word AutoCorrect, no `.doc`/`.xls`, no XML/XLSX export |
| G-17 | Levels (language variants), hotkeys, `{#setlevel}` | S | L | FR-DAT-01 | partial: `phrase_versions(phrase_id, lang)` + active-language setting; no level hotkeys/`{#setlevel}` |
| G-18 | Trash, comments, templates, links, folder prefix/suffix, multi-key sort | S | M | FR-DAT-02..05 | done: Trash (`trash` table holds a snapshot of the deleted phrase or folder tree; restore keeps uid, triggers, tags, versions, comments, history and quarantine; restore to the old folder or the top level; purge after `trash.days`, default 30; local to the PC: stripped from sync copies and kept by pulls, so nothing can be restored past the approval gate); comments (`phrase_comments`: author, time, text, resolved; synced and merged); template folders (`folders.is_template`: no triggers, not in the popup; "Phrase from template" copies text, format, tags, notes and versions, not abbreviations). A Trash dialog instead of a tree node. Phrase links: a phrase whose whole content is `{#insert -uid X}` (new `-uid` option) follows X, shown with a link icon and the target in its tooltip; the target keeps its own lock and approval. Folder text: `folders.text_before/text_after`, macro-enabled, wrapped around every phrase of the subtree at expansion (outer around inner; escaped in formatted phrases); part of each phrase's fingerprint, so a synced change re-quarantines; merged between PCs. Multi-key sort: two fields with direction (stable sort). Folder abbreviation prefix and bulk sort were done earlier. Not done: an `is_link` column (links are recognised by their content) |
| G-19 | Multiple mounted phrase libraries | S | L | FR-DAT-06 | done (`libraries.py`, `ui/libraries_dialog.py`, Phrases > Libraries): other PhraseForge phrase files (local or on a shared folder) mounted read-only or read-write; mirrored under their own root folder and refreshed when the file changes (30 s tick); read-only edits refused with a visible reason (store write guards, editor disabled); read-write edits written back at once by uid (last writer wins per item); trigger precedence personal > first-mounted (`Store.trigger_rank`); library phrases quarantined as "library"; mirrors stripped from cloud sync copies and from the content hash, and kept across pulls (restore hooks). Older files without uids mount read-only by row id. Not done: a password check mode per library, a sync config per library (FR-SYN-05 covers team libraries) |
| G-20 | Spell check | S | M | FR-EDT-01 | partial, **0.6.4** (#24), **0.6.5** (suggestions searched in the background, R15): red underline, suggestions, Add to dictionary / Ignore all, one Hunspell dictionary per script via spylls, dictionaries downloaded from LibreOffice (`spell.py`, `ui/spell_ui.py`); 5,000 words highlighted in 104 ms (English) / 157 ms (Arabic) on Linux. Missing: the dictionary does not follow the phrase's language level yet |
| G-21 | RTF, embedded files, Markdown/DOCX into editor | N | M | FR-EDT-02 | partial: RTF clipboard output |
| G-22 | Dynamic folders | S | L | FR-DYN-01/02 | done: right-click a folder > Dynamic folder... (`dynamic.py`, `ui/dynamic_dialog.py`): text file (line), CSV/TSV/Excel (row, header or explicit column map incl. autotext), folder on disk (file; copy or `{#document}` link; images), SQLite (read-only) and ODBC (read-only, single SELECT) queries; refreshed when the file changes or every `ttl_s` for queries, in place (stable phrase ids), max 5000 items. Deviation from FR-DYN-01: items are stored phrases tagged `dynamic` (not virtual), so popup, search and autotext work unchanged. A source is read only after approval on this PC (device setting `dynamic.approved.<id>`), so a synced folder cannot read local files; new items are quarantined. ODBC credentials sit in the connection string (FR-DYN-02 secret store not used) |
| G-23 | Macro recorder | N | L | FR-REC-01 | done: Phrases > Record macro (`recorder.py`, `platform/record_hook.py`, `ui/recording_bar.py`): keys as text runs plus `{#key}` chords, Backspace corrections folded in, mouse clicks / double-clicks / wheel (screen or window-relative), pauses dropped below `recorder.min_pause_ms` and capped at `recorder.max_pause_ms`; stop hotkey (default Ctrl+Shift+F12) or the Stop button; password fields and PhraseForge's own windows are not recorded; triggers are paused while recording. Replay through `{#mouse … -relative 1}` and `{#mouse wheel}`. Tested without Windows (event→macro, replay actions); the Windows hooks need a manual test |
| G-24 | Change-set sync | S | L | FR-SYN-01..04 | done (FR-SYN-01, FR-SYN-04): edits from two PCs merge instead of asking keep-mine/keep-theirs. State-based three-way merge (`cloud/merge.py`) against the last agreed copy (`<db>.sync-base.db`), keyed by a stable `uid` on folders, phrases and sticky notes; field-level, newer `modified` wins a same-field clash and the loser goes to phrase history; edit beats delete; a deleted folder comes back for a phrase kept in it; vars/settings/excluded programs/special triggers merge per key; shared-mirror and dynamic-folder items are not merged. Same remote file format, so older versions still read it; a copy without uids falls back to the question. FR-SYN-03 done: with sync.encrypt the sync copy and cloud backups are encrypted with a sync passphrase (AES-256-GCM via `vault.py`, scrypt; the PRD named XChaCha20-Poly1305, AES-GCM with a random 96-bit nonce per file is used instead), the file-property hash is keyed, a plain cloud copy is refused while encryption is on and a PC without the passphrase never overwrites an encrypted one. Missing: per-operation change log with HLC (merge uses timestamps), compaction (FR-SYN-02) |
| G-25 | Multi-user server, ACLs, directory identity | N | XL | FR-SYN-05 | done (stages 1 and 2): shared folders and phrases on SQL Server or PostgreSQL (`shared/`), Windows or database sign-in checked by the server; folder permissions for users, AD groups / roles and everyone, enforced by PhraseForge (not by the database), administrators; full change history with restore. Missing: database-enforced permissions (row-level security), offline queue beyond the next sync |
| G-26 | Outlook context | N | M | FR-OL-01 | partial: `{#outlook field}` via COM |
| G-27 | Duplicate finder, backup compare, vacuum | N | S | FR-UI-01 | done (`maintenance.py`, File > Maintenance): duplicates by normalised text (+ format and language versions) across all folders and by shared abbreviation (also of switched-off phrases), moved to the Trash; backup diff now-vs-backup or backup-vs-backup by uid (row id for older backups, encrypted backups with the vault key): added/removed/changed with the changed fields, and "bring back" of the old version (quarantined); integrity + foreign-key check; VACUUM (encrypted files compacted in memory and saved). Folder-level bulk "Remove duplicates" stays |
| G-28 | Admin lockdown policy file | N | S | FR-APP-04 | done: `%ProgramData%\PhraseForge\policy.toml` (`policy.py`, example in `docs/policy.example.toml`): settings_locked, editing_disabled (enforced in the store; sync pulls still apply), stats_enabled, macros_disabled, locked_settings, forced `[settings]`, message; an unreadable file fails closed. `plugins_allowed` waits for the plugin system |
| G-29 | Auto-update | N | M | FR-APP-05 | partial: GitHub release check + setup link |
| G-30 | SAPI, layout conversion, mouse/sound macros | N | S | FR-MAC-05 | **closed** (#49): `{#speak text -voice -rate}` (SAPI), `{#convertlayout -from -to}` with tables for en, ar, ru, de, fr (`macros/layouts.py`); mouse position and sound were added in 0.6.6 |
| G-31 | Full UI localisation | S | M | FR-UI-02 | partial, **changed in 0.6.0**: 1,277-entry Arabic table, RTL; list headers, panel title and breadcrumb now translated; strings are still found by hand (no extraction step) |
| G-32 | Full test suite hangs in one run (order-dependent Qt state) | M (quality) | S | FR-QA-01 | **closed** (0.5.6): the hang was gone after 0.5.5; the remaining Windows CI crash came from `SingleInstance` sockets (see G-08). The full suite runs in one process: 663 passed, 18 skipped (4 min 18 s on Linux offscreen, 2026-10-30). Still open from FR-QA-01: the < 3 min target and a per-test `pytest-timeout` |
| G-33 | Session awareness (lock, RDP) | N | S | FR-INP-06 | done, **0.6.10**: the trigger poll loop reads `WTSSessionInfoEx` (lock flag, connect state); locked or disconnected unhooks the keyboard and clears the typing buffer, unlocked hooks again; time and window triggers wait too. Unknown answers count as active |
| G-34 | `{#http}` can reach localhost/LAN/metadata addresses (incl. via redirect) | M (sec) | S | FR-SEC-06 | **closed** (0.6.1): without a proxy, `{#http}` uses a pinned transport (`net.pinned_transport`): one lookup, every answer checked, and the connection goes only to a checked address; TLS still verifies the certificate against the host name. The name check before the first request and every redirect (`net._guard`) stays. Tests: a rebinding resolver (public first, 127.0.0.1 second) is stopped and the local server sees nothing; the same test fails on 0.6.0. **Limit:** with a proxy set in Settings > Network the proxy resolves names, so only the name check applies there |

PE evidence for each gap: Section 1.2. Also open: `test_filesearch.py::test_speed_gate_50k_entries_answers_in_milliseconds` (median < 50 ms) was reported failing on slower machines in 0.5.4; it passed in the 0.5.6 Linux run, so its status on slower Windows machines is unconfirmed.

**Summary for 0.6.6:** G-28 closed (#30); G-25 open → partial (#32) → closed (#33); G-12 closed (#28); G-11 moved forward inside "partial": 9 closed, 14 partial, 11 open. **Summary for 0.6.4 and 0.6.5:** no gap changed state; G-16 and G-20 moved forward inside "partial", and R14 extends closed gap G-02. **Summary for `main` after 0.6.3:** G-20 partial (#24) → 6 closed, 15 partial, 13 open. **Summary for 0.6.3:** unchanged from 0.6.1 (the red-team fixes harden closed gaps G-01, G-02 and G-34 and add no new gap). **Summary for 0.6.1:** G-34 closed → 6 of 34 closed, 14 partial, 14 open.

**Summary for 0.6.0:** no gap changed state between 0.5.6 and 0.6.0. G-15, G-16 and G-31 moved forward inside "partial"; G-34 is still the open security item. The counts below still hold.

**Summary for 0.5.6:** 5 of 34 gaps closed (G-01, G-02, G-03, G-08, G-32), 15 partial, 14 open. G-03 is closed for its own scope; the per-file password-check modes of FR-SEC-08 (`on_start`, `on_open`, `on_view`) are still to do. Every remaining **must-have** gap is partial or open: G-05 and G-06 (input core), G-10, G-11 and G-12 (triggers and macros), G-13 (plugins), G-15 (PE import) and G-34 (DNS rebinding).

Out of scope by decision: licensing/activation, the vendor update server protocol, bit.ly/Twitter macros, DDE (`ddemacro/ddeset`, revisit on demand), Firebird/MySQL back ends, and the "AI for a fee" vendor proxy.

---

## 3. Clone requirements

Format: **FR-ID — statement.** *Acceptance:* testable criteria. *Test:* ID in Section 7. Requirements tagged `needs-PE-capture` must also match a recorded PE behaviour trace before they close.

### 3.1 Security (do first)

- **FR-SEC-01 — Secrets are stored DPAPI-protected (CurrentUser scope), never in plain text.** Applies to every settings key matching `ai.*key*`, `ai.*token*`, `net.proxy_password`, `cloud.*token*`, and any plugin-declared secret.
  *Acceptance:* (a) after setting a key, `SELECT value FROM settings` contains no substring of the key; (b) on a fresh DB the key round-trips through the UI; (c) a DB copied to another Windows user cannot decrypt it and the UI shows "re-enter key". *Test:* T-SEC-01.
- **FR-SEC-02 — Secrets and device-local settings are excluded from every sync upload, cloud backup and export.** *Acceptance:* the uploaded snapshot (or change set) contains none of the FR-SEC-01 keys; `export_dict()` omits them unless the user passes `include_secrets=True` and enters a password used to encrypt the export with AES-GCM. *Test:* T-SEC-02.
- **FR-SEC-03 — Migration.** On the first start of schema v3, existing plaintext secrets are encrypted in place, and the old rows are overwritten and the DB vacuumed. *Acceptance:* after migration, `strings phraseforge.db` finds no former key. *Test:* T-SEC-03.
- **FR-SEC-04 — Phrase trust levels.** *(As built since 0.5.5, extended in 0.6.2/0.6.3: a quarantine table plus fingerprints instead of the two columns below; see decision D7, Section 5.9.)* Each phrase has `origin ∈ {local, imported, synced, plugin}` and `trusted_hash` (SHA-256 of its content when last approved). *Acceptance:* a phrase whose content hash ≠ `trusted_hash` and whose origin ≠ local cannot run privileged macros (FR-SEC-05) until it is approved. Editing a phrase locally re-approves it. *Test:* T-SEC-04.
- **FR-SEC-05 — Privileged macros** (`run, open` with non-http targets, `http` to non-public or user-unapproved hosts, `sql`/`dbquery` with write statements or ODBC, `outputfile`, `mail -send`, `ad`, plugin calls flagged privileged, and (as built in 0.6.5) any file-reading macro whose path is a network share — `textfile`, `document`, `csv`, `image`, `xls`, `xlsfind`, `sql`, `pastefile`) require approval on first use for each (phrase, content hash). A trigger that fires without user input (time, app focus, clipboard) **never** shows an approval prompt; it skips execution and logs it. *Acceptance:* an imported phrase with `{#run calc.exe}` fired by a time trigger does not start calc and writes a log entry; the same phrase fired by its hotkey shows one approval dialog. *Test:* T-SEC-05.
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
- **FR-PLG-04 — Secrets are injected per call** by the host from the FR-SEC-01 store, only for secrets the manifest declares. *Not enforced yet (R97):* a plugin runs with the user's rights and can read the PF DB and unseal its DPAPI values; until a restricted token exists every plugin is treated as privileged. *Test:* T-PLG-04.
- **FR-PLG-05 — Network permission enforcement (best effort):** the host passes `HTTPS_PROXY` pointing to a local filtering proxy that allows only the manifest's hosts. Plugins that bypass the proxy are a documented residual risk; first-party plugins are reviewed. *Test:* T-PLG-05. **Done** (`tests/test_plugin_netproxy.py`): HTTPS tunnels only (plain HTTP refused), port 443 only, no network permission = everything refused.
- **FR-PLG-06 — Bundled first-party engines** are migrated from `ai.py` into plugins: openai, anthropic, openrouter, ollama (incl. pull/delete with progress), deepl. First-party plugins may run in-process (`runtime="builtin"`) only if they ship in the PF package and pass the same conformance suite. *Test:* T-PLG-03.
- **FR-PLG-07 — Macro plugins** register `{#ns.name}` commands (namespaced, so they cannot shadow built-ins); their arguments arrive already expanded; they return a text, actions or error result. Privileged-macro rules (FR-SEC-05) apply when the manifest requests `input`, `filesystem` or non-allowlisted `network`. *Test:* T-PLG-06.
- **FR-PLG-08 — Plugin manager UI:** install from file, enable/disable, show permissions and requests, show the last 100 RPC errors. Installing shows the permission diff and needs explicit consent; updates that widen permissions need consent again. *Test:* T-PLG-07.

### 3.6 AI and translation

- **FR-AI-01 — Preset model parity:** preset = {name, instruction, length, accuracy, variation, model, engine}; the PE preset serialisation (`|`-separated, `~pipe~` escape [C-DLL]) is importable through FR-IMP-01 when a user supplies PE's config. *Test:* T-AI-01.
- **FR-AI-02 — Vision:** `{#ai -image clipboard|file:<path>|region}` sends an image to engines whose `capabilities.vision` is true; otherwise `[ai: engine has no vision]`. *Test:* T-AI-02. **Done** (`tests/test_ai_parity.py`; network-share files need an approved phrase).
- **FR-AI-03 — Image generation** `{#aiimage -prompt -model -size}` → image action pasted as an image. *Test:* T-AI-03. **Done** (OpenAI images API format; OpenAI and Gemini). Also done: Settings > AI > Download Ollama model, and Usage (requests, tokens, images per provider/model, this PC only).
- **FR-AI-04 — DeepL engine** (free/pro endpoint chosen by key suffix `:fx`), glossary sync to DeepL glossaries, ignored words wrapped in XML tags that are preserved. *Test:* T-AI-04 (against a recorded mock). **Done** (`tests/test_deepl_glossary.py`, mock of the DeepL v2 glossary API): a glossary with languages set is uploaded as "PhraseForge: <name> #<hash>", reused while unchanged, replaced when edited; `-glossary` picks one by name.
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

- **FR-IMP-01 — PhraseExpress import (export-based; D3 option B).** *(v4: rewritten for the export routes the vendor manual documents; see U-15.)* The primary route is PE's per-phrase **text export**: PF imports one or many `.txt` files (file name → description, file text → content) and a folder of such files (sub-folders → folders), reading UTF-8, UTF-16 and the ANSI code page. Tables (CSV/TSV) and XML from PE or from third-party exporters are accepted when present. Triggers, macros-as-structure and levels do not survive the text route, and the import report must say so (0.5.9 reports only the count of imported and skipped files). PF also imports the user's `config.xml` (AI presets, glossaries, delimiter settings, excluded apps, hotkeys; secrets are **not** imported automatically, and the user is told to re-enter them). Folder tree, descriptions, plain/HTML content, autotext and hotkeys are mapped; macros go through FR-MAC-01. The import report lists every unsupported macro and option. *Acceptance:* the text route passes on synthetic fixtures today (`tests/test_phraseexpress_text_import.py`); full closure needs one real PE text export and, if it exists on the user's build, one CSV/XML export ([U-02], [U-15]) imported with 0 data loss for the fields that format carries. *Test:* T-IMP-01.
- **FR-IMP-02 — Imported items get `origin="imported"`** (FR-SEC-04) and the tag `phraseexpress`, and are placed under a new root folder by default. *Test:* T-IMP-02.
- **FR-IMP-03 — Native `.pxp`/`.pexdb` import is out of scope** unless [U-01]/[U-02] are resolved by a lawful route (Section 8): e.g. PE offers a documented plaintext export of these files, or a user decrypts their own files using PE itself. If such a route exists, the import adapter reads a decrypted SQLite copy mapped through Appendix A. *Test:* —
- **FR-IMP-04 — Additional importers:** Word AutoCorrect (`.acl` via Word COM, or the Word export), AutoHotkey hotstrings (`::abbr::text` incl. options `*`, `?`, `C`, `O`, `R`), Texter (`.texter`), Breevy, ShortKeys (CSV/text exports). Each is a separate `importer` plugin with fixtures. *Test:* T-IMP-04. *(v6: PE's own file import of Word, RTF, Excel and image files, with its four options, is built in 0.6.4 as `importers/files.py`, outside this plugin list; the importers above are still open.)*
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

- **FR-EDT-01 — Spell check** with Hunspell (via `spylls` pure-Python or `cyhunspell`/`hunspell` binding; U-08 in Section 10; `spylls` chosen in 0.6.4), using dictionaries from LibreOffice dictionaries (licensed per dictionary; **not** copied from PE's `dict\`). Red underline, suggestions menu, per-phrase language from its level. *Acceptance:* a misspelt word is underlined within 300 ms of typing in a 5k-word phrase, and the suggestions menu opens within 500 ms whatever the word (budget P-09). *Test:* T-EDT-01. *(As built in 0.6.4/0.6.5: one dictionary per script instead of per level; the level part is still open.)*
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

### 5.9 Decision D7 — trust-model storage (as built, recorded in v5)

FR-SEC-04 asked for two columns on every phrase, `origin` and `trusted_hash`. 0.5.5 shipped a different design, and 0.6.2/0.6.3 extended it after the red-team review.

| Option | Pros | Cons |
|---|---|---|
| A. `origin` + `trusted_hash` columns on `phrases` (FR-SEC-04 as written) | One place per phrase; easy to query | Schema change on every phrase; the hash covers content only, so it misses what changes behaviour outside the content (output targets, folder settings, variables); sync copies the columns, so trust would travel between PCs unless filtered |
| **B. Per-PC `phrase_quarantine` table + fingerprint comparison on untrusted writes (as built)** | Trust stays on the PC that granted it; a sync or import compares fingerprints before and after and quarantines only what changed; the fingerprint can cover more than content | Two mechanisms to keep in step (the table and the fingerprint); a phrase changed by a path that is neither import nor sync is not re-checked (none known) |

**Chosen: B.** The fingerprint (`db.phrase_fingerprints`) covers the content of every language version, the phrase's and its folders' output target and argument (0.6.2), and the values of the global variables the phrase reads (0.6.3; a run-time variable name counts all of them). Untrusted writes are `restore_from(untrusted="synced"|"imported")` (sync pull, File > Open) and every importer (`@untrusted_import`, which also re-quarantines existing phrases whose fingerprint the import changed). Device settings (`db.is_device_setting`: network, proxy, AI endpoints, program and file paths, sync and backup locations, file-search commands) never come from a pulled or opened file, a settings import or the migration file. FR-SEC-04's acceptance criteria still hold with B; the column names in FR-SEC-04 and FR-IMP-02 are superseded by this record.

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

### 6.1 Phase status at 0.6.5 (v6)

| Phase | Status | Done | Left |
|---|---|---|---|
| P0 | **mostly done** | FR-SEC-01..03 (secrets sealed, device-only, migrated); FR-SEC-06 incl. DNS rebinding (0.6.1); FR-SEC-07 (salted scrypt, the allowed fallback); FR-APP-01 (single instance); FR-QA-01 hang and Windows crash (one-process run passes) | perf harness `bench/` and baseline numbers (Section 7.4) not built; FR-QA-01 < 3 min target and `pytest-timeout` |
| P2 (pulled forward) | **partly done** | FR-SEC-04/05 trust gate for imported and synced phrases (`security.py`, `phrase_quarantine` table), hardened in 0.6.2/0.6.3 (output targets, Win-key aliases, device settings, variables) and 0.6.5 (network-share reads); storage recorded as decision D7; FR-SEC-08 lock before expansion | FR-SEC-08 `passcheck` modes; FR-DAT-00..05 |
| P5 (started early, user request) | **partly done** | FR-IMP-01 text route and folder tree; FR-IMP-05 HTML/DOCX export; OneNote exchange (outside the FR list); PE-style Word/RTF/Excel/image file import (0.6.4, outside the FR list) | FR-IMP-01 real-sample check and macro translation (needs P3 `pe_compat`); FR-IMP-02 `phraseexpress` tag and `origin` (imports use the 0.5.5 quarantine instead); FR-IMP-04 importers; FR-IMP-05 XML/XLSX |
| P6 (started early, parallel session) | **started** | FR-EDT-01 partial: spell check (0.6.4), suggestions off the UI thread (0.6.5) | FR-EDT-01 dictionary per phrase level; FR-EDT-02; FR-DYN-01/02; FR-OL-01; FR-UI-01/02 |
| P8 (started early, parallel session, 0.6.6) | **started** | FR-APP-04 lockdown policy (#30); FR-SYN-05 shared SQL database with folder permissions and history (#32, #33); R19 fixed | FR-APP-02/03/05, FR-REC-01, FR-MAC-05 |
| P1 (0.6.10, 0.6.12) | **started** | FR-INP-01..03 keyboard part (`pfhook.dll`, decision budget, native rule table, late-key handling); FR-INP-04; FR-INP-06; FR-TRG-06 keyboard block + replay (0.6.12) | FR-INP-01 mouse hook and x86; P-01..P-03 measured on a desktop runner; FR-INP-05 |
| P3, P4, P7 | not started | — | All their FRs |

**Next step on the critical path (v6, unchanged from v5):** P0 now lacks only the `bench/` harness and the FR-QA-01 timing items. Build `bench/` first, so P1 has the baseline numbers it is measured against: P-02 (matcher decision) and P-06 (popup with 10k phrases) can run on any OS in CI; P-01, P-03, P-04 and P-08 need a Windows runner with an interactive desktop (Section 7.3). Then start P1 with a `pfhook.dll` spike that measures P-01.

(v4 note: the 0.5.7–0.6.0 releases went to user-requested features, sync, import/export and UI quality; 0.6.1–0.6.3 went to security. v6 note: 0.6.4/0.6.5 went to P6/P5 features from a parallel session and their review; P0's `bench/` is still the critical-path item, and each review found defects only once the code was read and run against real inputs, so `bench/` should also time the spell and import paths.)

---

## 7. Testing and quality

### 7.1 Current baseline [REPO]

0.6.5: **860 tests** in 58 files (`pytest --collect-only`, Linux; adds `test_document_import.py` from #26, and `test_redteam.py` is now 78 cases with the 0.6.4 and 0.6.5 findings). `main` after 0.6.3 (`af02529`): **829 tests** in 57 files (adds `test_spell.py` from #24). 0.6.3: **816 tests collected** in 56 files (`pytest --collect-only`, Linux). New since 0.6.0: the DNS-rebinding and TLS-name tests (`test_security.py`), and `test_redteam.py` (58 cases). Each red-team case was run against the release before its fix and failed there; the control cases pass on both. Windows CI ran the full suite, the frozen-EXE self-test and the silent install/uninstall green on `5df197c` (#21), `308dd6d` (#22) and `0b39832` (#23).

0.6.0: **750 tests collected** (`pytest --collect-only`, Linux). Windows CI ran the full suite green on `6c4904f`, then the frozen-EXE self-test (which now also checks `PySide6.QtPdf`, the OneNote COM wrappers and the built-in Google client) and a silent install/uninstall. New since 0.5.6: tests for Drive folder detection, automatic sync, quick toolbar, drag and drop, OneNote exchange (with a fake COM client), export formats, PhraseExpress text import (incl. Windows line ends and UTF-16) and the visual audit (contrast ratios, primary buttons, icon palette, Arabic keys). OneNote, Windows OCR and clipboard paths are still checked only with fakes or on the CI runner, not on a machine with OneNote and PhraseExpress installed.

0.5.6: **663 passed, 18 skipped in one process** (Linux, `QT_QPA_PLATFORM=offscreen`, 4 min 18 s, 2026-10-30), across 46 test files. Areas as in v2, plus security (trust gate, folder locks, single instance), Google sign-in, sticky-notes UI and the Tools tab. Windows CI (`windows-build.yml`) runs the same suite, then builds and runs the frozen EXE with `--self-test`, on every PR. The v2 hang at `test_ui.py::test_theme_icons_tray` no longer happens. The later Windows-only access violation was traced to `SingleInstance` sockets that stayed alive after their owner was destroyed, and was fixed in #14 with a subprocess regression test (`test_security.py::test_destroyed_single_instance_leaves_nothing_that_crashes_later`).

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
| P-09 | **(v6)** Spell check: underline a 5k-word phrase; open the suggestions menu on any word | ≤ 300 ms; ≤ 500 ms. Measured on Linux at 0.6.5: 104 ms (English) / 157 ms (Arabic); menu ≤ 0.42 s for the worst Arabic word (the search finishes in the background) |

### 7.5 Security checks

- Input handling: no keystroke data is written to logs at any log level (test: grep logs after a typing session); learner skips password fields (`windows.py:149`), with a test using a UIA `IsPassword` control.
- Clipboard history excludes `ExcludeClipboardContentFromMonitorProcessing` and `CanIncludeInClipboardHistory=0` formats (password managers set these), and skips concealed-format clipboard items.
- Macro sandbox: `safe_calc` AST whitelist fuzzing; `{#run}` arguments are passed as an argv list, never through a shell; `{#sql}` is read-only unless privileged approval was given; `{#textfile}`/`{#outputfile}` resolve paths with symlinks resolved and are confined to user-approved roots for imported/synced phrases. *(Status at 0.6.5: `{#outputfile}` is privileged, and network-share paths in every file-reading macro need approval (R14); confinement of local paths to approved roots is not built.)*
- Plugin loading: manifest-only parsing before execution; plugins run with `python -I -S` (no CWD imports, as in the scratchpad rule for untrusted code); restricted token; job object; signature check for third-party plugins when `policy.plugins_require_signature=true`.
- No data leakage: sync payload E2E-encrypted (FR-SYN-03); a network egress test asserts that PF makes no outbound connections with all integrations disabled (`net` monitor in the integration job); crash reports are local only.
- Dependency audit: `pip-audit` in CI; pinned hashes in `requirements.lock`.
- Static analysis: `bandit` (no `shell=True`, no `eval`, no `pickle`, which the current code already satisfies [REPO]) and `ruff`.
- Native DLL: built with `/guard:cf /Qspectre /DYNAMICBASE /HIGHENTROPYVA`; fuzz the ring-buffer reader.

#### 7.5.1 Red-team review of 0.6.1 (2026-11-02), fixed in 0.6.2

Three parallel reviews (trust gate; file parsers and sync; secrets, IPC and network) attacked 0.6.1. Each fix has a regression test in `tests/test_redteam.py` that fails on 0.6.1 (31 of 41 cases; the other 10 are allowed-key controls).

| # | Finding | Severity | Fix |
|---|---|---|---|
| R1 | An imported/synced phrase or folder with output target "Specific program" ran that program with no approval, also from time/app triggers; the phrase fingerprint ignored output targets, so a sync could add one to a trusted phrase | Critical | `approved_for` treats a resolved `program` target as privileged (and `email`/`onenote` for unapproved phrases); the fingerprint covers the phrase's and its folders' targets; legacy `ui.trigger_extras` is migrated before the comparison |
| R2 | `{#key}` filter matched only `win`/`lwin`/`rwin`: `meta+r`, `super+r`, `cmd+r`, `windows+r`, `lwinkey`, `vk5b` and `ctrl+esc` (Start menu) passed, so typed commands could run | Critical | `security.opens_system_ui` normalises every key name the sender understands |
| R3 | A sync pull or an opened `.db` replaced every non-local setting: AI base URLs (this PC's key sent to another host), proxy, `net.allow_private_hosts`, backup folder, OCR log file, `onenote.exe`, file-search commands/actions; an incoming local-only key not set on this PC also got through | High | `db.is_device_setting` (prefixes + path/URL/program suffixes); `restore_from(untrusted=…)` drops the file's device settings and keeps this PC's; settings import and migration restore skip them |
| R4 | Settings export and the migration file wrote API keys and the proxy password in plain text | Medium | Secrets left out of both files |
| R5 | `httpx`/`urllib3` logged full request URLs (translated text, tokens in query strings) to `phraseforge.log` | Medium | HTTP loggers set to WARNING |
| R6 | Clipboard history kept passwords from password managers | Medium | Content marked `ExcludeClipboardContentFromMonitorProcessing`, `Clipboard Viewer Ignore` or `CanIncludeInClipboardHistory=0` is not recorded |
| R7 | `{#http}` forwarded custom headers (e.g. `x-api-key`) on a redirect to another host | Low | Headers the phrase set are dropped when the redirect leaves the origin |
| R8 | `100.64.0.0/10` (CGNAT, Tailscale, some cloud metadata) not blocked | Low | Added to `is_private_ip` |
| R9 | Deeply nested XML exhausted recursion in the PE XML importer | Low | Depth limit 200, clean error |

Held up: XML entity expansion and XXE (expat limits, no external entities), symlinks in folder import (not followed), export path sanitising, `_check_db` on pulled files, DPAPI sealing, Google sign-in (PKCE, state, loopback), single-instance IPC (argv only shows the window), the 0.6.1 pinned `{#http}` transport (decimal/octal/IPv6-mapped/NAT64 forms blocked).

Fixed in 0.6.3:
- **R10 (Medium):** synced or imported `{#var}` values could change what an "Always allow" phrase runs. The fingerprint now includes the values of the global variables a phrase reads (`{#var}`/`{#get}`; a run-time name counts every variable), so a pull or import that changes one sends the phrase back for approval. `quarantine_writes` also quarantines existing phrases whose fingerprint an import changed. The user's own `{#set -scope global}` changes nothing.
- **R11 (Low):** the update notice opened the URL from the GitHub API answer without a check. `updates.safe_release_url` accepts only `https://github.com/bahattab/B-PhraseForgeExpress/releases/…` (no credentials, no other port), and the notice falls back to the releases page.

Review of PR #7 (multiple-choice autotext, merged from a parallel session, shipped in 0.6.3), fixed in 0.6.4:
- Held up: a phrase chosen from the menu goes through the same expansion path as any other, so the folder password (`unlocked_for`) and the trust gate (`approved_for`) still apply; disabled folders and per-program restrictions are respected.
- **R12 (Low):** a delimiter-completed shared autotext (`sig` + Space) lost the delimiter: it was swallowed when the menu opened and never re-typed. The `choose:` command now carries the delimiter, and the chosen phrase re-types it.
- **R13 (Low):** the menu listed the names of phrases in locked folders, which the normal menu hides, and it erased the typed abbreviation before the folder was unlocked. Locked phrases now show as "Locked phrase", and the abbreviation is erased by the chosen phrase's own expansion, after unlock and approval; cancelling leaves what was typed.

Review of PR #24 (spell check) and PR #26 (Word, RTF, Excel and image import), both merged from a parallel session, fixed in 0.6.5:
- Held up: imported files are quarantined (`@untrusted_import`); the spelling underline never reaches the saved phrase; a file name holding `}{#run ...}` stays one quoted argument of the link macro; the DOCX size cap holds, because zipfile stops at the declared size.
- **R14 (High, older than both PRs):** the file-reading macros (`{#textfile}` and its aliases, `{#document}`, `{#csv}`, `{#image}`, `{#xls}`, `{#xlsfind}`, `{#sql}`, `{#pastefile}`) were not privileged, so a synced or imported `{#textfile "\\host\share\a.txt"}` ran without approval. On Windows that opens an SMB connection to the host, which sends the user's NTLM credentials. A network path (`\\`, `//`, after `%VAR%` expansion) in their file argument now needs an approved phrase. The static scan and the engine's run-time check both cover it, so a path built by another macro is blocked too. Local files still need no approval.
- **R15 (Medium):** spelling suggestions ran on the UI thread. A long misspelt Arabic word froze PhraseForge for 9 to 30 s on right-click (measured with the LibreOffice `ar` dictionary). Suggestions now search in the background with a 0.4 s wait, at most 3 searches at once. The menu opens at once, and the result is kept for the next right-click.
- **R16 (Medium):** an RTF with a code page Python does not know (`\ansicpg10000` from old Macs, `\ansicpg0`) raised `LookupError`. That broke the import and `{#document}`, which read the file before #26. Mac code pages and `\mac`/`\pc`/`\pca` are now mapped, and anything else falls back to cp1252. Also fixed: an emoji written by Word as two `\uN` surrogates came out as two broken characters that could not be stored; the pair is now joined.
- **R17 (Low):** the DTD check on `word/document.xml` searched the bytes for `<!DOCTYPE`, which a UTF-16 document passes. expat now reads the prolog and refuses any DTD in every encoding.
- **R18 (Low):** `spell.latin` and `spell.arabic` arrive by sync and were used as file names. Only codes in the dictionary list are used.

Noted while recording #32 in v6, fixed in 0.6.6 (#30 and #32 have not been reviewed as a whole):
- **R19 (High, fixed in 0.6.6):** a phrase pulled from the shared database is quarantined only when its `modified_by` names another user (`shared/mirror.py`, `_pull_phrase`). The client writes that column itself (`modified_by = ?` in `shared/server.py`), so anyone who can write to the tables can put the victim's name on a phrase, and its `{#run}` or `{#http}` runs without approval. A team that shares one database login is never quarantined at all. Fixed by deciding on content, not on the name, like a cloud sync pull (D7). `Mirror.pull` takes `phrase_fingerprints()` before and after. Every phrase the pull creates, or whose fingerprint it changes, is quarantined as "synced", whoever wrote it. The client's own pushes come back with the revision it already holds, so they are skipped and stay approved. A change that leaves the fingerprint alone (a new description) keeps an approval. A conflict copy keeps the trust of the local edit it saves. Tests: a phrase forged under my own name, and a team sharing one login, are both quarantined; both tests fail on 0.6.5.
- **Review of #27, #28, #30, #32 and #33 (0.6.7).** Four reviewers probed one or two PRs each; every High and Medium finding was reproduced again on `main` (`3a7b092`) before it was fixed (the `{#setlevel}` leak in R42 was found by reading the code), and each has a test in `tests/test_redteam.py` that is the probe turned around.
- **R20 (High):** a sentence repeated in three mails became a phrase with its `{#run}` live and no quarantine, so it ran without asking (`ui/suggestions_dialog.py`). Fixed: a suggestion is plain text, `{` is written as `{{`. A **Clear list** button forgets all stored suggestions (R42).
- **R21 (High):** the signature manager's preview (shown when it opens) and **Export to Outlook** expanded signatures with privileged macros allowed, so an imported signature's `{#outputfile}` wrote any file, the Startup folder included. The editor's Preview had the same hole. Fixed: a preview never runs privileged macros; an export runs them only when the signature, its footers and quotes are all approved (`signature_trusted`).
- **R22 (High):** a phrase the shared database would not take was copied to "Not saved" as a new, trusted phrase, though its text could be another user's `{#run}` (a drag-move is enough to get there). Fixed: the copy keeps the quarantine (`_keep_outside`).
- **R23 (High, docs):** the setup SQL granted every user INSERT/UPDATE on `pf_acl`, so anyone with SSMS or psql could make themselves administrator. Fixed in `docs/shared-database.md`: users get SELECT only on `pf_acl`, administrators a separate grant; PostgreSQL no longer uses `ON ALL TABLES`. **Still open by design:** folder permissions are applied by PhraseForge, not by the database, so a user with direct SQL access can still change phrases in folders the client would refuse. Real protection (row-level security, or stored procedures with DENY on the tables) needs a decision; the docs say so and recommend a separate database per group for secret folders.
- **R24 (High):** `{#sound "\\host\x.wav"}` opened a network path with no approval (NTLM leak, as R14). Fixed: `sound` is in `FILE_READERS`.
- **R25 (High):** `-validate filepath|folder` called `os.path.isfile` on a phrase's UNC default as the form opened. Fixed: a network path is never checked and the field asks for a path on this PC.
- **R26 (High, older than these PRs):** `{#insert "1"}` ran phrase id 1 but checked the trust of the phrase described "1". Fixed: the phrase is looked up once and that phrase is used for its text, lock and quarantine.
- **R27 (Medium):** File > Open, backup restore and sync pull replaced settings the policy locked. Fixed: `restore_from` keeps this PC's values of locked settings.
- **R28 (Medium):** the policy path followed `%ProgramData%`, which any user can set for a process. Fixed: `SHGetKnownFolderPath(FOLDERID_ProgramData)`.
- **R29 (Medium):** signature file names were cut at the last dot (`with_suffix`), so "Sig.v1" and "Sig.v2" overwrote each other and Outlook's default could name a missing file. Fixed: whole names, made unique (" (2)"), device names such as CON prefixed with "_", the same names in the files and the registry.
- **R30 (Medium):** deleting a shared folder deleted subfolders the user could not change or read. Fixed: every subfolder is checked; one refusal rolls the delete back.
- **R31 (Medium):** history showed versions from a secret folder after a move, and from under a deleted restricted parent; `changes_since` sent deleted rows with their text. Fixed: each history row is checked where it was; rights look through deleted folders; deleted rows the user may not read carry only id and revision.
- **R32 (Medium):** an unapproved phrase's `{#settemp}` (or `{#set -scope global}`) left a value a trusted phrase's `{#run {#gettemp x}}` then ran. Fixed: writing variables that other phrases read is privileged ("change variables other phrases use"); local `{#set}` is not.
- **R33 (Medium):** a phrase's regex ((a+)+) could hang the expansion worker or the form on the UI thread. Fixed (`saferegex.py`): length limits, nested repeats refused, a time limit (1 s, forms 0.3 s) after which the pattern is refused for the session. Limitation: a thread that ran out of time cannot be stopped; it finishes in the background, and no other regex runs until it does.
- **R34 (Medium):** `{#numlist -level 50000000}` built 400 MB. Fixed: level ≤ 20, start ≤ 1,000,000, indent ≤ 16 characters, output ≤ 1 MB.
- **R35 (Medium):** unbalanced HTML in a mail parsed in quadratic time (61 s for 400 KB). Fixed: depth limit 256, only open tags are searched, bodies over 1 MB are skipped before parsing.
- **R36 (Medium):** Italian and Dutch reply headers and Gmail forwards were not cut, so received text counted as the user's own (the way to R20). Fixed: those headers and the forward separators in several languages.
- **R37 (Low):** PostgreSQL "encrypted" was `sslmode=require` (no certificate check); the old "SQL Server" ODBC driver dropped Encrypt silently. Fixed: `verify-full` (`require` only with "Trust the server certificate"); the old driver is refused while encryption is on.
- **R38 (Low):** a misspelt policy key, or a folder at the policy path, left the policy open. Fixed: both fail closed.
- **R39 (Low):** with `editing_disabled`, pointing sync at one's own folder replaced the phrases. Fixed: the settings that choose where sync and the shared database read from are locked while editing is disabled. Not covered: switching the Google account itself.
- **R40 (Low):** one message with an unknown charset or deep MIME nesting lost the whole mailbox's analysis. Fixed: that message is skipped and logged.
- **R41 (Low):** a checked form value was output with the spaces the check ignored, and Arabic-Indic digits passed "integer". Fixed: the checked (stripped) value is output; digit rules are ASCII. "letters" still accepts Arabic.
- **R42 (Low):** `{#setlevel}` inside an inserted phrase leaked to the caller; RTF export passed control characters; mail suggestions could not be cleared. Fixed. Noted, not changed: a `*` entry and a per-user "no access" on the same folder add up (documented); `groups()` failing during a full re-read drops group-shared copies, which come back quarantined on the next sync.
- **Review of #34, #35 and #36 (0.6.8).** Three reviewers probed one PR each; every High and Medium finding was reproduced again on `main` (`639f339`) before it was fixed, except R49 (its probe needs about 10 GB of memory), and all 24 new tests in `tests/test_redteam.py` fail on `639f339`.
- **R43 (High, older than #34):** `{#mouse}` was not in PRIVILEGED. An imported phrase could click the Start button or a dialog's "Run"/"Allow" at fixed or window-relative coordinates, type a command and press Enter, with no prompt, even from an automatic trigger (Win+R was blocked). Fixed: `mouse` is privileged ("click, move or scroll the mouse in other programs"); wheel deltas are capped at 100 notches.
- **R44 (High, older than #36):** `Store.restore_from` copies the other file's whole schema, so a trigger planted in a cloud copy (`AFTER INSERT ON phrase_quarantine ... DELETE`) turned quarantine off for good and travelled on with every push. Fixed: every trigger and view is dropped before anything writes, on every load and pull; SCHEMA recreates PhraseForge's own; `trusted_schema=OFF` for the store and for files read from elsewhere.
- **R45 (Medium):** a dynamic folder that arrived with a sync or an opened file was approved by OK in its dialog, which read the source at once. Fixed: an unapproved stored source shows a warning with its source, path and query and needs an explicit Yes.
- **R46 (Medium):** the ODBC connection string (with `PWD=`) was stored in the phrase file and synced out. Fixed: it is kept in the device setting `dynamic.conn.<folder id>`, sealed like the API keys (`SECRET_PREFIXES`); 0.6.7 configs are moved out on first use.
- **R47 (Medium):** a dynamic folder could be set up or changed while the policy disabled editing. Fixed: `set_config`, `approve_source` and `remove` refuse under the lock; a source set up before the lock keeps refreshing (IT can hand out phrases that way).
- **R48 (Medium):** the "single SELECT" check accepted `SELECT 1 EXEC xp_cmdshell ...` and `WITH ... DELETE` (T-SQL needs no `;`). Fixed: write, execute and remote-access keywords are refused outside quoted text; `;` inside quotes is allowed. The UI still needs a read-only database login for real protection.
- **R49 (Medium):** text, table and folder sources read whole files before any limit (100 MB used 9.6 GB). Fixed: files over 20 MB are refused, text is read up to MAX_ITEMS lines, folder files are read with a byte limit.
- **R50 (Medium):** passwords typed into browser, Qt or WPF fields while recording were saved in the phrase (only Win32 EDIT password fields are detected), as was text typed into PhraseForge's own windows; the keys stayed in memory after the recording. Fixed: keys typed into PhraseForge's windows are skipped, the keys are cleared after the recording, and the recording bar warns that browser password fields are not detected. Not done: a UI Automation password check.
- **R51 (Medium, #36 with #38):** the plain `.sync-base.db` (all phrases) stayed next to the file after "Encrypt phrase file". Fixed: plain base and pre-sync backup copies are wiped when encryption is turned on.
- **R52 (Low):** bad values in the other copy (an unknown trigger kind or output mode) made every sync raise. Fixed: a merge that fails falls back to asking.
- **R53 (Low):** a deep folder chain made the merge quadratic (9000 levels: 30 s). Fixed: one pass to cut loops, memoised depth (4.7 s).
- **R54 (Low):** a forged future `modified` stamp (9999) won the conflict and stayed on the merged phrase, so it beat every later edit made on this PC. Fixed: a remote stamp after now counts as now, so later local edits win again. The other copy can still win a single conflict by claiming a recent edit; whatever it brings is quarantined like any pulled change.
- **R55 (Low, also plain pulls):** a pull could clear a folder password or move a phrase out of a locked folder without quarantine. Fixed: this PC's folder passwords are kept; a locked folder in the chain is part of the phrase fingerprint, so leaving it quarantines the phrase.
- **R56 (Low):** the only backup before a pull went to the cloud the pull came from. Fixed: `<file>.before-sync.db` is written next to the phrase file before every pull. Not done: asking before a pull that removes many phrases.
- **R57 (Low):** `recorder.*` settings came from sync (a stop key "e", hour-long sleeps). Fixed: device settings; pauses are capped at 60 s.
- **R58 (Low):** wheel merging ran over escaped text, middle clicks replayed as left clicks, other programs' injected clicks were recorded. Fixed: wheels merge as events, middle clicks are not recorded, `LLMHF_INJECTED` clicks are skipped.
- **R59 (Low):** a dynamic approval survived its folder, so a new folder with the same id inherited it. Fixed: the folder uid is part of the approval; approvals of deleted folders are cleared.
- **R60 (Low):** symlinks in a folder source were followed outside it. Fixed: links and files resolving outside the folder are skipped.
- **R61 (Low):** a `}` in a file name broke out of `{#document "..."}` (quarantine still blocked it). Fixed: such names are skipped.
- **R62 (Low):** folder sources walked the whole tree every 30 s, and a briefly empty source deleted every phrase. Fixed: at most 20,000 entries are looked at; an empty read keeps the phrases and records an error. Not verified: the per-phrase change notifications during a large refresh.
- **Review of #38 (0.6.9).** Two reviewers probed the encryption code (crypto and format; plaintext leaks). Every finding was reproduced on `main` before it was fixed, on Linux with the DPAPI stand-in; real DPAPI on Windows was not exercised. Each fix has a red-team test in `tests/test_redteam.py` that fails on `a0e3c56`. #41 landed during the review and covers most of R66.
- **R63 (High):** `change_passphrase` only re-wrapped the same data key, so every older copy (a backup, `.before-sync.db`, a copy someone took) unlocked the current file with its old passphrase or its DPAPI entry, and "ask for the passphrase every time" was bypassed by any older file. Fixed: a passphrase or mode change creates a new data key; the sync base, the pre-sync copy and the local backups are re-encrypted under it (with the old key, or their own DPAPI entry). A copy that only opens with a passphrase this PC no longer knows is left and listed in the dialog.
- **R64 (High):** local backups made before encryption was turned on stayed plain (up to 7 daily copies) while the dialog said "Backups made on this PC are encrypted too". Fixed: `enable_encryption` encrypts every plain `phrases-*.db` in the backups folder and the chosen backup folder, and the plain sync base and pre-sync copy (encrypted in place instead of wiped, so the next merge can still use them).
- **R65 (Medium):** a crash between wiping the plain file and moving `<db>.enc` into place left only `<db>.enc`; the next start opened a new, empty phrase file. Fixed: the plain file is renamed, the encrypted one moved into place, then the plain one wiped; a failure restores the plain file and the open store; a start finds a leftover `.enc` or `.plain-old` and uses it.
- **R66 (Medium):** the Backup & Sync copies and the plain snapshots in `%TEMP%` held every phrase. #41 now encrypts the uploads when "Encrypt what is uploaded" is on. Fixed here: the Encryption dialog says whether uploads are encrypted; the plain temp copies (snapshot, pull, merge) and their `-wal`/`-shm` files are overwritten before deletion while the phrase file is encrypted. Not changed: they are plain while they exist (a few seconds).
- **R67 (Medium):** sorts and `VACUUM` on the decrypted in-memory database spilled plain pages to `etilqs_*` files in `%TEMP%`. Fixed: `PRAGMA temp_store = MEMORY` on every in-memory database, and no `VACUUM` when the file is encrypted.
- **R68 (Low):** a malformed header (a list, a missing salt) crashed the start with AttributeError or KeyError, and scrypt's `p` came unbounded from the header. Fixed: every parse error is a VaultError; only `r = 8`, `p = 1` and 2^14 ≤ N ≤ 2^17 are accepted; a damaged file at the passphrase prompt shows a message.
- **R69 (Low):** "Change" with empty fields silently removed the recovery passphrase; changing or turning off encryption never asked for the current passphrase. Fixed: the current passphrase is required; empty fields keep it; removing it needs the "Remove the passphrase" box and a confirmation.
- **R70 (Low):** an older encrypted file with a DPAPI entry put back in place undid "ask every start" silently, and a plain file put back was used without a word. Fixed: a marker next to the file (`<name>.encrypted`) records encryption and ask mode; a plain file in its place, or an older one that opened without the passphrase, is reported at start, and the DPAPI entry is dropped from the latter at the next save. Not covered: someone who can also delete the marker.
- **R71 (Low):** File > Save As "Database copy" wrote every phrase in plain text. Fixed: for an encrypted file it asks, and Yes keeps the copy encrypted.
- **R72 (Low):** an encrypted backup made under an earlier key (before a passphrase change, or encryption off and on) could not be restored. Fixed: `restore_from` falls back to the copy's own DPAPI entry, then asks for its passphrase.
- **R73 (Low):** learned words, imported images, the file search history and the log stay plain. Fixed: the log no longer names skipped phrases or locked folders; the others are listed in the Encryption dialog and the README.
- **R74 (Low):** passphrases were not Unicode-normalised (an Arabic or accented passphrase typed with combining marks did not match) and scrypt used N = 2^15. Fixed: NFC (files from 0.6.8 still open with the raw form) and N = 2^17 for new wraps. The sync hash key of #41 keeps 2^15 so PCs on different versions agree.
- **R75 (Low):** a save that kept failing was only logged; `repr(Key)` printed the data key; a plain `.sync-base.part` left by a crash was not wiped; `pf-pull-*` `-wal`/`-shm` files were left in `%TEMP%`. Fixed: a failed save shows a tray message (once) and a message at exit; the key is hidden from `repr`; both leftovers are removed.
- **Review of #39, #41, #42, #44–#51 (0.6.11).** Five reviewers probed two or three PRs each on `af203ab`; every finding was reproduced on that commit before it was fixed, on Linux (DPAPI stand-in, stubbed Windows calls). Each fix has a red-team test in `tests/test_redteam.py` that fails on `af203ab`. R82 and the SAPI part of R94 are code reading only.
- **R76 (High, #45):** the library root was remembered by folder row id; row ids are reused, so after a pull a folder from the other PC could get the root's old id. It was then treated as the library: read-only, left out of pushes (the other PC lost it), renamed, and deleted on unmount. Fixed: the root's uid is stored and must match; otherwise the root is rebuilt.
- **R77 (Medium, #45, #51):** mounting a library (Libraries dialog, `--open`) added phrases while the policy disabled editing (the R39 class). Fixed: mounting and switching a library to read-write are refused under `editing_disabled`, and `library.list` is a locked sync-source setting.
- **R78 (High, #39):** a phrase restored from the trash got its old approval back although a pull had meanwhile given its folder a program output target or `{#run}` folder text. Fixed by R79's folder quarantine, and the trash snapshot keeps the phrase's fingerprint: a restore whose fingerprint changed is quarantined as "restored".
- **R79 (High, #42, also older for output targets):** folder text before/after and folder output targets were checked only through the fingerprints of phrases already in the folder, so a synced or imported (empty) folder with `{#run}` folder text ran it, unapproved and from automatic triggers, in every phrase created in or moved into it later. Fixed: `folder_quarantine` (by folder uid) records folders whose risky fields arrive by import, pull, merge or library; `quarantine_origin` follows the folder chain; approving "always" or saving the folder's properties releases it.
- **R80 (Medium, #46):** "Compare with backup" wrote a plain copy of an encrypted phrase file to `%TEMP%`. Fixed: the copy is encrypted (wiped if plain).
- **R81 (Medium/Low, #51):** a launch carrying a `phraseforge://` link also honoured other switches in the same command line (`--exec` without confirmation, `--import`, `--home` pointing the data folder at another phrase file) if a quote in the link broke the `"%1"` quoting (not verified which launchers pass one). Fixed: a launch with a link uses only the link. Also: the link question defaults to No, links name phrases by uid only, disabled phrases are not run by `--exec` or links, and a forwarded link is encoded again (it was decoded twice).
- **R82 (Medium, #44, code reading):** the elevated copy started by "restart as administrator" lost `--home`/`--portable` and accepted `--import`/`--open`/`--exec` from any program of the user. Fixed: the data folder is passed on; an elevated copy refuses those from later launches; the notice says programs started by phrases run elevated too. Not changed: automatic triggers run elevated.
- **R83 (Medium, #39, older too):** comments, phrase text, clipboard entries and notes were shown as rich-text tooltips, and Qt loaded `<img src>` files (on Windows a UNC path sends the network login). Fixed: `ui/safetext.plain_tip` in all those places.
- **R84 (Medium, #41):** an older encrypted sync copy (or a backup) put back as the sync copy with a higher `rev` was pulled by every PC. Fixed: the copy's name, kind and revision are in the authenticated vault header; a mismatched name or a revision older than this PC's last sync is refused ("take the cloud copy" still can). Not covered: copies uploaded by 0.6.10 or older.
- **R85 (Medium, older):** triggers were not part of the fingerprint, so a sync could add a schedule (or autotext, focus, clipboard trigger) to an approved `{#run}` phrase. Fixed: automatic triggers are in the fingerprint.
- **R86 (Medium, older):** regex autotext and clipboard-regex triggers used plain `re`; `(a+)+b` took 1.7 s per keystroke at 24 characters. Fixed: `saferegex.compile_checked`, clipboard text capped.
- **R87 (Medium/Low, #49):** `{#decstr}` used `(\d+)(\D*)$`, quadratic (25 s on 40,000 digits) on the expansion thread. Fixed: a linear scan.
- **R88 (Low, #41, not changed):** the content-hash property uses scrypt N=2^15 with a fixed salt, and turning encryption on shows the old plain hash next to the keyed one, so passphrases can be guessed offline about 5 times faster than against the file. Kept: changing it needs every PC on the new version at once. Use a long passphrase.
- **R89 (Low, #41):** "Upload this PC's phrases" and cloud backups on a PC with encryption off replaced or joined the encrypted copy in plain text. Fixed: refused while the cloud copy is encrypted.
- **R90 (Low, #41):** the content-hash key used the raw passphrase while the vault uses NFC, so PCs never agreed on "unchanged". Fixed: NFC.
- **R91 (Low, #47):** delimiter texts were rebuilt per trigger per keystroke; a 1.2 MB imported delimiter took 3.5 s per keystroke. Fixed: cached, capped at 200 characters and 12 parts.
- **R92 (Low, #48):** File > Scheduled tasks listed phrases from password-locked folders. Fixed.
- **R93 (Low, #44):** a late hook reply logged the key code (one key per stall); clipboard triggers fired while the PC was locked. Fixed: no key in the log; clipboard triggers wait for an active session.
- **R94 (Low, #49, #50):** one PhraseExpress row with ~400 nested macros stopped the whole import (RecursionError); `{#speak}` let SAPI read text as XML. Fixed: the row is imported untranslated with a note; SVSFIsNotXML.
- **R95 (Low, #39):** `trash.days` synced, so a pulled `trash.days=1` emptied this PC's trash. Fixed: `trash.` is a device prefix; days are capped at 3650.
- **R96 (Low, #45):** an encrypted library was mirrored into a plain phrase file; locked library folders were unlocked in the mirror; a new language version alone never reached the mirror; the approval dialog said "came from cloud sync" for library phrases. Fixed: mounting an encrypted library needs an encrypted phrase file; `password_hash` is mirrored; versions are compared; the dialog names libraries, restores and the shared database.
- **Review of #52 and #53 (0.6.13).** Three reviewers (install/manifest, runtime/host, engines) probed `708bf36`; every finding was reproduced before it was fixed. Each fix has a red-team test in `tests/test_redteam.py` that fails on `743798d`. Windows-only parts (job object, NTFS names, DPAPI) are code reading only.
- **R97 (Medium, #52):** `[permissions]` is only a declaration (no sandbox, network proxy or restricted token yet), but the trust gate and the consent text relied on it: a plugin declaring nothing was "unprivileged", so quarantined, imported and synced phrases, previews and automatic triggers ran it, and the dialog said it may do "nothing beyond answering PhraseForge". Probed: such a plugin wrote files and opened sockets; run by the frozen EXE it could open the phrase file and unseal every secret. Fixed: every plugin macro needs an approved phrase; the consent text says a plugin runs with the user's rights; docs/plugins.md and FR-PLG-04 corrected. Not fixed: isolation itself (FR-PLG-05).
- **R98 (Medium, #53):** `{#ai -provider plugin:<id>}` and `{#translate}` reached a plugin engine from unapproved phrases (clipboard, selection, images, local image files, the plugin's key), also with `macros_disabled = ["<id>.*"]`. Fixed: both are privileged when the engine they really use (written or chosen in Settings) is a plugin, statically (the whole call, nested macros included) and at run time; the administrator's `<id>.*` also blocks the plugin as an engine.
- **R99 (Low, #52):** the package was read again after the consent dialog, so a share could swap it. Fixed: it is copied once to a private folder; that copy is shown and installed, and a changed manifest is refused.
- **R100 (Low, #52):** the plugin name was rendered as rich text in the consent dialog (`<!--` hid the real list). Fixed: plain-text dialog, No by default; control and direction characters removed from names.
- **R101 (Low, #52):** an update with the same id replaced the code with no prompt (any author) and switched a plugin the user had turned off back on. Fixed: an update always asks, names a changed name; the enabled state is kept.
- **R102 (Low, #52):** a policy with `settings_locked` / `editing_disabled` but no `plugins_allowed` still allowed any plugin. Fixed: such a PC runs no plugins; the allow-list is still by id (signatures open).
- **R103 (Low, #52):** one non-UTF-8 `plugin.toml` made `installed()` raise and broke the trust check and the Plugins window; corrupt zips raised uncaught. Fixed: every read error is a ManifestError, each folder is read on its own.
- **R104 (Low, #52, Windows effects by code reading):** zip names were not checked against Windows rules (`x:stream`, trailing dots, `PLUGIN.TOML` next to `plugin.toml`, `CON`), nor ids and entries. Fixed.
- **R105 (Low, #52, not reachable):** `uninstall('..')` passed the parent check. Fixed: valid ids only, resolved paths.
- **R106 (Low, #52):** `--run-plugin <path>` ran any Python file before the policy was read (an application allow-list bypass for the signed EXE). Fixed: only the entry script of a plugin folder whose manifest matches, started by PhraseForge, and allowed by the policy.
- **R107 (Low, #52):** a removed plugin's secrets stayed; a new package with the same id received them. Fixed: `remove()` deletes them.
- **R108 (Low, #52):** unbounded reads of plugin output (memory grew with a plugin that never wrote a newline); a deeply nested JSON reply killed the reader thread. Fixed: 16 MB per line (the plugin is stopped beyond), 4 KB per stderr line, every parse error caught.
- **R109 (Low, #52):** timeouts added up (three hanging calls 24 s, more in `{#loop}`), callers queued without limit. Fixed: a plugin that timed out is not called again in the same phrase; a busy plugin times out the waiting call; previews no longer call plugins (R97).
- **R110 (Low, #52, code reading):** the job object's results were not checked and its handle leaked per restart. Fixed: a plugin is not run when it cannot be put in its job; the handle is closed. Not changed: the process is assigned after it starts (no suspended start).
- **R111 (Low, #53):** `ai.provider` / `translation.provider` sync, so a pull could route all AI and translation text to whatever plugin has that id here. Fixed: an incoming `plugin:` value never replaces this PC's choice.
- **R112 (Low, #53):** the consent for an AI or translation plugin did not say it receives the text and images sent to it, nor did an update that adds that kind. Fixed.
- **R113 (Low, #55):** `{#ai -provider ollama -image file:<any file>}` sent any local file (up to 20 MB) to Ollama. Fixed: only images, for every engine.
- **Review of #55 (0.6.14).** The whole of `708bf36`'s AI changes were read by the lead reviewer, without separate reviewers (R113 above was the part already covered with #53); every finding was reproduced on 0.6.13 before it was fixed, each with a red-team test that fails there. The network-share check for `-image file:` held in every form tried (`{#clipboard}`, variables, `%VAR%`), because the run-time check sees evaluated values.
- **R114 (Medium, #55):** `{#aiimage}` was not privileged, so an imported or synced phrase nobody approved made pictures billed to the user's API key without asking; `{#loop 1000}{#aiimage}{#endloop}` made 1000 in one expansion. Fixed: it needs an approved phrase, and any phrase makes at most 4 images.
- **R115 (Low, #55):** the 20 MB limit was per image and the number of `-image` parts was unlimited (40 parts held 200 MB for one `{#ai}`). Fixed: at most 8 images and 20 MB together.
- **R116 (Low, #55):** a progress line with a non-number `completed` or a bare JSON value ended the Ollama download thread with an uncaught error and left the progress dialog open forever. Fixed: counts are read safely and any failure ends the dialog.
- **R117 (Low, #55):** a server at the Ollama address that did not answer Ollama's JSON raised an uncaught error from "Download Ollama model...". Fixed: reported as an AIError. Also: the approval scan now reads `-Image` in any case (the run-time check already blocked it, but nobody was asked).
- **Review of #59, #61 and #62 (0.6.14).** Three reviewers (DeepL glossaries; network filter and signatures; `$/progress`) probed `d07095c`; every finding was reproduced again before it was fixed, each with a red-team test in `tests/test_redteam.py` that fails on `d07095c`.
- **R118 (Medium, #61):** `plugins_require_signature` was checked only when a plugin was installed: one installed before the policy, or whose files were changed afterwards, kept running. Also, `.pyc` files are outside the signature and Python ran a copy planted in the plugin's `__pycache__` instead of the signed source. Fixed: under the policy a plugin runs only while its installed files verify against a trusted key (cached by file times); Python plugins run with a private bytecode cache (`-X pycache_prefix`, `sys.pycache_prefix` in the EXE); a stray `.pyc` outside `__pycache__` fails the check.
- **R119 (Low, #61):** a deeply nested `plugin.sig` raised RecursionError out of the install dialog. Fixed: over 4 KB or unparsable is "invalid".
- **R120 (Low, #61):** any program on the PC could use a plugin's proxy (tunnel to its hosts, write "blocked" lines into its errors, take its 16 connections); a peer that stopped reading held a slot forever. Fixed: a random per-plugin password in the proxy URL (407 without it, nothing logged); the slot is taken only after the password; sends time out after 30 s.
- **R121 (Info, #61):** `network = ["127.0.0.1"]`, `localhost` and `169.254.169.254` were accepted, and an allowed name resolving inside was tunnelled. Fixed: IP literals and local names are refused in the manifest; the proxy connects only to a global address of the name.
- **R122 (Info, #61):** an older signed version installed over a newer one. Fixed under `plugins_require_signature`.
- **R123 (Low, #62):** `$/progress` restarted the timeout of calls that never asked to stream (a 5 s plugin macro could block an expansion for 50 s and never reached the R109 fail-fast); empty pieces restarted it too. Fixed: ignored unless the caller streams; empty pieces are no progress.
- **R124 (Low, #62):** the Prompt Optimizer's live line was a rich-text label, so streamed `<img src="file://...">` loaded local (on Windows, UNC) images. Fixed: plain text, control and direction characters removed.
- **R125 (Low, #62):** the 4 MB limit counted characters: 4 million one-character pieces cost 290 MB, and each 50 ms tick joined them all (180 ms). Fixed: bytes plus 64 per piece count; the window keeps only the last 200 characters.
- **R126 (Low, #59):** syncing glossary `A` deleted the server copy of `A #b` (prefix match), so using both deleted and re-created glossaries on every call; an unapproved `{#loop 200}` made 800 DeepL glossary requests. Fixed: exact name match; glossary ids are cached for 10 minutes per key (a translation that fails with a cached id refreshes it once).
- **R127 (Low, #59):** a copy DeepL had not finished preparing was deleted and uploaded again on each translation. Fixed: never deleted; the translation goes ahead without it meanwhile.
- **R128 (Low, #59):** a non-JSON or odd DeepL answer (a proxy page, `"glossaries": null`) raised a non-AIError that failed the whole translation. Fixed: reported as AIError, so an automatic glossary is skipped.
- **R129 (Low, #59):** a glossary DeepL refused (HTTP 400/413/422) was uploaded again before every translation. Fixed: not sent again for 10 minutes, and logged.

Still open: Linux single-instance socket squatting by the same user; with a proxy, `{#http}` relies on the name check only.

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
| U-02 | What PE's exports contain (triggers? macros? levels? folders?). v4: for the per-phrase text export the answer is plain or formatted text only (vendor manual); still open for any CSV/XML export, see U-15 | FR-IMP-01 fidelity | The user exports a small synthetic library from PE in each available format and adds it to `tests/fixtures/pe_exports/` |
| U-03 | Exact plugin ABI calling convention and string types | Only relevant if D2-C were chosen (it is not) | None needed |
| U-04 | Exact semantics of macros without visible parameter docs (`autocase, decstr, explode, parse, headfootfilled, qstext, check, numlist` styles…) | FR-MAC-02/03 compat fidelity | PE's public online macro documentation (allowed: public docs) + behaviour capture |
| U-05 | Whether `config.xml` secrets (`*APIKey`, AzureAD tokens) are obfuscated or plaintext | Importing settings, and a security note for users migrating | Inspect the user's own file manually; never import secrets automatically |
| U-06 | Default timing values (FocusDelay, SimKeyDelay, RestoreClbDelay, pause timing, fast-typing threshold) | Behavioural parity defaults | Capture plan 7.6 step 1, or read the user's `config.xml` values for their own machine |
| U-07 | Transport between `pexmsol.dll` and the main window (WM_COPYDATA?) | Only relevant for D6-B (not chosen) | None needed |
| U-08 | Availability of `sqlcipher3` and Hunspell bindings for Python 3.14 on Windows | D4, FR-EDT-01 | **Hunspell part resolved (v6):** 0.6.4 uses `spylls` (pure Python, no binary wheel needed); the frozen build bundles it (`collect_submodules("spylls")` in `phraseforge.spec`). **Not yet proven in the EXE:** `--self-test` imports PhraseForge's modules, but `spell.py` imports `spylls` only when a dictionary loads, so no CI step loads a dictionary in the frozen build. Add a self-test check that loads a tiny bundled `.aff/.dic` pair. `sqlcipher3` still open: spike `pip download` for cp314 win_amd64 |
| U-09 | PhraseExpress EULA terms on analysis/interoperability | Legal posture | The user reads the EULA shipped with the installer; counsel review before release |
| U-10 | Whether the PE "hub" sync uses field-level or row-level merge | D5 design reference only | Not required; PF defines its own semantics |
| U-11 | `words.pal` learning model semantics (connections/backconnections/ends) | Learner parity (E5) | Treat as inspiration only; PF keeps its own learner |
| U-12 | `LowLevelHooksTimeout` effective default on the target Windows builds | D1 risk sizing | Read `HKCU\Control Panel\Desktop\LowLevelHooksTimeout` on test machines; test with an induced stall |
| U-13 | Whether PE's "Window" trigger matches by title, class, exe, or a mix | FR parity of B11 | Capture 7.6 step 3 |
| U-14 | Whether the "SQL" macro dialog maps to a `{#sql}` macro (only the dialog form was observed) | Macro compat | Public docs |
| U-15 | **(v4)** Which export formats PE 18 actually offers. The binary contains exporter names (HTML, CSV, XML, Word, Excel, Android, TextExpander) [C-EXE], but the vendor manual documents only per-phrase text export and phrase-file export, and the user's install shows only those. Possible reasons: the exporters are edition-specific, hidden or retired. | Whether FR-IMP-01 can ever carry triggers and folders from PE without the encrypted file | The user checks Export in their PE edition with a folder selected and a phrase selected and sends a screenshot of the choices; no binary analysis needed |

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
