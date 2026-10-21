"""One SFTP tab: the local disk on the left, a host on the right, transfers between."""

from __future__ import annotations

import posixpath
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from pyommyssh.core.connections import ConnectionPool
from pyommyssh.core.hosts import Host
from pyommyssh.core.sftp import FileEntry, TransferProgress, TransferResult, localRoots
from pyommyssh.ui.filePane import FilePane, formatSize
from pyommyssh.ui.sftpBridge import SftpBridge
from pyommyssh.ui.workers import LocalListWorker

# Given the names that would be replaced; returns True to go ahead.
ReplacePrompt = Callable[[list[str]], bool]


def askReplaceWithDialog(parent: QWidget) -> ReplacePrompt:
    """Return a prompt that asks in a modal dialog before replacing files."""

    def prompt(names: list[str]) -> bool:
        listing = "\n".join(names[:10]) + ("\n..." if len(names) > 10 else "")
        answer = QMessageBox.question(
            parent, "Replace files", f"Replace {len(names)} item(s)?\n\n{listing}"
        )
        return answer == QMessageBox.StandardButton.Yes

    return prompt


def localParent(path: str) -> str | None:
    """The folder above a local path, or None at a drive or filesystem root."""
    current = Path(path)
    return None if current.parent == current else str(current.parent)


def remoteParent(path: str) -> str | None:
    """The folder above a remote POSIX path, or None at ``/``."""
    normalized = posixpath.normpath(path) if path else "/"
    return None if normalized == "/" else posixpath.dirname(normalized)


class SftpTab(QWidget):
    """Owns the SFTP bridge and the two panes, and moves files between them."""

    titleChanged = Signal(str)
    authRequired = Signal()

    def __init__(
        self,
        host: Host,
        pool: ConnectionPool,
        threadPool: QThreadPool,
        replacePrompt: ReplacePrompt | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.host = host
        self._threadPool = threadPool
        self._replacePrompt = replacePrompt or askReplaceWithDialog(self)
        self._liveSignals: set[QObject] = set()
        self._pendingUploads: list[tuple[Path, str]] | None = None
        self._transferLabel = ""
        self._bridge = SftpBridge(host, pool, self)
        self._bridge.connected.connect(self._onConnected)
        self._bridge.connectFailed.connect(self.showStatus)
        self._bridge.authRequired.connect(self.authRequired)
        self._bridge.listed.connect(self._onRemoteListed)
        self._bridge.listFailed.connect(lambda _path, message: self.remotePane.setError(message))
        self._bridge.existenceChecked.connect(self._onExistenceChecked)
        self._bridge.transferStarted.connect(self._onTransferStarted)
        self._bridge.transferProgress.connect(self._onTransferProgress)
        self._bridge.transferFinished.connect(self._onTransferFinished)
        self._bridge.transferFailed.connect(self._onTransferFailed)
        self._bridge.transferCancelled.connect(lambda: self.showStatus("Transfer cancelled"))
        self._bridge.transfersIdle.connect(self._onTransfersIdle)

        self.statusLabel = QLabel("")
        self.statusLabel.setObjectName("terminalStatus")
        self.statusLabel.setVisible(False)
        self.localPane = FilePane("Local")
        self.localPane.setRoots(localRoots())
        self.localPane.navigateRequested.connect(self.listLocal)
        self.localPane.selectionChanged.connect(self._updateButtons)
        self.remotePane = FilePane(host.name)
        self.remotePane.navigateRequested.connect(self.listRemote)
        self.remotePane.selectionChanged.connect(self._updateButtons)

        self.uploadButton = QPushButton("Upload →")
        self.uploadButton.setToolTip("Copy the selected local items to the remote folder")
        self.uploadButton.clicked.connect(self.uploadSelected)
        self.downloadButton = QPushButton("← Download")
        self.downloadButton.setToolTip("Copy the selected remote items to the local folder")
        self.downloadButton.clicked.connect(self.downloadSelected)
        self._updateButtons()
        middle = QVBoxLayout()
        middle.addStretch(1)
        middle.addWidget(self.uploadButton)
        middle.addWidget(self.downloadButton)
        middle.addStretch(1)
        middleWidget = QWidget()
        middleWidget.setLayout(middle)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.localPane)
        splitter.addWidget(middleWidget)
        splitter.addWidget(self.remotePane)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 1)

        self.transferLabel = QLabel("")
        self.transferBar = QProgressBar()
        self.transferBar.setTextVisible(False)
        self.cancelButton = QPushButton("Cancel")
        self.cancelButton.setToolTip("Stop the running transfer and drop the queued ones")
        self.cancelButton.clicked.connect(self._bridge.cancelTransfers)
        self.transferStrip = QWidget()
        self.transferStrip.setObjectName("transferStrip")
        stripLayout = QHBoxLayout(self.transferStrip)
        stripLayout.setContentsMargins(6, 4, 6, 4)
        stripLayout.addWidget(self.transferLabel, 1)
        stripLayout.addWidget(self.transferBar, 1)
        stripLayout.addWidget(self.cancelButton)
        self.transferStrip.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self.statusLabel)
        layout.addWidget(splitter, 1)
        layout.addWidget(self.transferStrip)

    # Status and lifecycle

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

    def shutdown(self) -> None:
        """Close the session and stop its threads; a running transfer is cut off."""
        self._bridge.shutdown()

    # Listing

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

    def _onConnected(self, home: str) -> None:
        self.statusLabel.setVisible(False)
        self.listRemote(home)
        self._updateButtons()

    def _onLocalListed(self, path: str, entries: list[FileEntry]) -> None:
        self.localPane.setEntries(path, entries, localParent(path))
        self._updateButtons()

    def _onRemoteListed(self, path: str, entries: list[FileEntry]) -> None:
        self.remotePane.setEntries(path, entries, remoteParent(path))
        self._updateButtons()

    # Transfers

    def _updateButtons(self) -> None:
        connected = self._bridge.isConnected() and bool(self.remotePane.currentPath())
        self.uploadButton.setEnabled(connected and bool(self.localPane.selectedEntries()))
        self.downloadButton.setEnabled(connected and bool(self.remotePane.selectedEntries()))

    def uploadSelected(self) -> None:
        """Copy the selected local items into the remote folder on show."""
        entries = self.localPane.selectedEntries()
        remoteDir = self.remotePane.currentPath()
        if not entries or not remoteDir:
            return
        pairs = [(Path(entry.path), posixpath.join(remoteDir, entry.name)) for entry in entries]
        self._pendingUploads = pairs
        self._showTransferStrip("Checking the remote folder...")
        self._bridge.checkExists([remote for _, remote in pairs])

    def _onExistenceChecked(self, exists: dict[str, bool]) -> None:
        pairs = self._pendingUploads
        self._pendingUploads = None
        if pairs is None:
            return
        clashing = [posixpath.basename(remote) for _, remote in pairs if exists.get(remote)]
        if clashing and not self._replacePrompt(clashing):
            self.transferStrip.setVisible(False)
            return
        self._showTransferStrip("Preparing...")
        for local, remote in pairs:
            self._bridge.upload(local, remote)

    def downloadSelected(self) -> None:
        """Copy the selected remote items into the local folder on show."""
        entries = self.remotePane.selectedEntries()
        localDir = self.localPane.currentPath()
        if not entries or not localDir:
            return
        pairs = [(entry.path, Path(localDir) / entry.name) for entry in entries]
        clashing = [entry.name for entry in entries if (Path(localDir) / entry.name).exists()]
        if clashing and not self._replacePrompt(clashing):
            return
        self._showTransferStrip("Preparing...")
        for remote, local in pairs:
            self._bridge.download(remote, local)

    def _showTransferStrip(self, message: str) -> None:
        self.statusLabel.setVisible(False)
        self.transferLabel.setText(message)
        self.transferBar.setRange(0, 0)
        self.transferStrip.setVisible(True)

    def _onTransferStarted(self, label: str) -> None:
        self._transferLabel = label
        self.transferLabel.setText(f"{label}: preparing...")
        self.transferBar.setRange(0, 0)

    def _onTransferProgress(self, progress: TransferProgress) -> None:
        if progress.bytesTotal > 0:
            self.transferBar.setRange(0, progress.bytesTotal)
            self.transferBar.setValue(progress.bytesDone)
        current = progress.currentFile or "preparing..."
        self.transferLabel.setText(
            f"{self._transferLabel}: {current}  {formatSize(progress.bytesDone)} / {formatSize(progress.bytesTotal)}"
            f"  ({progress.filesDone}/{progress.filesTotal} files)"
        )

    def _onTransferFinished(self, label: str, result: TransferResult) -> None:
        if result.skipped:
            self.showStatus(f"{label}: skipped {len(result.skipped)} item(s). {result.skipped[0]}")

    def _onTransferFailed(self, label: str, message: str) -> None:
        self.showStatus(f"{label} failed: {message}")

    def _onTransfersIdle(self) -> None:
        self.transferStrip.setVisible(False)
        if self.localPane.currentPath():
            self.listLocal(self.localPane.currentPath())
        if self.remotePane.currentPath():
            self.listRemote(self.remotePane.currentPath())
