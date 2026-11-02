"""Tests for the per-platform PyInstaller build scripts' command lines."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
ICON_DIR = SCRIPTS_DIR.parent / "src" / "ohmyssh" / "ui" / "icons"


def _canCreateSymlinks(root: Path) -> bool:
    """Report whether this account may create symlinks; Windows refuses without Developer Mode or admin rights."""
    probe = root / "symlink-probe"
    try:
        probe.symlink_to(root)
    except OSError:
        return False
    probe.unlink()
    return True


def _loadScript(name: str) -> ModuleType:
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    return importlib.import_module(name)


@pytest.mark.parametrize("name", ["build_windows", "build_macos", "build_linux"])
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


def test_linux_build_has_no_icon_and_names_the_program_after_the_app() -> None:
    script = _loadScript("build_linux")
    command = script.pyinstallerCommand(oneFile=False, clean=False)
    # PyInstaller only embeds icons on Windows and macOS; the window icon comes from the bundled SVG at run time.
    assert "--icon" not in command
    assert "--osx-bundle-identifier" not in command
    # PyInstaller uses the bare app name for both layouts: a folder holding the program, or the program itself.
    assert script.outputPath(oneFile=False) == script.DIST_DIR / "ohmyssh"
    assert script.outputPath(oneFile=True) == script.DIST_DIR / "ohmyssh"


def test_only_the_macos_build_offers_a_dmg_flag() -> None:
    macos = _loadScript("build_macos").argumentParser()
    assert macos.parse_args([]).dmg is False
    assert macos.parse_args(["--dmg", "--onefile"]).dmg is True
    for name in ["build_windows", "build_linux"]:
        with pytest.raises(SystemExit):
            _loadScript(name).argumentParser().parse_args(["--dmg"])


def test_disk_image_command_compresses_the_staged_folder_into_dist() -> None:
    script = _loadScript("build_macos")
    staging = Path("/tmp/stage")
    image = Path("/tmp/out.dmg")
    command = script.hdiutilCommand(staging, image)
    assert command[:2] == ["hdiutil", "create"]
    assert command[command.index("-volname") + 1] == "ohmyssh"
    assert command[command.index("-srcfolder") + 1] == str(staging)
    assert command[command.index("-format") + 1] == "UDZO"
    assert "-ov" in command and command[-1] == str(image)
    assert script.diskImagePath() == script.DIST_DIR / "ohmyssh.dmg"


def _fakeBundle(root: Path) -> Path:
    bundle = root / "ohmyssh.app"
    (bundle / "Contents" / "MacOS").mkdir(parents=True)
    (bundle / "Contents" / "MacOS" / "ohmyssh").write_text("#!/bin/sh\n")
    return bundle


def test_staging_holds_the_bundle_beside_an_applications_link(tmp_path: Path) -> None:
    if not _canCreateSymlinks(tmp_path):
        pytest.skip("this account cannot create symlinks")
    script = _loadScript("build_macos")
    staging = tmp_path / "stage"
    staging.mkdir()
    (staging / "stale.txt").write_text("left over from an earlier build")

    script.stageDiskImage(_fakeBundle(tmp_path), staging)

    assert sorted(child.name for child in staging.iterdir()) == ["Applications", "ohmyssh.app"]
    assert (staging / "ohmyssh.app" / "Contents" / "MacOS" / "ohmyssh").read_text() == "#!/bin/sh\n"
    link = staging / "Applications"
    assert link.is_symlink() and link.readlink() == Path("/Applications")


@pytest.mark.skipif(sys.platform != "darwin", reason="hdiutil only exists on macOS")
def test_disk_image_mounts_with_the_app_and_applications_link(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import subprocess

    script = _loadScript("build_macos")
    image = tmp_path / "dist" / "ohmyssh.dmg"
    image.parent.mkdir()

    assert script.buildDiskImage(_fakeBundle(tmp_path), tmp_path / "stage", image) == 0

    printed = capsys.readouterr()
    assert printed.err == ""
    assert printed.out.startswith(f"Built {image} (")
    mount = tmp_path / "mnt"
    subprocess.run(["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(mount), str(image)], check=True, capture_output=True)
    try:
        assert (mount / "ohmyssh.app" / "Contents" / "MacOS" / "ohmyssh").is_file()
        assert (mount / "Applications").is_symlink()
    finally:
        subprocess.run(["hdiutil", "detach", str(mount)], check=True, capture_output=True)
