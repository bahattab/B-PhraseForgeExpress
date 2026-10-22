"""Key names <-> Windows virtual-key codes. Pure Python (no Win32 calls)."""
from __future__ import annotations

MODIFIER_ALIASES = {
    "ctrl": "ctrl", "control": "ctrl", "ctl": "ctrl", "strg": "ctrl",
    "alt": "alt", "option": "alt", "menu": "alt",
    "shift": "shift",
    "win": "win", "windows": "win", "meta": "win", "super": "win", "cmd": "win", "lwin": "win", "rwin": "win",
}

# vk -> modifier name
MODIFIER_VKS = {
    0x10: "shift", 0xA0: "shift", 0xA1: "shift",
    0x11: "ctrl", 0xA2: "ctrl", 0xA3: "ctrl",
    0x12: "alt", 0xA4: "alt", 0xA5: "alt",
    0x5B: "win", 0x5C: "win",
}

VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN = 0x10, 0x11, 0x12, 0x5B
VK_BACK, VK_TAB, VK_RETURN, VK_ESCAPE, VK_SPACE = 0x08, 0x09, 0x0D, 0x1B, 0x20

NAMED_KEYS: dict[str, int] = {
    "backspace": 0x08, "bksp": 0x08, "bs": 0x08,
    "tab": 0x09, "enter": 0x0D, "return": 0x0D,
    "pause": 0x13, "capslock": 0x14, "escape": 0x1B, "esc": 0x1B, "space": 0x20,
    "pgup": 0x21, "pageup": 0x21, "pgdn": 0x22, "pagedown": 0x22,
    "end": 0x23, "home": 0x24, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "printscreen": 0x2C, "prtsc": 0x2C, "ins": 0x2D, "insert": 0x2D, "del": 0x2E, "delete": 0x2E,
    "apps": 0x5D, "contextmenu": 0x5D,
    "numlock": 0x90, "scrolllock": 0x91,
    "num0": 0x60, "num1": 0x61, "num2": 0x62, "num3": 0x63, "num4": 0x64,
    "num5": 0x65, "num6": 0x66, "num7": 0x67, "num8": 0x68, "num9": 0x69,
    "multiply": 0x6A, "add": 0x6B, "subtract": 0x6D, "decimal": 0x6E, "divide": 0x6F,
    "volumemute": 0xAD, "volumedown": 0xAE, "volumeup": 0xAF,
    "medianext": 0xB0, "mediaprev": 0xB1, "mediastop": 0xB2, "mediaplay": 0xB3,
    # modifiers as plain keys (for send_keys "shift" alone)
    "shiftkey": 0x10, "ctrlkey": 0x11, "altkey": 0x12, "lwinkey": 0x5B, "rwinkey": 0x5C,
}
for _i in range(1, 25):
    NAMED_KEYS[f"f{_i}"] = 0x6F + _i

# US-layout punctuation fallback (used when VkKeyScan is unavailable)
PUNCT_VKS = {
    ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF, "`": 0xC0,
    "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE, "plus": 0xBB, "minus": 0xBD,
}

# Keys that need KEYEVENTF_EXTENDEDKEY
EXTENDED_VKS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2C, 0x2D, 0x2E,
                0x5B, 0x5C, 0x5D, 0x6F, 0x90, 0xA3, 0xA5,
                0xAD, 0xAE, 0xAF, 0xB0, 0xB1, 0xB2, 0xB3}

VK_NAMES = {v: k for k, v in reversed(list(NAMED_KEYS.items()))}


def key_name_to_vk(name: str, vk_from_char=None) -> int:
    """Resolve 'a', '5', 'f5', 'enter', ';' ... to a VK code. Raises ValueError."""
    n = name.strip().lower()
    if not n:
        raise ValueError("empty key name")
    if n in NAMED_KEYS:
        return NAMED_KEYS[n]
    if len(n) == 1:
        if "a" <= n <= "z" or "0" <= n <= "9":
            return ord(n.upper())
        if vk_from_char is not None:
            vk = vk_from_char(n)
            if vk:
                return vk
        if n in PUNCT_VKS:
            return PUNCT_VKS[n]
    if n in PUNCT_VKS:
        return PUNCT_VKS[n]
    if n.startswith("vk") and n[2:]:
        return int(n[2:], 16)
    raise ValueError(f"unknown key: {name!r}")


def vk_to_name(vk: int) -> str:
    if 0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39:
        return chr(vk).lower()
    if vk in VK_NAMES:
        return VK_NAMES[vk]
    for ch, v in PUNCT_VKS.items():
        if v == vk and len(ch) == 1:
            return ch
    return f"vk{vk:02x}"
