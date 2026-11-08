"""Modal prompts used by the macro engine. Main (GUI) thread only.

Each function returns the value or raises host.Cancelled.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import QDate, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCalendarWidget, QCheckBox, QComboBox, QDateEdit, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QVBoxLayout, QWidget,
)

from phraseforge.ui import pe_style
from phraseforge.host import Cancelled, FormField
from phraseforge.ui.i18n import tr


def _prep(dlg: QDialog) -> None:
    dlg.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    dlg.setWindowFlag(Qt.WindowContextHelpButtonHint, False)


def _exec(dlg: QDialog) -> bool:
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    return dlg.exec() == QDialog.Accepted


def _buttons(dlg: QDialog) -> QDialogButtonBox:
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.button(QDialogButtonBox.Ok).setText(tr("OK"))
    bb.button(QDialogButtonBox.Ok).setObjectName("primary")
    bb.button(QDialogButtonBox.Cancel).setText(tr("Cancel"))
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    return bb


# ---------------------------------------------------------------- input
class InputDialog(QDialog):
    def __init__(self, prompt: str, default: str = "", multiline: bool = False, parent=None):
        super().__init__(parent)
        _prep(self)
        self.setWindowTitle("PhraseForge")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(prompt))
        if multiline:
            self.edit = QPlainTextEdit(default)
            self.edit.setMinimumSize(420, 160)
        else:
            self.edit = QLineEdit(default)
            self.edit.setMinimumWidth(360)
            self.edit.selectAll()
        lay.addWidget(self.edit)
        lay.addWidget(_buttons(self))

    def value(self) -> str:
        e = self.edit
        return e.toPlainText() if isinstance(e, QPlainTextEdit) else e.text()


def ask_input(prompt: str, default: str = "", multiline: bool = False) -> str:
    dlg = InputDialog(prompt, default, multiline)
    if not _exec(dlg):
        raise Cancelled()
    return dlg.value()


# ---------------------------------------------------------------- forms
class CheckCombo(QComboBox):
    """Drop-down list with a checkbox per item ({#formcheckcombo}); the box shows the checked items."""

    changed = Signal()

    def __init__(self, options: list[str], checked: list[str], parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        model = QStandardItemModel(self)
        for o in options:
            it = QStandardItem(o)
            it.setFlags(Qt.ItemIsEnabled)        # we toggle on press; no second toggle by the view
            it.setData(Qt.Checked if o in checked else Qt.Unchecked, Qt.CheckStateRole)
            model.appendRow(it)
        self.setModel(model)
        self.view().pressed.connect(self._toggle)
        self._refresh()

    def _toggle(self, index) -> None:
        it = self.model().itemFromIndex(index)
        on = it.data(Qt.CheckStateRole) == Qt.Checked
        it.setData(Qt.Unchecked if on else Qt.Checked, Qt.CheckStateRole)
        self._refresh()
        self.changed.emit()

    def set_checked(self, items: list[str]) -> None:
        m = self.model()
        for i in range(m.rowCount()):
            m.item(i).setData(Qt.Checked if m.item(i).text() in items else Qt.Unchecked, Qt.CheckStateRole)
        self._refresh()
        self.changed.emit()

    def checked(self) -> list[str]:
        m = self.model()
        return [m.item(i).text() for i in range(m.rowCount()) if m.item(i).data(Qt.CheckStateRole) == Qt.Checked]

    def _refresh(self) -> None:
        self.lineEdit().setText(", ".join(self.checked()))

    def hidePopup(self) -> None:
        super().hidePopup()
        self._refresh()          # picking an item would otherwise show only that item's text


class FormDialog(QDialog):
    """Builds a fill-in form from FormFields. values() returns {name: value}."""

    def __init__(self, title: str, fields: list[FormField], parent=None):
        super().__init__(parent)
        _prep(self)
        self.setWindowTitle(title or "PhraseForge")
        self.fields = fields
        self.widgets: dict[str, Any] = {}
        outer = QVBoxLayout(self)
        form = QFormLayout()
        outer.addLayout(form)
        for f in fields:
            label = f.label or f.name
            k = f.kind
            if k == "label":
                form.addRow(QLabel(str(f.default or label)))
                continue
            if k == "group":                  # {#formgroup}: fields go into a frame until groupend
                box = QGroupBox(label)
                box.setCheckable(f.checkable)
                inner = QWidget()
                form = QFormLayout(inner)
                form.setContentsMargins(0, 0, 0, 0)
                bl = QVBoxLayout(box)
                bl.addWidget(inner)
                if f.checkable:
                    box.setChecked(bool(f.default))
                    inner.setVisible(bool(f.default))
                    box.toggled.connect(inner.setVisible)
                    box.toggled.connect(lambda _on: (self._validate(), self.adjustSize()))
                outer.addWidget(box)
                self.widgets[f.name] = box
                continue
            if k == "groupend":
                form = QFormLayout()
                outer.addLayout(form)
                continue
            if k == "checkcombo":
                w = CheckCombo(f.options, list(f.default or []))
            elif k == "edit":
                w = QLineEdit(str(f.default or ""))
            elif k == "memo":
                w = QPlainTextEdit(str(f.default or ""))
                w.setMinimumHeight(90)
            elif k == "combo":
                w = QComboBox()
                w.setEditable(True)
                w.addItems(f.options)
                if f.default:
                    w.setCurrentText(str(f.default))
            elif k == "checkbox":
                w = QCheckBox()
                w.setChecked(str(f.default).lower() in ("1", "true", "yes", "on"))
            elif k == "radio":
                w = QWidget()
                hl = QHBoxLayout(w)
                hl.setContentsMargins(0, 0, 0, 0)
                grp = QButtonGroup(w)
                for i, opt in enumerate(f.options):
                    rb = QRadioButton(opt)
                    grp.addButton(rb, i)
                    hl.addWidget(rb)
                    if opt == f.default or (not f.default and i == 0):
                        rb.setChecked(True)
                w.group = grp  # type: ignore[attr-defined]
            elif k == "date":
                w = QDateEdit()
                w.setCalendarPopup(True)
                d = QDate.fromString(str(f.default), Qt.ISODate) if f.default else QDate.currentDate()
                w.setDate(d if d.isValid() else QDate.currentDate())
                w.setDisplayFormat("yyyy-MM-dd")
            elif k == "number":
                w = QDoubleSpinBox()
                w.setRange(-1e12, 1e12)
                w.setDecimals(4)
                try:
                    w.setValue(float(f.default or 0))
                except ValueError:
                    pass
            else:
                w = QLineEdit(str(f.default or ""))
            self.widgets[f.name] = w
            form.addRow(label + (" *" if f.required else ""), w)
            self._watch(w)
        self.error = QLabel()
        self.error.setObjectName("formError")
        self.error.setStyleSheet("color: #c0392b;")
        self.error.setWordWrap(True)
        self.error.hide()
        outer.addWidget(self.error)
        self.buttons = _buttons(self)
        outer.addWidget(self.buttons)
        self.setMinimumWidth(420)
        self._validate()

    def _watch(self, w) -> None:
        for sig in ("textChanged", "currentTextChanged", "toggled", "dateChanged", "valueChanged", "changed"):
            s = getattr(w, sig, None)
            if s is not None and hasattr(s, "connect"):
                s.connect(lambda *_a: self._validate())
        grp = getattr(w, "group", None)          # radio row; QCheckBox.group() is a Qt method
        if isinstance(grp, QButtonGroup):
            grp.buttonToggled.connect(lambda *_a: self._validate())

    def errors(self) -> list[str]:
        """Problems with the current entries; hidden (closed-group) fields are skipped."""
        from phraseforge.formcheck import field_error
        vals = self.values()
        closed = {f.name for f in self.fields if f.kind == "group" and f.checkable and not vals.get(f.name)}
        out = []
        for f in self.fields:
            if f.kind in ("label", "group", "groupend") or f.group in closed:
                continue
            if f.required or f.validate:
                msg = field_error(f, vals.get(f.name))
                if msg:
                    out.append(msg)
        return out

    def _validate(self) -> None:
        if not hasattr(self, "buttons"):
            return
        errs = self.errors()
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(not errs)
        self.error.setText(errs[0] if errs else "")
        self.error.setVisible(bool(errs))

    def accept(self) -> None:
        if self.errors():            # Enter in a line edit must not get past the check
            self._validate()
            return
        super().accept()

    def values(self) -> dict[str, Any]:
        from phraseforge.formcheck import clean_value
        out: dict[str, Any] = {}
        for f in self.fields:
            w = self.widgets.get(f.name)
            if w is None:
                continue
            if isinstance(w, CheckCombo):
                out[f.name] = w.checked()
            elif isinstance(w, QGroupBox):
                out[f.name] = w.isChecked() if w.isCheckable() else True
            elif isinstance(w, QLineEdit):
                out[f.name] = w.text()
            elif isinstance(w, QPlainTextEdit):
                out[f.name] = w.toPlainText()
            elif isinstance(w, QComboBox):
                out[f.name] = w.currentText()
            elif isinstance(w, QCheckBox):
                out[f.name] = w.isChecked()
            elif isinstance(w, QDateEdit):
                out[f.name] = w.date().toString(Qt.ISODate)
            elif isinstance(w, QDoubleSpinBox):
                v = w.value()
                out[f.name] = int(v) if v.is_integer() else v
            elif hasattr(w, "group"):
                b = w.group.checkedButton()
                out[f.name] = b.text() if b else ""
            if f.name in out:
                out[f.name] = clean_value(f, out[f.name])
        return out


def show_form(title: str, fields: list[FormField]) -> dict[str, Any]:
    dlg = FormDialog(title, fields)
    if not _exec(dlg):
        raise Cancelled()
    return dlg.values()


# ---------------------------------------------------------------- choose
class ChooseDialog(QDialog):
    def __init__(self, prompt: str, options: list[str], multi: bool = False, parent=None):
        super().__init__(parent)
        _prep(self)
        self.setWindowTitle("PhraseForge")
        self.multi = multi
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(prompt))
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(tr("Search"))
        lay.addWidget(self.filter)
        self.list = QListWidget()
        for o in options:
            it = QListWidgetItem(o)
            if multi:
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Unchecked)
            self.list.addItem(it)
        if options:
            self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(lambda _i: (not multi) and self.accept())
        lay.addWidget(self.list)
        lay.addWidget(_buttons(self))
        self.filter.textChanged.connect(self._filter)

    def _filter(self, text: str) -> None:
        t = text.lower()
        first = None
        for i in range(self.list.count()):
            it = self.list.item(i)
            hide = t not in it.text().lower()
            it.setHidden(hide)
            if not hide and first is None:
                first = i
        if first is not None:
            self.list.setCurrentRow(first)

    def selected(self) -> list[str]:
        if self.multi:
            return [self.list.item(i).text() for i in range(self.list.count())
                    if self.list.item(i).checkState() == Qt.Checked]
        it = self.list.currentItem()
        return [it.text()] if it else []


def choose(prompt: str, options: list[str], multi: bool = False) -> list[str]:
    dlg = ChooseDialog(prompt, options, multi)
    if not _exec(dlg):
        raise Cancelled()
    return dlg.selected()


# ---------------------------------------------------------------- date
def pick_date(prompt: str, default_iso: str = "") -> str:
    dlg = QDialog()
    _prep(dlg)
    dlg.setWindowTitle("PhraseForge")
    lay = QVBoxLayout(dlg)
    lay.addWidget(QLabel(prompt))
    cal = QCalendarWidget()
    d = QDate.fromString(default_iso, Qt.ISODate) if default_iso else QDate.currentDate()
    cal.setSelectedDate(d if d.isValid() else QDate.currentDate())
    cal.activated.connect(lambda _d: dlg.accept())
    lay.addWidget(cal)
    lay.addWidget(_buttons(dlg))
    if not _exec(dlg):
        raise Cancelled()
    return cal.selectedDate().toString(Qt.ISODate)


# ---------------------------------------------------------------- message
def message(text: str, title: str = "") -> None:
    box = QMessageBox(QMessageBox.Information, title or "PhraseForge", text)
    box.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    box.exec()


# ---------------------------------------------------------------- confirm expand
class ConfirmTip(QDialog):
    """Small frameless tip near the caret: Enter/click = expand, Esc = skip."""

    def __init__(self, description: str, parent=None, timeout_ms: int = 6000):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setObjectName("popupFrame")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.addWidget(QLabel(f"↵ {description}"))
        b = QPushButton(tr("OK"))
        b.setObjectName("primary")
        b.clicked.connect(self.accept)
        lay.addWidget(b)
        pe_style.primary(b).setDefault(True)
        QTimer.singleShot(timeout_ms, self.reject)
        pos = QCursor.pos() + QPoint(12, 18)
        self.move(pos)


def confirm_expand(description: str) -> bool:
    return _exec(ConfirmTip(description))


def ask_folder_password(store, folder, parent=None) -> bool:
    """Ask for a locked folder's password; True once it is unlocked (security.LOCKS)."""
    from phraseforge.security import LOCKS
    from PySide6.QtWidgets import QInputDialog
    pw, ok = QInputDialog.getText(parent, tr("Password"), tr('Password for "{name}":').format(name=folder.name),
                                  QLineEdit.Password)
    if not ok:
        return False
    if LOCKS.try_unlock(store, folder, pw):
        return True
    QMessageBox.warning(parent, tr("Password"), tr("Wrong password."))
    return False


ALLOW_ONCE, ALLOW_ALWAYS = "once", "always"


def approve_phrase(description: str, origin: str, reasons: list[str]) -> str:
    """Ask before an imported/synced phrase runs privileged macros.
    Returns ALLOW_ONCE, ALLOW_ALWAYS or "" (do not run)."""
    where = tr("was imported") if origin == "imported" else tr("came from cloud sync")
    box = QMessageBox()
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle(tr("Run this phrase?"))
    box.setText(tr('The phrase "{name}" {where} and has not been approved on this PC.').format(
        name=description, where=where))
    box.setInformativeText(tr("It wants to:") + "\n• " + "\n• ".join(tr(r) for r in reasons)
                           + "\n\n" + tr("Only allow it if you trust where it came from."))
    once = box.addButton(tr("Run once"), QMessageBox.AcceptRole)
    always = box.addButton(tr("Always allow"), QMessageBox.AcceptRole)
    cancel = box.addButton(tr("Do not run"), QMessageBox.RejectRole)
    box.setDefaultButton(cancel)
    box.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    box.exec()
    clicked = box.clickedButton()
    return ALLOW_ONCE if clicked is once else ALLOW_ALWAYS if clicked is always else ""
