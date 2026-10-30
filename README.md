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
- `B-PhraseForgeExpress-<version>-win64.zip`: the same program as a folder.

Windows SmartScreen may warn because the files are not code-signed: click
**More info > Run anyway**.

## Build the EXE and installer yourself

GitHub Actions builds everything on each push (`.github/workflows/windows-build.yml`);
pushing a tag such as `v0.5.7` also publishes a GitHub Release. To build locally on Windows
(needs Python 3.12 and [Inno Setup 6](https://jrsoftware.org/isinfo.php)):

```
python -m pip install -r requirements-build.txt
python packaging\make_icon.py
pyinstaller --noconfirm packaging\phraseforge.spec          # dist\B-PhraseForgeExpress\B-PhraseForgeExpress.exe
set PF_ONEFILE=1 && pyinstaller --noconfirm packaging\phraseforge.spec   # dist\B-PhraseForgeExpress-portable.exe
"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" /DAppVersion=0.5.7 packaging\installer.iss
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

Sync runs at start, every N minutes and on exit. If phrases changed on two PCs, nothing
is overwritten: this PC's copy is saved as a cloud backup and you choose which to keep.
Clipboard history and PC-specific settings are never uploaded.

## Arabic

Settings > Display > User Interface Language > Arabic turns the whole interface right to left.
The Arabic user guide is [docs/USER_GUIDE.ar.md](docs/USER_GUIDE.ar.md) (also under Help in the program).
Phrases can hold one version per language; dates can be Hijri with Arabic digits.

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
