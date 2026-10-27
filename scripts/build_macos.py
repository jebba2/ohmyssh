"""Build a standalone macOS app bundle of ohmyssh with PyInstaller.

When to use: after a change you want to ship as a double-clickable app, or
to check that packaging still works. Run it from the project root on a Mac
(PyInstaller cannot cross-compile):

    uv run python scripts/build_macos.py            # one-directory build
    uv run python scripts/build_macos.py --onefile  # single-file program inside the bundle
    uv run python scripts/build_macos.py --clean    # discard PyInstaller cache
    uv run python scripts/build_macos.py --dmg      # also wrap the app in dist/ohmyssh.dmg

Output is dist/ohmyssh.app for the architecture of the Mac doing the build.
With --dmg the app is staged in working/build/dmg beside a link to
/Applications and compressed with hdiutil into dist/ohmyssh.dmg, so the
mounted image shows the app and the folder to drag it into side by side.
The full PyInstaller log is written to working/build/pyinstaller.log; only
a short summary is printed here. PyInstaller ad-hoc signs the bundle, which
is enough to run it locally; a bundle handed to another Mac is quarantined
by Gatekeeper until the user opens it with right-click, Open.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from standalone_build import APP_NAME, DIST_DIR, ICON_DIR, WORK_DIR, argumentParser as sharedArgumentParser, baseCommand, runBuild

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


def diskImagePath() -> Path:
    """Return where --dmg writes the disk image."""
    return DIST_DIR / f"{APP_NAME}.dmg"


def stageDiskImage(bundle: Path, staging: Path) -> None:
    """Fill staging with a copy of the bundle and an Applications link, replacing anything from an earlier build."""
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    shutil.copytree(bundle, staging / bundle.name, symlinks=True)
    (staging / "Applications").symlink_to("/Applications")


def hdiutilCommand(staging: Path, image: Path) -> list[str]:
    """Return the hdiutil command that compresses the staged folder into a read-only image."""
    return ["hdiutil", "create", "-volname", APP_NAME, "-srcfolder", str(staging), "-ov", "-format", "UDZO", str(image)]


def buildDiskImage(bundle: Path, staging: Path, image: Path) -> int:
    """Wrap the bundle in a disk image; print its size, or hdiutil's complaint if it fails."""
    stageDiskImage(bundle, staging)
    result = subprocess.run(hdiutilCommand(staging, image), capture_output=True, text=True)
    if result.returncode != 0:
        print(f"hdiutil failed with exit code {result.returncode}:")
        print(result.stderr.strip())
        return result.returncode
    print(f"Built {image} ({image.stat().st_size / (1024 * 1024):.0f} MB)")
    return 0


def argumentParser() -> argparse.ArgumentParser:
    """Return the shared parser plus --dmg, which only makes sense on macOS."""
    parser = sharedArgumentParser(__doc__ or "")
    parser.add_argument("--dmg", action="store_true", help="also wrap the app in a disk image")
    return parser


def main() -> int:
    args = argumentParser().parse_args()
    bundle = outputPath(args.onefile)
    status = runBuild(pyinstallerCommand(args.onefile, args.clean), bundle, args.onefile)
    if status != 0 or not args.dmg:
        return status
    return buildDiskImage(bundle, WORK_DIR / "dmg", diskImagePath())


if __name__ == "__main__":
    sys.exit(main())
