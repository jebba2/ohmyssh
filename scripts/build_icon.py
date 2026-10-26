"""Render the app logo SVG into a Windows .ico and a macOS .icns file.

Run this after changing ``src/ohmyssh/ui/icons/app.svg`` so the packaged
apps pick up the new look; both files are committed because PyInstaller
needs them at build time and the SVG alone will not do for either platform.

    uv run python scripts/build_icon.py
    uv run python scripts/build_icon.py --out working/preview.ico --icns working/preview.icns --png working/preview.png

``--png`` also writes a single 256 px PNG, handy for checking the look.
The .ico holds PNG-compressed images at 16, 24, 32, 48, 64, 128 and 256 px,
which Windows Vista and later read. The .icns holds PNG images at 16, 32,
64, 128, 256, 512 and 1024 px, the sizes Finder and the Dock pick from.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SVG = PROJECT_ROOT / "src" / "ohmyssh" / "ui" / "icons" / "app.svg"
DEFAULT_ICO = PROJECT_ROOT / "src" / "ohmyssh" / "ui" / "icons" / "app.ico"
DEFAULT_ICNS = PROJECT_ROOT / "src" / "ohmyssh" / "ui" / "icons" / "app.icns"
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
# Each .icns entry type names one pixel size; these types all accept PNG data.
# 64 px is stored as the 32 px Retina slot (ic12), the way iconutil does it.
ICNS_TYPES = {16: b"icp4", 32: b"icp5", 64: b"ic12", 128: b"ic07", 256: b"ic08", 512: b"ic09", 1024: b"ic10"}
PREVIEW_SIZE = 256


def renderPng(svgPath: Path, size: int) -> bytes:
    """Rasterize the SVG to a square PNG of ``size`` pixels with a transparent background."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(str(svgPath))
    if not renderer.isValid():
        raise ValueError(f"{svgPath} is not a valid SVG")
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    # Saving by file name lets Qt pick PNG from the extension; the in-memory
    # overload's format argument is typed one way in the stubs and checked
    # another way at runtime.
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / f"icon-{size}.png"
        if not image.save(str(target)):
            raise ValueError(f"Could not render {svgPath} at {size} px")
        return target.read_bytes()


def writeIco(images: dict[int, bytes], path: Path) -> None:
    """Write PNG images keyed by pixel size as one .ico; 256 is stored as 0 per the format."""
    sizes = sorted(images)
    headerLength = 6 + 16 * len(sizes)
    header = struct.pack("<HHH", 0, 1, len(sizes))
    entries = b""
    offset = headerLength
    for size in sizes:
        data = images[size]
        dimension = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + entries + b"".join(images[size] for size in sizes))


def writeIcns(images: dict[int, bytes], path: Path) -> None:
    """Write PNG images keyed by pixel size as one .icns: a header, then type-tagged entries."""
    entries = b""
    for size in sorted(images):
        data = images[size]
        entries += ICNS_TYPES[size] + struct.pack(">I", 8 + len(data)) + data
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"icns" + struct.pack(">I", 8 + len(entries)) + entries)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render app.svg into a Windows .ico and a macOS .icns (and optionally a PNG preview).")
    parser.add_argument("--svg", type=Path, default=DEFAULT_SVG, help=f"source SVG (default: {DEFAULT_SVG})")
    parser.add_argument("--out", type=Path, default=DEFAULT_ICO, help=f"output .ico (default: {DEFAULT_ICO})")
    parser.add_argument("--icns", type=Path, default=DEFAULT_ICNS, help=f"output .icns (default: {DEFAULT_ICNS})")
    parser.add_argument("--png", type=Path, default=None, help="also write a 256 px PNG preview here")
    arguments = parser.parse_args()

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    QGuiApplication([])
    try:
        images = {size: renderPng(arguments.svg, size) for size in sorted({*ICON_SIZES, *ICNS_TYPES})}
    except ValueError as error:
        print(f"Failed: {error}")
        return 1
    writeIco({size: images[size] for size in ICON_SIZES}, arguments.out)
    print(f"Wrote {arguments.out} with sizes {', '.join(str(size) for size in ICON_SIZES)}")
    writeIcns({size: images[size] for size in ICNS_TYPES}, arguments.icns)
    print(f"Wrote {arguments.icns} with sizes {', '.join(str(size) for size in ICNS_TYPES)}")
    if arguments.png is not None:
        arguments.png.parent.mkdir(parents=True, exist_ok=True)
        arguments.png.write_bytes(renderPng(arguments.svg, PREVIEW_SIZE))
        print(f"Wrote {arguments.png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
