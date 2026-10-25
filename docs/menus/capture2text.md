# capture2text menu inventory

Program: Capture2Text v4.6.3 (Arabic build), `C:\Program Files\00 - Capture2Text v4.6.3 - Arabic\Capture2Text.exe`.
The script found no window (Capture2Text runs from the tray). The user then sent 9 screenshots
(2026-10-25). Everything below is **observed** from those screenshots.

## Tray menu (right-click the tray icon; tooltip "Capture2Text - English")
- Settings...
- Save to Clipboard (checkable)
- Show Popup Window (checkable)
- OCR Language ▸
- Text Orientation ▸
- Help ▸
- Exit

## Settings dialog: left list of pages
1. **Hotkeys**: Start OCR Capture (Ctrl+Shift+A), Re-Capture Last (Win+R), Text Line Capture
   (Ctrl+Shift+Alt+Z), Forward Text Line Capture (Ctrl+Shift+Alt+D), Bubble Capture (Win+S),
   Quick-Access Language 1/2/3 (Ctrl+Shift+Alt+A, Ctrl+Shift+Alt+S, Win+3), Text Orientation
   (Win+O), Toggle Whitelist, Toggle Blacklist (unmapped). Each row: Ctrl/Shift/Alt/Win check
   boxes and a key list; "<Unmapped>" turns a hotkey off. "Reset to defaults" link.
2. **OCR 1**: Current OCR Language (list, "Additional Languages..." link); Quick-Access Languages
   Slot 1–3; Whitelist and Blacklist (text, Enable, Add a-z / Add A-Z / Add 0-9); Miscellaneous:
   Text Orientation (Auto), Tesseract Config File, Scale Factor (3.5), Deskew capture, Trim capture.
3. **OCR 2**: Text Line Capture (Length 1500 px, Width 70, Look Ahead 14, Look Behind 14, Search
   Radius 30); Forward Text Line Capture (Length 750, Width 70, Look Ahead 14, Look Behind 1, Start
   Offset 25, Search Radius 30, First word only); Bubble Capture (Width 500, Height 500).
4. **Capture Box**: Background Color, Border Color, sample preview.
5. **Preview**: not in the screenshots.
6. **Output**: Save to clipboard, Show popup window, Keep line breaks; Logging (Log captures to
   file, Log File, Format `${capture}${linebreak}`); Debug (Save captured image, Save enhanced
   image, Append timestamp to image, Prepend capture box coordinates to captured text); Call
   Executable (Enable + command line).
7. **Replace**: per OCR language, a table of Find (regex) → Replace With; Add Rows, Clear Selection.
8. **Translate**: Append translation to clipboard; Separator (Space, Tab, Line Break, Comma,
   Semicolon, Pipe); Show translation in popup window; Server Timeout (2000 ms); table OCR
   Language → Translate To (using Google Translate).
9. **Speech**: not in the screenshots.
