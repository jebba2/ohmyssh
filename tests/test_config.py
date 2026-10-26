"""Tests for application settings and file locations."""

import sys
from pathlib import Path

import pytest

from ohmyssh.core.config import AppPaths, AppSettings, loadSettings, saveSettings, migrateLegacyConfigDir


def test_default_settings() -> None:
    settings = AppSettings()
    assert settings.refreshIntervalSeconds == 30
    assert settings.theme == "dark"
    assert settings.terminalFontSize == 11


def test_load_missing_file_gives_defaults(tmp_path: Path) -> None:
    assert loadSettings(tmp_path / "config.toml") == AppSettings()


def test_load_partial_file_fills_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[general]\nrefresh_interval = 5\n", encoding="utf-8")
    settings = loadSettings(path)
    assert settings.refreshIntervalSeconds == 5
    assert settings.theme == "dark"


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "config.toml"
    settings = AppSettings(refreshIntervalSeconds=12, theme="light", terminalFontSize=14)
    saveSettings(path, settings)
    assert loadSettings(path) == settings


def test_invalid_refresh_interval_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[general]\nrefresh_interval = 0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="refresh_interval"):
        loadSettings(path)


def test_app_paths_use_given_root(tmp_path: Path) -> None:
    paths = AppPaths(configDir=tmp_path / "cfg", workingDir=tmp_path / "working")
    assert paths.settingsFile == tmp_path / "cfg" / "config.toml"
    assert paths.hostsFile == tmp_path / "cfg" / "hosts.toml"
    assert paths.firstRunMarker == tmp_path / "cfg" / "first_run_done"
    assert paths.logFile == tmp_path / "working" / "logs" / "ohmyssh.log"


def test_app_paths_default_locations(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    paths = AppPaths.default()
    assert paths.configDir == tmp_path / "roaming" / "ohmyssh"
    # Running from source, generated files go in <project root>/working.
    assert paths.workingDir.name == "working"
    assert (paths.workingDir.parent / "pyproject.toml").is_file()


def test_app_paths_fall_back_to_home_config_without_appdata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    paths = AppPaths.default()
    assert paths.configDir == tmp_path / "home" / ".config" / "ohmyssh"


def test_legacy_config_dir_is_moved_once_and_never_over_an_existing_one(tmp_path: Path) -> None:
    root = tmp_path / "appdata"
    legacy = root / "pyommyssh"
    legacy.mkdir(parents=True)
    (legacy / "hosts.toml").write_text("[[hosts]]\nname = 'old'\nhostname = 'o'\n")
    paths = AppPaths(configDir=root / "ohmyssh", workingDir=tmp_path / "working")

    assert migrateLegacyConfigDir(paths) is True
    assert (paths.configDir / "hosts.toml").read_text().startswith("[[hosts]]")
    assert not legacy.exists()
    assert migrateLegacyConfigDir(paths) is False

    legacy.mkdir()
    (legacy / "hosts.toml").write_text("stale")
    assert migrateLegacyConfigDir(paths) is False
    assert (paths.configDir / "hosts.toml").read_text().startswith("[[hosts]]")
    assert (legacy / "hosts.toml").read_text() == "stale"


def test_bundled_mac_app_keeps_generated_files_in_application_support(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Inside a .app bundle the executable's folder is not a place to write logs."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "ohmyssh.app" / "Contents" / "MacOS" / "ohmyssh"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    paths = AppPaths.default()
    assert paths.workingDir == tmp_path / "home" / "Library" / "Application Support" / "ohmyssh" / "working"


def test_frozen_app_elsewhere_keeps_generated_files_beside_the_executable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "ohmyssh" / "ohmyssh.exe"))
    paths = AppPaths.default()
    assert paths.workingDir == tmp_path / "ohmyssh" / "working"
