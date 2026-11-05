"""What the administrator's policy (policy.py) looks like in the UI."""
from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QMessageBox

from phraseforge import policy
from phraseforge.ui.i18n import tr

log = logging.getLogger(__name__)


def _notice(what: str) -> str:
    p = policy.current()
    text = tr("{what} is locked by your administrator.").format(what=tr(what))
    return f"{text} {p.message}" if p.message else text


def settings_allowed(parent=None) -> bool:
    """False (after telling the user) when the policy keeps Settings closed."""
    if not policy.current().settings_locked:
        return True
    QMessageBox.information(parent, tr("Settings"), _notice("Settings"))
    return False


def editing_allowed() -> bool:
    return not policy.current().editing_disabled


def show_policy_error(parent, e: Exception) -> None:
    QMessageBox.information(parent, "PhraseForge", _notice("Editing phrases") if isinstance(e, policy.PolicyError)
                            else str(e))


def install_excepthook() -> None:
    """A change the policy refuses (Store raises PolicyError deep inside a click handler)
    shows a short notice instead of an error report."""
    previous = sys.excepthook

    def hook(kind, value, tb):
        if isinstance(value, policy.PolicyError):
            log.info("refused by policy: %s", value)
            try:
                show_policy_error(None, value)
            except Exception:
                pass
            return
        previous(kind, value, tb)
    sys.excepthook = hook
