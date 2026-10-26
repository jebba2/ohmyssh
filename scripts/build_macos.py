"""Build a standalone macOS app bundle of ohmyssh with PyInstaller.

When to use: after a change you want to ship as a double-clickable app, or
to check that packaging still works. Run it from the project root on a Mac
(PyInstaller cannot cross-compile):

    uv run python scripts/build_macos.py            # one-directory build
    uv run python scripts/build_macos.py --onefile  # single-file program inside the bundle
    uv run python scripts/build_macos.py --clean    # discard PyInstaller cache

Output is dist/ohmyssh.app for the architecture of the Mac doing the build.
The full PyInstaller log is written to working/build/pyinstaller.log; only
a short summary is printed here. PyInstaller ad-hoc signs the bundle, which
is enough to run it locally; a bundle handed to another Mac is quarantined
by Gatekeeper until the user opens it with right-click, Open.
"""

from __future__ import annotations

import sys
from pathlib import Path

from standalone_build import APP_NAME, DIST_DIR, ICON_DIR, baseCommand, parseArguments, runBuild

# Reverse-DNS name macOS uses to tell this app apart from others, from the
# author's domain in pyproject.toml.
BUNDLE_IDENTIFIER = "com.rev-x.ohmyssh"


def pyinstallerCommand(oneFile: bool, clean: bool) -> list[str]:
    """Return the PyInstaller command line for the requested build."""
    return baseCommand(oneFile, clean) + [
        "--icon",
        str(ICON_DIR / "app.icns"),
        "--osx-bundle-identifier",
        BUNDLE_IDENTIFIER,
    ]


def outputPath(oneFile: bool) -> Path:
    """Return the .app bundle; a one-file build also leaves a bare program beside it."""
    del oneFile
    return DIST_DIR / f"{APP_NAME}.app"


def main() -> int:
    args = parseArguments(__doc__ or "")
    return runBuild(pyinstallerCommand(args.onefile, args.clean), outputPath(args.onefile), args.onefile)


if __name__ == "__main__":
    sys.exit(main())
