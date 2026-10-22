"""Synthetic keyboard and mouse input via SendInput.

Every injected event carries INJECT_MAGIC in dwExtraInfo so our own keyboard
hook can ignore it.
"""
from __future__ import annotations

import ctypes
import time

from phraseforge.platform import keys as K
from phraseforge.platform._win32 import INJECT_MAGIC, INPUT, user32

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x1, 0x2, 0x4
MOUSEEVENTF_MOVE, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x1, 0x2, 0x4
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, MOUSEEVENTF_ABSOLUTE = 0x8, 0x10, 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

CHUNK = 48             # characters per SendInput batch
CHUNK_DELAY_S = 0.004  # pause between batches; some apps drop very fast input


def _send(inputs: list[INPUT]) -> int:
    if not inputs:
        return 0
    arr = (INPUT * len(inputs))(*inputs)
    return user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _key(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.ki.wVk, inp.ki.wScan, inp.ki.dwFlags = vk, scan, flags
    inp.ki.dwExtraInfo = INJECT_MAGIC
    return inp


def _vk_events(vk: int, up: bool) -> INPUT:
    flags = KEYEVENTF_KEYUP if up else 0
    if vk in K.EXTENDED_VKS:
        flags |= KEYEVENTF_EXTENDEDKEY
    scan = user32.MapVirtualKeyW(vk, 0) & 0xFF
    return _key(vk, scan, flags)


def utf16_units(text: str) -> list[int]:
    """Split text into UTF-16 code units (surrogate pairs for non-BMP chars)."""
    data = text.encode("utf-16-le")
    return [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]


def _char_inputs(ch: str) -> list[INPUT]:
    if ch == "\n":
        return [_vk_events(K.VK_RETURN, False), _vk_events(K.VK_RETURN, True)]
    if ch == "\t":
        return [_vk_events(K.VK_TAB, False), _vk_events(K.VK_TAB, True)]
    out = []
    for unit in utf16_units(ch):
        out.append(_key(0, unit, KEYEVENTF_UNICODE))
        out.append(_key(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
    return out


def type_text(text: str) -> None:
    """Type text as Unicode keystrokes. \\r\\n and \\r become Enter, \\t becomes Tab."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for i in range(0, len(text), CHUNK):
        batch: list[INPUT] = []
        for ch in text[i:i + CHUNK]:
            batch.extend(_char_inputs(ch))
        _send(batch)
        if i + CHUNK < len(text):
            time.sleep(CHUNK_DELAY_S)


def _vk_from_char(ch: str) -> int:
    r = user32.VkKeyScanW(ch)
    return 0 if r == -1 else r & 0xFF


def parse_chord(spec: str) -> tuple[list[int], int]:
    """'ctrl+shift+left' -> ([VK_CONTROL, VK_SHIFT], VK_LEFT)."""
    s = spec.replace(" ", "")
    if s.endswith("++"):          # "ctrl++" means ctrl + plus
        s = s[:-2] + "+plus"
    parts = [p for p in s.split("+") if p]
    if not parts:
        raise ValueError(f"no key in {spec!r}")
    mod_vk = {"ctrl": K.VK_CONTROL, "alt": K.VK_MENU, "shift": K.VK_SHIFT, "win": K.VK_LWIN}
    mods: list[int] = []
    for p in parts[:-1]:
        mod = K.MODIFIER_ALIASES.get(p.lower())
        if not mod:
            raise ValueError(f"{p!r} is not a modifier in {spec!r}")
        mods.append(mod_vk[mod])
    last = parts[-1]
    mod = K.MODIFIER_ALIASES.get(last.lower())
    key_vk = mod_vk[mod] if mod else K.key_name_to_vk(last, _vk_from_char)
    return mods, key_vk


def send_keys(spec: str, repeat: int = 1) -> None:
    """Press a chord like 'ctrl+a', 'enter', 'f5'. Several chords may be
    separated by spaces: 'ctrl+a ctrl+c'."""
    chords = [c for c in spec.split() if c] or [spec]
    for _ in range(max(1, repeat)):
        for chord in chords:
            mods, vk = parse_chord(chord)
            seq = [_vk_events(m, False) for m in mods] + [_vk_events(vk, False), _vk_events(vk, True)]
            seq += [_vk_events(m, True) for m in reversed(mods)]
            _send(seq)


def backspace(n: int) -> None:
    for i in range(0, max(0, n), CHUNK):
        k = min(CHUNK, n - i)
        _send([e for _ in range(k) for e in (_vk_events(K.VK_BACK, False), _vk_events(K.VK_BACK, True))])
        time.sleep(CHUNK_DELAY_S)


def press_left(n: int) -> None:
    for i in range(0, max(0, n), CHUNK):
        k = min(CHUNK, n - i)
        _send([e for _ in range(k) for e in (_vk_events(0x25, False), _vk_events(0x25, True))])


def release_modifiers() -> None:
    """Release modifiers the user still physically holds (e.g. after a hotkey),
    so typed text is not interpreted as shortcuts. A dummy key press first
    prevents a lone Alt/Win release from opening a menu."""
    held = [vk for vk in (0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C)
            if user32.GetAsyncKeyState(vk) & 0x8000]
    if not held:
        return
    seq = [_key(0xE8, 0, 0), _key(0xE8, 0, KEYEVENTF_KEYUP)]  # 0xE8 is unassigned
    seq += [_vk_events(vk, True) for vk in held]
    _send(seq)


def _mouse(flags: int, dx: int = 0, dy: int = 0) -> INPUT:
    inp = INPUT(type=INPUT_MOUSE)
    inp.mi.dx, inp.mi.dy, inp.mi.dwFlags = dx, dy, flags
    inp.mi.dwExtraInfo = INJECT_MAGIC
    return inp


def mouse_move(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))


def mouse_click(x: int | None = None, y: int | None = None, button: str = "left", double: bool = False) -> None:
    if x is not None and y is not None:
        mouse_move(x, y)
    down, up = ((MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP) if button == "right"
                else (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP))
    seq = [_mouse(down), _mouse(up)]
    _send(seq * (2 if double else 1))
