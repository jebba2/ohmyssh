"""Tests for application settings and file locations."""

from pathlib import Path

import pytest

from pyommyssh.core.config import AppPaths, AppSettings, loadSettings, saveSettings


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
    assert paths.logFile == tmp_path / "working" / "logs" / "pyommyssh.log"


def test_app_paths_default_locations(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    paths = AppPaths.default()
    assert paths.configDir == tmp_path / "roaming" / "pyommyssh"
    # Running from source, generated files go in <project root>/working.
    assert paths.workingDir.name == "working"
    assert (paths.workingDir.parent / "pyproject.toml").is_file()


def test_app_paths_fall_back_to_home_config_without_appdata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    paths = AppPaths.default()
    assert paths.configDir == tmp_path / "home" / ".config" / "pyommyssh"
