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
