"""Event sounds (Settings > Sounds): sound.<event>.enabled / sound.<event>.file.

play(setting, "phrase_insertion") plays the chosen .wav, or a Windows system
sound when no file is set. Asynchronous and never raises.
"""
from __future__ import annotations

import logging
import os
from typing import Callable

log = logging.getLogger(__name__)

EVENTS = ("phrase_insertion", "popup_display", "clipboard_cache",
          "unwanted_detected", "unwanted_skipped", "spelling_added")

# Windows sound aliases used when the user picked no file
DEFAULT_ALIAS = {
    "phrase_insertion": "SystemAsterisk",
    "popup_display": "SystemQuestion",
    "clipboard_cache": "SystemAsterisk",
    "unwanted_detected": "SystemExclamation",
    "unwanted_skipped": "SystemHand",
    "spelling_added": "SystemAsterisk",
}


def _winsound_player(path: str, alias: str) -> None:
    import winsound
    if path:
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    else:
        winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC | winsound.SND_NODEFAULT)


# replaced in tests
player: Callable[[str, str], None] = _winsound_player


def play(setting: Callable[[str, str], str], event: str) -> bool:
    """Play the sound for an event if enabled. Returns True when something was played."""
    if event not in EVENTS:
        return False
    try:
        if setting(f"sound.{event}.enabled", "0") != "1":
            return False
        path = setting(f"sound.{event}.file", "") or ""
        if path and not os.path.isfile(path):
            path = ""            # file moved/deleted: fall back to the system sound
        player(path, DEFAULT_ALIAS[event])
        return True
    except Exception:
        log.debug("sound %s failed", event, exc_info=True)
        return False


def play_event(event: str, store) -> bool:
    """Same as play(), taking the Store (used by the popup menu)."""
    return play(store.setting, event)
