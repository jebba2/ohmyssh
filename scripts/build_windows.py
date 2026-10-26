"""Build a standalone Windows executable of ohmyssh with PyInstaller.

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

import sys
from pathlib import Path

from standalone_build import APP_NAME, DIST_DIR, ICON_DIR, baseCommand, parseArguments, runBuild


def pyinstallerCommand(oneFile: bool, clean: bool) -> list[str]:
    """Return the PyInstaller command line for the requested build."""
    return baseCommand(oneFile, clean) + ["--icon", str(ICON_DIR / "app.ico")]


def outputPath(oneFile: bool) -> Path:
    """Return what PyInstaller produces: a single .exe or a folder with the .exe inside."""
    return DIST_DIR / f"{APP_NAME}.exe" if oneFile else DIST_DIR / APP_NAME


def main() -> int:
    args = parseArguments(__doc__ or "")
    return runBuild(pyinstallerCommand(args.onefile, args.clean), outputPath(args.onefile), args.onefile)


if __name__ == "__main__":
    sys.exit(main())
