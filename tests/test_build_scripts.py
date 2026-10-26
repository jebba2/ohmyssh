"""Tests for the per-platform PyInstaller build scripts' command lines."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
ICON_DIR = SCRIPTS_DIR.parent / "src" / "ohmyssh" / "ui" / "icons"


def _loadScript(name: str) -> ModuleType:
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    return importlib.import_module(name)


@pytest.mark.parametrize("name", ["build_windows", "build_macos"])
def test_every_build_bundles_the_icons_as_a_windowed_app(name: str) -> None:
    script = _loadScript(name)
    command = script.pyinstallerCommand(oneFile=False, clean=False)
    assert command[:3] == [sys.executable, "-m", "PyInstaller"]
    assert "--windowed" in command and "--noconfirm" in command
    assert "--onefile" not in command and "--clean" not in command
    addData = command[command.index("--add-data") + 1]
    assert addData.startswith(str(ICON_DIR)) and addData.endswith("ohmyssh/ui/icons")

    oneFile = script.pyinstallerCommand(oneFile=True, clean=True)
    assert "--onefile" in oneFile and "--clean" in oneFile


def test_windows_build_uses_the_ico_and_names_the_exe() -> None:
    script = _loadScript("build_windows")
    command = script.pyinstallerCommand(oneFile=False, clean=False)
    assert command[command.index("--icon") + 1] == str(ICON_DIR / "app.ico")
    assert "--osx-bundle-identifier" not in command
    assert script.outputPath(oneFile=False) == script.DIST_DIR / "ohmyssh"
    assert script.outputPath(oneFile=True) == script.DIST_DIR / "ohmyssh.exe"


def test_macos_build_uses_the_icns_and_names_the_app_bundle() -> None:
    script = _loadScript("build_macos")
    command = script.pyinstallerCommand(oneFile=False, clean=False)
    assert command[command.index("--icon") + 1] == str(ICON_DIR / "app.icns")
    assert command[command.index("--osx-bundle-identifier") + 1] == "com.rev-x.ohmyssh"
    # Both layouts wrap the program in a .app, which is what gets handed out.
    assert script.outputPath(oneFile=False) == script.DIST_DIR / "ohmyssh.app"
    assert script.outputPath(oneFile=True) == script.DIST_DIR / "ohmyssh.app"
