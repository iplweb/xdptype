"""Character and key-name to X11 keysym conversion."""

from __future__ import annotations

import ctypes
import ctypes.util
from functools import cache

# Characters that are typed as "function" keysyms rather than their codepoint.
_CONTROL = {
    "\n": 0xFF0D,  # Return
    "\r": 0xFF0D,  # Return
    "\t": 0xFF09,  # Tab
    "\b": 0xFF08,  # BackSpace
    "\x1b": 0xFF1B,  # Escape
}

KEY_NAMES = {
    "return": 0xFF0D,
    "enter": 0xFF0D,
    "tab": 0xFF09,
    "backspace": 0xFF08,
    "escape": 0xFF1B,
    "esc": 0xFF1B,
    "delete": 0xFFFF,
    "home": 0xFF50,
    "left": 0xFF51,
    "up": 0xFF52,
    "right": 0xFF53,
    "down": 0xFF54,
    "page_up": 0xFF55,
    "prior": 0xFF55,
    "page_down": 0xFF56,
    "next": 0xFF56,
    "end": 0xFF57,
    "insert": 0xFF63,
    "space": 0x0020,
    "shift": 0xFFE1,
    "shift_l": 0xFFE1,
    "shift_r": 0xFFE2,
    "control": 0xFFE3,
    "ctrl": 0xFFE3,
    "control_l": 0xFFE3,
    "control_r": 0xFFE4,
    "alt": 0xFFE9,
    "alt_l": 0xFFE9,
    "alt_r": 0xFFEA,
    "super": 0xFFEB,
    "super_l": 0xFFEB,
    "super_r": 0xFFEC,
    **{f"f{n}": 0xFFBE + n - 1 for n in range(1, 25)},
}


@cache
def _xkb_utf32_to_keysym():
    """``xkb_utf32_to_keysym`` from libxkbcommon, or None if unavailable."""
    name = ctypes.util.find_library("xkbcommon")
    if not name:
        return None
    try:
        func = ctypes.CDLL(name).xkb_utf32_to_keysym
    except (OSError, AttributeError):
        return None
    func.argtypes = [ctypes.c_uint32]
    func.restype = ctypes.c_uint32
    return func


def unicode_keysym(code: int) -> int:
    """Keysym from the Unicode range (0x01000000 + codepoint)."""
    return 0x01000000 + code


def char_to_keysym(char: str) -> int:
    """Map one character to its keysym.

    Prefers the legacy X11 keysym (``ą`` -> ``aogonek``, ``€`` ->
    ``EuroSign``), because compositors look keysyms up in the active layout
    and layouts use the legacy names: mutter silently drops a Unicode-range
    keysym (0x01000000 + codepoint) for a character that the layout has
    under its legacy name. libxkbcommon does the mapping when available;
    otherwise Latin-1 maps to the codepoint and the rest to the Unicode
    range.
    """
    if len(char) != 1:
        raise ValueError(f"expected a single character, got {char!r}")
    if char in _CONTROL:
        return _CONTROL[char]
    code = ord(char)
    if code < 0x20 or code == 0x7F:
        raise ValueError(f"cannot type control character {char!r}")
    if code <= 0x7E or 0xA0 <= code <= 0xFF:
        return code
    xkb = _xkb_utf32_to_keysym()
    if xkb is not None:
        keysym = xkb(code)
        if keysym:
            return keysym
    return unicode_keysym(code)


SHIFT = 0xFFE1


def char_to_strokes(char: str) -> tuple[int, bool]:
    """Return ``(keysym, with_shift)`` for typing ``char``.

    mutter (GNOME 50) presses the right modifiers for level 2 (Shift) and
    level 3 (AltGr), but not for level 4 (Shift+AltGr): ``Ą`` on the Polish
    layout comes out as ``a``. So a non-ASCII uppercase letter is sent as
    Shift held + its lowercase keysym, and the compositor adds AltGr itself.
    """
    lower = char.lower()
    if not char.isascii() and char.isupper() and len(lower) == 1 and lower != char:
        return char_to_keysym(lower), True
    return char_to_keysym(char), False


def key_to_keysym(name: str) -> int:
    """Map a key name (``Return``, ``Tab``, ``F5``…) or ``0x…`` literal."""
    lowered = name.lower()
    if lowered in KEY_NAMES:
        return KEY_NAMES[lowered]
    if lowered.startswith("0x"):
        return int(lowered, 16)
    if len(name) == 1:
        return char_to_keysym(name)
    raise ValueError(f"unknown key name {name!r}")
