"""Settings dialog laid out like PhraseExpress's (tree of pages on the left).

Reference: reference/phraseexpress/06_settings_*.png. Every control is bound to a
store setting (see settings_schema.SCHEMA) through self.bind(); load() fills the
controls, save() writes them back, reset_defaults() restores schema defaults.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Callable

from PySide6.QtCore import QLocale, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFontDialog,
    QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QMenu, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QScrollArea, QSlider, QSpinBox,
    QStackedWidget, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QColorDialog,
)

from phraseforge import paths
from phraseforge.db import Store
from phraseforge.ui.hotkey_picker import KEYS, HotkeyPicker
from phraseforge.ui.i18n import tr
from phraseforge.ui.iconset import icon
from phraseforge.ui.settings_schema import (
    SCHEMA, decode_delimiters, encode_delimiters, ensure_defaults,
)

APP = "PhraseForge"
# Engines as listed in PhraseExpress 18 (AI text processing / Language Translation)
PROVIDERS = [("OpenAI", "openai", "https://platform.openai.com/api-keys"),
             ("Anthropic (Claude)", "anthropic", "https://console.anthropic.com/settings/keys"),
             ("GPT4All", "gpt4all", "https://www.nomic.ai/gpt4all"),
             ("Ollama", "ollama", "https://ollama.com/download"),
             ("Google Gemini", "gemini", "https://aistudio.google.com/apikey"),
             ("OpenRouter", "openrouter", "https://openrouter.ai/keys"),
             ("OpenCode Zen", "opencode", "https://opencode.ai/zen"),
             ("Kilo Code", "kilocode", "https://app.kilo.ai")]
TRANSLATION_PROVIDERS = [("Free (MyMemory, no key)", "free", "https://mymemory.translated.net/"),
                         ("Deepl", "deepl", "https://www.deepl.com/your-account/keys")] + PROVIDERS
LOCAL_ENGINES = {"ollama": "Ollama server URL:", "gpt4all": "GPT4All server URL (Settings > Enable local API server):"}
# PhraseExpress 18 "Phrase menu contents" (order of the columns in a phrase row)
MENU_CONTENTS = [("Description - QuickKey", "description_quickkey"),
                 ("QuickKey - Description", "quickkey_description"),
                 ("Autotext - Description - QuickKey", "autotext_description_quickkey"),
                 ("Autotext - QuickKey - Description", "autotext_quickkey_description"),
                 ("QuickKey - Description - Autotext", "quickkey_description_autotext"),
                 ("Description - Autotext - QuickKey", "description_autotext_quickkey"),
                 ("Description - Autotext - Hotkey - QuickKey", "description_autotext_hotkey_quickkey"),
                 ("QuickKey - Autotext - Description - Hotkey", "quickkey_autotext_description_hotkey"),
                 ("Autotext - QuickKey - Description - Hotkey", "autotext_quickkey_description_hotkey"),
                 ("Autotext - Description - QuickKey - Hotkey", "autotext_description_quickkey_hotkey"),
                 ("Description - Hotkey - QuickKey", "description_hotkey_quickkey"),
                 ("QuickKey - Description - Hotkey", "quickkey_description_hotkey"),
                 # older PhraseForge values (kept so existing settings still load)
                 ("Description", "description"), ("Description - Autotext", "description_autotext"),
                 ("Description - Autotext - Hotkey", "description_autotext_hotkey")]
TRANSLATION_LANGUAGES = ["English", "Arabic", "Chinese", "Dutch", "French", "German", "Italian", "Japanese",
                         "Korean", "Polish", "Portuguese", "Russian", "Spanish", "Swedish", "Turkish", "Ukrainian"]

# (page key, tree text, parent key or None)
PAGES: list[tuple[str, str, str | None]] = [
    ("features", "Features", None),
    ("hotkeys", "Hotkeys", None),
    ("display", "Display", None),
    ("sounds", "Sounds", None),
    ("phrase_file", "Phrase File/Database", None),
    ("cloud", "Backup & Sync", "phrase_file"),
    ("ai", "AI text processing", None),
    ("ai_presets", "Custom presets", "ai"),
    ("ai_instructions", "Custom instructions", "ai"),
    ("translation", "Language Translation", None),
    ("translation_ignored", "Ignored words", "translation"),
    ("translation_glossaries", "Glossaries", "translation"),
    ("network", "Network", None),
    ("ocr", "Screen OCR", None),
    ("onenote", "OneNote", None),
    ("file_search", "Search files", None),
    ("phrase_menu", "Phrase Menu", None),
    ("phrase_menu_appearance", "Appearance", "phrase_menu"),
    ("phrase_menu_hotkeys", "Hotkeys", "phrase_menu"),
    ("phrase_menu_quicksearch", "Quick Search", "phrase_menu"),
    ("autocomplete", "AutoComplete", None),
    ("expert", "Expert Options", None),
    ("expert_text_insertion", "Text Insertion", "expert"),
    ("expert_delays", "Delays", "expert"),
    ("expert_phrase_formatting", "Phrase Formatting", "expert"),
    ("program_exclusions", "Program exclusions", "expert"),
]


def pages() -> list[str]:
    return [p[0] for p in PAGES]


def _b(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------- small widgets

OCR_AUTO_HINT = ("Auto: PhraseForge reads the capture with each installed OCR language and keeps "
                 "the one that fits, for example Arabic or English.")

class DataCombo(QComboBox):
    """Combo of (text, value) items. setCurrentText also accepts the stored value."""

    def __init__(self, items: list[tuple[str, str]] | list[str], parent=None):
        super().__init__(parent)
        for it in items:
            text, val = (it, it) if isinstance(it, str) else it
            self.addItem(text, val)

    def value(self) -> str:
        v = self.currentData()
        return self.currentText() if v is None else str(v)

    def set_value(self, v: str) -> None:
        i = self.findData(v)
        if i < 0:
            i = self.findText(v, Qt.MatchFixedString)
        if i >= 0:
            self.setCurrentIndex(i)
        elif self.isEditable():
            self.setEditText(v)

    def setCurrentText(self, text: str) -> None:  # noqa: N802 (Qt naming)
        self.set_value(text)


def filesearch_defaults() -> str:
    from phraseforge.filesearch import DEFAULT_WEB_KEYWORDS
    return DEFAULT_WEB_KEYWORDS


class Hotkey(HotkeyPicker):
    """HotkeyPicker that stores modifiers in canonical order (ctrl+alt+shift+win, as
    the trigger layer writes them) and has text-style accessors (setText/text/chord)."""

    ORDER = ("ctrl", "alt", "shift", "win")

    def value(self) -> str:
        v = super().value()
        if not v:
            return ""
        parts = v.split("+")
        return "+".join([m for m in self.ORDER if m in parts[:-1]] + parts[-1:])

    def setText(self, v: str) -> None:  # noqa: N802
        self.set_value(v)

    def text(self) -> str:
        return self.value()

    chord = text


class KeyCombo(QWidget):
    """A single key (no modifiers) chosen from a list, with a clear button (X)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox()
        self.combo.addItems(KEYS)
        self.combo.setMinimumWidth(330)
        lay.addWidget(self.combo)
        clear = QToolButton()
        clear.setIcon(icon("remove"))
        clear.setAutoRaise(True)
        clear.clicked.connect(lambda: self.combo.setCurrentIndex(0))
        lay.addWidget(clear)
        lay.addStretch(1)

    def value(self) -> str:
        t = self.combo.currentText()
        return "" if t == "None" else t.lower()

    def set_value(self, v: str) -> None:
        for i in range(self.combo.count()):
            if self.combo.itemText(i).lower() == (v or "none").lower():
                self.combo.setCurrentIndex(i)
                return
        self.combo.setCurrentIndex(0)


class RadioGroup(QWidget):
    """Vertical radio buttons storing one value."""

    def __init__(self, options: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QRadioButton] = {}
        for text, val in options:
            rb = QRadioButton(text)
            self.group.addButton(rb)
            lay.addWidget(rb)
            self.buttons[val] = rb

    def value(self) -> str:
        for v, b in self.buttons.items():
            if b.isChecked():
                return v
        return next(iter(self.buttons))

    def set_value(self, v: str) -> None:
        (self.buttons.get(v) or next(iter(self.buttons.values()))).setChecked(True)


class DelaySlider(QWidget):
    """Slider with tick marks and a "N ms" label (red when very short)."""

    def __init__(self, maximum: int = 1000, warn_below: int = 50, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, maximum)
        self.slider.setSingleStep(10)
        self.slider.setPageStep(50)
        self.slider.setTickPosition(QSlider.TicksBothSides)
        self.slider.setTickInterval(50)
        self.slider.setFixedWidth(185)
        self.label = QLabel()
        self.label.setMinimumWidth(60)
        self.warn_below = warn_below
        self.slider.valueChanged.connect(self._update)
        lay.addWidget(self.slider)
        lay.addWidget(self.label)
        lay.addStretch(1)

    def _update(self, v: int) -> None:
        self.label.setText(f"{v} ms")
        self.label.setStyleSheet("color: #c0392b;" if v < self.warn_below else "")

    def value(self) -> str:
        return str(self.slider.value())

    def set_value(self, v: str) -> None:
        self.slider.setValue(int(v or 0))
        self._update(self.slider.value())


class AppMethodTable(QWidget):
    """Program -> paste method list for output.app_methods ({"winword.exe": "paste", ...})."""
    METHODS = [("Type (key-by-key)", "type"), ("Paste (clipboard)", "paste")]

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QHeaderView, QTableWidget
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 0, 0)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Program (exe)", "Method"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setFixedHeight(96)
        lay.addWidget(self.table, 1)
        col = QVBoxLayout()
        add, rem = QPushButton("Add"), QPushButton("Remove")
        for b in (add, rem):
            b.setStyleSheet("min-width: 56px;")
            col.addWidget(b)
        col.addStretch(1)
        lay.addLayout(col)
        add.clicked.connect(lambda: self.add_row("", "paste", edit=True))
        rem.clicked.connect(lambda: self.table.removeRow(self.table.currentRow())
                            if self.table.currentRow() >= 0 else None)

    def add_row(self, exe: str, method: str, edit: bool = False) -> None:
        from PySide6.QtWidgets import QTableWidgetItem
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(exe))
        combo = DataCombo(self.METHODS)
        combo.set_value(method if method in ("type", "paste") else "paste")
        self.table.setCellWidget(r, 1, combo)
        if edit:
            self.table.setCurrentCell(r, 0)
            self.table.editItem(self.table.item(r, 0))

    def to_json(self) -> str:
        out = {}
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            exe = (it.text() if it else "").strip().lower()
            if exe:
                out[exe] = self.table.cellWidget(r, 1).value()
        return json.dumps(out, sort_keys=True)

    def load_json(self, v: str) -> None:
        self.table.setRowCount(0)
        try:
            data = json.loads(v or "{}")
        except ValueError:
            data = {}
        for exe, method in sorted((data if isinstance(data, dict) else {}).items()):
            self.add_row(str(exe), str(method))


def _group(title: str) -> tuple[QGroupBox, QVBoxLayout]:
    g = QGroupBox(title)
    lay = QVBoxLayout(g)
    lay.setContentsMargins(12, 10, 12, 10)
    lay.setSpacing(7)
    return g, lay


def _json_list(v: str) -> list[str]:
    try:
        data = json.loads(v or "[]")
    except ValueError:
        return []
    return [str(x) for x in data if str(x).strip()] if isinstance(data, list) else []


def _row(*widgets, stretch: bool = True) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    for x in widgets:
        if isinstance(x, str):
            x = QLabel(x)
        lay.addWidget(x)
    if stretch:
        lay.addStretch(1)
    return w


def _icon_button(name: str, tip: str, on_click: Callable | None = None) -> QToolButton:
    b = QToolButton()
    b.setIcon(icon(name))
    b.setAutoRaise(True)
    b.setToolTip(tip)
    if on_click:
        b.clicked.connect(lambda _=False: on_click())
    return b


def _spin(lo: int, hi: int) -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setFixedWidth(70)
    return s


def _run_with_wait(parent, text, fn):
    from phraseforge.ui.cloud_ui import run_with_wait
    return run_with_wait(parent, text, fn)


def _wrap_label(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    return lab


def _arrow_files() -> tuple[str, str]:
    """Small down/up arrow PNGs (the shared style replaces native combo/spin arrows)."""
    import tempfile
    d = os.path.join(tempfile.gettempdir(), "phraseforge_ui")
    os.makedirs(d, exist_ok=True)
    down, up = os.path.join(d, "arrow_down.png"), os.path.join(d, "arrow_up.png")
    for path, name in ((down, "expand"), (up, "collapse")):
        if not os.path.isfile(path):
            icon(name, "#444444").pixmap(10, 10).save(path)
    return down.replace("\\", "/"), up.replace("\\", "/")


def _local_qss() -> str:
    down, up = _arrow_files()
    return f"""
QGroupBox {{ font-weight: 600; }}
QGroupBox QWidget, QGroupBox QLabel, QGroupBox QCheckBox, QGroupBox QRadioButton,
QGroupBox QPushButton, QGroupBox QComboBox, QGroupBox QSpinBox, QGroupBox QLineEdit {{ font-weight: 400; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 18px; border: none; }}
QComboBox::down-arrow {{ image: url({down}); width: 10px; height: 10px; }}
QSpinBox {{ padding-right: 16px; }}
QSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 15px;
  border-left: 1px solid #d0d0d0; background: #f4f4f4; }}
QSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 15px;
  border-left: 1px solid #d0d0d0; background: #f4f4f4; }}
QSpinBox::up-arrow {{ image: url({up}); width: 8px; height: 8px; }}
QSpinBox::down-arrow {{ image: url({down}); width: 8px; height: 8px; }}
#WideButton {{ min-width: 180px; }}
"""


def play_sound(path: str = "") -> None:
    try:
        import winsound
        if path and os.path.isfile(path):
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        else:
            winsound.MessageBeep()
    except Exception:
        QApplication.beep()


# ---------------------------------------------------------------- dialog
class SettingsDialog(QDialog):
    def __init__(self, store: Store, page: str | QWidget | None = None, parent: QWidget | None = None):
        if isinstance(page, QWidget) and parent is None:   # old call style: SettingsDialog(store, parent)
            page, parent = None, page
        super().__init__(parent)
        self.store = store
        ensure_defaults(store)
        self.setWindowTitle(f"{APP} Settings")
        try:
            from phraseforge.ui.icons import app_icon
            self.setWindowIcon(app_icon())
        except Exception:
            pass
        self.resize(791, 490)
        self.setLocale(QLocale(QLocale.English, QLocale.UnitedStates))   # Western digits in spin boxes
        self.setStyleSheet(_local_qss())
        self._bindings: list[tuple[str, Callable[[], str], Callable[[str], None], QWidget | None]] = []
        self._syncs: list[Callable[[], None]] = []
        self._ai_keys: dict[str, str] = {}

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.tree = QTreeWidget()
        self.tree.setProperty("pf_i18n", True)          # page names are UI text
        self.tree.setObjectName("SettingsTree")
        self.tree.setHeaderHidden(True)
        self.tree.setFixedWidth(183)
        self.tree.setIndentation(16)
        self.tree.setRootIsDecorated(False)
        outer.addWidget(self.tree)

        right = QWidget()
        right.setObjectName("SettingsPage")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(16, 6, 16, 8)
        rl.setSpacing(6)
        self.stack = QStackedWidget()
        rl.addWidget(self.stack, 1)
        rl.addWidget(self._buttons())
        outer.addWidget(right, 1)

        self._page_index: dict[str, int] = {}
        items: dict[str, QTreeWidgetItem] = {}
        builders = {k: getattr(self, f"_page_{k}") for k, _, _ in PAGES}
        for key, text, parent_key in PAGES:
            it = QTreeWidgetItem([text])
            it.setData(0, Qt.UserRole, key)
            (items[parent_key].addChild(it) if parent_key else self.tree.addTopLevelItem(it))
            items[key] = it
            w = builders[key]()
            sa = QScrollArea()
            sa.setWidgetResizable(True)
            sa.setFrameShape(QFrame.NoFrame)
            sa.setWidget(w)
            w.setObjectName("SettingsPage")
            self._page_index[key] = self.stack.addWidget(sa)
        self.tree.expandAll()
        self._items = items
        self.tree.currentItemChanged.connect(self._on_tree)
        self.load()
        self._load_ai_key()
        self._update_translation_status()
        self.show_page(page if isinstance(page, str) and page in items else "features")

    # -------------------------------------------------- binding
    def bind(self, key: str, widget, kind: str | None = None):
        """Register widget<->setting. kind: auto from widget type."""
        if isinstance(widget, QCheckBox):
            get, put = (lambda w=widget: "1" if w.isChecked() else "0"), (lambda v, w=widget: w.setChecked(_b(v)))
        elif isinstance(widget, (QSpinBox,)):
            get, put = (lambda w=widget: str(w.value())), (lambda v, w=widget: w.setValue(int(v or 0)))
        elif isinstance(widget, DataCombo):
            get, put = widget.value, widget.set_value
        elif isinstance(widget, QPlainTextEdit):
            get, put = widget.toPlainText, widget.setPlainText
        elif isinstance(widget, QLineEdit):
            get, put = (lambda w=widget: w.text().strip()), widget.setText
        elif hasattr(widget, "value") and hasattr(widget, "set_value"):
            get, put = widget.value, widget.set_value
        else:
            raise TypeError(f"cannot bind {type(widget).__name__}")
        self._bindings.append((key, get, put, widget))
        return widget

    def bind_custom(self, key: str, get: Callable[[], str], put: Callable[[str], None]) -> None:
        self._bindings.append((key, get, put, None))

    def enable_with(self, source: QAbstractButton, target: QWidget) -> None:
        """Keep target enabled only while source is checked (also after load/reset)."""
        source.toggled.connect(target.setEnabled)
        self._syncs.append(lambda: target.setEnabled(source.isChecked()))

    def _sync_enabled(self) -> None:
        for f in self._syncs:
            f()

    def load(self) -> None:
        for key, _get, put, _w in self._bindings:
            put(self.store.setting(key, SCHEMA.get(key, "")))
        self.excluded.setPlainText("\n".join(sorted(self.store.excluded_apps())))
        self._sync_enabled()

    def save(self) -> None:
        self._stash_ai_key()
        self._stash_glossary()
        for key, get, _put, _w in self._bindings:
            self.store.set_setting(key, get())
        for prov, val in self._ai_keys.items():
            self.store.set_setting(self._key_setting(prov), val)
        self.store.set_excluded_apps(self.excluded.toPlainText().splitlines())

    def values(self) -> dict[str, str]:
        """Current (unsaved) control values by setting key."""
        return {k: g() for k, g, _p, _w in self._bindings}

    def reset_defaults(self) -> None:
        for key, _get, put, _w in self._bindings:
            put(SCHEMA.get(key, ""))
        self._ai_keys = {}
        self._load_ai_key()
        self._sync_enabled()

    def accept(self) -> None:
        self.save()
        super().accept()

    # -------------------------------------------------- navigation
    def show_page(self, key: str) -> None:
        it = self._items.get(key)
        if it:
            self.tree.setCurrentItem(it)
            self.stack.setCurrentIndex(self._page_index[key])

    def current_page(self) -> str:
        it = self.tree.currentItem()
        return it.data(0, Qt.UserRole) if it else ""

    def _on_tree(self, cur, _prev) -> None:
        if cur:
            key = cur.data(0, Qt.UserRole)
            self.stack.setCurrentIndex(self._page_index[key])
            if key == "ocr" and not self._ocr_queried:
                self._fill_ocr_languages(self.ocr_language.currentText())

    def _buttons(self) -> QWidget:
        opts = QPushButton("Settings options")
        m = QMenu(opts)
        m.addAction("Reset to defaults", self._confirm_reset)
        m.addSeparator()
        m.addAction("Export settings...", self._export)
        m.addAction("Import settings...", self._import)
        opts.setMenu(m)
        opts.setMinimumWidth(144)
        self.options_button = opts
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        hlp = QPushButton("Help")
        hlp.clicked.connect(self._help)
        for b in (ok, cancel, hlp):
            b.setMinimumWidth(74)
        return self._button_row(opts, ok, cancel, hlp)

    @staticmethod
    def _button_row(opts, ok, cancel, hlp) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 2, 0, 0)
        lay.addWidget(opts)
        lay.addStretch(1)
        for b in (ok, cancel, hlp):
            lay.addWidget(b)
        return w

    def _confirm_reset(self) -> None:
        if QMessageBox.question(self, f"{APP} Settings",
                                "Reset all settings on every page to their defaults?") == QMessageBox.Yes:
            self.reset_defaults()

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export settings", "phraseforge-settings.json", "JSON (*.json)")
        if path:
            self.export_to(path)

    def export_to(self, path: str) -> None:
        self.save()
        data = {k: v for k, v in self.store.settings().items()}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"format": "phraseforge-settings", "settings": data,
                       "excluded_apps": sorted(self.store.excluded_apps())}, fh, ensure_ascii=False, indent=2)

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import settings", "", "JSON (*.json)")
        if path:
            try:
                self.import_from(path)
            except Exception as e:
                QMessageBox.warning(self, "Import settings", str(e))

    def import_from(self, path: str) -> None:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("format") != "phraseforge-settings":
            raise ValueError("Not a PhraseForge settings file")
        for k, v in (data.get("settings") or {}).items():
            self.store.set_setting(str(k), str(v))
        if "excluded_apps" in data:
            self.store.set_excluded_apps(data["excluded_apps"])
        self._ai_keys = {}
        self.load()
        self._load_ai_key()

    def _help(self) -> None:
        readme = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "README.md")
        if os.path.isfile(readme):
            QDesktopServices.openUrl(QUrl.fromLocalFile(readme))

    # ================================================== pages
    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        return w, lay

    # ---- Features
    def _page_features(self) -> QWidget:
        w, lay = self._page()
        g, gl = _group("General Features")
        self.f_clipboard = self.bind("clipboard_history.enabled", QCheckBox("Clipboard Cache"))
        gl.addWidget(_row(self.f_clipboard, _icon_button("properties", "Clipboard Cache options",
                                                         self._clipboard_options)))
        self.f_last_used = self.bind("features.last_used_folder", QCheckBox("Last used phrases folder"))
        gl.addWidget(_row(self.f_last_used, _icon_button("properties", "Last used phrases options",
                                                         self._last_used_options)))
        stats = self.bind("features.usage_statistics", QCheckBox("Usage statistics"))
        gl.addWidget(_row(stats, _icon_button("info", "Count phrase usage to show the time you saved.")))
        gl.addWidget(self.bind("features.detect_unwanted_replacements", QCheckBox("Detect unwanted text replacements")))
        gl.addSpacing(6)
        gl.addWidget(self.bind("features.disable_capslock", QCheckBox("Disable CAPSLOCK key to prevent unintended activation")))
        gl.addWidget(self.bind("tray.left_click_popup", QCheckBox("Left click on the tray icon opens the phrase menu (Ctrl+click pauses, Alt+click opens settings)")))
        gl.addWidget(self.bind("autocorrect.capitalize_sentences", QCheckBox("Capitalize first letter of sentences")))
        gl.addWidget(self.bind("autocorrect.two_initial_capitals", QCheckBox("COrrect TWo INitial CApitals")))
        lay.addWidget(g)
        g, gl = _group("Startup")
        self.start_with_windows = self.bind("app.start_with_windows", QCheckBox(f"Start {APP} with Windows"))
        gl.addWidget(self.start_with_windows)
        gl.addWidget(self.bind("app.diagnostic_mode", QCheckBox("Diagnostic mode")))
        gl.addWidget(self.bind("updates.auto_check",
                               QCheckBox(f"Check GitHub for new versions of {APP} automatically (once a day)")))
        lay.addWidget(g)
        lay.addStretch(1)
        # values edited in the gear dialogs
        self._clip_max = self.store.setting("clipboard_history.max", SCHEMA["clipboard_history.max"])
        self._last_max = self.store.setting("last_used.max", SCHEMA["last_used.max"])
        self.bind_custom("clipboard_history.max", lambda: str(self._clip_max), self._set_clip_max)
        self.bind_custom("last_used.max", lambda: str(self._last_max), self._set_last_max)
        return w

    def _set_clip_max(self, v: str) -> None:
        self._clip_max = v

    def _set_last_max(self, v: str) -> None:
        self._last_max = v

    def _ask_int(self, title: str, label: str, value: str, lo: int, hi: int) -> str | None:
        v, ok = QInputDialog.getInt(self, title, label, int(value or 0), lo, hi)
        return str(v) if ok else None

    def _clipboard_options(self) -> None:
        v = self._ask_int("Clipboard Cache", "Maximum number of clipboard items:", self._clip_max, 1, 100000)
        if v is not None:
            self._clip_max = v

    def _last_used_options(self) -> None:
        v = self._ask_int("Last used phrases", "Maximum number of items:", self._last_max, 1, 500)
        if v is not None:
            self._last_max = v

    # ---- Hotkeys
    def _page_hotkeys(self) -> QWidget:
        w, lay = self._page()
        g, gl = _group("Hotkeys")
        gl.setSpacing(3)
        rows = [("hotkey.open_main", f"Open {APP}"),
                ("hotkey.toggle_expansion", "Enable/disable text expansion"),
                ("hotkey.new_phrase", "Create a new phrase"),
                ("hotkey.new_phrase_from_clipboard", "Create a new phrase from the clipboard"),
                ("hotkey.edit_last_phrase", "Edit the last used phrase"),
                ("hotkey.open_settings", f"Open the {APP} settings window"),
                ("popup.hotkey", "Open tray popup menu"),
                ("hotkey.popup_search", "Open popup menu in search mode"),
                ("hotkey.clear_clipboard_cache", "Empty clipboard cache"),
                ("clipboard_history.hotkey", "Show clipboard history")]
        for key, text in rows:
            gl.addWidget(QLabel(text))
            hk = self.bind(key, Hotkey())
            gl.addWidget(hk)
            if key == "popup.hotkey":
                self.popup_hotkey = hk
        gl.addWidget(QLabel(f"Pause {APP} for a short time"))
        pause = self.bind("hotkey.pause", Hotkey())
        rep = self.bind("pause.repetitions", QSpinBox())
        rep.setRange(1, 10)
        rep.setFixedWidth(80)
        secs = self.bind("pause.seconds", QSpinBox())
        secs.setRange(1, 3600)
        secs.setFixedWidth(80)
        grid = QGridLayout()
        grid.addWidget(pause, 1, 0)
        grid.addWidget(QLabel("Repetitions:"), 0, 1)
        grid.addWidget(QLabel("Pause for:"), 0, 2)
        grid.addWidget(rep, 1, 1)
        grid.addWidget(_row(secs, "s"), 1, 2)
        grid.setColumnStretch(0, 1)
        gl.addLayout(grid)
        lay.addWidget(g)
        lay.addStretch(1)
        return w

    def _set_active_language(self, v: str) -> None:
        self.active_lang.clear()
        self.active_lang.addItems(["Default"] + _json_list(self.store.setting("phrase.languages", "[]")))
        self.active_lang.setCurrentText(v or "Default")

    # ---- Display
    def _page_display(self) -> QWidget:
        w, lay = self._page()
        g, gl = _group("User Interface Language")
        self.language = self.bind("ui.language", DataCombo([("Autodetect", "auto"), ("English", "en"),
                                                             ("العربية (Arabic)", "ar")]))
        self.language.setFixedWidth(198)
        gl.addWidget(self.language)
        lay.addWidget(g)
        g, gl = _group("Display")
        gl.addWidget(self.bind("display.prompt_after_new_phrase",
                               QCheckBox("Prompt for additional information after creating a new phrase")))
        gl.addWidget(self.bind("display.highlight_unedited", QCheckBox("Highlight unedited language versions")))
        gl.addSpacing(10)
        show_all = QPushButton("Show all dialogs")
        show_all.setObjectName("WideButton")
        show_all.setToolTip("Show again the messages you chose not to show.")
        show_all.clicked.connect(self._show_all_dialogs)
        gl.addWidget(show_all)
        lay.addWidget(g)
        g, gl = _group("Phrase languages")
        gl.addWidget(QLabel("Languages for phrase versions (one per line):"))
        self.phrase_langs = QPlainTextEdit()
        self.phrase_langs.setFixedHeight(60)
        gl.addWidget(self.phrase_langs)
        self.bind_custom("phrase.languages",
                         lambda: json.dumps([x.strip() for x in self.phrase_langs.toPlainText().splitlines()
                                             if x.strip()], ensure_ascii=False),
                         lambda v: self.phrase_langs.setPlainText("\n".join(_json_list(v))))
        self.active_lang = QComboBox()
        self.active_lang.setEditable(True)
        self.active_lang.setFixedWidth(198)
        self.bind_custom("phrase.active_language",
                         lambda: "" if self.active_lang.currentText().strip() in ("", "Default")
                         else self.active_lang.currentText().strip(),
                         self._set_active_language)
        gl.addWidget(_row("Version inserted by autotext and hotkeys:", self.active_lang))
        lay.addWidget(g)
        g, gl = _group("Dates in phrases")
        self.date_lang = self.bind("date.lang", DataCombo([("English", "en"), ("Arabic", "ar"), ("German", "de")]))
        self.date_lang.setFixedWidth(198)
        gl.addWidget(_row("Month and day names:", self.date_lang))
        self.date_cal = self.bind("date.calendar", DataCombo([("Gregorian", "gregorian"),
                                                              ("Hijri (tabular)", "hijri")]))
        self.date_cal.setFixedWidth(198)
        gl.addWidget(_row("Calendar:", self.date_cal))
        self.date_digits = self.bind("date.digits", DataCombo([("0123456789", "latin"), ("٠١٢٣٤٥٦٧٨٩", "arabic")]))
        self.date_digits.setFixedWidth(198)
        gl.addWidget(_row("Digits:", self.date_digits))
        lay.addWidget(g)
        g, gl = _group("Color theme")
        self.theme = self.bind("ui.theme", DataCombo([("Adapt to system setting", "system"), ("Light", "light"),
                                                       ("Dark", "dark")]))
        self.theme.setFixedWidth(198)
        gl.addWidget(self.theme)
        lay.addWidget(g)
        lay.addStretch(1)
        return w

    def _show_all_dialogs(self) -> None:
        for k, v in self.store.settings().items():
            if k.startswith("dialog.hide.") and v != "0":
                self.store.set_setting(k, "0")
        QMessageBox.information(self, f"{APP} Settings", "All hidden messages will be shown again.")

    # ---- Sounds
    SOUNDS = [("phrase_insertion", "Phrase insertion"), ("popup_display", "Popup display"),
              ("unwanted_detected", "Detection of unwanted text replacement"),
              ("unwanted_skipped", "Skipped unwanted text replacement"),
              ("spelling_added", "Added new spelling correction"),
              ("clipboard_cache", "New content in clipboard cache")]

    def _page_sounds(self) -> QWidget:
        w, lay = self._page()
        g, gl = _group("Sounds")
        self._sound_files: dict[str, str] = {}
        grid = QGridLayout()
        grid.setVerticalSpacing(4)
        for r, (key, text) in enumerate(self.SOUNDS):
            grid.addWidget(self.bind(f"sound.{key}.enabled", QCheckBox(text)), r, 0)
            b = QPushButton(icon("folder"), "Select audio file")
            b.setFixedWidth(138)
            b.clicked.connect(lambda _=False, k=key: self._pick_sound(k))
            grid.addWidget(b, r, 1)
            t = QToolButton()
            t.setAutoRaise(True)
            t.setToolTip("Play")
            t.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_MediaPlay))
            t.clicked.connect(lambda _=False, k=key: play_sound(self._sound_files.get(k, "")))
            grid.addWidget(t, r, 2)
            self.bind_custom(f"sound.{key}.file", lambda k=key: self._sound_files.get(k, ""),
                             lambda v, k=key: self._sound_files.__setitem__(k, v))
        grid.setColumnStretch(0, 1)
        gl.addLayout(grid)
        lay.addWidget(g)
        lay.addStretch(1)
        return w

    def _pick_sound(self, key: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select audio file", self._sound_files.get(key, ""),
                                              "Wave audio (*.wav);;All files (*)")
        if path:
            self._sound_files[key] = path
            play_sound(path)

    # ---- Phrase file / database
    def _page_phrase_file(self) -> QWidget:
        w, lay = self._page()
        g, gl = _group("Backup")
        keep = self.bind("backup.keep_enabled", QCheckBox("Keep a backup of the last"))
        n = self.bind("backup.keep_count", QSpinBox())
        n.setRange(1, 999)
        n.setFixedWidth(52)
        gl.addWidget(_row(keep, n, "phrase file versions"))
        gl.addWidget(QLabel("Backup file directory:"))
        self.backup_dir = QLineEdit()
        self.backup_dir.setPlaceholderText(str(paths.backups_dir()))
        self.bind("backup.directory", self.backup_dir)
        gl.addWidget(_row(self.backup_dir, _icon_button("folder", "Choose folder", self._pick_backup_dir),
                          stretch=False))
        lay.addWidget(g)
        g, gl = _group("Phrase file")
        db = QLineEdit(str(paths.db_path()))
        db.setReadOnly(True)
        gl.addWidget(_row(db, _icon_button("folder_open", "Open folder",
                                           lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.data_dir())))),
                          stretch=False))
        lay.addWidget(g)
        lay.addStretch(1)
        return w

    def _pick_backup_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Backup file directory", self.backup_dir.text() or str(paths.backups_dir()))
        if d:
            self.backup_dir.setText(d)

    # ---- AI
    @staticmethod
    def _key_setting(provider: str) -> str:
        return f"ai.{provider}_url" if provider in LOCAL_ENGINES else f"ai.{provider}_key"

    def _page_ai(self) -> QWidget:
        w, lay = self._page()
        lay.setSpacing(6)
        lay.addWidget(_wrap_label(f"{APP} can generate and process text using 3rd party AI services. If an API key "
                                  "is required, it can be obtained from the service provider."))
        lay.addSpacing(8)
        lay.addWidget(QLabel("Engine:"))
        self.ai_provider = self.bind("ai.provider", DataCombo([(t, v) for t, v, _ in PROVIDERS]))
        self.ai_provider.setFixedWidth(181)
        self.ai_visit = QPushButton()
        self.ai_visit.setObjectName("WideButton")
        self.ai_visit.clicked.connect(self._visit_provider)
        lay.addWidget(_row(self.ai_provider, self.ai_visit))
        self.ai_key_label = QLabel("Your API key:")
        lay.addWidget(self.ai_key_label)
        self.ai_key = QLineEdit()
        self.ai_key.setEchoMode(QLineEdit.Password)
        self.ai_key.setMinimumWidth(518)
        self.ai_test = _icon_button("restore", "Test the connection", self._test_ai)
        self.ai_status_icon = QLabel()
        lay.addWidget(_row(self.ai_key, self.ai_test, self.ai_status_icon))
        self.ai_status = QLabel()
        lay.addWidget(self.ai_status)
        lay.addWidget(QLabel("Boost prompt hotkey (select a prompt in any program, then press it):"))
        lay.addWidget(self.bind("promptboost.hotkey", Hotkey()))
        lay.addWidget(QLabel("Model (leave empty for the provider's default):"))
        self.ai_model = self.bind("ai.model", QLineEdit())
        self.ai_model.setFixedWidth(330)
        lay.addWidget(self.ai_model)
        lay.addStretch(1)
        self._ai_current = ""
        self.ai_provider.currentIndexChanged.connect(lambda _i: (self._stash_ai_key(), self._load_ai_key()))
        return w

    def _stash_ai_key(self) -> None:
        if getattr(self, "_ai_current", ""):
            self._ai_keys[self._ai_current] = self.ai_key.text().strip()

    def _load_ai_key(self) -> None:
        prov = self.ai_provider.value()
        self._ai_current = prov
        if prov not in self._ai_keys:
            self._ai_keys[prov] = self.store.setting(self._key_setting(prov), SCHEMA.get(self._key_setting(prov), ""))
        local = prov in LOCAL_ENGINES
        self.ai_key.setEchoMode(QLineEdit.Normal if local else QLineEdit.Password)
        self.ai_key.setText(self._ai_keys[prov])
        self.ai_key_label.setText(LOCAL_ENGINES.get(prov, "Your API key:"))
        name = next(t for t, v, _ in PROVIDERS if v == prov).split(" (")[0]
        self.ai_visit.setText(f"Visit {name}")
        self.ai_status.setText("")
        self.ai_status_icon.clear()
        if hasattr(self, "tr_provider"):
            self._update_translation_status()

    def _visit_provider(self) -> None:
        url = next(u for _, v, u in PROVIDERS if v == self.ai_provider.value())
        QDesktopServices.openUrl(QUrl(url))

    def _test_ai(self) -> None:
        self._stash_ai_key()
        settings = dict(self.store.settings())
        settings.update({self._key_setting(p): v for p, v in self._ai_keys.items()})
        settings["ai.provider"] = self.ai_provider.value()
        settings["ai.model"] = self.ai_model.text().strip()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            from phraseforge import ai
            ai.complete(settings, "Reply with the single word OK.")
            self.ai_status.setText("Connection works.")
            self.ai_status_icon.setPixmap(icon("info").pixmap(16, 16))
        except Exception as e:
            self.ai_status.setText(f"Invalid API key or service not reachable: {str(e)[:120]}")
            self.ai_status_icon.setPixmap(icon("warning").pixmap(16, 16))
        finally:
            QApplication.restoreOverrideCursor()

    def _page_ai_presets(self) -> QWidget:
        w, lay = self._page()
        lay.setSpacing(4)
        lay.addWidget(QLabel("Presets:"))
        self.presets_list = QListWidget()
        self.presets_list.setStyleSheet("QListWidget { background: white; border: 1px solid #b9b9b9; }")
        side = QVBoxLayout()
        side.addWidget(_icon_button("add", "Add preset", self._add_preset))
        side.addWidget(_icon_button("pencil", "Edit preset", self._edit_preset))
        side.addStretch(1)
        side.addWidget(_icon_button("delete", "Delete preset", self._delete_preset))
        row = QHBoxLayout()
        row.addWidget(self.presets_list, 1)
        row.addLayout(side)
        lay.addLayout(row, 1)
        self.presets_list.itemDoubleClicked.connect(lambda _it: self._edit_preset())
        self.bind_custom("ai.presets", self._presets_json, self._set_presets)
        return w

    def _set_presets(self, v: str) -> None:
        self.presets_list.clear()
        try:
            data = json.loads(v or "[]")
        except ValueError:
            data = []
        for p in data:
            if isinstance(p, dict) and p.get("name"):
                it = self._preset_item(p["name"], p.get("prompt", ""), p.get("model", ""))
                self.presets_list.addItem(it)
        if self.presets_list.count():
            self.presets_list.setCurrentRow(0)

    @staticmethod
    def _preset_item(name: str, prompt: str, model: str = ""):
        from PySide6.QtWidgets import QListWidgetItem
        it = QListWidgetItem(name)
        it.setData(Qt.UserRole, prompt)
        it.setData(Qt.UserRole + 1, "" if (model or "").lower() == "auto" else (model or ""))
        it.setToolTip(prompt)
        return it

    def _presets_json(self) -> str:
        out = []
        for i in range(self.presets_list.count()):
            it = self.presets_list.item(i)
            row = {"name": it.text(), "prompt": it.data(Qt.UserRole) or ""}
            if it.data(Qt.UserRole + 1):
                row["model"] = it.data(Qt.UserRole + 1)
            out.append(row)
        return json.dumps(out, ensure_ascii=False)

    def _preset_dialog(self, name: str = "", prompt: str = "", model: str = "",
                       run: bool = True):
        """PhraseExpress "AI Presets": Preset label, Instruction ("Prompt") and, behind the
        gear button, Model (Auto = the engine's model) with Reset to defaults.
        Returns (label, prompt, model) or None; run=False returns the dialog (tests)."""
        from phraseforge.ai import DEFAULT_MODELS
        d = QDialog(self)
        d.setWindowTitle("AI Presets")
        d.resize(480, 200)
        v = QVBoxLayout(d)
        v.addWidget(QLabel("Preset label:"))
        d.label_edit = QLineEdit(name)
        v.addWidget(d.label_edit)
        v.addWidget(QLabel('Instruction ("Prompt"):'))
        d.prompt_edit = QPlainTextEdit(prompt)
        d.prompt_edit.setFixedHeight(60)
        gear = _icon_button("settings", "Model options", lambda: d.model_box.setVisible(not d.model_box.isVisible()))

        def _enhance():
            from phraseforge.ui.ai_ui import enhance
            out = enhance(self.store, d.prompt_edit.toPlainText(), parent=d)
            if out:
                d.prompt_edit.setPlainText(out)
        d.enhance_btn = _icon_button("m_ai", "Enhance prompt (rewrite it with the AI engine)", _enhance)
        v.addWidget(_row(d.prompt_edit, gear, d.enhance_btn, stretch=False))
        d.model_box = QWidget()
        mb = QVBoxLayout(d.model_box)
        mb.setContentsMargins(0, 0, 0, 0)
        mb.addWidget(QLabel("Model:"))
        d.model_combo = QComboBox()
        d.model_combo.setEditable(True)
        d.model_combo.addItems(["Auto"] + sorted({m for m in DEFAULT_MODELS.values() if m}))
        d.model_combo.setCurrentText(model or "Auto")
        reset = QPushButton("Reset to defaults")
        reset.clicked.connect(lambda: d.model_combo.setCurrentText("Auto"))
        mb.addWidget(_row(d.model_combo, reset))
        d.model_box.setVisible(bool(model))
        v.addWidget(d.model_box)
        ok, cancel = QPushButton("OK"), QPushButton("Cancel")
        ok.setDefault(True)
        ok.clicked.connect(d.accept)
        cancel.clicked.connect(d.reject)
        v.addWidget(_row(QWidget(), ok, cancel))

        def result():
            m = d.model_combo.currentText().strip()
            return d.label_edit.text().strip(), d.prompt_edit.toPlainText().strip(), \
                "" if m.lower() in ("", "auto") else m
        d.result_tuple = result
        if not run:
            return d
        if d.exec() == QDialog.Accepted and d.label_edit.text().strip():
            return result()
        return None

    def _add_preset(self) -> None:
        r = self._preset_dialog()
        if r:
            self.presets_list.addItem(self._preset_item(*r))
            self.presets_list.setCurrentRow(self.presets_list.count() - 1)

    def _edit_preset(self) -> None:
        it = self.presets_list.currentItem()
        if it:
            r = self._preset_dialog(it.text(), it.data(Qt.UserRole) or "", it.data(Qt.UserRole + 1) or "")
            if r:
                it.setText(r[0])
                it.setData(Qt.UserRole, r[1])
                it.setData(Qt.UserRole + 1, r[2])
                it.setToolTip(r[1])

    def _delete_preset(self) -> None:
        row = self.presets_list.currentRow()
        if row >= 0:
            self.presets_list.takeItem(row)

    def _page_ai_instructions(self) -> QWidget:
        w, lay = self._page()
        lay.setSpacing(4)
        lay.addWidget(QLabel("Info about you to provide better responses:"))
        lay.addWidget(self.bind("ai.instructions.about", QPlainTextEdit()), 1)
        lay.addSpacing(6)
        lay.addWidget(QLabel("How would you like the engine to respond:"))
        lay.addWidget(self.bind("ai.instructions.respond", QPlainTextEdit()), 1)
        return w

    # ---- Translation
    def _page_translation(self) -> QWidget:
        w, lay = self._page()
        lay.setSpacing(6)
        lay.addWidget(_wrap_label(f"{APP} can translate phrases and text into other languages using a 3rd party "
                                  "AI service. If an API key is required, it can be obtained from the service "
                                  "provider."))
        lay.addSpacing(8)
        lay.addWidget(QLabel("Translation Engine:"))
        self.tr_provider = self.bind("translation.provider",
                                     DataCombo([(t, v) for t, v, _ in TRANSLATION_PROVIDERS]))
        self.tr_provider.setFixedWidth(181)
        self.tr_visit = QPushButton("Visit provider")
        self.tr_visit.setObjectName("WideButton")
        self.tr_visit.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(next(
            u for _, v, u in TRANSLATION_PROVIDERS if v == self.tr_provider.value()))))
        lay.addWidget(_row(self.tr_provider, self.tr_visit))
        self.tr_key_label = QLabel("API key:")
        lay.addWidget(self.tr_key_label)
        self.tr_key = QLineEdit()           # same key store as the AI page (one key per engine)
        self.tr_key.setEchoMode(QLineEdit.Password)
        self.tr_key.setMinimumWidth(518)
        self.tr_key.textEdited.connect(self._translation_key_edited)
        lay.addWidget(self.tr_key)
        self.tr_status = QLabel()
        self.tr_status.setWordWrap(True)
        lay.addWidget(self.tr_status)
        lay.addStretch(1)
        self.tr_provider.currentIndexChanged.connect(lambda _i: self._update_translation_status())
        return w

    def _translation_key_edited(self, text: str) -> None:
        prov = self.tr_provider.value()
        if getattr(self, "_ai_current", "") == prov:
            self.ai_key.setText(text.strip())
        self._ai_keys[prov] = text.strip()
        self._update_translation_status(reload_key=False)

    def _update_translation_status(self, reload_key: bool = True) -> None:
        prov = self.tr_provider.value()
        if getattr(self, "_ai_current", "") == prov and hasattr(self, "ai_key"):
            self._ai_keys[prov] = self.ai_key.text().strip()
        key = self._ai_keys.get(prov) if prov in self._ai_keys else \
            self.store.setting(self._key_setting(prov), SCHEMA.get(self._key_setting(prov), ""))
        if not hasattr(self, "tr_key"):
            return
        name = next(t for t, v, _ in TRANSLATION_PROVIDERS if v == prov).split(" (")[0]
        self.tr_visit.setText(f"Visit {name}")
        local = prov in LOCAL_ENGINES
        self.tr_key_label.setText(LOCAL_ENGINES.get(prov, "API key:"))
        self.tr_key.setEchoMode(QLineEdit.Normal if local else QLineEdit.Password)
        if reload_key:
            self.tr_key.setText(key or "")
        if local:
            self.tr_status.setText(f"Uses the local server at {key or SCHEMA.get(self._key_setting(prov), '')}.")
        else:
            self.tr_status.setText("API key is set." if key else "No API key for this engine yet.")

    def _page_translation_ignored(self) -> QWidget:
        w, lay = self._page()
        lay.setSpacing(4)
        lay.addWidget(QLabel("Words excluded from translation (one word per line):"))
        lay.addWidget(self.bind("translation.ignored_words", QPlainTextEdit()), 1)
        return w

    def _page_translation_glossaries(self) -> QWidget:
        w, lay = self._page()
        lay.setSpacing(4)
        lay.addWidget(QLabel("Glossaries:"))
        self.gloss_combo = QComboBox()
        self.gloss_combo.setMinimumWidth(445)
        lay.addWidget(_row(self.gloss_combo, _icon_button("add", "New glossary", self._add_glossary),
                           _icon_button("pencil", "Rename glossary", self._rename_glossary),
                           _icon_button("delete", "Delete glossary", self._delete_glossary)))
        lay.addWidget(QLabel("Language pairs (one per line, syntax: OriginalWord=DesiredTranslation):"))
        self.gloss_text = QPlainTextEdit()
        lay.addWidget(self.gloss_text, 1)
        self._glossaries: dict[str, str] = {}
        self._gloss_langs: dict[str, list[str]] = {}
        self._gloss_current = ""
        self.gloss_combo.currentTextChanged.connect(self._switch_glossary)
        self.bind_custom("translation.glossaries", self._glossaries_json, self._set_glossaries)
        self.bind_custom("translation.glossary_langs",
                         lambda: json.dumps({k: v for k, v in self._gloss_langs.items() if k in self._glossaries},
                                            ensure_ascii=False),
                         self._set_glossary_langs)
        return w

    def _stash_glossary(self) -> None:
        if self._gloss_current in self._glossaries:
            self._glossaries[self._gloss_current] = self.gloss_text.toPlainText()

    def _switch_glossary(self, name: str) -> None:
        self._stash_glossary()
        self._gloss_current = name
        self.gloss_text.setPlainText(self._glossaries.get(name, ""))
        self.gloss_text.setEnabled(bool(name))

    def _set_glossaries(self, v: str) -> None:
        try:
            data = json.loads(v or "{}")
        except ValueError:
            data = {}
        self._glossaries = {str(k): str(t) for k, t in data.items()} if isinstance(data, dict) else {}
        self._gloss_current = ""
        self.gloss_combo.blockSignals(True)
        self.gloss_combo.clear()
        self.gloss_combo.addItems(list(self._glossaries))
        self.gloss_combo.blockSignals(False)
        self._switch_glossary(self.gloss_combo.currentText())

    def _set_glossary_langs(self, v: str) -> None:
        try:
            data = json.loads(v or "{}")
        except ValueError:
            data = {}
        self._gloss_langs = {str(k): list(p)[:2] for k, p in data.items()
                             if isinstance(p, (list, tuple)) and len(p) == 2} if isinstance(data, dict) else {}

    def _glossary_dialog(self, name: str = "", src: str = "English", dst: str = "English", run: bool = True):
        """PhraseExpress "New Glossary": Name, Source language, Target language."""
        d = QDialog(self)
        d.setWindowTitle("New Glossary" if not name else "Edit Glossary")
        g = QGridLayout(d)
        g.addWidget(QLabel("Name:"), 0, 0, 1, 2)
        d.name_edit = QLineEdit(name)
        g.addWidget(d.name_edit, 1, 0, 1, 2)
        g.addWidget(QLabel("Source language:"), 2, 0)
        g.addWidget(QLabel("Target language:"), 2, 1)
        d.src_combo, d.dst_combo = QComboBox(), QComboBox()
        for c, val in ((d.src_combo, src), (d.dst_combo, dst)):
            c.setEditable(True)
            c.addItems(TRANSLATION_LANGUAGES)
            c.setCurrentText(val)
        g.addWidget(d.src_combo, 3, 0)
        g.addWidget(d.dst_combo, 3, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        g.addWidget(bb, 4, 0, 1, 2)
        d.result_tuple = lambda: (d.name_edit.text().strip(), d.src_combo.currentText().strip(),
                                  d.dst_combo.currentText().strip())
        if not run:
            return d
        return d.result_tuple() if d.exec() == QDialog.Accepted else None

    def _glossaries_json(self) -> str:
        self._stash_glossary()
        return json.dumps(self._glossaries, ensure_ascii=False)

    def _add_glossary(self, name: str | None = None, src: str = "", dst: str = "") -> None:
        if name is None:
            r = self._glossary_dialog()
            if not r:
                return
            name, src, dst = r
        name = (name or "").strip()
        if name and name not in self._glossaries:
            self._stash_glossary()
            self._glossaries[name] = ""
            if src and dst:
                self._gloss_langs[name] = [src, dst]
            self.gloss_combo.addItem(name)
            self.gloss_combo.setCurrentText(name)

    def _rename_glossary(self) -> None:
        old = self.gloss_combo.currentText()
        if not old:
            return
        src, dst = self._gloss_langs.get(old, ["English", "English"])
        r = self._glossary_dialog(old, src, dst)
        if not r:
            return
        new, src, dst = r
        if new and (new == old or new not in self._glossaries):
            self._stash_glossary()
            self._glossaries[new] = self._glossaries.pop(old)
            self._gloss_langs.pop(old, None)
            self._gloss_langs[new] = [src, dst]
            self._gloss_current = new
            self.gloss_combo.setItemText(self.gloss_combo.currentIndex(), new)

    def _delete_glossary(self) -> None:
        name = self.gloss_combo.currentText()
        if name:
            self._glossaries.pop(name, None)
            self._gloss_langs.pop(name, None)
            self._gloss_current = ""
            self.gloss_combo.removeItem(self.gloss_combo.currentIndex())

    # ---- Network
    def _page_network(self) -> QWidget:
        w, lay = self._page()
        g = QGroupBox("Proxy Settings")
        grid = QGridLayout(g)
        grid.setContentsMargins(12, 10, 12, 10)
        server, user = self.bind("net.proxy_server", QLineEdit()), self.bind("net.proxy_user", QLineEdit())
        pw = self.bind("net.proxy_password", QLineEdit())
        pw.setEchoMode(QLineEdit.Password)
        port = self.bind("net.proxy_port", QSpinBox())
        port.setRange(1, 65535)
        port.setFixedWidth(60)
        grid.addWidget(QLabel("Server:"), 0, 0, Qt.AlignRight)
        grid.addWidget(server, 0, 1)
        grid.addWidget(QLabel("Username:"), 0, 2, Qt.AlignRight)
        grid.addWidget(user, 0, 3)
        grid.addWidget(QLabel("Port:"), 1, 0, Qt.AlignRight)
        grid.addWidget(port, 1, 1, Qt.AlignLeft)
        grid.addWidget(QLabel("Password:"), 1, 2, Qt.AlignRight)
        grid.addWidget(pw, 1, 3)
        lay.addWidget(g)
        gl_note = _wrap_label("Used for AI, translation, HTTP macros and Google Drive sync. "
                              "Leave Server empty to connect directly.")
        lay.addWidget(gl_note)
        lay.addStretch(1)
        return w

    # ---- Screen OCR (built in: Windows OCR engine, no external program)
    def _page_ocr(self) -> QWidget:
        w, lay = self._page()
        g, gl = _group("Text recognition")
        gl.addWidget(_wrap_label("PhraseForge reads text from the screen with the OCR engine built into "
                                 "Windows. No other program is needed. To read Arabic, add the Arabic "
                                 "language in Windows Settings > Time & language > Language & region."))
        gl.addWidget(QLabel("OCR language:"))
        self.ocr_language = DataCombo([])
        self.ocr_language.setEditable(True)
        self.ocr_language.setFixedWidth(198)
        self.ocr_language.setToolTip(tr(OCR_AUTO_HINT))
        self._ocr_queried = False   # ask Windows for its OCR languages only when the page is opened
        self.bind_custom("ocr.language", lambda: self.ocr_language.currentText().strip(),
                         lambda v: self._fill_ocr_languages(v, query=self._ocr_queried))
        test = QPushButton("Test OCR")
        test.clicked.connect(self._test_ocr)
        gl.addWidget(_row(self.ocr_language, test))
        self.ocr_installed = _wrap_label("")
        gl.addWidget(self.ocr_installed)
        gl.addWidget(_wrap_label(OCR_AUTO_HINT))
        self.ocr_scale = self.bind("ocr.scale", DataCombo(
            [("Automatic", "0"), ("1x", "1"), ("2x", "2"), ("3x", "3"), ("4x", "4")]))
        gl.addWidget(_row("Enlarge the capture before reading:", self.ocr_scale))
        gl.addWidget(QLabel("Keep only these characters (empty = all):"))
        self.ocr_whitelist = self.bind("ocr.whitelist", QLineEdit())
        self.ocr_whitelist.setPlaceholderText("0123456789")
        gl.addWidget(self.ocr_whitelist)
        gl.addWidget(QLabel("Remove these characters:"))
        self.ocr_blacklist = self.bind("ocr.blacklist", QLineEdit())
        gl.addWidget(self.ocr_blacklist)
        gl.addWidget(self.bind("ocr.keep_line_breaks", QCheckBox("Keep line breaks")))
        lay.addWidget(g)
        g, gl = _group("Mistral OCR (cloud)")
        gl.addWidget(_wrap_label("Mistral AI's OCR reads PDF files and images into Markdown, with tables and "
                                 "images (Tools > OCR PDF / image). It can also read screen captures. "
                                 "The file or capture is uploaded to Mistral's servers, so use it only for "
                                 "content you may share."))
        self.ocr_engine = self.bind("ocr.engine", DataCombo(
            [("Windows OCR (built in, offline)", "windows"), ("Mistral OCR (cloud)", "mistral")]))
        gl.addWidget(_row("Engine for screen captures:", self.ocr_engine))
        gl.addWidget(QLabel("Mistral API key:"))
        self.mistral_key = self.bind("ai.mistral_key", QLineEdit())
        self.mistral_key.setEchoMode(QLineEdit.Password)
        visit = QPushButton("Get a key")
        visit.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://console.mistral.ai/api-keys")))
        gl.addWidget(_row(self.mistral_key, visit))
        lay.addWidget(g)
        g, gl = _group("Output")
        gl.addWidget(self.bind("ocr.save_to_clipboard", QCheckBox("Save to clipboard")))
        gl.addWidget(self.bind("ocr.show_popup", QCheckBox("Show the result in a notification")))
        gl.addWidget(QLabel("Log captures to file (empty = off):"))
        self.ocr_log_file = self.bind("ocr.log_file", QLineEdit())
        gl.addWidget(_row(self.ocr_log_file, _icon_button("folder", "Browse", self._browse_ocr_log), stretch=False))
        gl.addWidget(QLabel("Log format (${capture}, ${linebreak}, ${tab}, ${timestamp}):"))
        self.ocr_log_format = self.bind("ocr.log_format", QLineEdit())
        gl.addWidget(self.ocr_log_format)
        lay.addWidget(g)
        g, gl = _group("Hotkeys")
        gl.addWidget(QLabel("Recognize a screen area and copy the text:"))
        self.ocr_hotkey = self.bind("ocr.hotkey", Hotkey())
        gl.addWidget(self.ocr_hotkey)
        gl.addWidget(QLabel("Re-capture the last area:"))
        gl.addWidget(self.bind("ocr.recapture_hotkey", Hotkey()))
        gl.addWidget(QLabel("Read the text line under the mouse pointer:"))
        gl.addWidget(self.bind("ocr.textline_hotkey", Hotkey()))
        gl.addWidget(QLabel("Read from the mouse pointer to the end of the line:"))
        gl.addWidget(self.bind("ocr.forward_hotkey", Hotkey()))
        gl.addWidget(QLabel("Read the text block (bubble) around the mouse pointer:"))
        gl.addWidget(self.bind("ocr.bubble_hotkey", Hotkey()))
        gl.addWidget(QLabel("Quick-access languages (up to 3, comma separated):"))
        self.ocr_quick = self.bind("ocr.quick_languages", QLineEdit())
        gl.addWidget(self.ocr_quick)
        for i in (1, 2, 3):
            gl.addWidget(QLabel(f"Capture with quick-access language {i}:"))
            gl.addWidget(self.bind(f"ocr.quick{i}_hotkey", Hotkey()))
        lay.addWidget(g)
        g, gl = _group("Replace")
        gl.addWidget(_wrap_label("Fix recognised text with regular expressions, one rule per line: "
                                 "find => replace. Start a section with [Arabic] to apply the rules "
                                 "below it to that OCR language only."))
        self.ocr_replace = self.bind("ocr.replace_rules", QPlainTextEdit())
        self.ocr_replace.setPlaceholderText("\\s+([.,;:!?]) => \\1\n[Arabic]\nي => ی")
        self.ocr_replace.setFixedHeight(90)
        gl.addWidget(self.ocr_replace)
        lay.addWidget(g)
        lay.addStretch(1)
        return w

    def _browse_ocr_log(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "OCR log file", self.ocr_log_file.text(), "Text files (*.txt);;All files (*)")
        if path:
            self.ocr_log_file.setText(path)

    def _fill_ocr_languages(self, current: str, query: bool = True) -> None:
        langs: list[str] = []
        if query:
            self._ocr_queried = True
            try:
                from phraseforge.ocr import WindowsOCR
                ocr = WindowsOCR()
                if ocr.available():
                    langs = ocr.languages()
            except Exception:
                langs = []
            self.ocr_installed.setText(
                tr("Installed in Windows: ") + ", ".join(langs) if langs else
                tr("Windows reported no OCR languages."))
        self.ocr_language.clear()
        self.ocr_language.addItems(["Auto"] + (langs or ["English", "Arabic"]))
        self.ocr_language.setEditText(current or "Auto")
        i = self.ocr_language.findText(current or "Auto")
        if i >= 0:
            self.ocr_language.setCurrentIndex(i)

    def _test_ocr(self) -> None:
        try:
            from phraseforge.app import _grab_screen_png
            from phraseforge.ocr import WindowsOCR
            from phraseforge.ui.region_select import select_region
            self.hide()
            rect = select_region()
            png = _grab_screen_png(rect) if rect else None
            self.show()
            if not png:
                return
            v = self.values()
            text = WindowsOCR(scale=int(v.get("ocr.scale", "0") or 0), whitelist=v.get("ocr.whitelist", ""),
                              blacklist=v.get("ocr.blacklist", "")).ocr_png(
                png, language=self.ocr_language.currentText(),
                keep_line_breaks=_b(self.values().get("ocr.keep_line_breaks", "1")))
            QMessageBox.information(self, tr("Screen OCR"), text or tr("(no text recognised)"))
        except Exception as e:  # show any OCR problem to the user
            self.show()
            QMessageBox.warning(self, tr("Screen OCR"), tr(str(e)))

    # ---- OneNote (desktop app through its official COM API)
    def _page_onenote(self) -> QWidget:
        w, lay = self._page()
        g, gl = _group("Microsoft OneNote")
        gl.addWidget(_wrap_label("PhraseForge talks to the OneNote desktop app through OneNote's own "
                                 "programming interface. OneNote must be installed and opened once."))
        gl.addWidget(QLabel("ONENOTE.EXE location:"))
        self.onenote_exe = self.bind("onenote.exe", QLineEdit())
        test = QPushButton("Test connection")
        test.clicked.connect(self._test_onenote)
        gl.addWidget(_row(self.onenote_exe, _icon_button("folder", "Browse", self._browse_onenote_exe), test,
                          stretch=False))
        gl.addWidget(self.bind("onenote.include_ocr",
                               QCheckBox("When reading pages, include text OneNote recognised in pictures")))
        lay.addWidget(g)

        g, gl = _group("Send to OneNote")
        gl.addWidget(QLabel("Default page or section (empty = a new page in Quick Notes):"))
        self.onenote_target = self.bind("onenote.default_target", QLineEdit())
        self.onenote_target.setPlaceholderText("Quick Notes")
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse_onenote_target)
        gl.addWidget(_row(self.onenote_target, browse, stretch=False))
        gl.addWidget(QLabel("Hotkey: send the clipboard to OneNote"))
        gl.addWidget(self.bind("onenote.send_hotkey", Hotkey()))
        gl.addWidget(QLabel("Hotkey: new quick note (Ctrl+Enter sends it here)"))
        gl.addWidget(self.bind("onenote.quick_note_hotkey", Hotkey()))
        lay.addWidget(g)

        g, gl = _group("Screen clipping")
        gl.addWidget(QLabel("Hotkey: clip a screen area"))
        gl.addWidget(self.bind("onenote.clip_hotkey", Hotkey()))
        self.onenote_clip_action = self.bind("onenote.clip_action", DataCombo(
            [("Add the picture to OneNote", "image"), ("Copy the recognised text (built-in OCR)", "ocr"),
             ("Both", "both")]))
        gl.addWidget(_row("Then:", self.onenote_clip_action))
        lay.addWidget(g)
        lay.addStretch(1)
        return w

    # ---- Search files (Listary-style launcher)
    def _page_file_search(self) -> QWidget:
        w, lay = self._page()
        g, gl = _group("Search files")
        gl.addWidget(_wrap_label("Find and open files, folders and programs by typing part of their name. "
                                 "All words must match, in any order. Enter opens, Ctrl+Enter opens the "
                                 "folder, Shift+Enter types the path into the program you were in."))
        gl.addWidget(self.bind("filesearch.enabled", QCheckBox("Index files when PhraseForge starts")))
        gl.addWidget(QLabel("Hotkey: open Search files"))
        gl.addWidget(self.bind("filesearch.hotkey", Hotkey()))
        gl.addWidget(self.bind("filesearch.double_ctrl", QCheckBox("Also open it by pressing Ctrl twice")))
        self.filesearch_again = self.bind("filesearch.press_again", DataCombo(
            [("Hide Search files", "hide"), ("Keep it open", "keep")]))
        gl.addWidget(_row("When pressing again:", self.filesearch_again))
        gl.addWidget(_wrap_label("In the window: Ctrl+N / Ctrl+P next and previous result, Ctrl+O actions. "
                                 "Command keywords: opt, rebuild, cmd, cmda, psh, psha, uninstall, connections, hosts."))
        lay.addWidget(g)
        g, gl = _group("Filters")
        gl.addWidget(_wrap_label("Type \"keyword:\" before your words, e.g. \"doc: report\". Built in: folder, file, "
                                 "doc, pic, video, audio. Add your own, one per line: "
                                 "keyword = Name; ext=pdf,docx; in=C:\\Folder; folders=0"))
        self.filesearch_filters = self.bind("filesearch.filters", QPlainTextEdit())
        self.filesearch_filters.setFixedHeight(60)
        gl.addWidget(self.filesearch_filters)
        lay.addWidget(g)
        g, gl = _group("Priorities")
        gl.addWidget(_wrap_label("One rule per line: high, normal, rare or skip, a colon, then a folder "
                                 "(environment variables allowed) or re: and a regular expression for the "
                                 "file name. High results come first, rare ones last, skip is not indexed."))
        self.filesearch_prio = self.bind("filesearch.priorities", QPlainTextEdit())
        self.filesearch_prio.setFixedHeight(110)
        gl.addWidget(self.filesearch_prio)
        lay.addWidget(g)
        g, gl = _group("Custom commands")
        gl.addWidget(_wrap_label("Type a keyword, a space and your text, then Enter. One per line: "
                                 "keyword = Title | program | parameters | working folder. "
                                 "{query} is the text you typed."))
        self.filesearch_commands = self.bind("filesearch.commands", QPlainTextEdit())
        self.filesearch_commands.setFixedHeight(60)
        gl.addWidget(self.filesearch_commands)
        lay.addWidget(g)
        g, gl = _group("Favorite folders")
        gl.addWidget(_wrap_label("Shown in Search files before you type anything. One folder per line."))
        self.filesearch_favorites = self.bind("filesearch.favorites", QPlainTextEdit())
        self.filesearch_favorites.setFixedHeight(60)
        gl.addWidget(self.filesearch_favorites)
        lay.addWidget(g)
        g, gl = _group("Actions (Ctrl+O)")
        gl.addWidget(_wrap_label("Built in: Open Containing Folder, Copy, Cut, Copy Path, Copy File Name. "
                                 "Custom actions, one per line: Title = program | parameters | working folder. "
                                 "{path}, {folder} and {name} are filled in."))
        self.filesearch_actions = self.bind("filesearch.actions", QPlainTextEdit())
        self.filesearch_actions.setFixedHeight(60)
        gl.addWidget(self.filesearch_actions)
        lay.addWidget(g)
        g, gl = _group("Web search keywords")
        gl.addWidget(_wrap_label("Type a keyword, a space and your words, e.g. \"g weather\", then Enter. "
                                 "One keyword per line: keyword=address with {q} where the words go. "
                                 "Empty = the built-in list: g, wiki, so, bing, b, gmail, twitter, youtube (yt), maps, amazon, ebay, imdb, facebook."))
        self.filesearch_web = self.bind("filesearch.web_keywords", QPlainTextEdit())
        self.filesearch_web.setFixedHeight(80)
        self.filesearch_web.setPlaceholderText(filesearch_defaults())
        gl.addWidget(self.filesearch_web)
        lay.addWidget(g)
        g, gl = _group("Folders to index")
        gl.addWidget(_wrap_label("One folder per line. Empty = Start menu, Desktop, Documents and Downloads."))
        self.filesearch_roots = self.bind("filesearch.roots", QPlainTextEdit())
        self.filesearch_roots.setFixedHeight(90)
        gl.addWidget(self.filesearch_roots)
        add = QPushButton("Add folder...")
        add.clicked.connect(self._add_filesearch_root)
        gl.addWidget(_row(add))
        gl.addWidget(self.bind("filesearch.include_hidden", QCheckBox("Include hidden and system files")))
        self.filesearch_refresh = self.bind("filesearch.refresh_minutes", _spin(5, 1440))
        gl.addWidget(_row("Rebuild the index every", self.filesearch_refresh, "minutes"))
        lay.addWidget(g)
        lay.addStretch(1)
        return w

    def _add_filesearch_root(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Folder to index")
        if d:
            text = self.filesearch_roots.toPlainText().rstrip()
            self.filesearch_roots.setPlainText((text + "\n" if text else "") + d)

    def _browse_onenote_exe(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "ONENOTE.EXE", self.onenote_exe.text(), "Programs (*.exe)")
        if path:
            self.onenote_exe.setText(path)

    def _browse_onenote_target(self) -> None:
        from phraseforge.ui.onenote_picker import OneNotePicker, default_client_factory
        dlg = OneNotePicker(self, mode="target", current=self.onenote_target.text(),
                            client_factory=default_client_factory(self.onenote_exe.text().strip()))
        if dlg.exec() and dlg.selected_ref() is not None:
            self.onenote_target.setText(dlg.selected_ref())

    def _test_onenote(self) -> None:
        exe = self.onenote_exe.text().strip()

        def count():
            from phraseforge.onenote import OneNote, flatten
            nodes = OneNote(exe).notebooks()
            return (len(nodes), len(flatten(nodes, "section")), len(flatten(nodes, "page")))

        ok, res = _run_with_wait(self, "Connecting to OneNote...", count)
        if ok:
            QMessageBox.information(self, "OneNote", "Connected: {} notebook(s), {} section(s), {} page(s).".format(*res))
        else:
            QMessageBox.warning(self, "OneNote", f"Could not connect to OneNote.\n\n{res}")

    # ---- Backup & Sync (Google Drive / folder)
    def _page_cloud(self) -> QWidget:
        w, lay = self._page()
        g, gl = _group("Back up and synchronize phrases")
        self.cloud_provider = QButtonGroup(w)
        self.cloud_radios = {}
        for val, text in (("off", "Off (this PC only)"),
                          ("gdrive", "Google Drive: sign in with your Google account"),
                          ("folder", "A folder, e.g. one synced by Google Drive for Desktop")):
            rb = QRadioButton(text)
            self.cloud_provider.addButton(rb)
            self.cloud_radios[val] = rb
            gl.addWidget(rb)
        self.bind_custom("sync.provider",
                         lambda: next((v for v, rb in self.cloud_radios.items() if rb.isChecked()), "off"),
                         lambda v: self.cloud_radios.get(v or "off", self.cloud_radios["off"]).setChecked(True))
        lay.addWidget(g)

        self.gdrive_box, gb = _group("Google Drive")
        self.gdrive_status = QLabel()
        self.gdrive_status.setWordWrap(True)
        gb.addWidget(self.gdrive_status)
        self.gdrive_client_btn = QPushButton("OAuth client file...")
        self.gdrive_client_btn.setToolTip('The "Desktop app" OAuth client JSON from Google Cloud Console')
        self.gdrive_client_btn.clicked.connect(self._choose_gdrive_client)
        self.gdrive_signin_btn = QPushButton("Sign in with Google")
        self.gdrive_signin_btn.clicked.connect(self._gdrive_sign_in_out)
        help_btn = QPushButton("How to set up")
        help_btn.clicked.connect(self._gdrive_help)
        gb.addWidget(_row(self.gdrive_client_btn, self.gdrive_signin_btn, help_btn))
        self.gdrive_folder = self.bind("sync.gdrive_folder", QLineEdit())
        gb.addWidget(_row("Drive folder:", self.gdrive_folder))
        lay.addWidget(self.gdrive_box)

        self.folder_box, fb = _group("Folder")
        self.sync_folder = self.bind("sync.folder_path", QLineEdit())
        self.sync_folder.setPlaceholderText(r"e.g. G:\My Drive\PhraseForge")
        fb.addWidget(_row(self.sync_folder, _icon_button("folder", "Browse", self._browse_sync_folder), stretch=False))
        lay.addWidget(self.folder_box)

        g, ob = _group("Options")
        self.sync_auto = self.bind("sync.auto", QCheckBox("Synchronize automatically every"))
        self.sync_interval = self.bind("sync.interval_min", _spin(1, 1440))
        ob.addWidget(_row(self.sync_auto, self.sync_interval, "minutes, at start and on exit"))
        self.cloud_backup_auto = self.bind("backup.cloud_auto", QCheckBox("Back up to the cloud every"))
        self.cloud_backup_hours = self.bind("backup.cloud_interval_hours", _spin(1, 720))
        ob.addWidget(_row(self.cloud_backup_auto, self.cloud_backup_hours, "hours"))
        self.cloud_keep = self.bind("backup.cloud_keep", _spin(1, 200))
        ob.addWidget(_row("Keep the newest", self.cloud_keep, "cloud backups"))
        lay.addWidget(g)

        sync_now = QPushButton("Synchronize now")
        sync_now.clicked.connect(lambda: self._cloud_action("sync"))
        backup_now = QPushButton("Back up now")
        backup_now.clicked.connect(lambda: self._cloud_action("backup"))
        restore = QPushButton("Restore from cloud backup...")
        restore.clicked.connect(lambda: self._cloud_action("restore"))
        self.cloud_last = QLabel()
        lay.addWidget(_row(sync_now, backup_now, restore))
        lay.addWidget(self.cloud_last)
        lay.addStretch(1)
        for rb in self.cloud_radios.values():
            rb.toggled.connect(self._update_cloud_ui)
        self._syncs.append(self._update_cloud_ui)
        return w

    def _drive(self):
        from phraseforge.cloud.gdrive import GoogleDrive
        if not hasattr(self, "_gdrive_obj"):
            self._gdrive_obj = GoogleDrive()
        return self._gdrive_obj

    def _update_cloud_ui(self, *_):
        prov = next((v for v, rb in self.cloud_radios.items() if rb.isChecked()), "off")
        self.gdrive_box.setEnabled(prov == "gdrive")
        self.folder_box.setEnabled(prov == "folder")
        try:
            d = self._drive()
            if not d.has_client():
                self.gdrive_status.setText("Step 1: choose your Google OAuth client file (see How to set up).")
                self.gdrive_signin_btn.setEnabled(False)
                self.gdrive_signin_btn.setText("Sign in with Google")
            elif d.signed_in():
                self.gdrive_status.setText("Signed in to Google Drive. PhraseForge can only see the files it created.")
                self.gdrive_signin_btn.setEnabled(True)
                self.gdrive_signin_btn.setText("Sign out")
            else:
                self.gdrive_status.setText("Not signed in. Click \"Sign in with Google\": your browser opens Google's login page.")
                self.gdrive_signin_btn.setEnabled(True)
                self.gdrive_signin_btn.setText("Sign in with Google")
        except Exception as e:  # library missing etc.
            self.gdrive_status.setText(f"Google Drive is not available: {e}")
            self.gdrive_signin_btn.setEnabled(False)
        last = self.store.setting("sync.last_time", "")
        self.cloud_last.setText(f"Last synchronized: {last.replace('T', ' ')}" if last else "Not synchronized yet.")

    def _choose_gdrive_client(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Google OAuth client file", "", "JSON (*.json)")
        if not path:
            return
        try:
            from phraseforge.cloud.gdrive import install_client_file
            install_client_file(path)
        except Exception as e:
            QMessageBox.warning(self, "Google Drive", str(e))
        self._update_cloud_ui()

    def _gdrive_sign_in_out(self) -> None:
        d = self._drive()
        if d.signed_in():
            if QMessageBox.question(self, "Google Drive", "Sign out and remove PhraseForge's access to Google Drive?") \
                    == QMessageBox.Yes:
                d.sign_out()
            self._update_cloud_ui()
            return
        ok, err = _run_with_wait(self, "Waiting for Google sign-in in your browser...", d.sign_in)
        if not ok:
            QMessageBox.warning(self, "Google Drive", f"Sign-in did not complete.\n\n{err}")
        else:
            email = d.email()
            QMessageBox.information(self, "Google Drive", f"Signed in{(' as ' + email) if email else ''}.")
            self.cloud_radios["gdrive"].setChecked(True)
        self._update_cloud_ui()

    def _gdrive_help(self) -> None:
        QMessageBox.information(self, "Set up Google sign-in", (
            "Google asks every app that uses Drive for its own free \"OAuth client\". One-time setup:\n\n"
            "1. Open console.cloud.google.com and create a project (any name).\n"
            "2. APIs & Services > Library: enable \"Google Drive API\".\n"
            "3. OAuth consent screen: User type External, add your own Google address as a test user.\n"
            "4. Credentials > Create credentials > OAuth client ID > Application type \"Desktop app\".\n"
            "5. Download the JSON file, then click \"OAuth client file...\" here and choose it.\n"
            "6. Click \"Sign in with Google\".\n\n"
            "PhraseForge only asks for access to files it creates itself (drive.file)."))

    def _browse_sync_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Sync folder", self.sync_folder.text())
        if d:
            self.sync_folder.setText(d)

    def _cloud_action(self, what: str) -> None:
        """Synchronize / back up / restore right away using the settings shown on this page."""
        self.save()
        from phraseforge.cloud.sync import CloudSync, make_remote
        try:
            remote = make_remote(self.store, self._drive())
        except Exception as e:
            QMessageBox.warning(self, "Backup & Sync", str(e))
            return
        if remote is None:
            QMessageBox.information(self, "Backup & Sync",
                                    "Choose Google Drive (and sign in) or a sync folder first.")
            return
        cs = CloudSync(self.store, remote)
        keep = int(self.store.setting("backup.cloud_keep", "10") or 10)
        if what == "backup":
            ok, res = _run_with_wait(self, "Backing up...", lambda: cs.backup_now(keep))
            msg = f"Backup saved: {res}" if ok else f"Backup failed: {res}"
            (QMessageBox.information if ok else QMessageBox.warning)(self, "Backup & Sync", msg)
        elif what == "restore":
            ok, files = _run_with_wait(self, "Reading cloud backups...", cs.list_backups)
            if not ok or not files:
                QMessageBox.information(self, "Backup & Sync", "No cloud backups found." if ok else str(files))
                return
            names = [f.name for f in files]
            name, picked = QInputDialog.getItem(self, "Restore from cloud backup",
                                                "Replace all phrases on this PC with:", names, 0, False)
            if picked and QMessageBox.question(self, "Restore", f"Replace all phrases with {name}?") == QMessageBox.Yes:
                ok, path = _run_with_wait(self, "Downloading...", lambda: cs.download(name))
                if ok:
                    cs.apply_pull(path)
                    QMessageBox.information(self, "Backup & Sync", "Phrases restored.")
                else:
                    QMessageBox.warning(self, "Backup & Sync", str(path))
        else:
            ok, res = _run_with_wait(self, "Synchronizing...", cs.sync)
            if not ok:
                QMessageBox.warning(self, "Backup & Sync", f"Synchronization failed: {res}")
            else:
                from phraseforge.ui.cloud_ui import handle_sync_result
                handle_sync_result(self, cs, res)
        self._update_cloud_ui()

    # ---- Phrase menu
    def _page_phrase_menu(self) -> QWidget:
        w, lay = self._page()
        g = QGroupBox("Popup Contents")
        gl = QGridLayout(g)
        gl.setContentsMargins(12, 10, 12, 10)
        gl.setVerticalSpacing(6)
        contents = self.bind("menu.contents", DataCombo(MENU_CONTENTS))
        gl.addWidget(QLabel("Phrase menu contents:"), 0, 0)
        gl.addWidget(contents, 0, 1, 1, 3)
        sort = self.bind("menu.sort_enabled", QCheckBox("Sort by..."))
        by = self.bind("menu.sort_by", DataCombo([("Description", "description"), ("Autotext", "autotext"),
                                                  ("Usage count", "usage"), ("Last use", "last_used"),
                                                  ("Creation date", "created")]))
        method = self.bind("menu.sort_method", DataCombo([("Alphabetically", "alpha"), ("Length", "length"),
                                                          ("Numerically", "numeric")]))
        order = self.bind("menu.sort_order", DataCombo([("Ascending", "asc"), ("Descending", "desc")]))
        gl.addWidget(sort, 1, 0)
        gl.addWidget(by, 1, 1)
        gl.addWidget(method, 1, 2)
        gl.addWidget(order, 1, 3)
        r = 2
        for key, text in (("menu.show_preview", "Show phrase preview"),
                          ("menu.language_buttons", "Show phrase language buttons"),
                          ("menu.hide_restricted", "Hide program-restricted phrases")):
            gl.addWidget(self.bind(key, QCheckBox(text)), r, 0, 1, 4)
            r += 1
        n = self.bind("smartcomplete.min_chars", QSpinBox())
        n.setRange(1, 20)
        n.setFixedWidth(40)
        gl.addWidget(_row("Suggest SmartComplete/AutoCorrect items after typing the first", n,
                          "matching characters"), r, 0, 1, 4)
        lay.addWidget(g)
        g = QGroupBox("Phrase Menu Position")
        gl2 = QGridLayout(g)
        gl2.setContentsMargins(12, 10, 12, 10)
        pos = self.bind("menu.position", DataCombo([("next to the caret", "caret"), ("below the caret", "below"),
                                                    ("above the caret", "above"),
                                                    ("next to the mouse pointer", "mouse"),
                                                    ("near task tray icon", "tray"),
                                                    ("at a fixed position", "fixed"),
                                                    ("in the screen center", "center")]))
        pos.setFixedWidth(172)
        fb = self.bind("menu.position_fallback", DataCombo([("Near the task tray", "tray"),
                                                            ("Centered in current window", "window"),
                                                            ("Centered in primary monitor", "primary"),
                                                            ("Centered in current monitor", "monitor"),
                                                            ("Next to the mouse cursor", "mouse"),
                                                            ("Fixed", "fixed"),
                                                            ("In the screen center", "center")]))
        fb.setFixedWidth(196)
        gl2.addWidget(_row("Show phrase menus", pos), 0, 0)
        gl2.addWidget(_row("If caret position is indeterminable show phrase menu", fb), 1, 0)
        lay.addWidget(g)
        lay.addStretch(1)
        return w

    APPEARANCE_ELEMENTS = [("Background color", "background", "#ffffff"), ("Description text", "description", "#000000"),
                           ("Autotext text", "autotext", "#000000"), ("Hotkey text", "hotkey", "#000000"),
                           ("QuickKey text", "quickkey", "#000000"), ("Selection color", "selection", "#cce4f7")]

    def _page_phrase_menu_appearance(self) -> QWidget:
        w, lay = self._page()
        g, gl = _group("Phrase Menu Appearance")
        gl.addWidget(QLabel("Click any element in the preview to edit its properties:"))
        self._appearance: dict = {}
        frame = QFrame()
        frame.setStyleSheet("QFrame#Preview { background: white; border: 1px solid #b9b9b9; }")
        frame.setObjectName("Preview")
        frame.setFixedWidth(327)
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(10, 4, 10, 10)
        fl.addWidget(QLabel("Preview:"))
        self.preview_rows: list[list[QPushButton]] = []
        for i in (1, 2):
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(8, 6, 8, 6)
            parts = []
            for key, text in (("description", f"Description{i}"), ("autotext", f"[abv{i}]"),
                              ("hotkey", f"(CTRL-ALT-{i})"), ("quickkey", f"NumPad{i}")):
                b = QPushButton(text)
                b.setFlat(True)
                b.setStyleSheet("QPushButton { border: none; background: transparent; min-width: 0; padding: 0 4px; }")
                b.clicked.connect(lambda _=False, k=key: self._pick_element(k))
                rl.addWidget(b)
                parts.append(b)
            row.setObjectName(f"PreviewRow{i}")
            row.mousePressEvent = lambda _e, k="selection" if i == 1 else "background": self._pick_element(k)
            fl.addWidget(row)
            self.preview_rows.append([row] + parts)
        gl.addWidget(frame)
        self.element_combo = DataCombo([(t, k) for t, k, _ in self.APPEARANCE_ELEMENTS])
        self.element_combo.setFixedWidth(268)
        self.color_button = QToolButton()
        self.color_button.setFixedSize(40, 24)
        self.color_button.clicked.connect(self._pick_color)
        self.element_combo.currentIndexChanged.connect(lambda _i: self._refresh_appearance())
        gl.addWidget(_row(self.element_combo, self.color_button))
        font = QPushButton("Change font")
        font.setFixedWidth(268)
        font.clicked.connect(self._pick_menu_font)
        gl.addWidget(font)
        lay.addWidget(g)
        lay.addWidget(self.bind("menu.dim_dark", QCheckBox("Dim colors in Dark mode")))
        reset = QPushButton("Reset phrase menu width")
        reset.setFixedWidth(190)
        reset.clicked.connect(lambda: setattr(self, "_menu_width", ""))
        self._menu_width = ""
        self.bind_custom("menu.width", lambda: self._menu_width, lambda v: setattr(self, "_menu_width", v))
        lay.addWidget(reset)
        lay.addStretch(1)
        self.bind_custom("menu.appearance", lambda: json.dumps(self._appearance), self._set_appearance)
        return w

    def _set_appearance(self, v: str) -> None:
        try:
            self._appearance = json.loads(v or "{}")
            if not isinstance(self._appearance, dict):
                self._appearance = {}
        except ValueError:
            self._appearance = {}
        self._refresh_appearance()

    def _color_of(self, key: str) -> str:
        default = next(c for _, k, c in self.APPEARANCE_ELEMENTS if k == key)
        return self._appearance.get(key, default)

    def _refresh_appearance(self) -> None:
        self.color_button.setStyleSheet(f"background: {self._color_of(self.element_combo.value())};"
                                        " border: 1px solid #8a8a8a;")
        font = self._appearance.get("font", "")
        for i, parts in enumerate(self.preview_rows):
            row = parts[0]
            bg = self._color_of("selection" if i == 0 else "background")
            row.setStyleSheet(f"QWidget#{row.objectName()} {{ background: {bg}; }}")
            for key, b in zip(("description", "autotext", "hotkey", "quickkey"), parts[1:]):
                b.setStyleSheet("QPushButton { border: none; background: transparent; min-width: 0;"
                                f" padding: 0 4px; color: {self._color_of(key)}; }}")
                if font:
                    f = QFont()
                    f.fromString(font)
                    b.setFont(f)

    def _pick_element(self, key: str) -> None:
        self.element_combo.set_value(key)
        self._refresh_appearance()

    def _pick_color(self) -> None:
        from PySide6.QtGui import QColor
        key = self.element_combo.value()
        c = QColorDialog.getColor(QColor(self._color_of(key)), self, "Color")
        if c.isValid():
            self._appearance[key] = c.name()
            self._refresh_appearance()

    def _pick_menu_font(self) -> None:
        cur = QFont()
        if self._appearance.get("font"):
            cur.fromString(self._appearance["font"])
        ok, f = QFontDialog.getFont(cur, self, "Phrase menu font")
        if isinstance(ok, QFont):        # PySide returns (font, ok) or (ok, font) depending on version
            ok, f = f, ok
        if ok:
            self._appearance["font"] = f.toString()
            self._refresh_appearance()

    def _page_phrase_menu_hotkeys(self) -> QWidget:
        w, lay = self._page()
        g, gl = _group("Hotkeys in phrase menu")
        gl.addWidget(QLabel("Phrase confirmation hotkey"))
        gl.addWidget(self.bind("menu.confirm_hotkey", KeyCombo()))
        gl.addWidget(QLabel('Phrase selection hotkey in the phrase menu ("QuickKey")'))
        mod = self.bind("menu.quickkey_modifier", DataCombo([("None", "none"), ("Shift", "shift"), ("Alt", "alt"),
                                                             ("Ctrl", "ctrl"), ("Win", "win")]))
        mod.setFixedWidth(84)
        keys = self.bind("menu.quickkey_keys", DataCombo([("None", "none"), ("Numbers [1-9]", "digits"),
                                                          ("Numpad [Num1-Num9]", "numpad"),
                                                          ("Letters [a-z]", "letters"),
                                                          ("Function keys [F1-F12]", "fkeys")]))
        keys.setFixedWidth(260)
        gl.addWidget(_row(mod, keys))
        gl.addWidget(QLabel("Search in the phrase menu"))
        gl.addWidget(self.bind("menu.search_hotkey", KeyCombo()))
        gl.addWidget(QLabel("Language selection"))
        lm = self.bind("menu.language_modifier", DataCombo([("Ctrl + Left/Right", "ctrl"), ("Alt + Left/Right", "alt"),
                                                           ("Shift + Left/Right", "shift"),
                                                           ("Win + Left/Right", "win"), ("None", "none")]))
        lm.setFixedWidth(200)
        gl.addWidget(lm)
        lay.addWidget(g)
        lay.addStretch(1)
        return w

    def _page_phrase_menu_quicksearch(self) -> QWidget:
        w, lay = self._page()
        g, gl = _group("Popup QuickSearch")
        for key, text, tip in (
                ("quicksearch.descriptions", "Search within descriptions",
                 "Checked: search descriptions and abbreviations. Unchecked: also search the phrase text."),
                ("quicksearch.match_case", "Match case", ""),
                ("quicksearch.subfolders", "Include sub-folders", "Unchecked: only phrases at the top level."),
                ("quicksearch.quick_jump", "Quick Jump",
                 "Checked: typing a letter jumps to the matching menu item. Unchecked: typing starts a search.")):
            cb = self.bind(key, QCheckBox(text))
            cb.setToolTip(tip)
            gl.addWidget(cb)
        lay.addWidget(g)
        lay.addStretch(1)
        return w

    # ---- AutoComplete
    def _page_autocomplete(self) -> QWidget:
        w, lay = self._page()
        lay.setSpacing(6)
        lay.addWidget(_wrap_label(
            f"{APP} can optionally analyze your typing patterns to detect repetitive text input. It builds a "
            "personal library of your frequently used phrases, allowing it to suggest or automatically insert "
            "text, helping you save time and reduce typing effort. Sensitive data can be excluded from analysis."))
        lay.addWidget(QLabel("All data is stored on your computer only and never transmitted anywhere else."))
        g, gl = _group("AutoComplete Options")
        gl.addWidget(self.bind("autocomplete.learn_corrections", QCheckBox("Learn individual spelling corrections")))
        self.learning = self.bind("learning.enabled", QCheckBox("Suggest entered sentences"))
        gl.addWidget(self.learning)
        gl.addWidget(self.bind("autocomplete.suggest_words", QCheckBox("Suggest entered words")))
        gl.addWidget(self.bind("learning.remind_abbreviation", QCheckBox(
            "Remind me of the autotext when I type a phrase that already exists")))
        lay.addWidget(g)
        g, gl = _group("AutoComplete Filter")
        for key, text in (("autocomplete.filter_letter", "Suggestions must begin with a letter"),
                          ("autocomplete.filter_upper", "Suggestions must begin with an UPPER CASE letter"),
                          ("autocomplete.filter_number", "Suggestions must begin with a number"),
                          ("autocomplete.filter_special", "Suggestions must begin with a special character")):
            gl.addWidget(self.bind(key, QCheckBox(text)))
        lay.addWidget(g)
        lay.addStretch(1)
        return w

    # ---- Expert options
    def _page_expert(self) -> QWidget:
        w, lay = self._page()
        g = QGroupBox("Autotext")
        gl = QGridLayout(g)
        gl.setContentsMargins(12, 10, 12, 10)
        gl.addWidget(QLabel("Default leading delimiters:"), 0, 0)
        gl.addWidget(QLabel("Default trailing delimiters:"), 0, 1)
        self.leading = QLineEdit()
        self.leading.setFixedWidth(176)
        self.delimiters = QLineEdit()
        self.delimiters.setFixedWidth(176)
        self.bind_custom("autotext.leading_delimiters", lambda: decode_delimiters(self.leading.text()),
                         lambda v: self.leading.setText(encode_delimiters(v)))
        self.bind_custom("autotext.delimiters", lambda: decode_delimiters(self.delimiters.text()),
                         lambda v: self.delimiters.setText(encode_delimiters(v)))
        tip = "Control characters are written as #code, e.g. #9 = Tab, #10 = new line, #13 = Enter."
        self.leading.setToolTip(tip)
        self.delimiters.setToolTip(tip)
        gl.addWidget(self.leading, 1, 0)
        gl.addWidget(self.delimiters, 1, 1)
        gl.addWidget(self.bind("autotext.route_enter_tab", QCheckBox(f"Route Enter and Tab-key through {APP}")),
                     2, 0, 1, 2)
        gl.setColumnStretch(2, 1)
        lay.addWidget(g)
        g, gl2 = _group("Application Restrictions")
        restrict = self.bind("app.restrict_enabled", QCheckBox("Execute only in specific programs"))
        progs = self.bind("app.restrict_programs", QLineEdit())
        progs.setPlaceholderText("winword.exe, outlook.exe")
        self.enable_with(restrict, progs)
        gl2.addWidget(_row(restrict, progs, stretch=False))
        lay.addWidget(g)
        g, gl3 = _group("Email Delivery Method")
        mail = self.bind("mail.method", RadioGroup([("Send emails using MAPI (Recommended)", "mapi"),
                                                    ("Use Outlook OLE Automation", "outlook"), ("Gmail", "gmail"),
                                                    ("Send emails using mailto: command", "mailto")]))
        gl3.addWidget(mail)
        utf8 = self.bind("mail.utf8", QCheckBox("UTF-8 encoding in {#mail} macro (recommended for Outlook 2007/2010)"))
        utf8.setContentsMargins(18, 0, 0, 0)
        gl3.addWidget(_row(QLabel("   "), utf8))
        self.enable_with(mail.buttons["mailto"], utf8)
        lay.addWidget(g)
        lay.addStretch(1)
        return w

    def _page_expert_text_insertion(self) -> QWidget:
        w, lay = self._page()
        g, gl = _group("Paste Method")
        method = self.bind("output.method", RadioGroup([
            ("Paste text using the Windows Clipboard", "clipboard"),
            ('Paste text via keystroke simulation ("key-by-key") with method:', "keys")]))
        gl.addWidget(method)
        keym = self.bind("output.key_method", DataCombo([("VK_Packet (recommended)", "vk_packet"),
                                                         ("Unicode characters", "unicode"),
                                                         ("Scan codes", "scancode")]))
        keym.setFixedWidth(230)
        paste_long = self.bind("output.paste_long", QCheckBox("Paste text via the Windows clipboard if length exceeds"))
        self.paste_threshold = self.bind("output.paste_threshold", QSpinBox())
        self.paste_threshold.setRange(0, 100000)
        self.paste_threshold.setFixedWidth(60)
        sub = QWidget()
        sl = QVBoxLayout(sub)
        sl.setContentsMargins(16, 0, 0, 0)
        sl.addWidget(_row(keym))
        sl.addWidget(_row(paste_long, self.paste_threshold, "characters"))
        gl.addWidget(sub)
        self.enable_with(method.buttons["keys"], sub)
        self.enable_with(paste_long, self.paste_threshold)
        fmt = self.bind("output.format", DataCombo([("Auto", "auto"), ("Plain text", "plain"),
                                                    ("Rich text", "rich"), ("HTML", "html")]))
        fmt.setFixedWidth(142)
        gl.addWidget(_row("Phrase output format:", fmt))
        rich = self.bind("output.rich_formats", DataCombo([("HTML only", "html"), ("RTF & HTML", "rtf_html"),
                                                           ("RTF only", "rtf")]))
        rich.setFixedWidth(142)
        gl.addWidget(_row("Formatted text as:", rich))
        gl.addSpacing(4)
        gl.addWidget(self.bind("output.restore_clipboard", QCheckBox("Restore clipboard contents after phrase insertion")))
        more = QLabel('<a href="more">(more)</a>')
        more.linkActivated.connect(lambda _l: QMessageBox.information(
            self, "Paste method", "Some programs accept text only by pasting or only by typing. "
            f"{APP} remembers the method that works for those programs."))
        per_app = self.bind("output.per_app_method",
                            QCheckBox("Specific paste method for several target applications"))
        gl.addWidget(_row(per_app, more))
        self.app_methods = AppMethodTable()
        self.bind_custom("output.app_methods", self.app_methods.to_json, self.app_methods.load_json)
        gl.addWidget(self.app_methods)
        self.enable_with(per_app, self.app_methods)
        gl.addWidget(self.bind("output.force_focus", QCheckBox("Force focus change")))
        gl.addWidget(self.bind("output.minimize_main",
                               QCheckBox(f"Auto-minimize {APP} program window before phrase insertion")))
        up = self.bind("output.uppercase_if", QCheckBox("Output in UPPERCASE if"))
        n = self.bind("output.uppercase_chars", QSpinBox())
        n.setRange(1, 20)
        n.setFixedWidth(50)
        gl.addWidget(_row(up, n, "chars of Autotext is entered in uppercase"))
        lay.addWidget(g)
        g, gl = _group("Autotext timing")
        pause = self.bind("autotext.pause_ms", _spin(100, 5000))
        pause.setSingleStep(50)
        pause.setToolTip('Used by the Autotext options "When pausing after autotext input" '
                         'and "When continue typing quickly after autotext".')
        gl.addWidget(_row("Pause/fast-typing time:", pause, "ms"))
        lay.addWidget(g)
        lay.addStretch(1)
        return w

    def _page_expert_delays(self) -> QWidget:
        w, lay = self._page()
        g = QGroupBox("Delay Settings")
        f = QFormLayout(g)
        f.setContentsMargins(12, 16, 12, 10)
        f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        f.setVerticalSpacing(12)
        for key, text, warn in (("delay.focus", "Program focus change delay:", 50),
                                ("delay.clipboard_restore", "Clipboard restore delay:", 100),
                                ("delay.keypress", "Key press simulation (by macros) delay:", 20),
                                ("delay.paste", "Clipboard paste delay:", 50)):
            f.addRow(text, self.bind(key, DelaySlider(warn_below=warn)))
        lay.addWidget(g)
        lay.addStretch(1)
        return w

    def _page_expert_phrase_formatting(self) -> QWidget:
        w, lay = self._page()
        g, gl = _group("Phrase Formatting")
        gl.addWidget(QLabel("Default phrase format:"))
        fmt = self.bind("format.default", DataCombo([("Unformatted", "plain"), ("Formatted (rich text)", "rich")]))
        fmt.setFixedWidth(275)
        gl.addWidget(fmt)
        gl.addWidget(QLabel("Displayed font for unformatted phrases:"))
        self.font_button = QPushButton()
        self.font_button.setFixedSize(275, 42)
        self._font = ""
        self.font_button.clicked.connect(self._pick_font)
        self.bind_custom("format.font", lambda: self._font, self._set_font)
        gl.addWidget(self.font_button)
        gl.addWidget(QLabel("HTML font formatting output:"))
        html = self.bind("format.html_output", DataCombo([("Auto", "auto"), ("Inline styles", "inline"),
                                                          ("CSS style block", "css")]))
        html.setFixedWidth(275)
        gl.addWidget(html)
        lay.addWidget(g)
        lay.addStretch(1)
        return w

    def _set_font(self, v: str) -> None:
        self._font = v or "Arial,10"
        fam, _, size = self._font.partition(",")
        self.font_button.setText(f"{fam}, {size or 10}pt")

    def _pick_font(self) -> None:
        fam, _, size = self._font.partition(",")
        ok, f = QFontDialog.getFont(QFont(fam, int(size or 10)), self, "Font")
        if isinstance(ok, QFont):
            ok, f = f, ok
        if ok:
            self._set_font(f"{f.family()},{f.pointSize()}")

    def _page_program_exclusions(self) -> QWidget:
        w, lay = self._page()
        g, gl = _group("Excluded programs")
        gl.addWidget(_wrap_label(f"{APP} never expands phrases, records the clipboard or learns text in these "
                                 "programs. One program file name per line, for example keepass.exe."))
        self.excluded = QPlainTextEdit()
        self.excluded.setPlaceholderText("keepass.exe")
        gl.addWidget(self.excluded, 1)
        lay.addWidget(g, 1)
        return w

