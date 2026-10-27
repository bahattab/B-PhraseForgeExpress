# PyInstaller spec for PhraseForge.
#   pyinstaller packaging/phraseforge.spec                  -> dist/B-PhraseForgeExpress/B-PhraseForgeExpress.exe (folder build, used by the installer)
#   set PF_ONEFILE=1 & pyinstaller packaging/phraseforge.spec -> dist/B-PhraseForgeExpress-portable.exe (single file)
# Run packaging/make_icon.py first so packaging/build/phraseforge.ico exists.
import os
import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
ONEFILE = os.environ.get("PF_ONEFILE") == "1"
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "phraseforge" / "__init__.py").read_text()).group(1)
ICON = ROOT / "packaging" / "build" / "phraseforge.ico"

# Windows version resource (shown in Explorer > Properties > Details).
nums = (VERSION.split(".") + ["0", "0", "0"])[:4]
nums = tuple(int(re.sub(r"\D.*", "", n) or 0) for n in nums)
version_file = ROOT / "packaging" / "build" / "version_info.txt"
version_file.parent.mkdir(parents=True, exist_ok=True)
version_file.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'PhraseForge'),
      StringStruct('FileDescription', 'B-PhraseForgeExpress text expander and file launcher'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', 'PhraseForge'),
      StringStruct('LegalCopyright', 'MIT License'),
      StringStruct('OriginalFilename', 'B-PhraseForgeExpress.exe'),
      StringStruct('ProductName', 'B-PhraseForgeExpress'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""", encoding="utf-8")

datas = [
    (str(ROOT / "README.md"), "."),     # About dialog / Help open README next to the package
    (str(ROOT / "docs" / "USER_GUIDE.ar.md"), "docs"),   # Help > User guide in the Arabic interface
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "phraseforge" / "macros" / "README.md"), "phraseforge/macros"),
]
datas += collect_data_files("qtawesome")          # icon fonts
datas += collect_data_files("googleapiclient")    # Drive API discovery documents

hiddenimports = collect_submodules("phraseforge")   # modules loaded lazily / by name
hiddenimports += ["google_auth_oauthlib.flow", "google.auth.transport.requests",
                  "googleapiclient.discovery", "googleapiclient.http"]
# Built-in OCR (Windows.Media.Ocr through the WinRT bindings).
hiddenimports += ["winrt.windows.media.ocr", "winrt.windows.globalization", "winrt.windows.graphics.imaging",
                  "winrt.windows.storage.streams", "winrt.windows.foundation",
                  "winrt.windows.foundation.collections", "winrt.runtime", "winrt.system"]

# Qt modules PhraseForge never uses; keeps the build much smaller.
excludes = [
    "tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtQuick", "PySide6.QtQml",
    "PySide6.QtQuick3D", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtMultimedia",
    "PySide6.QtPdf", "PySide6.QtBluetooth", "PySide6.QtSerialPort", "PySide6.QtSql",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtLocation", "PySide6.QtPositioning",
    "PySide6.QtSensors", "PySide6.QtWebSockets", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtTextToSpeech", "PySide6.QtNfc", "PySide6.QtSpatialAudio",
]

a = Analysis(
    [str(ROOT / "phraseforge" / "__main__.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

common = dict(
    debug=False,
    strip=False,
    upx=False,
    console=False,          # GUI app: no console window
    icon=str(ICON) if ICON.exists() else None,
    version=str(version_file),
)

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="B-PhraseForgeExpress-portable",
              runtime_tmpdir=None, **common)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="B-PhraseForgeExpress", **common)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="B-PhraseForgeExpress")
