"""SVG icons shipped with the app, looked up by name.

The files live next to this module so PyInstaller can bundle the folder
with a single ``--add-data`` entry (see scripts/build_windows.py).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon

ICON_DIR = Path(__file__).resolve().parent
ICON_NAMES: frozenset[str] = frozenset({"terminal", "edit", "key", "folder", "app"})


def iconPath(name: str) -> Path:
    """Return the SVG file for a known icon name."""
    if name not in ICON_NAMES:
        raise KeyError(f"Unknown icon '{name}'")
    return ICON_DIR / f"{name}.svg"


def loadIcon(name: str) -> QIcon:
    """Load a bundled icon."""
    return QIcon(str(iconPath(name)))
