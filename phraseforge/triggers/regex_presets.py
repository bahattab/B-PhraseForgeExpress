"""Ready-made patterns for RegEx Autotext and RegEx Clipboard triggers (PRD FR-TRG-04).

Autotext patterns are matched against the end of what was typed, so each one is written to
end where the item ends; a trigger usually puts a delimiter after it (see TRAILING) so that
"user@example.co" does not fire before ".com" is finished. FIXTURES holds text that must and
must not match, and the tests run every one.
"""
from __future__ import annotations

import re

_OCT = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_H16 = r"[0-9A-Fa-f]{1,4}"

PRESETS: dict[str, str] = {
    "Email address": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}",
    "Web address (URL)": r"(?:https?://|www\.)[^\s<>\"']+[^\s<>\"'.,;:!?)\]]",
    "ISBN-10": r"(?:\d[- ]?){9}[\dXx]",
    "ISBN-13": r"97[89][- ]?(?:\d[- ]?){9}\d",
    "IPv4 address": rf"{_OCT}(?:\.{_OCT}){{3}}",
    "IPv6 address": (rf"(?:{_H16}:){{7}}{_H16}|(?:{_H16}:){{1,7}}:|(?:{_H16}:){{1,6}}:{_H16}"
                     rf"|::(?:{_H16}:){{0,5}}{_H16}|::"),
    "MAC address": r"[0-9A-Fa-f]{2}(?:([:-])[0-9A-Fa-f]{2})(?:\1[0-9A-Fa-f]{2}){4}",
    "Time (HH:MM[:SS])": r"(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?",
}

# (must match in full, must not match in full)
FIXTURES: dict[str, tuple[list[str], list[str]]] = {
    "Email address": (["a@b.co", "first.last+tag@mail.example.org"], ["a@b", "@b.com", "a b@c.com", "a@b.c"]),
    "Web address (URL)": (["https://example.com/a?b=1", "www.example.org", "http://x.io/p"],
                          ["example.com", "ftp://x.io", "https://"]),
    "ISBN-10": (["0306406152", "0-306-40615-2", "080442957X"], ["030640615", "03064061522", "abcdefghij"]),
    "ISBN-13": (["9780306406157", "978-0-306-40615-7"], ["1234567890123", "978030640615"]),
    "IPv4 address": (["192.168.0.1", "8.8.8.8", "255.255.255.255"], ["256.1.1.1", "1.2.3", "01.2.3.4.5"]),
    "IPv6 address": (["2001:db8:0:0:0:0:2:1", "fe80::1", "::1", "::"], ["2001:db8:::1", "12345::", "g::1"]),
    "MAC address": (["00:1A:2B:3C:4D:5E", "00-1a-2b-3c-4d-5e"], ["00:1A:2B:3C:4D", "00:1A-2B:3C:4D:5E", "0G:1A:2B:3C:4D:5E"]),
    "Time (HH:MM[:SS])": (["09:30", "23:59:59", "00:00"], ["24:00", "9:30", "12:60", "12:30:60"]),
}


def full_match(name: str, text: str) -> bool:
    return re.fullmatch(PRESETS[name], text) is not None

