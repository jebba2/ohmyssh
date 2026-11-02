"""Build a standalone Linux program of ohmyssh with PyInstaller.

When to use: after a change you want to ship as a double-clickable app, or
to check that packaging still works. Run it from the project root on Linux
(PyInstaller cannot cross-compile):

    uv run python scripts/build_linux.py            # one-directory build
    uv run python scripts/build_linux.py --onefile  # single program file
    uv run python scripts/build_linux.py --clean    # discard PyInstaller cache

Output lands in dist/ohmyssh: a folder holding the ohmyssh program and its
support files, or with --onefile the bare program. The build runs on the
machine's architecture and needs a glibc at least as new as the builder's
on any machine it is copied to. PyInstaller cannot embed an icon on Linux;
the window icon comes from the bundled SVG at run time. The full
PyInstaller log is written to working/build/pyinstaller.log; only a short
summary is printed here.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from standalone_build import APP_NAME, DIST_DIR, argumentParser as sharedArgumentParser, baseCommand, runBuild


def pyinstallerCommand(oneFile: bool, clean: bool) -> list[str]:
    """Return the PyInstaller command line; Linux adds nothing to the shared flags."""
    return baseCommand(oneFile, clean)


def outputPath(oneFile: bool) -> Path:
    """Return what PyInstaller produces: the bare program, or a folder of the same name with the program inside."""
    del oneFile
    return DIST_DIR / APP_NAME


def argumentParser() -> argparse.ArgumentParser:
    """Return the parser for this script's flags; Linux has no extras beyond the shared ones."""
    return sharedArgumentParser(__doc__ or "")


def main() -> int:
    args = argumentParser().parse_args()
    return runBuild(pyinstallerCommand(args.onefile, args.clean), outputPath(args.onefile), args.onefile)


if __name__ == "__main__":
    sys.exit(main())
