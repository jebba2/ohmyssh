"""One SFTP tab: the local disk on the left, a host on the right."""

from __future__ import annotations

import posixpath
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThreadPool, Signal
from PySide6.QtWidgets import QLabel, QSplitter, QVBoxLayout, QWidget

from pyommyssh.core.connections import ConnectionPool
from pyommyssh.core.hosts import Host
from pyommyssh.core.sftp import FileEntry, localRoots
from pyommyssh.ui.filePane import FilePane
from pyommyssh.ui.sftpBridge import SftpBridge
from pyommyssh.ui.workers import LocalListWorker


def localParent(path: str) -> str | None:
    """The folder above a local path, or None at a drive or filesystem root."""
    current = Path(path)
    return None if current.parent == current else str(current.parent)


def remoteParent(path: str) -> str | None:
    """The folder above a remote POSIX path, or None at ``/``."""
    normalized = posixpath.normpath(path) if path else "/"
    return None if normalized == "/" else posixpath.dirname(normalized)


class SftpTab(QWidget):
    """Owns the SFTP bridge and the two panes, and keeps each pane's listing current."""

    titleChanged = Signal(str)
    authRequired = Signal()

    def __init__(
        self,
        host: Host,
        pool: ConnectionPool,
        threadPool: QThreadPool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.host = host
        self._threadPool = threadPool
        self._liveSignals: set[QObject] = set()
        self._bridge = SftpBridge(host, pool, self)
        self._bridge.connected.connect(self._onConnected)
        self._bridge.connectFailed.connect(self.showStatus)
        self._bridge.authRequired.connect(self.authRequired)
        self._bridge.listed.connect(self._onRemoteListed)
        self._bridge.listFailed.connect(lambda _path, message: self.remotePane.setError(message))

        self.statusLabel = QLabel("")
        self.statusLabel.setObjectName("terminalStatus")
        self.statusLabel.setVisible(False)
        self.localPane = FilePane("Local")
        self.localPane.setRoots(localRoots())
        self.localPane.navigateRequested.connect(self.listLocal)
        self.remotePane = FilePane(host.name)
        self.remotePane.navigateRequested.connect(self.listRemote)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.localPane)
        splitter.addWidget(self.remotePane)
        splitter.setChildrenCollapsible(False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.statusLabel)
        layout.addWidget(splitter, 1)

    def showStatus(self, message: str) -> None:
        """Show a message above the panes."""
        self.statusLabel.setText(message)
        self.statusLabel.setVisible(True)

    def start(self) -> None:
        """Connect to the host and list the local home folder."""
        self.showStatus("Connecting...")
        self._bridge.start()
        if not self.localPane.currentPath():
            self.listLocal(str(Path.home()))

    def listLocal(self, path: str) -> None:
        """List a local folder in the thread pool and show it on the left."""
        self.localPane.setLoading(path)
        worker = LocalListWorker(path)
        signals = worker.signals
        self._liveSignals.add(signals)
        signals.listed.connect(self._onLocalListed)
        signals.failed.connect(lambda _path, message: self.localPane.setError(message))
        for signal in (signals.listed, signals.failed):
            signal.connect(lambda *_, s=signals: self._liveSignals.discard(s))
        self._threadPool.start(worker)

    def listRemote(self, path: str) -> None:
        """List a remote folder through the bridge and show it on the right."""
        self.remotePane.setLoading(path)
        self._bridge.listDir(path)

    def shutdown(self) -> None:
        """Close the session and stop its threads."""
        self._bridge.shutdown()

    def _onConnected(self, home: str) -> None:
        self.statusLabel.setVisible(False)
        self.listRemote(home)

    def _onLocalListed(self, path: str, entries: list[FileEntry]) -> None:
        self.localPane.setEntries(path, entries, localParent(path))

    def _onRemoteListed(self, path: str, entries: list[FileEntry]) -> None:
        self.remotePane.setEntries(path, entries, remoteParent(path))
