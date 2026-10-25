# phraseexpress menu inventory

Program: `C:\Program Files (x86)\PhraseExpress\phraseexpress.exe`. Added to the goal on
2026-10-25 as the seventh reference program, and the main model for PhraseForge.

Status: **pending**. Nothing has been captured from the user's PC yet. To capture it:
- Run `powershell -ExecutionPolicy Bypass -File tools\capture_menus.ps1 -Exe "C:\Program Files (x86)\PhraseExpress\phraseexpress.exe" -Name phraseexpress`
  with the PhraseExpress main window open. It walks the menus and ribbon up to 10 levels.
- Screenshots are still needed for what UI Automation cannot open: the tray-icon menu, the
  popup phrase menu, and each page of Settings.

Until then, PhraseForge's PhraseExpress-style features (folders, phrase editor, triggers with word
position and execution modes, macros, popup menu, SmartComplete, clipboard cache, settings pages)
come from PhraseExpress's public manual, as described in `SPEC.md`, and are marked
*documented* in `docs/EVIDENCE.md`.
