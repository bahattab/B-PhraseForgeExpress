# B-PhraseForgeExpress (PhraseForge)

An original text expander for Windows with the feature set of PhraseExpress,
built-in screen OCR and sticky notes, and import of TextExpander snippet exports.
PhraseForge does not start any other program for these features.
See [SPEC.md](SPEC.md) for the design and [macro reference](phraseforge/macros/README.md).

## Install (Windows)

Download from the repository's **Releases** page (or the latest *Windows build* run under
**Actions > Artifacts**):

- `B-PhraseForgeExpress-Setup-<version>.exe`: installer. No admin rights needed; adds Start menu and
  optional desktop shortcut and "start with Windows". Uninstall from Windows Settings > Apps.
  Your phrases in `%APPDATA%\PhraseForge` are kept when you uninstall.
- `B-PhraseForgeExpress-portable.exe`: single file, no install. Starts a little slower.
  It is **portable**: all its data (phrases, settings, backups, dictionaries, logs) goes into a
  `PhraseForgeData` folder next to the EXE, so it can run from a USB stick, and it writes
  nothing to `%APPDATA%` or the registry. For that reason "Start with Windows" and "Export
  signatures to Outlook" are switched off there. Any copy becomes portable with a file
  `portable.ini` next to it or the `--portable` switch; `--home <folder>` uses any data folder.
  On another PC, keys saved under Windows' protection (AI keys, an encrypted phrase file
  without a passphrase) cannot be opened: give an encrypted portable phrase file a passphrase.
- `B-PhraseForgeExpress-<version>-win64.zip`: the same program as a folder.

Windows SmartScreen may warn because the files are not code-signed: click
**More info > Run anyway**.

## Build the EXE and installer yourself

GitHub Actions builds everything on each push (`.github/workflows/windows-build.yml`);
pushing a tag such as `v0.6.6` also publishes a GitHub Release. To build locally on Windows
(needs Python 3.12 and [Inno Setup 6](https://jrsoftware.org/isinfo.php)):

```
python -m pip install -r requirements-build.txt
python packaging\make_icon.py
rem native keyboard hook, from an "x64 Native Tools Command Prompt for VS"
mkdir native\pfhook\build
cl /nologo /O2 /W4 /LD native\pfhook\pfhook.c /Fonative\pfhook\build\ /Fephraseforge\platform\pfhook.dll /link user32.lib
pyinstaller --noconfirm packaging\phraseforge.spec          # dist\B-PhraseForgeExpress\B-PhraseForgeExpress.exe
set PF_ONEFILE=1 && pyinstaller --noconfirm packaging\phraseforge.spec   # dist\B-PhraseForgeExpress-portable.exe
"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" /DAppVersion=0.6.6 packaging\installer.iss
dist\B-PhraseForgeExpress\B-PhraseForgeExpress.exe --self-test               # writes selftest.txt in the data folder
```

## Run from source

The Python environment lives outside this Google Drive folder, at
`C:\venvs\phraseforge`, so Drive doesn't sync thousands of package files and
Qt's DLLs stay under Windows' path-length limit. Recreate it with:

```
python -m venv C:\venvs\phraseforge
C:\venvs\phraseforge\Scripts\python -m pip install -r requirements-build.txt
```

Easiest: double-click `PhraseForge.bat` (works from anywhere). Or run from this folder:

```
C:\venvs\phraseforge\Scripts\python -m phraseforge             # main window + tray icon
C:\venvs\phraseforge\Scripts\python -m phraseforge --minimized # tray only
C:\venvs\phraseforge\Scripts\python -m pytest -p no:cacheprovider  # full test suite
```

### Keyboard hook

Builds from GitHub include `pfhook.dll`, a small native keyboard hook
([native/pfhook/pfhook.c](native/pfhook/pfhook.c)). Keys never wait on Python for more
than 40 ms: if PhraseForge is busy, keys pass straight to the program (hotkeys are still
caught), so typing elsewhere never lags and Windows does not remove the hook. The macro
recorder's mouse hook lives in the same DLL, so recording never makes the mouse lag. Without the
DLL (running from source without building it) PhraseForge uses its older Python hook.
To force that one, set `PHRASEFORGE_HOOK=python` or the setting `input.native_hook` to `0`.

PhraseForge also:

- stops listening while the PC is locked or a Remote Desktop session is disconnected,
  and starts again when you are back;
- shows a message when a program that runs as administrator comes to the front: Windows
  does not let a normal program read or type keys there. Click the message to restart
  PhraseForge as administrator. Phrases are not half-typed into such a window;
- holds back the keys you press while it types a phrase and types them right after the
  phrase, so they never land in the middle of it. Settings > Text Insertion can drop them
  instead, or let them through; holding back stops by itself after 10 seconds;
- opens the phrase menu and suggestion tips at the text caret in more programs: besides
  the classic Windows caret it asks Windows accessibility (MSAA, UI Automation), so
  browsers, Electron apps such as VS Code, Office and WPF programs work too. Where no
  caret can be found the menu opens where Settings > Popup menu says (mouse by default).

## Screen OCR and sticky notes

- **Screen OCR** (Ctrl+Alt+O): draw a box and the text is copied. Optional hotkeys in
  Settings > Screen OCR read the text line under the mouse pointer, from the pointer to the
  end of the line, or the text block around it, without drawing a box. To read Arabic, add
  the Arabic language once in Windows Settings > Time & language > Language & region.
- **Sticky notes**: Tools > New sticky note (or the tray menu). Notes are small desktop
  windows with seven colours, bold/italic/underline/strikethrough/bullets and "always on
  top"; they are saved as you type and reopen where they were. Tools > Sticky Notes lists,
  searches and deletes notes, and can import your Microsoft Sticky Notes file once.

## Prompt Tower (AI context from project files)

Tools > AI > **Prompt Tower** builds one prompt from many files of a project for ChatGPT, Claude,
Gemini or coding agents. Tick files in a folder tree (`.gitignore`, `.towerignore` and folders
like `node_modules` are skipped), add text before and after, and choose XML, Markdown or your own
templates with a project tree. It shows a token estimate. You can copy the prompt, open it in a chat
site, save it as a phrase, or save the whole set and insert it anywhere with
`{#prompttower "name"}`. It is a clean-room rebuild of the workflow of the
[Prompt Tower](https://github.com/backnotprop/prompt-tower) VS Code extension; see
[docs/PROMPT_TOWER_SPEC.md](docs/PROMPT_TOWER_SPEC.md).

## Prompt Optimizer, Boost prompt and Mistral OCR

- **Prompt Optimizer** (Tools > AI): a chat that asks clarifying questions and ends with an
  "Optimized Prompt:" you copy; templates with `{{fields}}`, your own templates, and project context
  (languages and frameworks). Rebuilt from [AI Prompt Optimizer](https://github.com/mhemdan/ai-prompt-optimizer).
- **Boost prompt**: select a prompt in any program and press Ctrl+Alt+B to replace it with a detailed,
  structured prompt; also a button in the phrase editor and `{#promptboost text}`. Uses the instruction of
  [PromptBoost](https://github.com/chrisdias/vscode-promptboost).
- **Mistral OCR** (Tools > OCR PDF / image): PDF or image to Markdown with tables and images, saved in a
  folder named after the file; optional cloud engine for screen OCR. Like
  [Mistral OCR Unofficial](https://github.com/sldyns/mistral-ocr-unofficial), without the separate script.
  The file is uploaded to Mistral.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Default hotkeys

| Hotkey | Action |
|---|---|
| Ctrl+Alt+Space | Phrase popup / search |
| Ctrl+Alt+V | Clipboard history |
| Ctrl+Alt+O | OCR a screen region to the clipboard (built-in Windows OCR) |
| Ctrl+Alt+F | Search files: find and open files, folders and programs by name |

Data lives in `%APPDATA%\PhraseForge` (override with `PHRASEFORGE_HOME`).

## Search files

Ctrl+Alt+F (or tray > Search files) opens a launcher: type parts of a file, folder or
program name in any order (`rep 2026 pdf`). Enter opens it, Ctrl+Enter opens its folder,
Shift+Enter types the full path into the program you were in, Ctrl+C copies the path.
Programs and items you open often come first. Pressing Ctrl twice also opens it, and
web keywords work too: `g weather`, `yt`, `wiki`, `maps` (add your own in Settings). Settings > Search files chooses the folders
(default: Start menu, Desktop, Documents, Downloads) and how often the index is rebuilt.

## Google Drive backup & sync

Settings > Phrase File/Database > **Backup & Sync**. Choose one:

- **Google Drive (sign in with Google):** your browser opens Google's login page;
  PhraseForge never sees your password and can only see files it created
  (`drive.file` scope). The sign-in token is encrypted with your Windows account (DPAPI).
- **A folder:** any folder, e.g. `G:\My Drive\PhraseForge` from Google Drive for Desktop.
  No login needed.

Click **Sign in with Google**. If the program was built with a built-in Google client
(see below), the browser opens right away. Otherwise PhraseForge opens a setup window the
first time (free, about 5 minutes; Google requires every app to have its own client ID):

1. Open https://console.cloud.google.com and create a project.
2. APIs & Services > Library: enable **Google Drive API** (the setup window has a button for it).
3. Google Auth Platform (OAuth consent screen): User type **External**. Add your Google address
   under Audience > Test users, or click **Publish app** (in testing mode Google signs you out
   after 7 days).
4. Clients (Credentials) > Create client > Application type **Desktop app**.
5. Paste the **Client ID** and **Client secret** into the setup window (or choose the downloaded JSON).
6. Approve in the browser.

**Built-in client for everyone (maintainers):** create the Desktop app client once as above,
publish the app, then add the repository secrets `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`
(Settings > Secrets and variables > Actions). The release build writes them into the program
(step "Built-in Google sign-in client" in `.github/workflows/windows-build.yml`) and users only click **Sign in with Google**. Google does not
treat a Desktop app client secret as confidential.

Sync runs at start, every N minutes and on exit. If phrases changed on two PCs, both sets of
changes are merged: new phrases from both PCs are kept, and edits to different fields of one
phrase are combined. When both PCs changed the same text, the newer edit wins and the other
one stays in the phrase's history. A deleted phrase stays deleted unless the other PC edited
it. This PC's copy is saved as a cloud backup before every merge. Turn off "merge both sets of
changes" to be asked which copy to keep instead (also used for the very first sync of a PC
that already has phrases, and for a cloud copy from a version before 0.7).
Clipboard history and PC-specific settings are never uploaded.

**End-to-end encryption:** tick "Encrypt what is uploaded" and enter a sync passphrase (the same
on every PC). The sync copy and the cloud backups are then encrypted (AES-256-GCM) before they
leave the PC, so Google Drive or the sync folder only holds scrambled data. The passphrase is
stored on each PC protected by Windows; nobody can recover it. While encryption is on, a cloud
copy that is not encrypted is never taken in: use "Upload this PC's phrases" to replace it.

## Encrypting the phrase file

Settings > Phrase File/Database > **Encryption...** encrypts the phrase file on disk (AES-256-GCM).
PhraseForge then reads the phrases into memory, works there, and writes the file back encrypted a
moment after every change. The key is random and protected by Windows for your account, so the
file opens without a question on this PC. A passphrase is optional: it opens the file on another
PC or after Windows was reinstalled. Or choose "Ask for the passphrase every time PhraseForge
starts": then only the passphrase opens it. Write it down; nobody can recover it.
Local backups are encrypted the same way, including those made before encryption was turned on.
Changing the passphrase, or switching to "ask every time", gives the file a new key and
re-encrypts the local backups with it, so an old copy no longer opens the current file.
The Backup & Sync copies are encrypted only with "Encrypt what is uploaded" (Settings > Backup &
Sync). Not covered: the learned words, imported images (the `assets` folder), the file search
history and the log. "Save As" database copies ask whether to stay encrypted.

## Arabic

Settings > Display > User Interface Language > Arabic turns the whole interface right to left.
The Arabic user guide is [docs/USER_GUIDE.ar.md](docs/USER_GUIDE.ar.md) (also under Help in the program).
Phrases can hold one version per language; dates can be Hijri with Arabic digits.

## Maintenance

File > **Maintenance** has three tabs:
- **Duplicates:** phrases with the same text in any folder, and abbreviations used by more than
  one phrase. Select the extra ones and move them to the Trash.
- **Compare with backup:** what was added, removed or changed since a backup (or between two
  backup files, encrypted ones included). "Bring back the backup's version" adds the old phrase
  again next to the current one (it needs approval again before privileged macros run).
- **Database:** check the phrase file for damage, and compact it.

## Phrase libraries

Phrases > **Libraries** mounts other PhraseForge phrase files next to your own, for example a
team file on a shared folder. Each library is its own top-level folder; its abbreviations,
hotkeys and phrase menu work like your own.
- **Read only:** use the phrases; edits inside it are refused with a message.
- **Read and write:** your edits are saved to the library file at once; other PCs pick them up
  within about 30 seconds (and changes made by others reach you the same way).
- When two places have the same abbreviation, your own phrase wins, then the library higher
  in the list.
- Phrases a library adds or changes need your approval before they run programs or other
  privileged macros. Libraries are not part of your cloud sync: each PC mounts its own.

## Trash, templates and comments

- **Trash:** Delete moves a phrase or folder (with everything in it) to Phrases > **Trash**.
  Restore puts it back in its folder, with its abbreviations, tags, language versions, comments,
  history and approval state. Entries older than 30 days are removed at start
  (setting `trash.days`, 0 = keep). The trash stays on this PC and is not synced.
- **Template folders:** right-click a folder > **Template folder**. Its phrases are never expanded
  and are not in the phrase menu. New > **Phrase from template...** copies one (text, format,
  tags, notes and language versions; not its abbreviation).
- **Phrase links:** right-click a phrase > **Create link to this phrase**. The link (its own
  folder, abbreviation and hotkey) always inserts the current text of the original.
- **Folder text:** folder Properties > **Text before / after each phrase** is added to every
  phrase in the folder and its subfolders when it is inserted (macros work; outer folders go
  around inner ones). Changing it sends the folder's synced or imported phrases back for approval.
- **Sort by two fields:** folder menu > Bulk edit > **Sort by two fields...**
- **Comments:** right-click a phrase > **Comments...** to leave notes for yourself or your team
  (author, time, resolved). They sync and merge between PCs.

## Import and export

- Phrases > Import: PhraseForge JSON, CSV, folder of .txt files; PhraseExpress CSV export;
  TextExpander CSV / `.textexpander`; macOS Text Replacements `.plist`; OneNote pages.
  PhraseExpress `.pexdb` files are encrypted: export a CSV from PhraseExpress instead.
- Phrases > Export: JSON, CSV, text files, Word (.docx) and PDF documents (Arabic right to left),
  and files for PhraseExpress, TextExpander and macOS.

## License

MIT, see [LICENSE](LICENSE). Third-party parts keep their own licenses: PySide6 (LGPL),
QtAwesome icon fonts (MIT / SIL OFL), Google API client libraries (Apache 2.0).
Screen OCR uses the OCR engine that ships with Windows 10/11, called in-process through the
WinRT Python bindings (MIT); no Capture2Text code is used. PhraseExpress and TextExpander are trademarks of their owners;
PhraseForge is an independent project and contains none of their code.
