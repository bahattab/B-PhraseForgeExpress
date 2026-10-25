# B-PhraseForgeExpress (PhraseForge)

An original text expander for Windows with the feature set of PhraseExpress,
screen OCR through Capture2Text, and import of TextExpander snippet exports.
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
pushing a tag such as `v0.3.0` also publishes a GitHub Release. To build locally on Windows
(needs Python 3.12 and [Inno Setup 6](https://jrsoftware.org/isinfo.php)):

```
python -m pip install -r requirements-build.txt
python packaging\make_icon.py
pyinstaller --noconfirm packaging\phraseforge.spec          # dist\B-PhraseForgeExpress\B-PhraseForgeExpress.exe
set PF_ONEFILE=1 && pyinstaller --noconfirm packaging\phraseforge.spec   # dist\B-PhraseForgeExpress-portable.exe
"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" /DAppVersion=0.3.0 packaging\installer.iss
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

## Default hotkeys

| Hotkey | Action |
|---|---|
| Ctrl+Alt+Space | Phrase popup / search |
| Ctrl+Alt+V | Clipboard history |
| Ctrl+Alt+O | OCR a screen region to the clipboard (Capture2Text) |
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

One-time Google setup (free, about 5 minutes; Google requires every app to have its own client ID):

1. Open https://console.cloud.google.com and create a project.
2. APIs & Services > Library: enable **Google Drive API**.
3. OAuth consent screen: User type **External**; add your Google address as a test user.
4. Credentials > Create credentials > **OAuth client ID** > Application type **Desktop app**.
5. Download the JSON, then in PhraseForge click **OAuth client file...** and pick it.
6. Click **Sign in with Google**.

Sync runs at start, every N minutes and on exit. If phrases changed on two PCs, nothing
is overwritten: this PC's copy is saved as a cloud backup and you choose which to keep.
Clipboard history and PC-specific settings are never uploaded.

## Import

- File > Import: PhraseForge JSON, CSV, folder of .txt files.
- File > Import > From TextExpander: TextExpander CSV export or `.textexpander` group file.

## License

MIT, see [LICENSE](LICENSE). Third-party parts keep their own licenses: PySide6 (LGPL),
QtAwesome icon fonts (MIT / SIL OFL), Google API client libraries (Apache 2.0).
Capture2Text (GPLv3) is not included; PhraseForge only starts its command-line tool
if you have it installed. PhraseExpress and TextExpander are trademarks of their owners;
PhraseForge is an independent project and contains none of their code.
