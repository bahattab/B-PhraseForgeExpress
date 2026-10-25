# listary menu inventory

Program: `C:\Program Files\Listary\Listary.exe`. The capture script found no window (Listary
runs from the tray). The user then sent 16 screenshots of the Options window (2026-10-25).
Everything below is **observed** from those screenshots. The tray menu itself is still pending.

## Options window: left list
General · Appearance · Hotkey · File Search · Actions · Commands · Web Search · Menu ·
Integration · About. Buttons: OK, Cancel, Apply. The Web Search, Menu, Integration and About pages
are not in the screenshots.

1. **General**: Language (English); Listary 5 Settings: Import; Launcher position: Reset; Start
   Listary when Windows starts; Share anonymous analytics data; Check for updates automatically
   (Check for beta updates); Use software render; "Open folder with" (collapsed).
2. **Appearance**: Light, Dark (PRO), Follow System (PRO).
3. **Hotkey**: Show Listary = "Press Ctrl twice" (Reset button); When pressing again: Hide Listary
   / Switch to file search; Disable for full-screen games and apps; File Search Window (unset);
   Quick Switch Ctrl+G; Show popup menu (unset); Next item Ctrl+N; Previous item Ctrl+P; Preview
   Alt+P; Actions Ctrl+O.
4. **File Search**, three tabs:
   - *Filters*: "Type "keyword:" to use search filters." List: Folder, File, Document, Picture,
     Video, Audio. Add/remove/move (PRO). A filter has Keyword, Name, Extra query, Search in,
     Search for: Folder / File + Extensions.
   - *Index*: Add a network drive or local folder (PRO), Rebuild index, Remove a folder from search
     results; list of indexed drives and folders.
   - *Priorities*: groups High / Normal / Rarely used files. Default rules: Normal =
     %USERPROFILE%\AppData\Roaming\Microsoft\Internet Explorer, …\Microsoft\Windows,
     %ProgramData%\Microsoft\Windows\Start Menu. Rarely used = "Hide system and hidden file search
     results by default", %SystemDrive%\Windows.old, $WINDOWS.~BT, $Windows.~WS, %ProgramData%,
     %SystemRoot%, %USERPROFILE%\AppData, %ProgramW6432%, %ProgramFiles(x86)%, regex `^\.`, `^~`,
     `^[^.]+$`, `^node_modules$`, `^\$`. "Add Rule" dialog: Folder or File name (regex), Priority =
     High / Normal / Rarely used files / Do not index.
5. **Actions**: Open Containing Folder, Copy, Cut, Copy Path to Clipboard, Edit with VS Code. The
   + menu adds Custom Action or Copy File Name to Clipboard. A custom action has Hotkey, Scope
   (Listary / File Explorer), Keyword, Title, Path, Parameter, Working directory, Silent, Run as admin.
6. **Commands** (keyword → command, each can be disabled): opt Options, rebuild Rebuild index,
   `..` Go to Parent Folder, mkdir Create Folder, cmd Command Prompt, cmda Command Prompt (Admin),
   psh PowerShell, psha PowerShell (Admin), touch Create File, shutdown Shutdown Computer, reboot
   Reboot Computer, uninstall Uninstall a Program, connections Network Connections, hosts Edit Hosts.
