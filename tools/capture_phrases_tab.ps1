# Phrases ribbon tab: dropdowns, button dialogs, editor combos, tree context menus.
# Precondition: Phrases tab active, temp phrase selected (frame coords measured 2026-10-21).
$t = Join-Path $PSScriptRoot "capture_menu_path.ps1"
$c = Join-Path $PSScriptRoot "close_popups.ps1"
$items = @(
  @(187, 123, "14_dropdown_send_receive"),
  @(273, 123, "14_dropdown_color"),
  @(374, 109, "14_dialog_program_restrictions"),
  @(447, 120, "14_dialog_move_to"),
  @(536, 97, "14_dialog_find_replace"),
  @(566, 120, "14_dropdown_edit_history"),
  @(634, 123, "14_dropdown_paste"),
  @(790, 114, "14_dropdown_manage_languages"),
  @(899, 114, "14_dropdown_import"),
  @(957, 114, "14_dropdown_export"),
  @(1013, 114, "14_dialog_print_phrases"),
  @(444, 737, "15_combo_trigger_type"),
  @(444, 783, "15_combo_output_target"),
  @(1363, 737, "15_trigger_button_1"),
  @(1383, 737, "15_trigger_button_aa"),
  @(1409, 737, "15_trigger_button_options"),
  @(1436, 217, "15_description_tags_button")
)
foreach ($i in $items) {
  & $t -X $i[0] -Y $i[1] -Steps "0" -Name $i[2]
  & $c | Out-Null
}
& $t -X 89 -Y 511 -Steps "0" -Name "16_context_menu_phrase" -RightClick; & $c | Out-Null
& $t -X 121 -Y 491 -Steps "0" -Name "16_context_menu_folder" -RightClick; & $c | Out-Null
& $t -X 700 -Y 500 -Steps "0" -Name "16_context_menu_content" -RightClick; & $c | Out-Null
"done"
