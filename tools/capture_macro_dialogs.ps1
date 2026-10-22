# Open each PhraseExpress macro menu item and capture the dialog it shows.
# Precondition: PhraseExpress main window maximized on the primary screen,
# cursor in a (temporary) phrase's content so the "Phrase content" ribbon tab is shown.
param([string[]]$Only, [string[]]$Items)
Add-Type @"
using System; using System.Runtime.InteropServices;
public static class Mouse {
  [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr v);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, UIntPtr e);
  public static void Click(int x, int y) { SetCursorPos(x, y); mouse_event(2,0,0,0,UIntPtr.Zero); mouse_event(4,0,0,0,UIntPtr.Zero); }
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr h, System.Text.StringBuilder s, int n);
  // visible windows of the process other than the main window and shadow layers
  public static int Popups(uint pid) {
    int n = 0;
    EnumWindows((h, l) => { uint p; GetWindowThreadProcessId(h, out p);
      if (p == pid && IsWindowVisible(h)) { var c = new System.Text.StringBuilder(128); GetClassName(h, c, 128);
        string s = c.ToString(); if (s != "TpexMWnd4" && !s.Contains("ShadowPart") && !s.Contains("TApplication")) n++; }
      return true; }, IntPtr.Zero);
    return n;
  }
}
"@
$pePid = [uint32](Get-Process phraseexpress).Id
function Close-Popups {
  for ($t = 0; $t -lt 5 -and [Mouse]::Popups($pePid) -gt 0; $t++) {
    $ws.SendKeys("{ESC}"); Start-Sleep -Milliseconds 700
  }
}
[void][Mouse]::SetProcessDpiAwarenessContext([IntPtr](-4))
$scale = 1600 / 1456   # screenshot frame -> physical pixels
$ws = New-Object -ComObject WScript.Shell
$cap = Join-Path $PSScriptRoot "capture_windows.ps1"

# name, button (frame coords), items (index -> short name); submenu-only items omitted
$menus = @(
  @{ n = "datetime"; x = 700; y = 76; items = @{1 = "date_time"; 2 = "date_calc"; 3 = "time_calc" } },
  @{ n = "userinput"; x = 697; y = 97; items = @{1 = "manual_input"; 2 = "form_input"; 5 = "document_generator"; 6 = "file_select"; 7 = "file_save" } },
  @{ n = "externaldata"; x = 707; y = 120; items = @{2 = "translate"; 3 = "ai_text"; 4 = "external_doc"; 5 = "embed_file"; 6 = "excel_cells"; 7 = "csv"; 8 = "xml_xpath"; 9 = "find_excel_col"; 10 = "find_excel_row"; 11 = "db_query"; 12 = "env_var" } },
  @{ n = "output"; x = 793; y = 76; items = @{2 = "random_text"; 3 = "gender"; 4 = "output_file"; 5 = "paste_file"; 6 = "message_box"; 7 = "notification"; 8 = "ascii"; 9 = "random_number"; 10 = "cursor_pos"; 11 = "paste_method"; 12 = "set_language" } },
  @{ n = "automation"; x = 804; y = 97; items = @{1 = "create_email"; 2 = "open_web"; 3 = "run_program"; 4 = "open_file"; 5 = "open_folder"; 6 = "app_focus"; 7 = "macro_loop" } },
  @{ n = "programming"; x = 809; y = 120; items = @{1 = "insert_phrase"; 2 = "check_value"; 3 = "if_then_else"; 4 = "calculation"; 5 = "set_phrase_content"; 6 = "wait"; 7 = "set_variable"; 8 = "output_variable" } },
  @{ n = "textops"; x = 914; y = 76; items = @{1 = "text_length"; 2 = "substring"; 3 = "regex_extract"; 4 = "trim"; 5 = "trim_leading"; 6 = "trim_trailing"; 7 = "replace"; 8 = "substring_pos"; 9 = "last_pos"; 10 = "sentence_case"; 11 = "upper"; 12 = "lower"; 13 = "upper_first"; 14 = "lower_first"; 15 = "upper_words"; 16 = "lower_words" } },
  @{ n = "clipboard"; x = 903; y = 97; items = @{1 = "paste_copy"; 2 = "insert_from_clipboard"; 3 = "put_into_clipboard" } }
)

foreach ($m in $menus) {
  if ($Only -and $m.n -notin $Only) { continue }
  foreach ($k in ($m.items.Keys | Sort-Object)) {
    if ($Items -and $m.items[$k] -notin $Items) { continue }
    Close-Popups
    [Mouse]::Click([int]($m.x * $scale), [int]($m.y * $scale))
    Start-Sleep -Milliseconds 600
    for ($d = 0; $d -lt $k; $d++) { $ws.SendKeys("{DOWN}"); Start-Sleep -Milliseconds 60 }
    $ws.SendKeys("{ENTER}")
    Start-Sleep -Milliseconds 1500
    $name = "11_macro_{0}_{1:D2}_{2}" -f $m.n, $k, $m.items[$k]
    $lines = & $cap -Name $name -PopupsOnly
    if ($lines) { $lines } else { "$name  (no dialog: inserted directly)" }
    Close-Popups   # cancel the dialog; never sends Esc to the main window
  }
}
"done"
