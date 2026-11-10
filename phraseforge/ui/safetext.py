"""Plain text for Qt tooltips.

Qt shows a tooltip as rich text when it looks like HTML, and loads the images it names: a
synced comment or phrase with <img src="\\\\host\\share\\x.png"> made Windows connect to that
share when the mouse passed over it, sending the user's network login (security R83).
"""
from __future__ import annotations

import html


def plain_tip(text) -> str:
    """Text that Qt always shows as plain text (line breaks kept)."""
    text = "" if text is None else str(text)
    if "<" not in text:                    # no tag, so Qt shows it as plain text already
        return text
    return "<p style='white-space:pre-wrap'>" + html.escape(text, quote=False) + "</p>"
