"""Declarative framework for macro dialogs (look of PhraseExpress's macro dialogs).

A MacroSpec lists fields; MacroDialog renders them:

    ┌ Title ─────────────────────────────────────────┐
    │ Name: [Date/Time        ]                   (?) │  <- grey header band
    │ description text                                │
    │ fields (label above, or label left for "form") │
    │ [⊕ Process output]                 [OK][Cancel] │
    └─────────────────────────────────────────────────┘

Fields are small dataclasses. build(values) -> macro text; parse(args, opts) -> values
re-opens a dialog pre-filled from an existing macro token.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from PySide6.QtCore import QDate, Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDateEdit, QDialog, QFileDialog, QFormLayout,
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QMenu,
    QPlainTextEdit, QPushButton, QRadioButton, QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from phraseforge.ui.iconset import icon

# ---------------------------------------------------------------- context (set by the app)
_CONTEXT: dict[str, Any] = {"store": None, "settings": {}}


def set_context(store=None, settings: dict | None = None) -> None:
    """Give dialogs access to the phrase store (phrase/folder pickers, variables)."""
    _CONTEXT["store"] = store
    if settings is not None:
        _CONTEXT["settings"] = settings


def get_store():
    return _CONTEXT.get("store")


# ---------------------------------------------------------------- quoting helpers
def q(s: Any) -> str:
    """Quote a value as one macro argument. Nested {#macros} are kept verbatim
    (the parser reads them with their own quoting); plain text is escaped."""
    s = "" if s is None else str(s)
    out, i = [], 0
    while i < len(s):
        if s.startswith("{#", i):
            end = _outer_end(s[i:])
            if end > 0:
                out.append(s[i:i + end + 1])
                i += end + 1
                continue
        if s.startswith("{{", i):
            out.append("{{")
            i += 2
            continue
        c = s[i]
        out.append({'"': '\\"', "{": "{{"}.get(c, c))   # backslash only escapes a quote
        i += 1
    text = "".join(out)
    if text.endswith("\\") and not text.endswith('\\"'):
        text += "."          # "C:\" would read as an escaped quote; "C:\." is the same folder
    return '"' + text + '"'


def opt(name: str, value: Any, default: Any = None) -> str:
    """' -name "value"' or '' when empty / equal to the default; True -> flag."""
    if value is True:
        return f" -{name}"
    if value in (None, "", False) or (default is not None and str(value) == str(default)):
        return ""
    return f" -{name} {q(value)}"


def call(name: str, *args: Any, **opts: Any) -> str:
    """Build '{#name "a" "b" -opt "v"}'; trailing empty args are dropped."""
    a = list(args)
    while a and a[-1] in (None, ""):
        a.pop()
    s = "{#" + name + "".join(" " + q(x) for x in a)
    for k, v in opts.items():
        s += opt(k.rstrip("_"), v)
    return s + "}"


def add_caption(macro: str, caption: str) -> str:
    """Store the dialog's Name as -caption on the outermost macro (not for blocks)."""
    if not caption or not macro.startswith("{#") or not macro.endswith("}"):
        return macro
    head = re.match(r"\{#(\w+)", macro)
    if not head or head.group(1).lower() in ("if", "loop", "foreach", "form") or macro.count("{#") > 1 and \
            _outer_end(macro) != len(macro) - 1:
        return macro
    return macro[:-1] + f" -caption {q(caption)}}}"


def _outer_end(s: str) -> int:
    """Index of the '}' closing the macro that starts at 0 (-1 if not balanced)."""
    depth, i, inq = 0, 0, False
    while i < len(s):
        c = s[i]
        if c == "\\" and inq:
            i += 2
            continue
        if c == '"':
            inq = not inq
        elif s.startswith("{#", i):
            depth += 1
            i += 2
            continue
        elif c == "}" and depth:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


# ---------------------------------------------------------------- field descriptors
@dataclass
class Field:
    key: str = ""
    label: str = ""
    default: Any = ""
    required: bool = False
    enabled_if: tuple | None = None   # (key, predicate_value or callable)
    visible_if: tuple | None = None
    tip: str = ""


@dataclass
class Line(Field):
    placeholder: str = ""
    width: int | None = None
    pencil: bool = False              # small pencil button: edit in a bigger box
    password: bool = False


@dataclass
class Memo(Field):
    height: int = 70
    placeholder: str = ""
    macro_menu: bool = True           # right-click inserts a macro


@dataclass
class Spin(Field):
    minimum: int = 0
    maximum: int = 999_999_999
    suffix: str = ""
    width: int = 120


@dataclass
class Combo(Field):
    options: list = field(default_factory=list)   # [text] or [(text, value)]
    editable: bool = False
    width: int | None = None
    options_fn: Callable[[], list] | None = None


@dataclass
class Check(Field):
    pass


@dataclass
class Radio(Field):
    options: list = field(default_factory=list)   # [(text, value)]
    title: str = ""                                # group box title ('' = no box)


@dataclass
class FilePath(Field):
    mode: str = "open"                # open | save | dir
    filter: str = "All files (*)"


@dataclass
class Text(Field):
    """Static description text."""
    text: str = ""


@dataclass
class Group(Field):
    title: str = ""
    fields: list = field(default_factory=list)


@dataclass
class Row(Field):
    fields: list = field(default_factory=list)


@dataclass
class Column(Field):
    """Vertical stack without a border (use inside Row for two-column dialogs)."""
    fields: list = field(default_factory=list)
    stretch: int = 0


@dataclass
class PickPhrase(Field):
    """'Select phrase' / 'Select folder' link; value = phrase description or folder path."""
    kind: str = "phrase"              # phrase | folder | either


@dataclass
class ListPick(Field):
    """List box of presets (value = selected item's value)."""
    options: list = field(default_factory=list)   # [(text, value)]
    height: int = 260
    width: int = 160


@dataclass
class Button(Field):
    """Push button calling action(dialog)."""
    action: Callable | None = None


@dataclass
class Preview(Field):
    """Live preview box: text = preview(values)."""
    fn: Callable[[dict], str] | None = None
    big: bool = True


@dataclass
class Custom(Field):
    """Any widget: factory(dialog) -> (widget, getter, setter)."""
    factory: Callable | None = None


# ---------------------------------------------------------------- spec
@dataclass
class MacroSpec:
    kind: str
    title: str
    build: Callable[[dict], str]
    fields: list = field(default_factory=list)
    description: str = ""
    name: str | None = None            # default Name: text (None = title)
    commands: tuple = ()               # macro command names this spec edits
    parse: Callable[[list, dict], dict] | None = None
    layout: str = "stacked"            # stacked | form
    process_output: bool = True
    show_name: bool = True
    width: int = 368
    menu_text: str = ""                # text in the dropdown menu (default title)
    shortcut: str = ""
    direct: bool = False               # no dialog: build({}) is inserted directly
    help: str = ""
    name_fn: Callable[[dict], str] | None = None   # derive Name from values (e.g. "Wait 3000 milliseconds")
    hooks: dict = field(default_factory=dict)      # key -> fn(dialog, new_value) when that field changes
    init: Callable | None = None                   # fn(dialog) after building (extra wiring)


# ---------------------------------------------------------------- preview engine
class PreviewHost:
    """Non-interactive host for live previews inside dialogs."""

    def __init__(self):
        self.settings = dict(_CONTEXT.get("settings") or {})

    def ask_input(self, prompt, default="", multiline=False):
        return default

    def show_form(self, title, fields):
        return {f.name: f.default for f in fields}

    def choose(self, prompt, options, multi=False):
        return options[:1]

    def pick_date(self, prompt, default_iso):
        return default_iso

    def message(self, text, title=""):
        return None

    def select_screen_region(self):
        return None

    def get_clipboard(self):
        return "[clipboard]"

    def set_clipboard(self, text):
        return None

    def clipboard_history(self, index):
        return f"[clipboard {index}]"

    def phrase_content(self, key):
        return (f"[{key}]", "text")

    def get_var(self, name, scope="global"):
        store = get_store()
        return store.get_var(name, scope) if store is not None else ""

    def set_var(self, name, value, scope="global"):
        return None

    def run_program(self, *a, **k):
        return 0

    def open_target(self, target):
        return None

    def wait_for_window(self, *a, **k):
        return True

    def focused_app(self):
        return ("app.exe", "Window")

    def http_request(self, *a, **k):
        return "[http]"

    def ai_complete(self, prompt, provider="", model="", system=""):
        return "[AI]"

    def ocr_region(self, *a, **k):
        return "[OCR]"

    def ocr_image(self, *a, **k):
        return "[OCR]"

    def setting(self, key, default=""):
        return self.settings.get(key, default)


def preview_macro(macro: str) -> str:
    try:
        from phraseforge.macros import MacroEngine
        return MacroEngine(PreviewHost(), get_store()).expand_to_text(macro)
    except Exception as e:  # preview must never break the dialog
        return f"[{e}]"


# ---------------------------------------------------------------- widgets
class MacroTextEdit(QPlainTextEdit):
    """Multi-line field whose right-click menu can insert macros."""

    def __init__(self, macro_menu: bool = True, parent=None):
        super().__init__(parent)
        self._macro_menu = macro_menu

    def contextMenuEvent(self, ev):
        m = self.createStandardContextMenu()
        if self._macro_menu:
            from phraseforge.ui import macro_ui
            m.addSeparator()
            sub = m.addMenu(icon("m_programming"), "Insert macro")
            for title, menu in macro_ui.macro_menus(sub, self.insertPlainText, nested=True).items():
                menu.setTitle(title)
                sub.addMenu(menu)
        m.exec(ev.globalPos())


class MacroLineEdit(QLineEdit):
    def contextMenuEvent(self, ev):
        m = self.createStandardContextMenu()
        from phraseforge.ui import macro_ui
        m.addSeparator()
        sub = m.addMenu(icon("m_programming"), "Insert macro")
        for title, menu in macro_ui.macro_menus(sub, self.insert, nested=True).items():
            menu.setTitle(title)
            sub.addMenu(menu)
        m.exec(ev.globalPos())


class LinkLabel(QLabel):
    clicked = Signal()

    def __init__(self, text: str, parent=None):
        super().__init__(f'<a href="#">{text}</a>', parent)
        self.setObjectName("Hyperlink")
        self.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.linkActivated.connect(lambda _: self.clicked.emit())


def pick_phrase_or_folder(parent, kind: str = "phrase") -> str | None:
    """Tree picker over the store; falls back to typing the name."""
    store = get_store()
    if store is None:
        text, ok = QInputDialog.getText(parent, "Select " + kind, "Phrase description:" if kind == "phrase"
                                        else "Folder path (A/B):")
        return text if ok and text else None
    from PySide6.QtWidgets import QDialogButtonBox, QTreeWidget, QTreeWidgetItem
    dlg = QDialog(parent)
    dlg.setWindowTitle("Select phrase" if kind == "phrase" else "Select folder")
    dlg.resize(380, 460)
    lay = QVBoxLayout(dlg)
    tree = QTreeWidget()
    tree.setHeaderHidden(True)
    lay.addWidget(tree)

    def add(parent_item, folder_id, path):
        for f in store.folders(folder_id):
            it = QTreeWidgetItem([f.name])
            it.setIcon(0, icon("folder"))
            p = f"{path}/{f.name}" if path else f.name
            it.setData(0, Qt.UserRole, ("folder", p))
            (parent_item.addChild(it) if parent_item else tree.addTopLevelItem(it))
            add(it, f.id, p)
        if kind != "folder":
            for ph in store.phrases(folder_id):
                it = QTreeWidgetItem([ph.description])
                it.setIcon(0, icon("phrase"))
                it.setData(0, Qt.UserRole, ("phrase", ph.description))
                (parent_item.addChild(it) if parent_item else tree.addTopLevelItem(it))
    add(None, None, "")
    tree.expandToDepth(0)
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    lay.addWidget(bb)
    tree.itemDoubleClicked.connect(lambda *_: dlg.accept())
    if dlg.exec() != QDialog.Accepted or not tree.currentItem():
        return None
    k, v = tree.currentItem().data(0, Qt.UserRole)
    if kind in ("phrase", "folder") and k != kind:
        return None
    return v


PROCESS_OUTPUT = [
    ("Convert to UPPER CASE", "upper"), ("Convert to lower case", "lower"),
    ("Begin sentences with uppercase", "sentence"), ("UPPER CASE first character", "ucfirst"),
    ("UPPER CASE first char of each word", "ucwords"), ("Trim", "trim"), ("Text length", "length"),
    None,
    ("URL encode", "urlencode"), ("HTML encode", "htmlencode"), ("Base64 encode", "base64"),
    None,
    ("Put into clipboard", "setclipboard"), ("Store in variable...", "set"),
    ("Translate (AI)...", "translate"),
]


# ---------------------------------------------------------------- dialog
class MacroDialog(QDialog):
    def __init__(self, spec: MacroSpec, values: dict | None = None, caption: str = "", parent=None):
        super().__init__(parent)
        self.spec = spec
        self.setWindowTitle(spec.title)
        self.setMinimumWidth(spec.width)
        self.getters: dict[str, Callable[[], Any]] = {}
        self.setters: dict[str, Callable[[Any], None]] = {}
        self.widgets: dict[str, QWidget] = {}
        self.deps: list[tuple[QWidget, tuple, str]] = []
        self.previews: list[tuple[QLabel, Callable]] = []
        self.process: tuple[str, str] | None = None       # (op, extra)
        self.result_text: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 10)
        root.setSpacing(6)
        # header band
        self.name_edit = QLineEdit(caption or spec.name or spec.title)
        if spec.show_name:
            band = QFrame()
            band.setObjectName("MacroHeader")
            band.setAttribute(Qt.WA_StyledBackground, True)
            band.setStyleSheet("#MacroHeader { background: #e3e3e3; border: none; }")
            hb = QHBoxLayout(band)
            hb.setContentsMargins(16, 8, 12, 8)
            lab = QLabel("Name:")
            lab.setStyleSheet("font-weight: 600;")
            hb.addWidget(lab)
            self.name_edit.setFixedWidth(186)
            self.name_edit.selectAll()
            hb.addWidget(self.name_edit)
            hb.addStretch(1)
            help_btn = QToolButton()
            help_btn.setIcon(icon("help"))
            help_btn.setAutoRaise(True)
            help_btn.setToolTip(spec.help or spec.description or spec.title)
            help_btn.clicked.connect(self._help)
            hb.addWidget(help_btn)
            root.addWidget(band)
        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(16, 4, 16, 0)
        self.body.setSpacing(4)
        if spec.description:
            d = QLabel(spec.description)
            d.setWordWrap(True)
            self.body.addWidget(d)
            self.body.addSpacing(6)
        if spec.layout == "form":
            form = QFormLayout()
            form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
            form.setHorizontalSpacing(6)
            for f in spec.fields:
                self._add_form_field(form, f)
            self.body.addLayout(form)
        else:
            for f in spec.fields:
                self._add_field(self.body, f)
        self.body.addStretch(1)
        root.addWidget(body, 1)
        # footer
        foot = QHBoxLayout()
        foot.setContentsMargins(16, 6, 12, 0)
        if spec.process_output:
            self.process_btn = QPushButton(icon("process"), "Process output")
            self.process_btn.setMinimumWidth(172)
            self.process_btn.setMenu(self._process_menu())
            foot.addWidget(self.process_btn)
        foot.addStretch(1)
        self.ok_btn = QPushButton("OK")
        self.ok_btn.setDefault(True)
        self.ok_btn.clicked.connect(self._accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        foot.addWidget(self.ok_btn)
        foot.addWidget(cancel)
        root.addLayout(foot)

        if spec.init:
            spec.init(self)
        if values:
            self._loading = True
            self.set_values(values)
            self._loading = False
        self._refresh()
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    # -------------------------------------------------- building
    def _register(self, f: Field, w: QWidget, getter, setter, signal=None):
        if f.key:
            self.getters[f.key] = getter
            self.setters[f.key] = setter
            self.widgets[f.key] = w
            if f.default not in (None, "") or isinstance(f.default, (bool, int)):
                try:
                    setter(f.default)
                except Exception:
                    pass
        if f.enabled_if:
            self.deps.append((w, f.enabled_if, "enabled"))
        if f.visible_if:
            self.deps.append((w, f.visible_if, "visible"))
        if f.tip:
            w.setToolTip(f.tip)
        if signal is not None:
            hook = self.spec.hooks.get(f.key) if f.key else None
            if hook is not None:
                signal.connect(lambda *_, hook=hook, getter=getter: not getattr(self, "_loading", False)
                               and hook(self, getter()))
            signal.connect(lambda *_: self._refresh())

    def _make(self, f: Field) -> QWidget | None:
        """Create the editor widget for a field (without its caption)."""
        if isinstance(f, Line):
            w = MacroLineEdit()
            if f.placeholder:
                w.setPlaceholderText(f.placeholder)
            if f.width:
                w.setFixedWidth(f.width)
            if f.password:
                w.setEchoMode(QLineEdit.Password)
            self._register(f, w, w.text, lambda v, w=w: w.setText(str(v)), w.textChanged)
            if f.pencil:
                box = QWidget()
                h = QHBoxLayout(box)
                h.setContentsMargins(0, 0, 0, 0)
                h.setSpacing(0)
                h.addWidget(w)
                b = QToolButton()
                b.setIcon(icon("pencil"))
                b.setAutoRaise(True)
                b.clicked.connect(lambda _=False, w=w: self._edit_big(w))
                h.addWidget(b)
                return box
            return w
        if isinstance(f, Memo):
            w = MacroTextEdit(f.macro_menu)
            w.setFixedHeight(f.height) if f.height < 200 else w.setMinimumHeight(f.height)
            if f.placeholder:
                w.setPlaceholderText(f.placeholder)
            self._register(f, w, w.toPlainText, lambda v, w=w: w.setPlainText(str(v)), w.textChanged)
            return w
        if isinstance(f, Spin):
            w = QSpinBox()
            w.setRange(f.minimum, f.maximum)
            w.setFixedWidth(f.width)
            if f.suffix:
                box = QWidget()
                h = QHBoxLayout(box)
                h.setContentsMargins(0, 0, 0, 0)
                h.addWidget(w)
                h.addWidget(QLabel(f.suffix))
                h.addStretch(1)
                self._register(f, w, w.value, lambda v, w=w: w.setValue(int(v or 0)), w.valueChanged)
                return box
            self._register(f, w, w.value, lambda v, w=w: w.setValue(int(v or 0)), w.valueChanged)
            return w
        if isinstance(f, Combo):
            w = QComboBox()
            w.setEditable(f.editable)
            opts = f.options_fn() if f.options_fn else f.options
            for o in opts:
                text, value = (o if isinstance(o, tuple) else (o, o))
                w.addItem(text, value)
            if f.width:
                w.setFixedWidth(f.width)

            def get(w=w, editable=f.editable):
                if editable:
                    t = w.currentText()
                    i = w.findText(t)
                    return w.itemData(i) if i >= 0 and w.itemData(i) is not None else t
                return w.currentData()

            def setv(v, w=w):
                i = w.findData(v)
                if i < 0:
                    i = w.findText(str(v))
                if i >= 0:
                    w.setCurrentIndex(i)
                elif w.isEditable():
                    w.setEditText(str(v))
            self._register(f, w, get, setv, w.currentTextChanged)
            return w
        if isinstance(f, Check):
            w = QCheckBox(f.label)
            self._register(f, w, w.isChecked, lambda v, w=w: w.setChecked(bool(v) and v not in ("0", "false")),
                           w.toggled)
            return w
        if isinstance(f, Radio):
            box = QGroupBox(f.title) if f.title else QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(8 if f.title else 0, 4, 4, 4)
            v.setSpacing(3)
            grp = QButtonGroup(box)
            buttons = []
            for text, value in f.options:
                rb = QRadioButton(text)
                rb.setProperty("value", value)
                grp.addButton(rb)
                v.addWidget(rb)
                buttons.append(rb)
            if buttons:
                buttons[0].setChecked(True)

            def get(buttons=buttons):
                for b in buttons:
                    if b.isChecked():
                        return b.property("value")
                return None

            def setv(val, buttons=buttons):
                for b in buttons:
                    if str(b.property("value")) == str(val):
                        b.setChecked(True)
            self._register(f, box, get, setv, grp.buttonToggled)
            box.setProperty("radio_buttons", buttons)
            return box
        if isinstance(f, FilePath):
            box = QWidget()
            h = QHBoxLayout(box)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(6)
            w = MacroLineEdit()
            h.addWidget(w)
            b = QToolButton()
            b.setIcon(icon("folder_open"))
            b.clicked.connect(lambda _=False, w=w, f=f: self._browse(w, f))
            h.addWidget(b)
            self._register(f, box, w.text, lambda v, w=w: w.setText(str(v)), w.textChanged)
            return box
        if isinstance(f, Text):
            lab = QLabel(f.text)
            lab.setWordWrap(True)
            self._register(f, lab, lab.text, lab.setText)
            return lab
        if isinstance(f, PickPhrase):
            base_text = {"phrase": "Select phrase", "folder": "Select folder"}.get(f.kind, "Select phrase(folder)")
            lab = LinkLabel(base_text)
            state = {"v": ""}

            def setv(v, lab=lab, f=f, state=state, base=base_text):
                state["v"] = v or ""
                lab.setText(f'<a href="#">{v or base}</a>')
                self._refresh()

            lab.clicked.connect(lambda f=f, setv=setv: (lambda r: r and setv(r))(pick_phrase_or_folder(self, f.kind)))
            self._register(f, lab, lambda state=state: state["v"], setv)
            return lab
        if isinstance(f, ListPick):
            w = QListWidget()
            w.setStyleSheet("QListWidget { background: white; border: 1px solid #a0a0a0; }"
                            "QListWidget::item:selected { background: #0078d7; color: white; border: none; }")
            w.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            w.setFixedWidth(f.width)
            w.setMinimumHeight(f.height)
            for text, value in f.options:
                w.addItem(text)
                w.item(w.count() - 1).setData(Qt.UserRole, value)
            w.setSelectionMode(QAbstractItemView.SingleSelection)

            def get(w=w):
                it = w.currentItem()
                return it.data(Qt.UserRole) if it else None

            def setv(v, w=w):
                for i in range(w.count()):
                    if w.item(i).data(Qt.UserRole) == v:
                        w.setCurrentRow(i)
            self._register(f, w, get, setv, w.currentRowChanged)
            return w
        if isinstance(f, Button):
            b = QPushButton(f.label)
            b.clicked.connect(lambda _=False, f=f: f.action and f.action(self))
            if f.enabled_if:
                self.deps.append((b, f.enabled_if, "enabled"))
            return b
        if isinstance(f, Preview):
            box = QGroupBox("Preview:")
            v = QVBoxLayout(box)
            lab = QLabel("")
            lab.setAlignment(Qt.AlignCenter)
            lab.setWordWrap(True)
            if f.big:
                lab.setStyleSheet("font-size: 12pt; font-weight: 600; padding: 8px;")
            v.addWidget(lab)
            self.previews.append((lab, f.fn))
            return box
        if isinstance(f, Custom):
            w, getter, setter = f.factory(self)
            self._register(f, w, getter, setter)
            return w
        if isinstance(f, Group):
            box = QGroupBox(f.title)
            v = QVBoxLayout(box)
            v.setSpacing(4)
            for sub in f.fields:
                self._add_field(v, sub)
            if f.enabled_if:
                self.deps.append((box, f.enabled_if, "enabled"))
            return box
        if isinstance(f, Column):
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(4)
            for sub in f.fields:
                self._add_field(v, sub)
            v.addStretch(1)
            return box
        if isinstance(f, Row):
            box = QWidget()
            g = QGridLayout(box)
            g.setContentsMargins(0, 0, 0, 0)
            g.setHorizontalSpacing(12)
            for col, sub in enumerate(f.fields):
                if isinstance(sub, Column):
                    g.addWidget(self._make(sub), 0, col, 2, 1)
                    if sub.stretch:
                        g.setColumnStretch(col, sub.stretch)
                    continue
                if sub.label and not isinstance(sub, (Check, Button)):
                    cap = QLabel(sub.label)
                    g.addWidget(cap, 0, col)
                    if sub.enabled_if:
                        self.deps.append((cap, sub.enabled_if, "enabled"))
                w = self._make(sub)
                if isinstance(sub, Text):
                    w.setWordWrap(False)       # "Shift date by" stays on one line
                g.addWidget(w, 1, col)
            g.setColumnStretch(len(f.fields), 1)
            return box
        return None

    def _add_field(self, lay, f: Field):
        if f.label and not isinstance(f, (Check, Group, Row, Button, Radio, Text, Preview)):
            cap = QLabel(f.label)
            lay.addSpacing(2)
            lay.addWidget(cap)
            if f.enabled_if:
                self.deps.append((cap, f.enabled_if, "enabled"))
            if f.visible_if:
                self.deps.append((cap, f.visible_if, "visible"))
        if isinstance(f, Radio) and f.label and not f.title:
            lay.addWidget(QLabel(f.label))
        w = self._make(f)
        if w is not None:
            lay.addWidget(w)

    def _add_form_field(self, form: QFormLayout, f: Field):
        w = self._make(f)
        if w is None:
            return
        if f.label and not isinstance(f, (Check, Button, Group, Text, Radio, Preview)):
            cap = QLabel(f.label + ":")
            cap.setStyleSheet("font-weight: 600;")
            form.addRow(cap, w)
            if f.visible_if:
                self.deps.append((cap, f.visible_if, "visible"))
        else:
            form.addRow("", w)

    # -------------------------------------------------- behaviour
    def values(self) -> dict:
        out = {}
        for k, g in self.getters.items():
            try:
                out[k] = g()
            except Exception:
                out[k] = None
        return out

    def set_values(self, values: dict) -> None:
        for k, v in values.items():
            s = self.setters.get(k)
            if s is not None and v is not None:
                try:
                    s(v)
                except Exception:
                    pass

    def _cond(self, cond: tuple, vals: dict) -> bool:
        key, want = cond
        v = vals.get(key)
        if callable(want):
            return bool(want(v))
        if isinstance(want, (list, tuple, set)):
            return v in want
        return v == want

    def _refresh(self):
        vals = self.values()
        for w, cond, what in self.deps:
            ok = self._cond(cond, vals)
            (w.setEnabled if what == "enabled" else w.setVisible)(ok)
        req_ok = all(str(vals.get(f.key) or "").strip() for f in self._all_fields() if f.required and f.key
                     and (not f.enabled_if or self._cond(f.enabled_if, vals)))
        self.ok_btn.setEnabled(req_ok)
        if self.spec.name_fn and self.name_edit.text() in ("", self.spec.name or "", self.spec.title,
                                                            getattr(self, "_auto_name", "")):
            self._auto_name = self.spec.name_fn(vals)
            self.name_edit.setText(self._auto_name)
        for lab, fn in self.previews:
            try:
                lab.setText(fn(vals) if fn else preview_macro(self.spec.build(vals)))
            except Exception as e:
                lab.setText(f"[{e}]")

    def _all_fields(self, fields=None):
        for f in (self.spec.fields if fields is None else fields):
            yield f
            if isinstance(f, (Group, Row, Column)):
                yield from self._all_fields(f.fields)

    def _browse(self, w: QLineEdit, f: FilePath):
        if f.mode == "dir":
            p = QFileDialog.getExistingDirectory(self, f.label or "Select folder", w.text())
        elif f.mode == "save":
            p, _ = QFileDialog.getSaveFileName(self, f.label or "Save file", w.text(), f.filter)
        else:
            p, _ = QFileDialog.getOpenFileName(self, f.label or "Select file", w.text(), f.filter)
        if p:
            w.setText(p.replace("/", "\\"))

    def _edit_big(self, w: QLineEdit):
        text, ok = QInputDialog.getMultiLineText(self, "Edit", "Value (right-click for macros):", w.text())
        if ok:
            w.setText(text)

    def _help(self):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, self.spec.title, self.spec.help or self.spec.description or
                                "Fill in the fields and press OK to insert the macro.")

    def _process_menu(self) -> QMenu:
        m = QMenu(self)
        none = m.addAction("(No processing)")
        none.triggered.connect(lambda: self._set_process(None))
        m.addSeparator()
        for it in PROCESS_OUTPUT:
            if it is None:
                m.addSeparator()
                continue
            text, op = it
            a = QAction(text, m)
            a.triggered.connect(lambda _=False, op=op, text=text: self._set_process((op, ""), text))
            m.addAction(a)
        return m

    def _set_process(self, proc, text: str = ""):
        if proc and proc[0] == "set":
            name, ok = QInputDialog.getText(self, "Store in variable", "Variable name:")
            if not ok or not name:
                return
            proc = ("set", name)
        if proc and proc[0] == "translate":
            lang, ok = QInputDialog.getText(self, "Translate", "Target language:", text="English")
            if not ok or not lang:
                return
            proc = ("translate", lang)
        self.process = proc
        self.process_btn.setText(f"Process output: {text.rstrip('.')}" if proc else "Process output")

    def build_text(self) -> str:
        text = self.spec.build(self.values())
        if self.process and text:
            op, extra = self.process
            if op == "set":
                text = f"{{#set {q(extra)} {q(text)}}}"
            elif op == "translate":
                text = f"{{#translate {q(text)} -to {q(extra)}}}"
            else:
                text = f"{{#{op} {q(text)}}}"
        cap = self.name_edit.text().strip()
        default_name = self.spec.name or self.spec.title
        if self.spec.name_fn:
            default_name = self.spec.name_fn(self.values())
        if cap and cap != default_name:
            text = add_caption(text, cap)
        return text

    def _accept(self):
        self.result_text = self.build_text()
        self.accept()
