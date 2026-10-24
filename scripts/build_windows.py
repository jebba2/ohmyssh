"""Build a standalone Windows executable of pyommyssh with PyInstaller.

When to use: after a change you want to ship as a double-clickable app, or
to check that packaging still works. Run it from the project root:

    uv run python scripts/build_windows.py            # one-directory build
    uv run python scripts/build_windows.py --onefile  # single .exe
    uv run python scripts/build_windows.py --clean    # discard PyInstaller cache

Output lands in dist/. The full PyInstaller log is written to
working/build/pyinstaller.log; only a short summary is printed here.
One-directory builds start faster and are less likely to be flagged by
antivirus software than one-file builds.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENTRY_POINT = PROJECT_ROOT / "src" / "pyommyssh" / "__main__.py"
ICON_DIR = PROJECT_ROOT / "src" / "pyommyssh" / "ui" / "icons"
WORK_DIR = PROJECT_ROOT / "working" / "build"
DIST_DIR = PROJECT_ROOT / "dist"
LOG_FILE = WORK_DIR / "pyinstaller.log"
APP_NAME = "pyommyssh"
TAIL_LINES = 25


def pyinstallerCommand(oneFile: bool, clean: bool) -> list[str]:
    """Return the PyInstaller command line for the requested build."""
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
        f"{ICON_DIR}{os.pathsep}pyommyssh/ui/icons",
        "--icon",
        str(ICON_DIR / "app.ico"),
    ]
    if oneFile:
        command.append("--onefile")
    if clean:
        command.append("--clean")
    return command


def directorySize(path: Path) -> int:
    """Return the total size in bytes of a file or directory tree."""
    if path.is_file():
        return path.stat().st_size
    return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--onefile", action="store_true", help="produce a single executable")
    parser.add_argument("--clean", action="store_true", help="clear the PyInstaller cache first")
    args = parser.parse_args()

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    command = pyinstallerCommand(args.onefile, args.clean)
    print(f"Building {APP_NAME} ({'one file' if args.onefile else 'one directory'})...")
    with LOG_FILE.open("w", encoding="utf-8") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, cwd=PROJECT_ROOT)

    if result.returncode != 0:
        print(f"PyInstaller failed with exit code {result.returncode}. Last {TAIL_LINES} log lines:")
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        print("\n".join(lines[-TAIL_LINES:]))
        print(f"Full log: {LOG_FILE}")
        return result.returncode

    output = DIST_DIR / f"{APP_NAME}.exe" if args.onefile else DIST_DIR / APP_NAME
    sizeMb = directorySize(output) / (1024 * 1024)
    print(f"Built {output} ({sizeMb:.0f} MB)")
    print(f"Log: {LOG_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
