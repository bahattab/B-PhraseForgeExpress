"""Trigger rows like PhraseExpress's editor: one row per trigger, any of 8 types.

Row data is a plain dict (see default_row()). Rows map to models.Trigger for the
database; options the model has no field for (word position, execution mode,
delimiters, SmartComplete, window scope) are kept in the JSON setting
"ui.trigger_extras" via ExtrasStore, keyed per owner ("p:<phrase id>",
"f:<folder id>", "s:<special folder>").
"""
from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QTime, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QMessageBox, QPushButton, QStackedWidget, QTimeEdit, QToolButton, QVBoxLayout, QWidget,
)

from phraseforge.models import AutotextMode, Trigger, TriggerKind
from phraseforge.ui.hotkey_picker import HotkeyPicker
from phraseforge.ui.iconset import icon
from phraseforge.ui.pe_style import caption

# UI trigger types, in PhraseExpress order.
TYPES = [
    ("autotext", "Autotext"),
    ("smartcomplete", "SmartComplete"),
    ("regex_autotext", "RegEx Autotext"),
    ("hotkey", "Hotkey"),
    ("window", "Window"),
    ("time", "Time"),
    ("clipboard", "Clipboard"),
    ("regex_clipboard", "RegEx Clipboard"),
]
TYPE_LABELS = dict(TYPES)
KIND_FOR_TYPE = {
    "autotext": TriggerKind.AUTOTEXT, "regex_autotext": TriggerKind.REGEX,
    "hotkey": TriggerKind.HOTKEY, "window": TriggerKind.APP_FOCUS, "time": TriggerKind.TIME,
    "clipboard": TriggerKind.CLIPBOARD, "regex_clipboard": TriggerKind.CLIPBOARD_REGEX,
    "smartcomplete": None,   # suggestion-only; no database trigger
}
TYPE_FOR_KIND = {v: k for k, v in KIND_FOR_TYPE.items() if v is not None}

WORD_POSITIONS = [("start", "Start of a word (default)"), ("end", "End of a word"),
                  ("middle", "Middle of a word"), ("entire", "Entire word")]
EXEC_MODES = [("immediate", "Execute immediately after autotext input"),
              ("confirm", "After manual confirmation"),
              ("pause", "When pausing after autotext input"),
              ("continue", "When continue typing quickly after autotext")]
MODE_FOR_EXEC = {"immediate": AutotextMode.IMMEDIATE, "confirm": AutotextMode.CONFIRM,
                 "pause": AutotextMode.DELIMITER, "continue": AutotextMode.DELIMITER}
WINDOW_SCOPES = [("any", "any program"), ("program", "specific program")]
DELIMITERS = ["Default", "None", "Space", "Enter", "Tab", "Punctuation", "Any non-letter"]


def default_row(type_: str = "autotext") -> dict[str, Any]:
    return {"type": type_, "value": "", "case_sensitive": False, "word_pos": "start",
            "exec": "immediate" if type_ == "autotext" else "immediate",
            "lead_delim": "Default", "trail_delim": "None", "remove_trailing": False,
            "window_scope": "any", "enabled": True}


def row_to_trigger(row: dict) -> Trigger | None:
    kind = KIND_FOR_TYPE.get(row.get("type"))
    value = (row.get("value") or "").strip() if row.get("type") != "autotext" else (row.get("value") or "")
    if kind is None or not value:
        return None
    t = Trigger(kind=kind, value=value, enabled=row.get("enabled", True))
    if kind == TriggerKind.AUTOTEXT:
        t.mode = MODE_FOR_EXEC.get(row.get("exec", "immediate"), AutotextMode.DELIMITER)
        t.case_sensitive = bool(row.get("case_sensitive"))
        t.word_start_only = row.get("word_pos", "start") in ("start", "entire")
    return t


def trigger_to_row(t: Trigger) -> dict:
    row = default_row(TYPE_FOR_KIND.get(TriggerKind(t.kind), "autotext"))
    row["value"] = t.value
    row["enabled"] = t.enabled
    if TriggerKind(t.kind) == TriggerKind.AUTOTEXT:
        row["case_sensitive"] = t.case_sensitive
        row["word_pos"] = "start" if t.word_start_only else "middle"
        row["exec"] = {AutotextMode.IMMEDIATE: "immediate", AutotextMode.CONFIRM: "confirm",
                       AutotextMode.DELIMITER: "pause"}[AutotextMode(t.mode)]
    return row


class ExtrasStore:
    """Small JSON side-store in a settings key for data the models lack."""

    def __init__(self, store, key: str = "ui.trigger_extras"):
        self.store, self.key = store, key

    def _all(self) -> dict:
        try:
            return json.loads(self.store.setting(self.key, "") or "{}")
        except (ValueError, TypeError):
            return {}

    def get(self, owner: str, default=None):
        return self._all().get(owner, default)

    def put(self, owner: str, value) -> None:
        d = self._all()
        if value in (None, {}, []):
            d.pop(owner, None)
        else:
            d[owner] = value
        self.store.set_setting(self.key, json.dumps(d, ensure_ascii=False))


def rows_for_owner(extras: ExtrasStore, owner: str, db_triggers: list[Trigger]) -> list[dict]:
    """Prefer saved UI rows if they still agree with the database triggers."""
    saved = extras.get(owner) or {}
    rows = saved.get("rows") if isinstance(saved, dict) else None
    if rows:
        derived = [(TriggerKind(t.kind).value, t.value) for t in
                   (row_to_trigger(r) for r in rows) if t is not None]
        actual = [(TriggerKind(t.kind).value, t.value) for t in db_triggers]
        if derived == actual:
            return [dict(default_row(r.get("type", "autotext")), **r) for r in rows]
    return [trigger_to_row(t) for t in db_triggers]


# ---------------------------------------------------------------- dialogs
class ExpertOptionsDialog(QDialog):
    """Leading/trailing delimiter options for an autotext (15_dialog_autotext_expert_options)."""

    def __init__(self, row: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Expert options")
        lay = QVBoxLayout(self)
        intro = QLabel("Here you can configure characters that must be entered before\n"
                       "or after an Autotext to trigger the phrase.")
        lay.addWidget(intro)
        lay.addWidget(caption("Leading delimiter"))
        self.lead = QComboBox(); self.lead.addItems(DELIMITERS)
        self.lead.setCurrentText(row.get("lead_delim", "Default"))
        lay.addWidget(self._with_info(self.lead, "Characters required before the autotext."))
        lay.addWidget(caption("Trailing delimiter"))
        self.trail = QComboBox(); self.trail.addItems(DELIMITERS)
        self.trail.setCurrentText(row.get("trail_delim", "None"))
        lay.addWidget(self._with_info(self.trail, "Characters required after the autotext."))
        self.remove_trailing = QCheckBox("Remove trailing delimiter")
        self.remove_trailing.setChecked(bool(row.get("remove_trailing")))
        lay.addWidget(self.remove_trailing)
        self.trail.currentTextChanged.connect(self._sync)
        self._sync()
        lay.addSpacing(8)
        bottom = QHBoxLayout()
        reset = QPushButton("Reset to defaults")
        reset.clicked.connect(self._reset)
        bottom.addWidget(reset)
        bottom.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        bottom.addWidget(bb)
        lay.addLayout(bottom)

    @staticmethod
    def _with_info(w, tip):
        box = QWidget(); h = QHBoxLayout(box); h.setContentsMargins(0, 0, 0, 0)
        w.setFixedWidth(130); h.addWidget(w)
        info = QLabel(); info.setPixmap(icon("info").pixmap(16, 16)); info.setToolTip(tip)
        h.addWidget(info); h.addStretch(1)
        return box

    def _sync(self, *_):
        self.remove_trailing.setEnabled(self.trail.currentText() != "None")

    def _reset(self):
        self.lead.setCurrentText("Default"); self.trail.setCurrentText("None")
        self.remove_trailing.setChecked(False)

    def values(self) -> dict:
        return {"lead_delim": self.lead.currentText(), "trail_delim": self.trail.currentText(),
                "remove_trailing": self.remove_trailing.isChecked() and self.remove_trailing.isEnabled()}


class AddTagDialog(QDialog):
    """15_dialog_add_tag: 'Tag:' + help icon, one line edit, OK/Cancel."""

    def __init__(self, existing: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add new tag")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Tag:"))
        top.addStretch(1)
        help_ = QLabel(); help_.setPixmap(icon("help").pixmap(16, 16))
        help_.setToolTip("Tags group phrases across folders and are searchable.")
        top.addWidget(help_)
        lay.addLayout(top)
        self.edit = QComboBox(); self.edit.setEditable(True)
        self.edit.addItems(sorted(existing or []))
        self.edit.setCurrentText("")
        lay.addWidget(self.edit)
        lay.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def tag(self) -> str:
        return self.edit.currentText().strip()


# ---------------------------------------------------------------- one row
class TriggerRow(QWidget):
    changed = Signal()
    remove_requested = Signal(object)

    def __init__(self, row: dict | None = None, parent=None):
        super().__init__(parent)
        self.data = dict(default_row(), **(row or {}))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.type_combo = QComboBox()
        for key, label in TYPES:
            self.type_combo.addItem(label, key)
        self.type_combo.setFixedWidth(144)
        lay.addWidget(self.type_combo)

        self.stack = QStackedWidget()
        self.stack.setSizePolicy(self.stack.sizePolicy().horizontalPolicy(), self.stack.sizePolicy().verticalPolicy())
        self._pages: dict[str, QWidget] = {}
        self._build_pages()
        lay.addWidget(self.stack, 1)

        self.exec_button = QToolButton()
        self.exec_button.setIcon(icon("exec_mode"))
        self.exec_button.setAutoRaise(True)
        self.exec_button.setPopupMode(QToolButton.InstantPopup)
        self.exec_button.setMenu(self._exec_menu())
        self.exec_button.setStyleSheet("QToolButton::menu-indicator{image:none;width:0}")
        lay.addWidget(self.exec_button)
        self.remove_button = QToolButton()
        self.remove_button.setIcon(icon("remove"))
        self.remove_button.setAutoRaise(True)
        self.remove_button.setToolTip("Remove this trigger")
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self))
        lay.addWidget(self.remove_button)

        self.type_combo.currentIndexChanged.connect(self._type_changed)
        self.set_row(self.data)

    # -------------------------------------------------- pages
    def _build_pages(self):
        # autotext: field with inline word-position and case buttons
        self.autotext_edit = QLineEdit()
        self.word_action = QAction(icon("word_position"), "", self.autotext_edit)
        self.word_action.triggered.connect(self._show_word_menu)
        self.case_action = QAction(icon("case"), "", self.autotext_edit)
        self.case_action.setCheckable(True)
        self.case_action.toggled.connect(self._case_toggled)
        # trailing actions stack right-to-left: add Aa first so it ends up rightmost
        self.autotext_edit.addAction(self.case_action, QLineEdit.TrailingPosition)
        self.autotext_edit.addAction(self.word_action, QLineEdit.TrailingPosition)
        self.autotext_edit.textEdited.connect(lambda t: self._set("value", t))
        self._add_page("autotext", self.autotext_edit)

        self._add_page("smartcomplete", QWidget())   # no value; suggestion based on content

        self.regex_edit = QComboBox(); self.regex_edit.setEditable(True)
        self.regex_edit.lineEdit().textEdited.connect(lambda t: self._set("value", t))
        self._add_page("regex_autotext", self.regex_edit)

        self.hotkey = HotkeyPicker(clearable=False)
        self.hotkey.changed.connect(lambda v: self._set("value", v))
        self._add_page("hotkey", self.hotkey)

        win = QWidget(); wl = QHBoxLayout(win); wl.setContentsMargins(0, 0, 0, 0); wl.setSpacing(6)
        self.window_scope = QComboBox()
        for k, label in WINDOW_SCOPES:
            self.window_scope.addItem(label, k)
        self.window_scope.setFixedWidth(150)
        self.window_scope.currentIndexChanged.connect(
            lambda _i: self._set("window_scope", self.window_scope.currentData()))
        self.window_edit = QComboBox(); self.window_edit.setEditable(True)
        self.window_edit.lineEdit().setPlaceholderText("window title or program (e.g. notepad.exe)")
        self.window_edit.lineEdit().textEdited.connect(lambda t: self._set("value", t))
        wl.addWidget(self.window_scope); wl.addWidget(self.window_edit, 1)
        self._add_page("window", win)

        tw = QWidget(); tl = QHBoxLayout(tw); tl.setContentsMargins(0, 0, 0, 0)
        self.time_edit = QTimeEdit(); self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.setFixedWidth(72)
        from PySide6.QtCore import QLocale
        self.time_edit.setLocale(QLocale(QLocale.English, QLocale.UnitedStates))
        self.time_edit.timeChanged.connect(lambda t: self._set("value", t.toString("HH:mm")))
        tl.addWidget(self.time_edit); tl.addStretch(1)
        self._add_page("time", tw)

        self.clip_edit = QLineEdit()
        self.clip_edit.textEdited.connect(lambda t: self._set("value", t))
        self._add_page("clipboard", self.clip_edit)

        self.clip_regex_edit = QComboBox(); self.clip_regex_edit.setEditable(True)
        self.clip_regex_edit.lineEdit().textEdited.connect(lambda t: self._set("value", t))
        self._add_page("regex_clipboard", self.clip_regex_edit)

    def _add_page(self, key: str, w: QWidget):
        holder = QWidget(); h = QHBoxLayout(holder); h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(w, 1)
        self._pages[key] = holder
        self.stack.addWidget(holder)

    # -------------------------------------------------- menus
    def _word_menu(self) -> QMenu:
        m = QMenu(self)
        for key, label in WORD_POSITIONS:
            a = m.addAction(icon("word_position"), label)
            a.setCheckable(True)
            a.setChecked(self.data.get("word_pos") == key)
            a.triggered.connect(lambda _=False, k=key: self._set("word_pos", k, refresh=True))
        m.addSeparator()
        m.addAction("Expert options").triggered.connect(self.open_expert_options)
        m.addSeparator()
        m.addAction(icon("help"), "Help").triggered.connect(lambda: QMessageBox.information(
            self, "Autotext", "Choose where the autotext may appear inside a word.\n"
            "Start of a word is the default: the autotext must begin a word."))
        return m

    def _show_word_menu(self):
        m = self._word_menu()
        br = self.autotext_edit.mapToGlobal(self.autotext_edit.rect().bottomRight())
        br.setX(br.x() - m.sizeHint().width())
        m.exec(br)

    def _exec_menu(self) -> QMenu:
        m = QMenu(self)
        group = []
        for key, label in EXEC_MODES:
            a = m.addAction(icon("exec_mode"), label)
            a.setCheckable(True)
            a.setData(key)
            a.triggered.connect(lambda _=False, k=key: self._set("exec", k, refresh=True))
            group.append(a)
        m.addSeparator()
        m.addAction(icon("help"), "Help").triggered.connect(lambda: QMessageBox.information(
            self, "Execution", "Choose when the phrase runs after its trigger is detected."))
        m.aboutToShow.connect(lambda: [a.setChecked(a.data() == self.data.get("exec")) for a in group])
        return m

    def open_expert_options(self):
        dlg = ExpertOptionsDialog(self.data, self)
        if dlg.exec():
            self.data.update(dlg.values())
            self.changed.emit()

    # -------------------------------------------------- state
    def _set(self, key, value, refresh=False):
        if self.data.get(key) == value:
            return
        self.data[key] = value
        if refresh:
            self._refresh_icons()
        self.changed.emit()

    def _case_toggled(self, on: bool):
        self._set("case_sensitive", on)
        self._refresh_icons()

    def _type_changed(self, _i: int):
        t = self.type_combo.currentData()
        self.data["type"] = t
        self.data["value"] = ""
        self._load_value()
        self._refresh_icons()
        self.changed.emit()

    def _refresh_icons(self):
        t = self.data["type"]
        self.stack.setCurrentWidget(self._pages[t])
        self.exec_button.setVisible(t != "hotkey")
        self.case_action.blockSignals(True)
        self.case_action.setChecked(bool(self.data.get("case_sensitive")))
        self.case_action.blockSignals(False)
        self.case_action.setToolTip(
            "Case sensitivity is enabled. Click here to enable automatic capitalization."
            if self.data.get("case_sensitive") else
            "Automatic capitalization is enabled. Click here to make the autotext case sensitive.")
        pos = dict(WORD_POSITIONS).get(self.data.get("word_pos", "start"), "")
        self.word_action.setToolTip(f"Autotext position: {pos}")
        self.exec_button.setToolTip(dict(EXEC_MODES).get(self.data.get("exec", "immediate"), ""))

    def _load_value(self):
        t, v = self.data["type"], self.data.get("value", "")
        widgets = [self.autotext_edit, self.regex_edit, self.hotkey, self.window_edit,
                   self.window_scope, self.time_edit, self.clip_edit, self.clip_regex_edit]
        for w in widgets:
            w.blockSignals(True)
        try:
            if t == "autotext":
                self.autotext_edit.setText(v)
            elif t == "regex_autotext":
                self.regex_edit.setEditText(v)
            elif t == "hotkey":
                self.hotkey.set_value(v)
            elif t == "window":
                self.window_edit.setEditText(v)
                i = self.window_scope.findData(self.data.get("window_scope", "any"))
                self.window_scope.setCurrentIndex(max(0, i))
            elif t == "time":
                qt = QTime.fromString(v or "00:00", "HH:mm")
                self.time_edit.setTime(qt if qt.isValid() else QTime(0, 0))
                if not v:
                    self.data["value"] = "00:00"
            elif t == "clipboard":
                self.clip_edit.setText(v)
            elif t == "regex_clipboard":
                self.clip_regex_edit.setEditText(v)
        finally:
            for w in widgets:
                w.blockSignals(False)

    def set_row(self, row: dict):
        self.data = dict(default_row(row.get("type", "autotext")), **row)
        self.type_combo.blockSignals(True)
        self.type_combo.setCurrentIndex(max(0, self.type_combo.findData(self.data["type"])))
        self.type_combo.blockSignals(False)
        self._load_value()
        self._refresh_icons()

    def row(self) -> dict:
        return dict(self.data)


# ---------------------------------------------------------------- list of rows
class TriggerList(QWidget):
    """'Trigger' caption with ⊕ add menu, then one TriggerRow per trigger."""
    changed = Signal()

    def __init__(self, title: str = "Trigger", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        head = QHBoxLayout()
        cap = caption(title)
        cap.setTextFormat(Qt.RichText)
        cap.setText("<u>T</u>" + title[1:] if title.startswith("T") else title)
        head.addWidget(cap)
        head.addStretch(1)
        self.add_button = QToolButton()
        self.add_button.setIcon(icon("add"))
        self.add_button.setAutoRaise(True)
        self.add_button.setToolTip("Add another trigger")
        self.add_button.setPopupMode(QToolButton.InstantPopup)
        self.add_button.setStyleSheet("QToolButton::menu-indicator{image:none;width:0}")
        m = QMenu(self)
        for key, label in TYPES:
            m.addAction(label).triggered.connect(lambda _=False, k=key: self.add_row(default_row(k), focus=True))
        self.add_button.setMenu(m)
        head.addWidget(self.add_button)
        lay.addLayout(head)
        self._rows_lay = QVBoxLayout()
        self._rows_lay.setSpacing(4)
        lay.addLayout(self._rows_lay)
        self.rows: list[TriggerRow] = []

    def add_row(self, row: dict | None = None, focus: bool = False) -> TriggerRow:
        r = TriggerRow(row, self)
        r.changed.connect(self.changed)
        r.remove_requested.connect(self.remove_row)
        self._rows_lay.addWidget(r)
        self.rows.append(r)
        if focus:
            r.stack.currentWidget().setFocus()
            self.changed.emit()
        return r

    def remove_row(self, r: TriggerRow):
        if len(self.rows) == 1:          # keep one empty row, like PhraseExpress
            r.set_row(default_row("autotext"))
        else:
            self.rows.remove(r)
            r.setParent(None)
            r.deleteLater()
        self.changed.emit()

    def set_rows(self, rows: list[dict]):
        for r in self.rows:
            r.setParent(None)
            r.deleteLater()
        self.rows = []
        for row in rows or [default_row("autotext")]:
            self.add_row(row)

    def get_rows(self) -> list[dict]:
        return [r.row() for r in self.rows]

    def triggers(self) -> list[Trigger]:
        return [t for t in (row_to_trigger(r) for r in self.get_rows()) if t is not None]

    def meaningful_rows(self) -> list[dict]:
        """Rows worth remembering (drops the empty default autotext row)."""
        return [r for r in self.get_rows()
                if r.get("value") or r.get("type") not in ("autotext", "regex_autotext", "clipboard",
                                                            "regex_clipboard", "window")]
