# onenote menu inventory

Captured 2026-10-25 on the user's PC with `tools/capture_menus.ps1 -All` (UI Automation,
expand-only). Program: `C:\Program Files\Microsoft Office\root\Office16\ONENOTE.EXE`.
88 items, deepest level 10, 9 screenshots (kept on the user's PC, not committed).

**Privacy edit before commit:** the raw capture also listed the user's notebook, section and
page names, page links, the open page's title and the signed-in account name. Those are
the user's own notes, not OneNote's interface, so they are replaced here with `<user content>`.
The script now does this by itself (`-KeepNames` turns it off).

## Window: `<window title hidden>`
- MsoDockTop `<Pane>`
  - Ribbon `<Pane>`
    - Quick Access Toolbar `<ToolBar>`
      - Back (Alt, 1) {disabled} `<Button>`
      - Customize Quick Access Toolbar `<MenuItem>` → `<Menu>`
    - Microsoft search box (Alt, Q) `<MenuItem>` → search `<Edit>` + results `<Menu>`
    - Account (Alt, Z P) `<MenuItem>` → `<Menu>`: account name `<Button>`, My Microsoft account `<Hyperlink>`, Office user info `<Hyperlink>`, Sign out of this account `<Button>` (depth 10)
    - Minimize / Restore Down / Close `<Button>`
    - File Tab (Alt, F) `<Button>`
      - Home (Alt, H) `<TabItem>`
      - Insert (Alt, N) `<TabItem>`
      - Draw (Alt, D) `<TabItem>`
      - History (Alt, S 1) `<TabItem>`
      - Review (Alt, R) `<TabItem>`
      - View (Alt, W) `<TabItem>`
      - Help (Alt, E) `<TabItem>`
      - Class Notebook (Alt, Y 1) `<TabItem>`
      - Sticky Notes (Alt, S 2) `<Button>`
      - Share (Alt, Z S) `<MenuItem>`
    - Feedback (Alt, Y 2) `<Button>`
  - Notebook pane
    - notebooks and sections: 40 entries `<user content>`, which the script could not expand automatically
    - Quick Notes `<Button>`
    - Resize Notebook List `<Button>`
    - Resize Page Tabs `<Button>`
    - Add Page `<Button>`
    - Sort Pages `<Button>`
    - page list: 27 `<ListItem>` entries `<user content>`; each shows the shortcut **Ctrl+Alt+G**
    - Line up / Page up / Page down / Line down `<Button>`
  - Navigation Controls `<Group>`
    - Search `<Pane>` → Search `<Button>`
    - Full Page View `<Button>`
  - OneNote Page `<Pane>`
    - horizontal scroll: Column left / Page left / Page right / Column right `<Button>`
    - Page date and time `<Edit>`
    - page links `<Hyperlink>` `<user content>`
    - Sections `<Pane>` → Collapse sidebar `<Button>`

## Not captured automatically
The commands inside each ribbon tab (Home, Insert, Draw…) are not in this capture: the script
selected each tab and took a screenshot, but OneNote's ribbon groups did not show up as UI
Automation children. Right-click menus are not captured either. Both still need screenshots.
