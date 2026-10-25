; Inno Setup 6 script for PhraseForge.
; Build the PyInstaller folder first (dist\B-PhraseForgeExpress), then:
;   iscc /DAppVersion=0.3.0 packaging\installer.iss
; Output: dist\B-PhraseForgeExpress-Setup-<version>.exe

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "B-PhraseForgeExpress"
#define AppExe "B-PhraseForgeExpress.exe"
; Run-key value name used by phraseforge/autostart.py (NAME); keep them equal.
#define RunName "PhraseForge"
#define Root ".."

[Setup]
; Fixed AppId keeps upgrades and uninstall working across versions. Never change it.
AppId={{6492015F-15DE-4192-AAB0-5E08A8DD971B}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=PhraseForge
AppPublisherURL=https://github.com/bahattab/B-PhraseForgeExpress
AppSupportURL=https://github.com/bahattab/B-PhraseForgeExpress/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Installs for the current user without admin rights; the user can pick "all users" instead.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile={#Root}\LICENSE
SetupIconFile={#Root}\packaging\build\phraseforge.ico
UninstallDisplayIcon={app}\{#AppExe}
OutputDir={#Root}\dist
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Close a running copy before files are replaced.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "Start B-PhraseForgeExpress when Windows starts"; GroupDescription: "Startup:"

[Files]
Source: "{#Root}\dist\B-PhraseForgeExpress\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Same per-user Run value the app's own "Start with Windows" setting uses (phraseforge/autostart.py).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#RunName}"; \
  ValueData: """{app}\{#AppExe}"" --minimized"; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /IM {#AppExe} /F"; Flags: runhidden; RunOnceId: "KillPhraseForge"

[UninstallDelete]
Type: files; Name: "{app}\*.log"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#RunName}');
  // Phrases in %APPDATA%\PhraseForge are kept on purpose so a reinstall keeps the user's data.
end;
