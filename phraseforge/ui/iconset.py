"""Semantic icon names -> qtawesome icons (MIT-licensed icon fonts).

PhraseForge never ships PhraseExpress artwork. Every UI module asks for icons
by meaning, e.g. icon("new_folder"), so the whole look can be re-skinned here.
"""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtGui import QIcon

# (qtawesome name, color). Colors follow an Office-like palette.
BLUE, GREEN, ORANGE, RED, GREY, PURPLE, TEAL, YELLOW = (
    "#2b6cb0", "#2f9e44", "#e8590c", "#d6336c", "#5f6b7a", "#7048e8", "#0c8599", "#f2b01e")

ICONS: dict[str, tuple[str, str]] = {
    # insert / phrases
    "new_folder": ("mdi6.folder-plus", YELLOW),
    "new_phrase": ("mdi6.file-document-plus-outline", BLUE),
    "folder": ("mdi6.folder", YELLOW),
    "file_search": ("mdi6.file-search-outline", TEAL),
    "refresh": ("mdi6.refresh", GREY),
    "folder_open": ("mdi6.folder-open", YELLOW),
    "phrase": ("mdi6.file-document-outline", BLUE),
    "phrase_rich": ("mdi6.file-document-edit-outline", BLUE),
    "last_used": ("mdi6.history", GREY),
    "clipboard_cache": ("mdi6.clipboard-text-clock-outline", GREY),
    "sticky_notes": ("mdi6.note-outline", YELLOW),
    "phrases_root": ("mdi6.cloud-outline", BLUE),
    "sync": ("mdi6.cloud-sync-outline", BLUE),
    "color": ("mdi6.palette-outline", ORANGE),
    "access_rights": ("mdi6.account-lock-outline", GREY),
    "program_restrictions": ("mdi6.application-cog-outline", RED),
    "up": ("mdi6.arrow-up-circle-outline", BLUE),
    "down": ("mdi6.arrow-down-circle-outline", BLUE),
    "move_to": ("mdi6.folder-move-outline", BLUE),
    "duplicate": ("mdi6.content-duplicate", BLUE),
    "find_replace": ("mdi6.file-find-outline", BLUE),
    "edit_history": ("mdi6.history", BLUE),
    "paste": ("mdi6.content-paste", GREY),
    "cut": ("mdi6.content-cut", BLUE),
    "copy": ("mdi6.content-copy", BLUE),
    "languages": ("mdi6.translate", ORANGE),
    "import": ("mdi6.import", GREEN),
    "export": ("mdi6.export", BLUE),
    "print": ("mdi6.printer-outline", BLUE),
    "delete": ("mdi6.delete-outline", RED),
    "properties": ("mdi6.cog-outline", GREY),
    "tag": ("mdi6.tag-plus-outline", GREEN),
    # view / help
    "two_columns": ("mdi6.view-column-outline", PURPLE),
    "three_columns": ("mdi6.view-parallel-outline", PURPLE),
    "flat_list": ("mdi6.format-list-bulleted", GREY),
    "fit_columns": ("mdi6.arrow-expand-horizontal", BLUE),
    "statistics": ("mdi6.chart-bar", ORANGE),
    "license": ("mdi6.key-outline", YELLOW),
    "updates": ("mdi6.cloud-download-outline", GREEN),
    "about": ("mdi6.information-outline", BLUE),
    "support": ("mdi6.face-agent", GREY),
    "help": ("mdi6.help-circle-outline", BLUE),
    # file menu
    "open": ("mdi6.folder-open-outline", GREY),
    "save_as": ("mdi6.content-save-edit-outline", PURPLE),
    "restore": ("mdi6.backup-restore", GREY),
    "users": ("mdi6.account-group-outline", GREY),
    "settings": ("mdi6.tune-variant", GREY),
    "migration": ("mdi6.package-variant", GREY),
    "exit": ("mdi6.power", RED),
    "database": ("mdi6.database-outline", ORANGE),
    # content tab
    "bold": ("mdi6.format-bold", GREY), "italic": ("mdi6.format-italic", GREY),
    "underline": ("mdi6.format-underline", GREY), "strike": ("mdi6.format-strikethrough", GREY),
    "subscript": ("mdi6.format-subscript", GREY), "superscript": ("mdi6.format-superscript", GREY),
    "highlight": ("mdi6.marker", YELLOW), "font_color": ("mdi6.format-color-text", RED),
    "font": ("mdi6.format-font", GREY),
    "align_left": ("mdi6.format-align-left", GREY), "align_center": ("mdi6.format-align-center", GREY),
    "align_right": ("mdi6.format-align-right", GREY), "align_justify": ("mdi6.format-align-justify", GREY),
    "indent_less": ("mdi6.format-indent-decrease", GREY), "indent_more": ("mdi6.format-indent-increase", GREY),
    "bullets": ("mdi6.format-list-bulleted", GREY), "numbering": ("mdi6.format-list-numbered", GREY),
    "paragraph": ("mdi6.format-paragraph", GREY),
    "picture": ("mdi6.image-outline", BLUE), "hyperlink": ("mdi6.link-variant", BLUE),
    "table": ("mdi6.table", GREY),
    # macro groups
    "m_datetime": ("mdi6.calendar-clock", BLUE), "m_userinput": ("mdi6.form-textbox", BLUE),
    "m_external": ("mdi6.database-import-outline", BLUE), "m_output": ("mdi6.export-variant", PURPLE),
    "m_automation": ("mdi6.cog-play-outline", PURPLE), "m_programming": ("mdi6.code-braces", ORANGE),
    "m_textops": ("mdi6.format-text", ORANGE), "m_clipboard": ("mdi6.clipboard-outline", ORANGE),
    "m_recorder": ("mdi6.record-circle", RED), "m_ocr": ("mdi6.text-recognition", TEAL),
    # OneNote picker (generic note icons, not Microsoft artwork)
    "on_notebook": ("mdi6.notebook-outline", PURPLE), "on_group": ("mdi6.folder-multiple-outline", PURPLE),
    "on_section": ("mdi6.bookmark-outline", PURPLE), "on_page": ("mdi6.file-document-outline", GREY),
    "on_send": ("mdi6.note-plus-outline", PURPLE), "on_clip": ("mdi6.crop", PURPLE),
    # trigger row
    "add": ("mdi6.plus-circle-outline", GREEN), "remove": ("mdi6.close", GREY),
    "word_position": ("mdi6.code-brackets", GREY), "case": ("mdi6.format-letter-case", GREY),
    "exec_mode": ("mdi6.lightning-bolt-outline", GREEN),
    "search": ("mdi6.magnify", GREY), "pin": ("mdi6.pin-outline", GREY),
    "back": ("mdi6.arrow-left-circle-outline", BLUE), "forward": ("mdi6.arrow-right-circle-outline", BLUE),
    "info": ("mdi6.information-outline", BLUE), "warning": ("mdi6.alert-outline", ORANGE),
    "pencil": ("mdi6.pencil-outline", BLUE), "process": ("mdi6.plus-circle-outline", GREEN),
    "collapse": ("mdi6.chevron-up", GREY), "expand": ("mdi6.chevron-down", GREY),
    # main window shell (UI-1)
    "folder_locked": ("mdi6.folder-lock", YELLOW), "open_tab": ("mdi6.tab-plus", BLUE),
    "bulk_edit": ("mdi6.playlist-edit", GREY), "sort": ("mdi6.sort-alphabetical-ascending", GREY),
    "select_all": ("mdi6.select-all", GREY), "pin_desktop": ("mdi6.pin-outline", GREY),
    "column_toggle": ("mdi6.view-column", PURPLE), "local_file": ("mdi6.file-cabinet", GREY),
    "email": ("mdi6.email-outline", BLUE), "text_file": ("mdi6.file-document-outline", GREY),
    "folder_tree": ("mdi6.file-tree-outline", YELLOW), "textexpander": ("mdi6.lightning-bolt-outline", ORANGE),
}


@lru_cache(maxsize=None)
def icon(name: str, color: str | None = None) -> QIcon:
    """Return the icon for a semantic name (empty icon if unknown)."""
    spec = ICONS.get(name)
    if not spec:
        return QIcon()
    try:
        import qtawesome as qta
        return qta.icon(spec[0], color=color or spec[1])
    except Exception:  # qtawesome missing or font not found
        return QIcon()
