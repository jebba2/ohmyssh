"""Terminal emulation state and keyboard encoding, independent of any GUI.

``TerminalSession`` wraps a pyte screen with scrollback. The GUI feeds it
bytes from the SSH channel and paints whatever it reports. ``encodeKey``
turns a named key press into the bytes a VT100-style terminal would send.
"""

from __future__ import annotations

import pyte
from pyte.screens import Char

SCROLLBACK_LINES = 2000

# Modifier bits for CSI sequences such as ESC [ 1 ; 5 A (Ctrl+Up).
_SHIFT_BIT = 1
_ALT_BIT = 2
_CTRL_BIT = 4

# Keys whose cursor-style sequences accept a modifier parameter.
_CSI_LETTER_KEYS: dict[str, str] = {
    "Up": "A",
    "Down": "B",
    "Right": "C",
    "Left": "D",
    "Home": "H",
    "End": "F",
}

_TILDE_KEYS: dict[str, int] = {
    "Insert": 2,
    "Delete": 3,
    "PageUp": 5,
    "PageDown": 6,
    "F5": 15,
    "F6": 17,
    "F7": 18,
    "F8": 19,
    "F9": 20,
    "F10": 21,
    "F11": 23,
    "F12": 24,
}

_SIMPLE_KEYS: dict[str, bytes] = {
    "Return": b"\r",
    "Enter": b"\r",
    "Backspace": b"\x7f",
    "Tab": b"\t",
    "Escape": b"\x1b",
    "F1": b"\x1bOP",
    "F2": b"\x1bOQ",
    "F3": b"\x1bOR",
    "F4": b"\x1bOS",
}

# Ctrl plus a punctuation key maps to the control characters 0x00 and 0x1b-0x1f.
_CTRL_PUNCTUATION: dict[str, bytes] = {
    "@": b"\x00",
    " ": b"\x00",
    "[": b"\x1b",
    "\\": b"\x1c",
    "]": b"\x1d",
    "^": b"\x1e",
    "_": b"\x1f",
}


class TerminalSession:
    """Screen state for one terminal, with scrollback and dirty-row tracking."""

    def __init__(self, cols: int = 80, rows: int = 24) -> None:
        self._screen = pyte.HistoryScreen(cols, rows, history=SCROLLBACK_LINES)
        self._stream = pyte.ByteStream(self._screen)

    def feed(self, data: bytes) -> None:
        """Process bytes received from the remote side."""
        self._stream.feed(data)

    def resize(self, cols: int, rows: int) -> None:
        """Change the terminal dimensions, preserving visible content."""
        self._screen.resize(lines=rows, columns=cols)

    def size(self) -> tuple[int, int]:
        """Return (cols, rows)."""
        return self._screen.columns, self._screen.lines

    def cursor(self) -> tuple[int, int]:
        """Return the cursor position as (x, y)."""
        return self._screen.cursor.x, self._screen.cursor.y

    def cursorHidden(self) -> bool:
        """Return True when the remote side has hidden the cursor."""
        return self._screen.cursor.hidden

    def lines(self) -> list[str]:
        """Return the visible rows as padded strings."""
        return self._screen.display

    def cellAt(self, x: int, y: int) -> Char:
        """Return the styled character at a screen position."""
        return self._screen.buffer[y][x]

    def scrollbackLines(self) -> list[str]:
        """Return rows that scrolled off the top, oldest first."""
        cols = self._screen.columns
        return [
            "".join(row[x].data if x in row else " " for x in range(cols))
            for row in self._screen.history.top
        ]

    def takeDirtyRows(self) -> set[int]:
        """Return rows changed since the last call and mark them clean."""
        dirty = set(self._screen.dirty)
        self._screen.dirty.clear()
        return dirty


def _modifierCode(ctrl: bool, alt: bool, shift: bool) -> int:
    return 1 + (_SHIFT_BIT if shift else 0) + (_ALT_BIT if alt else 0) + (_CTRL_BIT if ctrl else 0)


def _encodeControlCharacter(keyName: str) -> bytes | None:
    if keyName in _CTRL_PUNCTUATION:
        return _CTRL_PUNCTUATION[keyName]
    upper = keyName.upper()
    if len(upper) == 1 and "A" <= upper <= "Z":
        return bytes([ord(upper) - ord("A") + 1])
    return None


def encodeKey(
    keyName: str,
    text: str = "",
    ctrl: bool = False,
    alt: bool = False,
    shift: bool = False,
) -> bytes:
    """Return the bytes a terminal sends for a key press.

    ``keyName`` is a Qt-style key name such as ``"Return"``, ``"F5"`` or a
    single printable character. ``text`` is the character the key produces
    with the current modifiers. Lone modifier keys produce no bytes.
    """
    encoded: bytes | None = None

    if keyName in _CSI_LETTER_KEYS:
        letter = _CSI_LETTER_KEYS[keyName]
        if ctrl or alt or shift:
            encoded = f"\x1b[1;{_modifierCode(ctrl, alt, shift)}{letter}".encode()
            # Alt is already carried in the modifier parameter.
            alt = False
        else:
            encoded = f"\x1b[{letter}".encode()
    elif keyName in _TILDE_KEYS:
        encoded = f"\x1b[{_TILDE_KEYS[keyName]}~".encode()
    elif keyName in _SIMPLE_KEYS:
        encoded = _SIMPLE_KEYS[keyName]
    elif ctrl and len(keyName) == 1:
        encoded = _encodeControlCharacter(keyName)
    elif text and not ctrl:
        encoded = text.encode()

    if encoded is None:
        return b""
    return b"\x1b" + encoded if alt else encoded
