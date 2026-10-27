"""Shared PyInstaller plumbing for the per-platform build scripts.

Not run directly: ``build_windows.py`` and ``build_macos.py`` import this
and add only what differs between platforms, the icon file and bundle
details. Everything else (paths, flags, logging, the printed summary) lives
here so the two builds cannot drift apart.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENTRY_POINT = PROJECT_ROOT / "src" / "ohmyssh" / "__main__.py"
ICON_DIR = PROJECT_ROOT / "src" / "ohmyssh" / "ui" / "icons"
WORK_DIR = PROJECT_ROOT / "working" / "build"
DIST_DIR = PROJECT_ROOT / "dist"
LOG_FILE = WORK_DIR / "pyinstaller.log"
APP_NAME = "ohmyssh"
TAIL_LINES = 25


def baseCommand(oneFile: bool, clean: bool) -> list[str]:
    """Return the platform-independent part of the PyInstaller command line."""
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(ENTRY_POINT),
        "--name",
        APP_NAME,
        "--windowed",
        "--noconfirm",
        "--paths",
        str(PROJECT_ROOT / "src"),
        "--workpath",
        str(WORK_DIR),
        "--specpath",
        str(WORK_DIR),
        "--distpath",
        str(DIST_DIR),
        "--add-data",
        f"{ICON_DIR}{os.pathsep}ohmyssh/ui/icons",
    ]
    if oneFile:
        command.append("--onefile")
    if clean:
        command.append("--clean")
    return command


def argumentParser(description: str) -> argparse.ArgumentParser:
    """Return a parser with the flags every build script shares, --onefile and --clean, for a script to extend."""
    parser = argparse.ArgumentParser(description=description, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--onefile", action="store_true", help="produce a single executable")
    parser.add_argument("--clean", action="store_true", help="clear the PyInstaller cache first")
    return parser


def directorySize(path: Path) -> int:
    """Return the total size in bytes of a file or directory tree."""
    if path.is_file():
        return path.stat().st_size
    return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())


def runBuild(command: list[str], output: Path, oneFile: bool) -> int:
    """Run PyInstaller with its output logged to a file; print a short summary or the log tail."""
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Building {APP_NAME} ({'one file' if oneFile else 'one directory'})...")
    with LOG_FILE.open("w", encoding="utf-8") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, cwd=PROJECT_ROOT)

    if result.returncode != 0:
        print(f"PyInstaller failed with exit code {result.returncode}. Last {TAIL_LINES} log lines:")
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        print("\n".join(lines[-TAIL_LINES:]))
        print(f"Full log: {LOG_FILE}")
        return result.returncode

    sizeMb = directorySize(output) / (1024 * 1024)
    print(f"Built {output} ({sizeMb:.0f} MB)")
    print(f"Log: {LOG_FILE}")
    return 0
