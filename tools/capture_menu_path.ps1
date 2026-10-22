# Open a ribbon dropdown, walk a keyboard path into it, and capture what shows.
# -Steps examples: "4>" = 4th item, open its submenu (capture the menus)
#                  "4>2" = 4th item, submenu, 2nd item, Enter (capture the dialog)
param(
  [Parameter(Mandatory = $true)][double]$X, [Parameter(Mandatory = $true)][double]$Y,  # button, screenshot frame coords
  [Parameter(Mandatory = $true)][string]$Steps,
  [Parameter(Mandatory = $true)][string]$Name,
  [switch]$RightClick
)
Add-Type @"
using System; using System.Runtime.InteropServices;
public static class M2 {
  [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr v);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, UIntPtr e);
  public static void Click(int x, int y, bool right) { SetCursorPos(x, y);
    if (right) { mouse_event(8,0,0,0,UIntPtr.Zero); mouse_event(16,0,0,0,UIntPtr.Zero); }
    else { mouse_event(2,0,0,0,UIntPtr.Zero); mouse_event(4,0,0,0,UIntPtr.Zero); } }
}
"@
[void][M2]::SetProcessDpiAwarenessContext([IntPtr](-4))
# Safety: only click when a PhraseExpress window is in the foreground.
Add-Type @"
using System; using System.Runtime.InteropServices;
public static class FgCheck { [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint p);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool attach);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  // Bring a window to the front by briefly sharing input state with the current foreground thread.
  public static void Activate(IntPtr h) {
    uint p; uint fgThread = GetWindowThreadProcessId(GetForegroundWindow(), out p);
    uint me = GetCurrentThreadId();
    AttachThreadInput(me, fgThread, true);
    ShowWindow(h, 3); SetForegroundWindow(h);
    AttachThreadInput(me, fgThread, false); } }
"@
$main = (Get-Process phraseexpress).MainWindowHandle
if ($main -ne [IntPtr]::Zero) { [FgCheck]::Activate($main); Start-Sleep -Milliseconds 400 }
$fgPid = 0; [void][FgCheck]::GetWindowThreadProcessId([FgCheck]::GetForegroundWindow(), [ref]$fgPid)
if ((Get-Process -Id $fgPid -ErrorAction SilentlyContinue).ProcessName -ne "phraseexpress") {
  "SKIPPED $Name : PhraseExpress is not the foreground window"; return
}
$scale = 1600 / 1456
$ws = New-Object -ComObject WScript.Shell
[M2]::Click([int]($X * $scale), [int]($Y * $scale), $RightClick.IsPresent)
Start-Sleep -Milliseconds 700
$parts = $Steps -split ">", 2
$first = [int]$parts[0]
for ($i = 0; $i -lt $first; $i++) { $ws.SendKeys("{DOWN}"); Start-Sleep -Milliseconds 60 }
if ($parts.Count -eq 2) {
  $ws.SendKeys("{RIGHT}"); Start-Sleep -Milliseconds 500
  if ($parts[1]) {
    $second = [int]$parts[1]
    for ($i = 1; $i -lt $second; $i++) { $ws.SendKeys("{DOWN}"); Start-Sleep -Milliseconds 60 }
    $ws.SendKeys("{ENTER}"); Start-Sleep -Milliseconds 1500
  }
} elseif ($Steps -ne "0") {
  $ws.SendKeys("{ENTER}"); Start-Sleep -Milliseconds 1500
}
& (Join-Path $PSScriptRoot "capture_windows.ps1") -Name $Name -PopupsOnly
