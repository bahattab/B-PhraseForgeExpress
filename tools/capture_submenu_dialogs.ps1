# Capture the dialogs opened from macro submenu items.
$t = Join-Path $PSScriptRoot "capture_menu_path.ps1"
$c = Join-Path $PSScriptRoot "close_popups.ps1"
$form = "appearance", "text_label", "separator", "enum_group", "phrases_dropdown", "calendar", "numeric_input", "numeric_slider"
for ($j = 1; $j -le $form.Count; $j++) {
  & $t -X 697 -Y 97 -Steps "3>$j" -Name ("13_form_{0:D2}_{1}" -f $j, $form[$j - 1]); & $c | Out-Null
}
$wys = "input_field", "drop_down", "phrase_selection", "check_box", "calendar"
for ($j = 1; $j -le $wys.Count; $j++) {
  & $t -X 697 -Y 97 -Steps "4>$j" -Name ("13_wysiwyg_{0:D2}_{1}" -f $j, $wys[$j - 1]); & $c | Out-Null
}
& $t -X 793 -Y 76 -Steps "1>11" -Name "13_keypress_more"; & $c | Out-Null
& $t -X 707 -Y 120 -Steps "13>8" -Name "13_activedirectory_more"; & $c | Out-Null
"done"
