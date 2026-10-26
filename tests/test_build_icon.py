"""Tests for the script that renders the app logo into a Windows .ico."""

from __future__ import annotations

import struct
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_icon.py"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *arguments], capture_output=True, text=True, check=False)


def test_script_writes_a_multi_size_ico_and_a_preview(tmp_path: Path) -> None:
    icoPath = tmp_path / "out" / "app.ico"
    pngPath = tmp_path / "out" / "preview.png"
    completed = _run("--out", str(icoPath), "--png", str(pngPath))
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Wrote" in completed.stdout

    data = icoPath.read_bytes()
    reserved, imageType, count = struct.unpack("<HHH", data[:6])
    assert (reserved, imageType, count) == (0, 1, 7)
    sizes: list[int] = []
    for index in range(count):
        entry = data[6 + 16 * index : 6 + 16 * (index + 1)]
        width, height, _, _, planes, bitCount, length, offset = struct.unpack("<BBBBHHII", entry)
        assert width == height and (planes, bitCount) == (1, 32)
        image = data[offset : offset + length]
        assert image.startswith(PNG_SIGNATURE)
        pngWidth, pngHeight = struct.unpack(">II", image[16:24])
        assert pngWidth == pngHeight == (256 if width == 0 else width)
        sizes.append(pngWidth)
    assert sizes == [16, 24, 32, 48, 64, 128, 256]

    preview = pngPath.read_bytes()
    assert preview.startswith(PNG_SIGNATURE)
    assert struct.unpack(">II", preview[16:24]) == (256, 256)


def test_script_rejects_a_bad_svg(tmp_path: Path) -> None:
    bad = tmp_path / "bad.svg"
    bad.write_text("this is not svg")
    completed = _run("--svg", str(bad), "--out", str(tmp_path / "bad.ico"))
    assert completed.returncode == 1
    assert "not a valid SVG" in completed.stdout
    assert not (tmp_path / "bad.ico").exists()


def test_committed_ico_matches_the_svg() -> None:
    """The .ico in the repo must be regenerated whenever app.svg changes."""
    icoPath = SCRIPT.parent.parent / "src" / "ohmyssh" / "ui" / "icons" / "app.ico"
    assert icoPath.is_file(), "run scripts/build_icon.py to create app.ico"
    header = icoPath.read_bytes()[:6]
    assert struct.unpack("<HHH", header) == (0, 1, 7)


def _icnsEntries(data: bytes) -> list[tuple[str, int]]:
    """Return (type, png pixel size) for every entry in an .icns file."""
    assert data[:4] == b"icns"
    assert struct.unpack(">I", data[4:8])[0] == len(data)
    entries: list[tuple[str, int]] = []
    offset = 8
    while offset < len(data):
        entryType = data[offset : offset + 4].decode("ascii")
        length = struct.unpack(">I", data[offset + 4 : offset + 8])[0]
        image = data[offset + 8 : offset + length]
        assert image.startswith(PNG_SIGNATURE)
        pngWidth, pngHeight = struct.unpack(">II", image[16:24])
        assert pngWidth == pngHeight
        entries.append((entryType, pngWidth))
        offset += length
    assert offset == len(data)
    return entries


def test_script_writes_a_png_backed_icns(tmp_path: Path) -> None:
    icnsPath = tmp_path / "out" / "app.icns"
    completed = _run("--out", str(tmp_path / "out" / "app.ico"), "--icns", str(icnsPath))
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert str(icnsPath) in completed.stdout

    assert _icnsEntries(icnsPath.read_bytes()) == [
        ("icp4", 16),
        ("icp5", 32),
        ("ic12", 64),
        ("ic07", 128),
        ("ic08", 256),
        ("ic09", 512),
        ("ic10", 1024),
    ]


def test_committed_icns_matches_the_svg() -> None:
    """The .icns in the repo must be regenerated whenever app.svg changes."""
    icnsPath = SCRIPT.parent.parent / "src" / "ohmyssh" / "ui" / "icons" / "app.icns"
    assert icnsPath.is_file(), "run scripts/build_icon.py to create app.icns"
    assert len(_icnsEntries(icnsPath.read_bytes())) == 7
