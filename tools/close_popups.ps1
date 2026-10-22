# Press Esc until PhraseExpress has no popup/dialog open (never Esc to the main window).
Add-Type @"
using System; using System.Runtime.InteropServices; using System.Text;
public static class P3 {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  public static int Popups(uint pid) { int n = 0;
    EnumWindows((h, l) => { uint p; GetWindowThreadProcessId(h, out p);
      if (p == pid && IsWindowVisible(h)) { var c = new StringBuilder(128); GetClassName(h, c, 128); string s = c.ToString();
        if (s != "TpexMWnd4" && !s.Contains("ShadowPart") && !s.Contains("TApplication")) n++; } return true; }, IntPtr.Zero);
    return n; }
}
"@
$pePid = [uint32](Get-Process phraseexpress).Id
$ws = New-Object -ComObject WScript.Shell
for ($t = 0; $t -lt 6 -and [P3]::Popups($pePid) -gt 0; $t++) { $ws.SendKeys("{ESC}"); Start-Sleep -Milliseconds 600 }
"popups left: $([P3]::Popups($pePid))"
