"""Application settings and the file locations they live in.

Settings and the app-managed host list live in the per-user config
directory. Logs and other generated files live in ``working/`` under the
project root when running from source, or beside the executable when frozen.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

import tomli_w

APP_NAME = "pyommyssh"


def projectRoot() -> Path:
    """Return the directory that owns ``working/``.

    From source this is the directory containing ``pyproject.toml``. In a
    PyInstaller build it is the directory containing the executable.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


@dataclass(frozen=True)
class AppPaths:
    """Where configuration and generated files are stored."""

    configDir: Path
    workingDir: Path

    @classmethod
    def default(cls) -> AppPaths:
        """Resolve the standard locations for this user and platform."""
        appData = os.environ.get("APPDATA")
        configRoot = Path(appData) if appData else Path.home() / ".config"
        return cls(configDir=configRoot / APP_NAME, workingDir=projectRoot() / "working")

    @property
    def settingsFile(self) -> Path:
        return self.configDir / "config.toml"

    @property
    def hostsFile(self) -> Path:
        return self.configDir / "hosts.toml"

    @property
    def logFile(self) -> Path:
        return self.workingDir / "logs" / f"{APP_NAME}.log"


@dataclass(frozen=True)
class AppSettings:
    """User-tunable settings persisted in ``config.toml``."""

    refreshIntervalSeconds: int = 30
    theme: str = "dark"
    terminalFontSize: int = 11


def _readInt(section: dict[str, object], key: str, default: int) -> int:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _readStr(section: dict[str, object], key: str, default: str) -> str:
    value = section.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def loadSettings(path: Path) -> AppSettings:
    """Read settings from ``path``; missing keys and a missing file use defaults."""
    if not path.is_file():
        return AppSettings()
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    defaults = AppSettings()
    general = data.get("general", {})
    ui = data.get("ui", {})
    settings = AppSettings(
        refreshIntervalSeconds=_readInt(general, "refresh_interval", defaults.refreshIntervalSeconds),
        theme=_readStr(ui, "theme", defaults.theme),
        terminalFontSize=_readInt(ui, "terminal_font_size", defaults.terminalFontSize),
    )
    if settings.refreshIntervalSeconds < 1:
        raise ValueError("refresh_interval must be at least 1 second")
    if settings.terminalFontSize < 6:
        raise ValueError("terminal_font_size must be at least 6")
    return settings


def saveSettings(path: Path, settings: AppSettings) -> None:
    """Write settings to ``path``, creating parent directories as needed."""
    # TOML keys mirror OmnySSH's config.toml where an equivalent exists.
    document = {
        "general": {"refresh_interval": settings.refreshIntervalSeconds},
        "ui": {"theme": settings.theme, "terminal_font_size": settings.terminalFontSize},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        tomli_w.dump(document, handle)
