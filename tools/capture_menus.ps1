<#
Capture the menu / ribbon hierarchy of a running program with Windows UI Automation
and write it to docs\menus\<Name>.md, plus screenshots in reference\<Name>\ (gitignored).

Safe by design: it only EXPANDS menus, ribbon tabs and dropdowns (ExpandCollapse /
SelectionItem patterns) and collapses them again with Esc. It never "invokes"
(clicks) a command, so it cannot change your notes, snippets or settings.
It reads the user interface only; it does not inspect the program's files.

Usage (PowerShell, from the repository folder):
  powershell -ExecutionPolicy Bypass -File tools\capture_menus.ps1 -Exe "C:\Program Files\Listary\Listary.exe" -Name listary
  powershell -ExecutionPolicy Bypass -File tools\capture_menus.ps1 -All      # the five reference programs
Options: -MaxDepth 10  -NoScreenshots
#>
param(
  [string]$Exe, [string]$Name, [int]$MaxDepth = 10, [switch]$NoScreenshots, [switch]$All
)
$ErrorActionPreference = "Continue"
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Windows.Forms, System.Drawing
$UIA = [System.Windows.Automation.AutomationElement]
$TW = [System.Windows.Automation.TreeWalker]::ControlViewWalker
$CT = [System.Windows.Automation.ControlType]
$Root = Split-Path $PSScriptRoot -Parent

$Targets = @(
  @{ Exe = "C:\Program Files\Microsoft Office\root\Office16\ONENOTE.EXE"; Name = "onenote" },
  @{ Exe = "C:\Program Files\Microsoft Office\root\Office16\onenotecapture.exe"; Name = "onenotecapture" },
  @{ Exe = "C:\Program Files\Microsoft Office\root\Office16\ONENOTEM.EXE"; Name = "onenotem" },
  @{ Exe = "C:\Program Files\Smile\TextExpander\TextExpander.exe"; Name = "textexpander" },
  @{ Exe = "C:\Program Files\Listary\Listary.exe"; Name = "listary" }
)

function Shot($el, $dir, [ref]$n) {
  if ($NoScreenshots) { return }
  try {
    $r = $el.Current.BoundingRectangle
    if ($r.Width -lt 4 -or $r.Height -lt 4 -or [double]::IsInfinity($r.Width)) { return }
    $bmp = New-Object System.Drawing.Bitmap ([int]$r.Width), ([int]$r.Height)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen([int]$r.X, [int]$r.Y, 0, 0, $bmp.Size)
    $n.Value++
    $bmp.Save((Join-Path $dir ("{0:D4}.png" -f $n.Value)), [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
  } catch {}
}

function Label($el) {
  $c = $el.Current
  $t = $c.ControlType.ProgrammaticName -replace "ControlType\.", ""
  $s = "$($c.Name)"
  if ($c.AcceleratorKey) { $s += "  [$($c.AcceleratorKey)]" }
  if ($c.AccessKey) { $s += "  (Alt: $($c.AccessKey))" }
  if (-not $c.IsEnabled) { $s += "  {disabled}" }
  return "$s  <$t>"
}

function Children($el) {
  $list = @(); $ch = $TW.GetFirstChild($el)
  while ($ch -ne $null -and $list.Count -lt 400) { $list += $ch; $ch = $TW.GetNextSibling($ch) }
  return $list
}

function Expandable($el) {
  $p = $null
  if ($el.TryGetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern, [ref]$p)) { return $p }
  return $null
}

$script:lines = New-Object System.Collections.Generic.List[string]
$script:count = 0; $script:maxSeen = 0

function Walk($el, $depth, $dir, [ref]$n, $seen) {
  if ($depth -gt $MaxDepth) { return }
  foreach ($ch in (Children $el)) {
    try { $key = ($ch.GetRuntimeId() -join ".") } catch { continue }
    if ($seen.Contains($key)) { continue }; [void]$seen.Add($key)
    $c = $ch.Current
    $interesting = $c.ControlType -in @($CT::MenuItem, $CT::MenuBar, $CT::Menu, $CT::TabItem, $CT::SplitButton,
                                       $CT::Button, $CT::CheckBox, $CT::ComboBox, $CT::ToolBar, $CT::Group,
                                       $CT::ListItem, $CT::Hyperlink, $CT::RadioButton, $CT::Edit, $CT::Pane, $CT::Window)
    if ($interesting -and $c.Name) {
      $script:lines.Add(("  " * $depth) + "- " + (Label $ch) + "  [observed, depth $depth]")
      $script:count++; if ($depth -gt $script:maxSeen) { $script:maxSeen = $depth }
    }
    $sel = $null
    if ($c.ControlType -eq $CT::TabItem -and $ch.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern, [ref]$sel)) {
      try { $sel.Select(); Start-Sleep -Milliseconds 500; Shot $el $dir $n } catch {}
    }
    $exp = Expandable $ch
    if ($exp -and $c.IsEnabled -and $depth -lt $MaxDepth) {
      try {
        $exp.Expand(); Start-Sleep -Milliseconds 450
        # A dropdown usually opens as a new top-level menu/window; walk it as children of this item.
        $popup = $UIA::RootElement.FindFirst([System.Windows.Automation.TreeScope]::Children,
          (New-Object System.Windows.Automation.PropertyCondition($UIA::ControlTypeProperty, $CT::Menu)))
        if ($popup) { Shot $popup $dir $n; Walk $popup ($depth + 1) $dir $n $seen }
        Walk $ch ($depth + 1) $dir $n $seen
        try { $exp.Collapse() } catch { [System.Windows.Forms.SendKeys]::SendWait("{ESC}") }
        Start-Sleep -Milliseconds 200
      } catch {
        $script:lines.Add(("  " * ($depth + 1)) + "- (could not expand automatically: open '$($c.Name)' by hand)  [manual]")
      }
    } elseif ($depth -lt $MaxDepth) {
      Walk $ch ($depth + 1) $dir $n $seen
    }
  }
}

function Capture($exe, $name) {
  $dir = Join-Path $Root "reference\$name"; New-Item -ItemType Directory -Force $dir | Out-Null
  $out = Join-Path $Root "docs\menus\$name.md"; New-Item -ItemType Directory -Force (Split-Path $out) | Out-Null
  $script:lines = New-Object System.Collections.Generic.List[string]; $script:count = 0; $script:maxSeen = 0
  if (-not (Test-Path $exe)) { Set-Content $out "# $name`n`nNot installed at $exe"; Write-Host "${name}: not installed"; return }
  $proc = Get-Process | Where-Object { $_.Path -eq $exe } | Select-Object -First 1
  if (-not $proc) { $proc = Start-Process $exe -PassThru; Start-Sleep -Seconds 8 }
  $windows = $UIA::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children,
    (New-Object System.Windows.Automation.PropertyCondition($UIA::ProcessIdProperty, $proc.Id)))
  $n = 0; $seen = New-Object System.Collections.Generic.HashSet[string]
  $script:lines.Add("# $name menu inventory")
  $script:lines.Add("")
  $script:lines.Add("Captured $(Get-Date -Format s) with tools/capture_menus.ps1 (UI Automation, expand-only). Program: $exe")
  $script:lines.Add("")
  if ($windows.Count -eq 0) {
    $script:lines.Add("No visible window. This program lives in the tray: right-click its tray icon and run the script again, or record the menu by hand.  [manual]")
  }
  foreach ($w in $windows) {
    $script:lines.Add("## Window: $($w.Current.Name)")
    Shot $w $dir ([ref]$n)
    Walk $w 0 $dir ([ref]$n) $seen
    $script:lines.Add("")
  }
  $script:lines.Add("")
  $script:lines.Add("Items: $($script:count). Deepest level reached: $($script:maxSeen). Screenshots: $n (in reference\$name, not committed).")
  $script:lines.Add("Not captured automatically: tray-icon menus, right-click context menus, Options dialogs that open only via a command; open them by hand and run again.")
  Set-Content -Encoding UTF8 $out $script:lines
  Write-Host "$name -> $out ($($script:count) items, depth $($script:maxSeen))"
}

if ($All) { foreach ($t in $Targets) { Capture $t.Exe $t.Name } }
elseif ($Exe -and $Name) { Capture $Exe $Name }
else { Write-Host "Give -Exe and -Name, or -All. See the comment at the top of this file." }
