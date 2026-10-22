# With the Settings tree focused on its first page, capture every page by
# pressing Down between captures. Only the settings dialog window is saved.
param([int]$Pages = 21, [string]$Prefix = "06_settings")
$names = @("features","hotkeys","display","sounds","phrase_file","ai","ai_presets","ai_instructions",
  "translation","translation_ignored","translation_glossaries","network","phrase_menu","phrase_menu_appearance",
  "phrase_menu_hotkeys","phrase_menu_quicksearch","autocomplete","expert","expert_text_insertion",
  "expert_delays","expert_phrase_formatting")
$ws = New-Object -ComObject WScript.Shell
$out = Join-Path $PSScriptRoot "..\reference\phraseexpress"
for ($i = 0; $i -lt $Pages; $i++) {
  Start-Sleep -Milliseconds 700
  $n = "{0}_{1:D2}_{2}" -f $Prefix, ($i + 1), $names[$i]
  $lines = & (Join-Path $PSScriptRoot "capture_windows.ps1") -Name $n
  foreach ($l in $lines) {   # keep only the Settings dialog capture
    $file = Join-Path $out ($l -split "  ")[0]
    if ($l -match "title=.*Settings") { $l } else { Remove-Item $file -ErrorAction SilentlyContinue }
  }
  $ws.SendKeys("{DOWN}")
}
