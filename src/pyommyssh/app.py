"""Application entry point: logging, settings, hosts, and the main window."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from pyommyssh.core.config import AppPaths, AppSettings, loadSettings
from pyommyssh.core.hosts import HostStore
from pyommyssh.core.sshconfig import SshConfigEditor
from pyommyssh.ui.icons import loadIcon
from pyommyssh.ui.mainWindow import MainWindow
from pyommyssh.ui.theme import DARK_STYLESHEET

LOG_MAX_BYTES = 1_000_000
LOG_BACKUPS = 3
# Windows groups taskbar buttons by this ID; without our own, a run from
# source is grouped under python.exe and shows Python's icon.
APP_USER_MODEL_ID = "pyommyssh.desktop"

logger = logging.getLogger(__name__)


def registerWindowsAppId() -> bool:
    """Give the process its own taskbar identity on Windows so the taskbar shows our icon.

    Returns False on other platforms or if Windows refuses, which is not fatal.
    """
    if sys.platform != "win32":
        return False
    import ctypes

    try:
        result = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (AttributeError, OSError) as error:
        logger.warning("Could not set the Windows app id: %s", error)
        return False
    return result == 0


def configureLogging(logFile: Path) -> None:
    """Send application logs to a rotating file under the working directory."""
    logFile.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(logFile, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def main() -> int:
    """Run the GUI and return the process exit code."""
    paths = AppPaths.default()
    configureLogging(paths.logFile)
    registerWindowsAppId()
    app = QApplication(sys.argv)
    app.setApplicationName("pyommyssh")
    app.setWindowIcon(loadIcon("app"))
    app.setStyleSheet(DARK_STYLESHEET)

    try:
        settings = loadSettings(paths.settingsFile)
    except ValueError as error:
        logger.error("Invalid settings in %s: %s", paths.settingsFile, error)
        QMessageBox.warning(None, "Settings", f"{paths.settingsFile}: {error}\nUsing defaults.")
        settings = AppSettings()

    hostStore = HostStore(paths.hostsFile)
    hostStore.load()
    sshConfig = SshConfigEditor(Path.home() / ".ssh" / "config", backupDir=paths.workingDir / "backups")
    logger.info(
        "Loaded %d hosts from %s and %d from %s",
        len(sshConfig.hosts()),
        sshConfig.path,
        len(hostStore.hosts()),
        paths.hostsFile,
    )

    window = MainWindow(
        settings=settings,
        hostStore=hostStore,
        sshConfig=sshConfig,
        knownHostsPath=Path.home() / ".ssh" / "known_hosts",
        firstRunMarker=paths.firstRunMarker,
    )
    window.show()
    window.runFirstLaunchSetup()
    window.refreshAll()
    return app.exec()
