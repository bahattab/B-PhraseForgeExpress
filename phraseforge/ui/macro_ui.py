"""Macro insertion UI: ribbon "Macros" group, macro menus, macro dialogs, chip names.

Public API (used by the phrase editor / main window):
    build_macro_group(group, insert)          fill a RibbonGroup like PhraseExpress's Macros group
    macro_menus(parent, insert) -> {title: QMenu}
    open_macro_dialog(kind, parent=None) -> str | None
    display_name(token) -> str                chip label for a "{#...}" token
    edit_macro(token, parent=None) -> str | None
    shortcut_actions(widget, insert) -> list[QAction]   Ctrl+D/M/E/R/O/L/I/G/K on a widget
    set_context(store=None, settings=None)    phrase store for pickers and previews
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QMenu, QPlainTextEdit, QVBoxLayout, QWidget,
)

from phraseforge.ui.iconset import icon
from phraseforge.ui.macro_dialog_kit import MacroDialog, set_context  # noqa: F401  (re-export)
from phraseforge.ui.macro_specs import SPECS

Insert = Callable[[str], None]

# ---------------------------------------------------------------- menu layout (mirrors PhraseExpress)
# entries: kind | ("Title", [submenu entries]) | ("@direct", "Text", macro) | None (separator)
OUTLOOK = [("@direct", "Title", "{#outlook title}"), ("@direct", "First name", "{#outlook firstname}"),
           ("@direct", "Last name", "{#outlook lastname}"), None,
           ("@direct", "Sender email", "{#outlook senderemail}"),
           ("@direct", "Recipient email", "{#outlook recipientemail}"),
           ("@direct", "Subject", "{#outlook subject}"), ("@direct", "Body", "{#outlook body}"), None,
           ("@direct", "Gender", "{#outlook gender}")]
ACTIVE_DIRECTORY = [("@direct", "Name", "{#ad name}"), ("@direct", "Email", "{#ad email}"),
                    ("@direct", "Nickname", "{#ad nickname}"), ("@direct", "Telephone number", "{#ad telephone}"),
                    ("@direct", "Street", "{#ad street}"), ("@direct", "ZIP code", "{#ad zip}"),
                    ("@direct", "City", "{#ad city}"), None, ("@kind", "More...", "ad_more")]
KEYPRESS = [("@direct", "Enter", "{#key enter}"), ("@direct", "Tab", "{#key tab}"), ("@direct", "Esc", "{#key esc}"),
            ("@direct", "Del", "{#key delete}"), ("@direct", "BackSpace", "{#key backspace}"), None,
            ("@direct", "Left", "{#key left}"), ("@direct", "Right", "{#key right}"), ("@direct", "Up", "{#key up}"),
            ("@direct", "Down", "{#key down}"), None, ("@kind", "More...", "keypress")]
FORM = ["form_appearance", None, "text_label", "separator", None, "enum_group", "phrases_dropdown", "calendar",
        "numeric_input", "numeric_slider"]
WYSIWYG = [("@kind", "Input field", "w_input_field"), ("@kind", "Drop down", "w_drop_down"),
           ("@kind", "Phrase selection", "w_phrase_selection"), ("@kind", "Check box", "w_check_box"),
           ("@kind", "Calendar", "w_calendar")]

MENUS: list[tuple[str, str, list]] = [
    ("Date/Time", "m_datetime", ["date_time", "date_calc", "time_calc"]),
    ("User input", "m_userinput", ["manual_input", None, "form_input", ("Form", FORM), None,
                                   ("WYSIWYG form", WYSIWYG), None, "document_generator", "file_select", "file_save"]),
    ("External data", "m_external", [("Outlook email", OUTLOOK), "translate", "ai_text", None, "external_doc",
                                     "embed_file", "excel_cells", "csv", "xml_xpath", "find_excel_col",
                                     "find_excel_row", "db_query", "env_var", ("ActiveDirectory value", ACTIVE_DIRECTORY)]),
    ("Output", "m_output", [("Keypress", KEYPRESS), "random_text", "gender", "output_file", "paste_file",
                            "message_box", "notification", "ascii", "random_number", "cursor_pos", "paste_method",
                            "set_language"]),
    ("Automation", "m_automation", ["create_email", "open_web", None, "run_program", "open_file", "open_folder", None,
                                    "app_focus", "macro_loop"]),
    ("Programming", "m_programming", ["insert_phrase", "check_value", "if_then_else", "calculation",
                                      "set_phrase_content", "wait", None, "set_variable", "output_variable"]),
    ("Text operations", "m_textops", ["text_length", "substring", "regex_extract", None, "trim", "trim_leading",
                                      "trim_trailing", None, "replace", "substring_pos", "last_pos", None,
                                      "sentence_case", "upper", "lower", "upper_first", "lower_first", "upper_words",
                                      "lower_words"]),
    ("Clipboard", "m_clipboard", ["paste_copy", None, "insert_from_clipboard", "put_into_clipboard"]),
]
SHORTCUTS = {"date_time": "Ctrl+D", "manual_input": "Ctrl+M", "create_email": "Ctrl+E", "run_program": "Ctrl+R",
             "open_file": "Ctrl+O", "macro_loop": "Ctrl+L", "insert_phrase": "Ctrl+I", "output_variable": "Ctrl+G",
             "keypress": "Ctrl+K"}
MENU_TEXT = {"wait": "Wait x milliseconds", "ad_more": "More...", "keypress": "More...",
             "insert_from_clipboard": "Insert text from clipboard", "put_into_clipboard": "Put text into clipboard",
             "w_input_field": "Input field", "w_drop_down": "Drop down", "w_phrase_selection": "Phrase selection",
             "w_check_box": "Check box", "w_calendar": "Calendar"}


# ---------------------------------------------------------------- dialogs
def open_macro_dialog(kind: str, parent: QWidget | None = None, values: dict | None = None,
                      caption: str = "") -> str | None:
    s = SPECS.get(kind)
    if s is None:
        raise KeyError(kind)
    if s.direct:
        return s.build(values or {})
    dlg = MacroDialog(s, values, caption, parent)
    if dlg.exec() == QDialog.Accepted:
        return dlg.result_text
    return None


def _run(kind: str, insert: Insert, parent):
    text = open_macro_dialog(kind, parent)
    if text:
        insert(text)


def _fill(menu: QMenu, entries: list, insert: Insert, parent):
    for e in entries:
        if e is None:
            menu.addSeparator()
        elif isinstance(e, str):
            s = SPECS[e]
            a = QAction(MENU_TEXT.get(e) or s.menu_text or s.title, menu)
            if e in SHORTCUTS:
                a.setShortcut(QKeySequence(SHORTCUTS[e]))
                a.setShortcutVisibleInContextMenu(True)
            a.setData(e)
            a.triggered.connect(lambda _=False, k=e: _run(k, insert, parent))
            menu.addAction(a)
        elif e[0] == "@direct":
            a = QAction(e[1], menu)
            a.setData(e[2])
            a.triggered.connect(lambda _=False, t=e[2]: insert(t))
            menu.addAction(a)
        elif e[0] == "@kind":
            a = QAction(e[1], menu)
            if e[2] in SHORTCUTS:
                a.setShortcut(QKeySequence(SHORTCUTS[e[2]]))
                a.setShortcutVisibleInContextMenu(True)
            a.setData(e[2])
            a.triggered.connect(lambda _=False, k=e[2]: _run(k, insert, parent))
            menu.addAction(a)
        else:
            sub = menu.addMenu(e[0])
            _fill(sub, e[1], insert, parent)


def macro_menus(parent: QWidget, insert: Insert, nested: bool = False) -> dict[str, QMenu]:
    """The 8 macro menus keyed by title (same items as the ribbon dropdowns)."""
    out = {}
    for title, icon_name, entries in MENUS:
        m = QMenu(title, parent)
        m.setIcon(icon(icon_name))
        _fill(m, entries, insert, parent if isinstance(parent, QWidget) else None)
        out[title] = m
    return out


def build_macro_group(group, insert: Insert) -> None:
    """Fill a RibbonGroup: three columns of dropdown buttons like PhraseExpress's Macros group."""
    menus = macro_menus(group, insert)
    cols = [["Date/Time", "User input", "External data"], ["Output", "Automation", "Programming"],
            ["Text operations", "Clipboard"]]
    icons = dict((t, i) for t, i, _ in MENUS)
    for titles in cols:
        col = group.add_column()
        for t in titles:
            col.add_small(t, icons[t], None, menus[t], split=False)
    cols_widget = group.row.itemAt(group.row.count() - 1).widget()
    cols_widget.add_small("Screen OCR", "m_ocr", lambda: _run("ocr", insert, group.window()))
    group.macro_menus = menus          # handy for tests / other modules


def shortcut_actions(widget: QWidget, insert: Insert) -> list[QAction]:
    """Install PhraseExpress's macro keyboard shortcuts on a widget (e.g. the content editor)."""
    acts = []
    for kind, keys in SHORTCUTS.items():
        a = QAction(widget)
        a.setShortcut(QKeySequence(keys))
        a.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        a.triggered.connect(lambda _=False, k=kind: _run(k, insert, widget))
        widget.addAction(a)
        acts.append(a)
    return acts


# ---------------------------------------------------------------- tokens
def _tok_text(tok) -> str:
    from phraseforge.macros.parser import Call, Text
    if tok is None:
        return "1"
    out = []
    for p in tok.parts:
        out.append(p.text if isinstance(p, Text) else p.raw if isinstance(p, Call) else "")
    return "".join(out)


def parse_token(token: str):
    """(name, args: list[str], opts: dict[str, str]) for one '{#...}' token, or None."""
    from phraseforge.macros.parser import Call, parse_flat
    try:
        nodes = parse_flat(token.strip())
    except Exception:
        return None
    if len(nodes) != 1 or not isinstance(nodes[0], Call):
        return None
    c = nodes[0]
    return c.name, [_tok_text(t) for t in c.args], {k: _tok_text(v) for k, v in c.opts.items()}


_CMD_TO_KIND: dict[str, str] = {}
for _k, _s in SPECS.items():
    for _c in _s.commands:
        _CMD_TO_KIND.setdefault(_c, _k)

BLOCK_NAMES = {"if": "If", "elseif": "Else if", "else": "Else", "endif": "End if", "loop": "Macro loop",
               "endloop": "End loop", "foreach": "For each", "endforeach": "End for each", "form": "Form",
               "endform": "End form"}
SIMPLE_NAMES = {"formvalue": "Form value", "date": "Date/Time", "time": "Date/Time", "datetime": "Date/Time",
                "cursor": "Set cursor position", "formseparator": "Separator", "key": "Keypress",
                "keys": "Keypress", "outlook": "Outlook", "ad": "ActiveDirectory", "var": "Variable",
                "clipboard": "Clipboard", "clipboardhistory": "Clipboard cache", "setclipboard": "Put text into clipboard"}


def display_name(token: str) -> str:
    """Chip label for a macro token (uses -caption when the user named it)."""
    parsed = parse_token(token)
    if parsed is None:
        import re
        m = re.match(r"\{#(\w+)", token or "")
        n = m.group(1).lower() if m else ""
        return BLOCK_NAMES.get(n, n.capitalize() or token)
    name, args, opts = parsed
    if opts.get("caption"):
        return opts["caption"]
    if name in BLOCK_NAMES:
        return BLOCK_NAMES[name]
    if name in ("key", "keys") and args:
        return "Key: " + args[0]
    if name == "outlook" and args:
        return "Outlook: " + args[0]
    if name == "ad" and args:
        return "AD: " + args[0]
    if name in ("var", "get") and args:
        return "Variable: " + args[0]
    if name == "formvalue" and args:
        return "Form value: " + args[0]
    if name == "insert" and args:
        return "Insert: " + args[0]
    if name == "env" and args:
        return f"%{args[0]}%"
    if name in ("sleep", "wait") and args:
        return f"Wait {args[0]} milliseconds"
    if name in SIMPLE_NAMES:
        return SIMPLE_NAMES[name]
    kind = _CMD_TO_KIND.get(name)
    if kind:
        s = SPECS[kind]
        return MENU_TEXT.get(kind) if MENU_TEXT.get(kind) not in (None, "More...") else s.title
    return name.capitalize()


def edit_macro(token: str, parent: QWidget | None = None) -> str | None:
    """Re-open the dialog for an existing macro token; raw text editor when no dialog fits."""
    parsed = parse_token(token)
    if parsed is not None:
        name, args, opts = parsed
        kind = _CMD_TO_KIND.get(name)
        if name in ("replace", "regexreplace"):
            kind = "replace"
        s = SPECS.get(kind) if kind else None
        if s is not None and s.parse is not None and not s.direct:
            try:
                values = s.parse(args, opts)
                if name == "regexreplace":
                    values["regex"] = True
            except Exception:
                values = None
            if values is not None:
                return open_macro_dialog(kind, parent, values, caption=opts.get("caption", ""))
    return raw_edit(token, parent)


def raw_edit(token: str, parent: QWidget | None = None) -> str | None:
    dlg = QDialog(parent)
    dlg.setWindowTitle("Edit macro")
    dlg.resize(520, 220)
    v = QVBoxLayout(dlg)
    v.addWidget(QLabel("Macro text:"))
    ed = QPlainTextEdit(token)
    v.addWidget(ed)
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    v.addWidget(bb)
    return ed.toPlainText() if dlg.exec() == QDialog.Accepted else None


def all_menu_kinds() -> list[str]:
    """Every dialog kind reachable from the menus (for tests)."""
    out: list[str] = []

    def walk(entries):
        for e in entries:
            if e is None:
                continue
            if isinstance(e, str):
                out.append(e)
            elif e[0] == "@kind":
                out.append(e[2])
            elif e[0] != "@direct":
                walk(e[1])
    for _t, _i, entries in MENUS:
        walk(entries)
    out.append("ocr")
    return out
