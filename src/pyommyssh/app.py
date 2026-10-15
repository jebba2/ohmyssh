"""Application entry point: logging, settings, hosts, and the main window."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from pyommyssh.core.config import AppPaths, AppSettings, loadSettings
from pyommyssh.core.hosts import HostStore, loadSshConfig
from pyommyssh.ui.mainWindow import MainWindow
from pyommyssh.ui.theme import DARK_STYLESHEET

LOG_MAX_BYTES = 1_000_000
LOG_BACKUPS = 3

logger = logging.getLogger(__name__)


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
    app = QApplication(sys.argv)
    app.setApplicationName("pyommyssh")
    app.setStyleSheet(DARK_STYLESHEET)

    try:
        settings = loadSettings(paths.settingsFile)
    except ValueError as error:
        logger.error("Invalid settings in %s: %s", paths.settingsFile, error)
        QMessageBox.warning(None, "Settings", f"{paths.settingsFile}: {error}\nUsing defaults.")
        settings = AppSettings()

    hostStore = HostStore(paths.hostsFile)
    hostStore.load()
    sshConfigHosts = loadSshConfig()
    logger.info(
        "Loaded %d hosts from ssh config and %d from %s",
        len(sshConfigHosts),
        len(hostStore.hosts()),
        paths.hostsFile,
    )

    window = MainWindow(
        settings=settings,
        hostStore=hostStore,
        sshConfigHosts=sshConfigHosts,
        knownHostsPath=Path.home() / ".ssh" / "known_hosts",
    )
    window.show()
    window.refreshAll()
    return app.exec()
