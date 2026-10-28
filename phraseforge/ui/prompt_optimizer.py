"""Prompt Optimizer window: chat with the AI engine to turn an idea into a precise prompt.

See phraseforge/prompt_optimizer.py for the conversation logic.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QTextBrowser, QToolButton,
    QVBoxLayout, QWidget,
)

from phraseforge import prompt_optimizer as po
from phraseforge.ui.i18n import tr
from phraseforge.ui.icons import app_icon


class TemplateForm(QDialog):
    """Fill in the {{variables}} of a template."""

    def __init__(self, t: po.Template, parent=None):
        super().__init__(parent)
        self.t = t
        self.setWindowTitle(t.name)
        f = QFormLayout(self)
        if t.description:
            f.addRow(QLabel(t.description))
        self.fields: dict[str, QWidget] = {}
        for v in t.variables:
            w = QPlainTextEdit() if v in ("code", "error", "steps") else QLineEdit()
            if isinstance(w, QPlainTextEdit):
                w.setFixedHeight(80)
            self.fields[v] = w
            f.addRow(v.replace("_", " ").capitalize() + ":", w)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def values(self) -> dict[str, str]:
        return {k: (w.toPlainText() if isinstance(w, QPlainTextEdit) else w.text()) for k, w in self.fields.items()}


class PromptOptimizerWindow(QWidget):
    save_as_phrase = Signal(str, str)        # description, prompt
    to_prompt_tower = Signal(str)            # optimized prompt -> Prompt Tower "text before the files"

    def __init__(self, store, parent=None, chat_fn=None):
        super().__init__(parent, Qt.Window)
        self.store = store
        self._chat_fn = chat_fn
        self.quiet = False
        self.setWindowTitle("Prompt Optimizer - PhraseForge")
        self.setWindowIcon(app_icon())
        self.resize(820, 680)
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        self.tpl_btn = QToolButton()
        self.tpl_btn.setText(tr("Start from a template"))
        self.tpl_btn.setPopupMode(QToolButton.InstantPopup)
        self.tpl_menu = QMenu(self.tpl_btn)
        self.tpl_menu.aboutToShow.connect(self._fill_templates)
        self.tpl_btn.setMenu(self.tpl_menu)
        top.addWidget(self.tpl_btn)
        top.addStretch(1)
        self.use_project = QCheckBox(tr("Use project context:"))
        top.addWidget(self.use_project)
        self.project = QComboBox()
        self.project.setEditable(True)
        self.project.setMinimumWidth(260)
        self.project.addItems(self._recent_folders())
        top.addWidget(self.project)
        b = QPushButton(tr("Browse..."))
        b.clicked.connect(self._browse)
        top.addWidget(b)
        lay.addLayout(top)
        self.context_label = QLabel()
        self.context_label.setStyleSheet("color:#666666")
        lay.addWidget(self.context_label)
        self.use_project.toggled.connect(lambda _on: self._update_context())
        self.project.currentTextChanged.connect(lambda _t: self._update_context())

        self.transcript = QTextBrowser()
        self.transcript.setOpenExternalLinks(True)
        lay.addWidget(self.transcript, 1)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText(tr("Describe what you want, e.g. \"help me build a page for an AI teacher\". "
                                         "Enter sends, Shift+Enter adds a line."))
        self.input.setFixedHeight(90)
        self.input.installEventFilter(self)
        lay.addWidget(self.input)
        row = QHBoxLayout()
        self.send_btn = QPushButton(tr("Send"))
        self.send_btn.setDefault(True)
        self.send_btn.clicked.connect(lambda: self.send())
        row.addWidget(self.send_btn)
        b = QPushButton(tr("Write the prompt now"))
        b.setToolTip(tr("Skip further questions and get the optimized prompt"))
        b.clicked.connect(lambda: self.send(tr("Continue with what you know and write the optimized prompt now.")))
        row.addWidget(b)
        b = QPushButton(tr("New conversation"))
        b.clicked.connect(self.new_conversation)
        row.addWidget(b)
        row.addStretch(1)
        self.copy_btn = QPushButton(tr("Copy optimized prompt"))
        self.copy_btn.clicked.connect(self.copy_optimized)
        row.addWidget(self.copy_btn)
        more = QToolButton()
        more.setText(tr("More"))
        more.setPopupMode(QToolButton.InstantPopup)
        mm = QMenu(more)
        mm.addAction(tr("Save as phrase"), self._save_phrase)
        mm.addAction(tr("Use in Prompt Tower"), lambda: self.optimized() and self.to_prompt_tower.emit(self.optimized()))
        mm.addAction(tr("Save my message as a template..."), self._save_template)
        more.setMenu(mm)
        row.addWidget(more)
        lay.addLayout(row)
        self.status = QLabel()
        lay.addWidget(self.status)
        self.new_conversation()

    # ---------------------------------------------------------------- helpers
    def _recent_folders(self) -> list[str]:
        try:
            v = json.loads(self.store.setting("prompttower.recent", "") or "[]")
        except ValueError:
            v = []
        return [x for x in v if isinstance(x, str)]

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, tr("Choose the project folder"), self.project.currentText())
        if d:
            self.project.setEditText(d)
            self.use_project.setChecked(True)

    def _update_context(self) -> str:
        text = ""
        if self.use_project.isChecked() and Path(self.project.currentText()).is_dir():
            text = po.analyze_project(self.project.currentText()).describe()
        self.context_label.setText(text.replace("\n", " · ") if text else "")
        self.conv.context = text
        return text

    def eventFilter(self, obj, e):  # noqa: N802
        if obj is self.input and e.type() == QEvent.KeyPress and e.key() in (Qt.Key_Return, Qt.Key_Enter) \
                and not e.modifiers() & Qt.ShiftModifier:
            self.send()
            return True
        return super().eventFilter(obj, e)

    def _render(self) -> None:
        parts = []
        for m in self.conv.history:
            who = tr("You") if m["role"] == "user" else tr("Optimizer")
            colour = "#e8f1fb" if m["role"] == "user" else "#f4f4f4"
            body = html.escape(m["content"]).replace("\n", "<br>")
            parts.append(f'<div style="background:{colour};padding:6px;margin:4px 0">'
                         f"<b>{who}</b><br>{body}</div>")
        if not parts:
            parts.append(f'<p style="color:#666666">{html.escape(tr("Describe your task. The optimizer asks a few questions if needed, then writes an optimized prompt you can copy."))}</p>')
        self.transcript.setHtml("".join(parts))
        self.transcript.verticalScrollBar().setValue(self.transcript.verticalScrollBar().maximum())
        self.copy_btn.setEnabled(bool(self.conv.optimized()))

    # ---------------------------------------------------------------- actions
    def new_conversation(self) -> None:
        self.conv = po.Conversation(dict(self.store.settings()), chat_fn=self._chat_fn)
        self._update_context()
        self.status.setText("")
        self._render()

    def send(self, text: str | None = None) -> str | None:
        msg = (self.input.toPlainText() if text is None else text).strip()
        if not msg:
            return None
        from phraseforge.ui.ai_ui import run_busy
        self.send_btn.setEnabled(False)
        self.status.setText(tr("Thinking…"))
        try:
            reply = run_busy(lambda: self.conv.send(msg))
        except Exception as e:      # noqa: BLE001 - shown to the user
            self.status.setText(tr("The AI engine could not answer:") + f" {e}")
            if not self.quiet:
                QMessageBox.warning(self, "Prompt Optimizer", f"{e}\n\n" + tr("Check the engine in Settings > AI."))
            return None
        finally:
            self.send_btn.setEnabled(True)
        if text is None:
            self.input.clear()
        self.status.setText(tr("The optimized prompt is ready.") if self.conv.optimized() else "")
        self._render()
        return reply

    def optimized(self) -> str:
        return self.conv.optimized()

    def copy_optimized(self) -> str:
        out = self.optimized()
        if out:
            QApplication.clipboard().setText(out)
            self.status.setText(tr("Copied."))
        return out

    def _save_phrase(self) -> None:
        out = self.optimized()
        if out:
            first = next((l for l in out.splitlines() if l.strip()), "Prompt")
            self.save_as_phrase.emit(first.strip("#* ")[:70], out)
            self.status.setText(tr("Saved as a phrase."))

    # ---------------------------------------------------------------- templates
    def templates(self) -> list[po.Template]:
        return po.BUILTIN_TEMPLATES + po.parse_templates(self.store.setting("promptopt.templates", ""))

    def _fill_templates(self) -> None:
        self.tpl_menu.clear()
        for t in self.templates():
            a = self.tpl_menu.addAction(t.name, lambda t=t: self.use_template(t))
            a.setToolTip(t.description)

    def use_template(self, t: po.Template, values: dict | None = None) -> str:
        if values is None:
            if not t.variables:
                values = {}
            else:
                d = TemplateForm(t, self)
                if d.exec() != QDialog.Accepted:
                    return ""
                values = d.values()
        text = t.fill(values)
        self.input.setPlainText(text)
        self.input.setFocus()
        return text

    def _save_template(self, name: str | None = None) -> bool:
        text = self.input.toPlainText().strip()
        if not text:
            self.status.setText(tr("Write the message first; use {{name}} for fields to fill in."))
            return False
        if name is None:
            name, ok = QInputDialog.getText(self, "Prompt Optimizer", tr("Template name:"))
            if not ok:
                return False
        name = name.strip()
        if not name:
            return False
        try:
            items = json.loads(self.store.setting("promptopt.templates", "") or "[]")
        except ValueError:
            items = []
        items = [i for i in items if isinstance(i, dict) and i.get("name") != name]
        items.append({"name": name, "description": "", "text": text})
        self.store.set_setting("promptopt.templates", json.dumps(items, ensure_ascii=False))
        self.status.setText(tr("Template saved."))
        return True
