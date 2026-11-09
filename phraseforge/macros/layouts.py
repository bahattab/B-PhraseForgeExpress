"""Keyboard layouts for {#convertlayout} (PRD FR-MAC-05): text typed with the wrong layout
switched on ("hgsghl" instead of "السلام") is re-mapped key by key.

Each layout lists, for the 47 character keys in the order of a US keyboard (` 1..0 - =,
q..\\, a..', z../), what the key types without and with Shift. Tables cover the main block
only; anything else is left as it is (compat: approximate).
"""
from __future__ import annotations

_US = ("`1234567890-=qwertyuiop[]\\asdfghjkl;'zxcvbnm,./",
       '~!@#$%^&*()_+QWERTYUIOP{}|ASDFGHJKL:"ZXCVBNM<>?')


def _keys(s: str) -> list[str]:
    return list(s)


LAYOUTS: dict[str, tuple[list[str], list[str]]] = {
    "en": (_keys(_US[0]), _keys(_US[1])),
    # Arabic (101): the B key types the lam-alef pair; Shift gives diacritics and punctuation
    "ar": (["ذ", *"1234567890-=", *"ضصثقفغعهخحجد\\", *"شسيبلاتنمكط", "ئ", "ء", "ؤ", "ر", "لا", "ى", "ة",
            "و", "ز", "ظ"],
           ["ّ", *"!@#$%^&*)(_+", "َ", "ً", "ُ", "ٌ", "لإ", "إ", "‘", "÷", "×", "؛", "<", ">", "|",
            "ِ", "ٍ", "]", "[", "لأ", "أ", "ـ", "،", "/", ":", '"', "~", "ْ", "}", "{", "لآ", "آ", "’", ",", ".", "؟"]),
    "ru": (_keys("ё1234567890-=йцукенгшщзхъ\\фывапролджэячсмитьбю."),
           _keys('Ё!"№;%:?*()_+ЙЦУКЕНГШЩЗХЪ/ФЫВАПРОЛДЖЭЯЧСМИТЬБЮ,')),
    "de": (_keys("^1234567890ß´qwertzuiopü+#asdfghjklöäyxcvbnm,.-"),
           _keys("°!\"§$%&/()=?`QWERTZUIOPÜ*'ASDFGHJKLÖÄYXCVBNM;:_")),
    "fr": (_keys("²&é\"'(-è_çà)=azertyuiop^$*qsdfghjklmùwxcvbn,;:!"),
           _keys("³1234567890°+AZERTYUIOP¨£µQSDFGHJKLM%WXCVBN?./§")),
}
ALIASES = {"english": "en", "us": "en", "arabic": "ar", "russian": "ru", "german": "de", "french": "fr"}


def layout(name: str) -> tuple[list[str], list[str]]:
    key = ALIASES.get(name.strip().lower(), name.strip().lower()[:2])
    if key not in LAYOUTS:
        raise KeyError(name)
    return LAYOUTS[key]


def convert(text: str, src: str, dst: str) -> str:
    """Re-type text written with layout src as if layout dst had been on."""
    a, b = layout(src), layout(dst)
    table: dict[str, str] = {}
    for shift in (1, 0):                         # unshifted wins where both produce the same text
        for k, out in enumerate(a[shift]):
            # "لا" from the B key reads the same as ل then ا typed apart: treat it as two keys
            if len(out) == 1:
                table[out] = b[shift][k]
    longest = max(len(k) for k in table)
    out, i = [], 0
    while i < len(text):
        for n in range(longest, 0, -1):
            piece = text[i:i + n]
            if len(piece) == n and piece in table:
                out.append(table[piece])
                i += n
                break
        else:
            out.append(text[i])
            i += 1
    return "".join(out)
