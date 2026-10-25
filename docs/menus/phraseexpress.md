# phraseexpress menu inventory

Program: `C:\Program Files (x86)\PhraseExpress\phraseexpress.exe`, **PhraseExpress Free v18.0.84f**
(title bar). Added to the goal on 2026-10-25 as the seventh reference program and the main model
for PhraseForge. Captured the same day by Claude through screen control of the user's PC, with
the user's permission, view only: menus were opened and closed, Settings was closed with Cancel.
Everything below is **observed**. The user's own folder and phrase names, account name and AI
API key are visible on screen and are left out here.

## Main window
Title bar with Quick Access Toolbar. Ribbon tabs: **File · Phrases · View · Help**, a search box
"Search in Description [F3]", and the signed-in account at the right. Panes: Files and Folders
("Default": Last Used, Clipboard Cache, Phrases, Trash) · Folders and phrases (Description column)
· editor (Description, Trigger: Autotext with options and case buttons, add/remove trigger, Notes).
Status bar: local phrase file path and last update time.

### File (backstage menu)
- Open ▸ Local phrase file · Connect to SQL database [Demo]
- Save As...
- Restore from backup
- Send/Receive updates Ctrl-F5
- User Manager
- Settings
- Migration Assistant ▸ Save settings and phrases into migration file · Restore settings and phrases from migration file
- Exit

### Phrases tab
- Insert: New Folder · New Phrase ▾ (File, Separator)
- Sync: Send/Receive updates ▾
- Edit: Color ▾ (Auto, Theme Colors, Standard Colors) · Access rights · Program restrictions · Up · Down · Move to... · Duplicate · Find and Replace · Edit history ▾ (recent edits)
- Clipboard: Paste · Cut · Copy
- Languages: Manage languages [Demo] ▾
- Import / Export: Import ▾ (File import, Files including directory structure, MS Word AutoCorrect, MS Word Autotext, MS Outlook emails, Database) · Export ▾ (Email attachment, Text file) · Print phrases

### View tab
Two columns · Three columns · Flat list · Resize column to fit contents.

### Help tab
Statistics · License manager · Check for updates · About PhraseExpress · Get support · Help.

### Folder context menu (3 levels)
Add new... ▸ (Phrase Ctrl-N, Folder Ctrl-O, File, Separator) · Cut · Copy · Paste · Select All ·
Unload · Translate [Demo] · Bulk edit ▸ · Enable triggers ✓ · Show in phrase menu ✓ · Pin to
desktop [Demo] · Sort ▸ · Properties Alt-Enter.
- Bulk edit ▸ Remove duplicates · Descriptions ▸ · Phrase contents ▸ · Autotexts ▸
  - Descriptions ▸ Generate · Prefix text · Append text · Strip trailing spaces · Strip leading spaces · Upper case first letter · Lower case first letter · UPPERCASE · lowercase
  - Phrase contents ▸ Generate · Change font · Convert to Rich Text format · Convert to plain text · Prefix text · Append text · Strip trailing spaces · Strip leading spaces · … (list continues below the screen)
  - Autotexts ▸ Generate · Prefix text · Append text · Strip trailing spaces · Strip leading spaces · Upper case first char · lower case first char · … (continues)
- Sort ▸ None · Description (selected) · Description length · Date created · Date modified · Last used · Times used · … (continues)

## Settings (tree and every page)
Buttons: Settings options ▾ (Revert to default settings, Load settings, Export settings) · OK · Cancel · Help.

1. **Features**: General Features: Clipboard Cache ⚙, Last used phrases folder ⚙, Usage statistics, Detect unwanted text replacements, Suggest Gender-O-Matic, Disable CAPSLOCK key to prevent unintended activation, Capitalize first letter of sentences, COrrect TWo INitial CApitals, Try out features of higher product editions. Startup: Start PhraseExpress with Windows, Diagnostic mode.
2. **Hotkeys**: Create a new phrase (Ctrl+Alt+C) · Edit the last used phrase · Open the PhraseExpress settings window · Open tray popup menu (Ctrl+Alt+Space) · Empty clipboard cache · Pause PhraseExpress for a short time (Repetitions 1, Pause for 10 s). Each with Shift/Ctrl/Alt/Win toggles and a key list.
3. **Display**: User Interface Language (Autodetect); Prompt for additional information after creating a new phrase; Highlight unedited language versions; Show all dialogs; Color theme (Adapt to system setting).
4. **Sounds**: Phrase insertion · Popup display · Detection of unwanted text replacement · Skipped unwanted text replacement · Added new spelling correction · New content in clipboard cache; each with Select audio file.
5. **Phrase File/Database**: Backup: keep a backup of the last 7 phrase file versions, backup directory. Phrase contents caching: None / Preload all phrases on program launch / Cache after first use. Phrase file synchronization [Demo]: on program start, when opening, when closing the main window.
6. **AI text processing**: Engine (OpenRouter shown), Visit button, Your API key (hidden here), model list. **Custom presets**: Correct grammar, Simplify, Summarize, Rewrite in longer form, Change from passive to active language, Create variation, Rewrite more polite, Rewrite more informal, Change to first-person plural form, Change to first-person form, Change to male gender, Change to female gender, Change to plural, Change to singular, plus presets the user added. **Custom instructions**: Info about you; How would you like the engine to respond.
7. **Language Translation**: Translation Engine (DeepL), API key. **Ignored words** (one per line). **Glossaries** (OriginalWord=DesiredTranslation per line).
8. **Network**: SQL server options (Auto-search for SQL servers, Optimize SQL connection for VPN/Internet); Proxy (Server, Port 80, Username, Password); Check for updates (Important updates), Include beta versions, Stay up-to-date automatically, Check now.
9. **Phrase Menu**: Phrase menu contents (Description - QuickKey); Sort by (Description, Alphabetically, Ascending); Show phrase preview; Show phrase language buttons; Hide program-restricted phrases; Suggest SmartComplete/AutoCorrect after the first 3 characters; Show phrase menus next to the caret, else next to the mouse cursor. **Appearance**: clickable preview, Background color, Change font, Dim colors in Dark mode, Reset phrase menu width. **Hotkeys**: confirmation Tab; QuickKey None + Numpad; Search F3; Language selection Ctrl+Right. **Quick Search**: Search within descriptions, Match case, Include sub-folders, Quick Jump.
10. **AutoComplete**: Learn individual spelling corrections; Suggest entered sentences; Suggest entered words; Filter: must begin with a letter / an UPPER CASE letter / a number / a special character.
11. **Expert Options**: default leading and trailing delimiters; Route Enter and Tab-key through PhraseExpress; Execute only in specific programs; Email delivery: MAPI / Outlook OLE / Gmail / mailto (UTF-8 option). **Text Insertion**: clipboard or key-by-key (VK_Packet), clipboard if longer than 100 characters, Phrase output format Auto, Restore clipboard, Specific paste method per application, Force focus change, Auto-minimize main window, Output in UPPERCASE if 2 chars are typed in uppercase. **Delays**: focus change 200 ms, clipboard restore 450 ms, key press 90 ms, clipboard paste 50 ms (the user's current values). **Phrase Formatting**: Default phrase format (Formatted), font for unformatted phrases (Arial 10pt), HTML font formatting output (Auto).

## Not captured
- Tray-icon menu and the popup phrase menu: screen control is limited to left clicks on the
  Windows taskbar, so the tray icon could not be right-clicked. Needs a screenshot from the user.
- The ends of the long Bulk edit and Sort submenus, which ran below the screen.
