# Save every visible top-level window of a process as PNG (works even when covered).
# Usage: .\tools\capture_windows.ps1 -Name main_window [-Process phraseexpress]
param(
  [Parameter(Mandatory = $true)][string]$Name,
  [string]$Process = "phraseexpress",
  [string]$OutDir = (Join-Path $PSScriptRoot "..\reference\phraseexpress"),
  [switch]$PopupsOnly
)
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices; using System.Text; using System.Collections.Generic;
public static class WinCap {
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr v);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  public static List<IntPtr> Windows(uint pid) {
    var list = new List<IntPtr>();
    EnumWindows((h, l) => { uint p; GetWindowThreadProcessId(h, out p);
      if (p == pid && IsWindowVisible(h)) list.Add(h); return true; }, IntPtr.Zero);
    return list;
  }
}
"@
[void][WinCap]::SetProcessDpiAwarenessContext([IntPtr](-4))  # per-monitor v2: real pixel sizes
New-Item -ItemType Directory -Force $OutDir | Out-Null
$procs = Get-Process $Process -ErrorAction Stop
$i = 0
foreach ($p in $procs) {
  foreach ($h in [WinCap]::Windows([uint32]$p.Id)) {
    $r = New-Object WinCap+RECT; [void][WinCap]::GetWindowRect($h, [ref]$r)
    $w = $r.R - $r.L; $hgt = $r.B - $r.T
    if ($w -lt 40 -or $hgt -lt 20) { continue }
    $t = New-Object Text.StringBuilder 256; [void][WinCap]::GetWindowText($h, $t, 256)
    $c = New-Object Text.StringBuilder 256; [void][WinCap]::GetClassName($h, $c, 256)
    if ($c.ToString() -match "ShadowPart") { continue }               # drop shadow layers
    if ($PopupsOnly -and $c.ToString() -eq "TpexMWnd4") { continue }  # drop the main window
    $bmp = New-Object Drawing.Bitmap $w, $hgt
    $g = [Drawing.Graphics]::FromImage($bmp); $hdc = $g.GetHdc()
    [void][WinCap]::PrintWindow($h, $hdc, 2)   # PW_RENDERFULLCONTENT
    $g.ReleaseHdc($hdc); $g.Dispose()
    $file = Join-Path $OutDir ("{0}{1}.png" -f $Name, $(if ($i) { "_$i" } else { "" }))
    $bmp.Save($file, [Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
    "{0}  {1}x{2}  class={3}  title={4}" -f (Split-Path $file -Leaf), $w, $hgt, $c, $t
    $i++
  }
}
