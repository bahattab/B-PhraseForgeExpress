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

## Settings drop-down lists (observed, user screenshots 2026-10-25)
- AI text processing > Engine / Language Translation > Translation Engine: Deepl (translation only),
  OpenAI, Anthropic (Claude), GPT4All, Ollama, OpenRouter. The translation page has its own API key box
  and shows "Invalid API key. Please check API key and your account status." when the test fails.
- Custom presets > "AI Presets" dialog: Preset label, Instruction ("Prompt"), gear button that shows
  Model (Auto) and Reset to defaults.
- Glossaries > "New Glossary": Name, Source language, Target language.
- Phrase Menu > Phrase menu contents: Description - QuickKey · QuickKey - Description ·
  Autotext - Description - QuickKey · Autotext - QuickKey - Description · QuickKey - Description - Autotext ·
  Description - Autotext - QuickKey · Description - Autotext - Hotkey - QuickKey ·
  QuickKey - Autotext - Description - Hotkey · Autotext - QuickKey - Description - Hotkey ·
  Autotext - Description - QuickKey - Hotkey · Description - Hotkey - QuickKey · QuickKey - Description - Hotkey
- Sort by: Description, Autotext, Usage count, Last use · Alphabetically, Length · Ascending, Descending
- Show phrase menus: next to the caret, below the caret, above the caret, next to the mouse pointer,
  near task tray icon, at a fixed position
- If caret position is indeterminable: Near the task tray, Centered in current window, Centered in primary
  monitor, Centered in current monitor, Next to the mouse cursor, Fixed
- Phrase Menu > Hotkeys: QuickKey modifier None, Shift, Alt, Ctrl, Win; keys None, Numbers [1-9],
  Numpad [Num1-Num9], Letters [a-z], Function keys [F1-F12]; confirmation and search key lists
  (Tab, Enter, Caps Lock, Ins, LWin, RWin, Apps, Num0-9, F1-F24 ...)
- Expert Options > Text Insertion: key-by-key method VK_Packet (recommended) / SendKey; Phrase output
  format Auto, RTF & HTML, RTF only, HTML only.

## Tray icon right-click menu (observed, user screenshot 2026-10-25)
1. About PhraseExpress Free v18.0.84f
2. Language selection >
3. ✓ Enabled in "<program used last>" (per-program on/off; showed the name of the program that had focus)
4. Open PhraseExpress
5. Settings
6. **Register for professional use**
7. Exit

## Phrase menu (popup) (observed, user screenshot 2026-10-25)
- Blue title band with the PHRASE EXPRESS wordmark, a search button and a pin button.
- Scroll arrows at the top and bottom of the list.
- Folders first, sorted by name, with the special folders Clipboard Cache and Last Used sorted in
  among them; then the phrases of the root folder. Each folder row has a ">" arrow.
- Footer: "New phrase..." and **Register for professional use**.
- (The user's own folder and phrase names are not recorded here.)

## New phrase dialog (observed, user screenshots 2026-10-25)
"Enter additional information for the new phrase..." (after the Create new phrase hotkey, when
Settings > Display "Prompt for additional information after creating a new phrase" is on):
- Description
- Trigger: type list (Autotext, SmartComplete, RegEx Autotext, Hotkey, Window, Time, Clipboard,
  RegEx Clipboard), value box with delimiter and case buttons, execution-mode button, remove (X),
  and a green (+) button with the same type list to add another trigger.
- Execution-mode menu: Execute immediately after autotext input · After manual confirmation ·
  When pausing after autotext input · When continue typing quickly after autotext · Help
- Execute only in specific programs (checkbox)
- Save in folder (list) + folder button opening "Select target folder..." (search box and folder tree)
- OK / Cancel

## Tray icon clicks (published, not confirmed by screenshots)
Source: PhraseExpress Windows help, "User interface" page (https://www.phraseexpress.com/doc/ui/),
read through a web search summary on 2026-10-25: left click opens the phrase menu, double click
the main window, right click the menu above, Ctrl+click disables PhraseExpress for a while,
Alt+click opens the settings.

## Not captured
- Tray-icon menu and the popup phrase menu: screen control is limited to left clicks on the
  Windows taskbar, so the tray icon could not be right-clicked; the user sent screenshots of the tray menu and
  the phrase menu instead (above). The click behaviour is still only from the published help.
- The ends of the long Bulk edit and Sort submenus, which ran below the screen.
