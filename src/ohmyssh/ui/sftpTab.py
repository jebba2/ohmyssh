"""One SFTP tab: the local disk on the left, a host on the right, transfers between."""

from __future__ import annotations

import posixpath
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThreadPool, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ohmyssh.core.connections import ConnectionPool
from ohmyssh.core.hosts import Host
from ohmyssh.core.sftp import FileEntry, TransferProgress, TransferResult, localRoots, removeLocal, renameLocal
from ohmyssh.ui.elidedLabel import ElidedLabel
from ohmyssh.ui.filePane import FilePane, acceptAsCopy, formatSize
from ohmyssh.ui.sftpBridge import SftpBridge
from ohmyssh.ui.workers import LocalListWorker

# The transfer bar never shrinks below this, however long the file name beside it.
PROGRESS_BAR_MIN_WIDTH = 160

MAX_LISTED_NAMES = 10


def _listNames(names: list[str]) -> str:
    return "\n".join(names[:MAX_LISTED_NAMES]) + ("\n..." if len(names) > MAX_LISTED_NAMES else "")


@dataclass
class SftpPrompts:
    """The questions the SFTP tab asks; tests swap in canned answers.

    ``replace`` gets the names that would be overwritten and returns True to
    go ahead. ``text`` gets a title, a label, and a default and returns the
    entered text or None. ``confirm`` gets a question and returns True for yes.
    """

    replace: Callable[[list[str]], bool]
    text: Callable[[str, str, str], str | None]
    confirm: Callable[[str], bool]


def dialogSftpPrompts(parent: QWidget) -> SftpPrompts:
    """Prompts that ask with modal dialogs on ``parent``."""

    def replace(names: list[str]) -> bool:
        answer = QMessageBox.question(parent, "Replace files", f"Replace {len(names)} item(s)?\n\n{_listNames(names)}")
        return answer == QMessageBox.StandardButton.Yes

    def text(title: str, label: str, default: str) -> str | None:
        entered, accepted = QInputDialog.getText(parent, title, label, text=default)
        return entered if accepted else None

    def confirm(question: str) -> bool:
        return QMessageBox.question(parent, "Confirm", question) == QMessageBox.StandardButton.Yes

    return SftpPrompts(replace=replace, text=text, confirm=confirm)


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
        prompts: SftpPrompts | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.host = host
        self._threadPool = threadPool
        self._prompts = prompts or dialogSftpPrompts(self)
        self._liveSignals: set[QObject] = set()
        # Upload batches waiting for their existence check, oldest first.
        self._pendingUploads: list[list[tuple[Path, str]]] = []
        self._transferLabel = ""
        self._bridge = SftpBridge(host, pool, self)
        self._bridge.connected.connect(self._onConnected)
        self._bridge.connectFailed.connect(self.showStatus)
        self._bridge.authRequired.connect(self.authRequired)
        self._bridge.listed.connect(self._onRemoteListed)
        self._bridge.listFailed.connect(lambda _path, message: self.remotePane.setError(message))
        self._bridge.existenceChecked.connect(self._onExistenceChecked)
        self._bridge.operationDone.connect(lambda _message: self.listRemote(self.remotePane.currentPath()))
        self._bridge.operationFailed.connect(self.showStatus)
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
        self.localPane.entriesDropped.connect(self._onEntriesDroppedOnLocal)
        self.remotePane = FilePane(host.name)
        self.remotePane.navigateRequested.connect(self.listRemote)
        self.remotePane.selectionChanged.connect(self._updateButtons)
        self.remotePane.entriesDropped.connect(self._onEntriesDroppedOnRemote)
        self.remotePane.urlsDropped.connect(self._onFilesDroppedOnRemote)

        self.localNewFolderButton = QPushButton("New folder")
        self.localNewFolderButton.clicked.connect(self.createLocalFolder)
        self.localRenameButton = QPushButton("Rename")
        self.localRenameButton.clicked.connect(self.renameLocalSelected)
        self.localDeleteButton = QPushButton("Delete")
        self.localDeleteButton.clicked.connect(self.deleteLocalSelected)
        self.localRefreshButton = QPushButton("Refresh")
        self.localRefreshButton.clicked.connect(self.refreshLocal)
        localSide = self._paneWithActions(
            self.localPane,
            (self.localNewFolderButton, self.localRenameButton, self.localDeleteButton, self.localRefreshButton),
        )

        self.newFolderButton = QPushButton("New folder")
        self.newFolderButton.clicked.connect(self.createRemoteFolder)
        self.renameButton = QPushButton("Rename")
        self.renameButton.clicked.connect(self.renameSelected)
        self.deleteButton = QPushButton("Delete")
        self.deleteButton.clicked.connect(self.deleteSelected)
        self.refreshButton = QPushButton("Refresh")
        self.refreshButton.clicked.connect(self.refreshRemote)
        remoteSide = self._paneWithActions(
            self.remotePane, (self.newFolderButton, self.renameButton, self.deleteButton, self.refreshButton)
        )

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
        splitter.addWidget(localSide)
        splitter.addWidget(middleWidget)
        splitter.addWidget(remoteSide)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 1)

        self.transferLabel = ElidedLabel()
        self.transferBar = QProgressBar()
        self.transferBar.setTextVisible(False)
        self.transferBar.setMinimumWidth(PROGRESS_BAR_MIN_WIDTH)
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
        # Files from the OS dropped anywhere else on the tab go to the remote folder on show.
        self.setAcceptDrops(True)

    @staticmethod
    def _paneWithActions(pane: FilePane, buttons: tuple[QPushButton, ...]) -> QWidget:
        """A pane with its row of action buttons underneath."""
        actions = QHBoxLayout()
        for button in buttons:
            actions.addWidget(button)
        actions.addStretch(1)
        side = QWidget()
        layout = QVBoxLayout(side)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(pane, 1)
        layout.addLayout(actions)
        return side

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        acceptAsCopy(event, event.mimeData().hasUrls())

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        acceptAsCopy(event, event.mimeData().hasUrls())

    def dropEvent(self, event: QDropEvent) -> None:
        if acceptAsCopy(event, event.mimeData().hasUrls()):
            self.remotePane.handleDrop(event.mimeData(), None)

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
        remoteSelected = self.remotePane.selectedEntries()
        localSelected = self.localPane.selectedEntries()
        self.uploadButton.setEnabled(connected and bool(localSelected))
        self.downloadButton.setEnabled(connected and bool(remoteSelected))
        self.newFolderButton.setEnabled(connected)
        self.renameButton.setEnabled(connected and len(remoteSelected) == 1)
        self.deleteButton.setEnabled(connected and bool(remoteSelected))
        self.localNewFolderButton.setEnabled(bool(self.localPane.currentPath()))
        self.localRenameButton.setEnabled(len(localSelected) == 1)
        self.localDeleteButton.setEnabled(bool(localSelected))

    # Prompts shared by both sides

    def _askName(self, title: str, label: str, default: str) -> str | None:
        """Ask for a name; None when the prompt was cancelled or left blank."""
        name = self._prompts.text(title, label, default)
        stripped = name.strip() if name else ""
        return stripped or None

    def _confirmDelete(self, names: list[str], where: str) -> bool:
        plural = "item" if len(names) == 1 else "items"
        return self._prompts.confirm(f"Delete {len(names)} {plural} from {where}?\n\n{_listNames(names)}")

    # Remote operations

    def refresh(self) -> None:
        """List both panes again."""
        self.refreshLocal()
        self.refreshRemote()

    def refreshRemote(self) -> None:
        """List the remote pane again."""
        if self.remotePane.currentPath():
            self.listRemote(self.remotePane.currentPath())

    def createRemoteFolder(self) -> None:
        """Ask for a name and create that folder in the remote folder on show."""
        remoteDir = self.remotePane.currentPath()
        if not remoteDir:
            return
        name = self._askName("New folder", "Folder name", "")
        if name:
            self._bridge.mkdir(posixpath.join(remoteDir, name))

    def renameSelected(self) -> None:
        """Ask for a new name for the one selected remote item."""
        selected = self.remotePane.selectedEntries()
        if len(selected) != 1:
            return
        entry = selected[0]
        name = self._askName("Rename", "New name", entry.name)
        if name and name != entry.name:
            self._bridge.rename(entry.path, posixpath.join(posixpath.dirname(entry.path), name))

    def deleteSelected(self) -> None:
        """Confirm once, then delete the selected remote files and empty folders."""
        selected = self.remotePane.selectedEntries()
        if not selected or not self._confirmDelete([entry.name for entry in selected], self.host.name):
            return
        for entry in selected:
            self._bridge.remove(entry.path)

    # Local operations

    def refreshLocal(self) -> None:
        """List the local pane again."""
        if self.localPane.currentPath():
            self.listLocal(self.localPane.currentPath())

    def createLocalFolder(self) -> None:
        """Ask for a name and create that folder in the local folder on show."""
        localDir = self.localPane.currentPath()
        if not localDir:
            return
        name = self._askName("New folder", "Folder name", "")
        if name:
            path = Path(localDir) / name
            if self._tryLocal(lambda: path.mkdir(), f"Could not create {path}"):
                self.refreshLocal()

    def renameLocalSelected(self) -> None:
        """Ask for a new name for the one selected local item; a taken name is refused."""
        selected = self.localPane.selectedEntries()
        if len(selected) != 1:
            return
        entry = selected[0]
        name = self._askName("Rename", "New name", entry.name)
        if name and name != entry.name:
            source = Path(entry.path)
            destination = source.with_name(name)
            if self._tryLocal(lambda: renameLocal(source, destination), f"Could not rename {source} to {destination}"):
                self.refreshLocal()

    def deleteLocalSelected(self) -> None:
        """Confirm once, then delete the selected local files and empty folders."""
        selected = self.localPane.selectedEntries()
        if not selected or not self._confirmDelete([entry.name for entry in selected], "this computer"):
            return
        removedAny = False
        for entry in selected:
            path = Path(entry.path)
            removedAny = self._tryLocal(lambda: removeLocal(path), f"Could not remove {path}") or removedAny
        if removedAny:
            self.refreshLocal()

    def _tryLocal(self, operation: Callable[[], None], failure: str) -> bool:
        """Run a local file operation; shows why it failed and returns whether it worked."""
        try:
            operation()
        except OSError as error:
            self.showStatus(f"{failure}: {error}")
            return False
        return True

    def uploadSelected(self) -> None:
        """Copy the selected local items into the remote folder on show."""
        remoteDir = self.remotePane.currentPath()
        pairs = [(Path(entry.path), posixpath.join(remoteDir, entry.name)) for entry in self.localPane.selectedEntries()]
        self._startUploads(pairs)

    def downloadSelected(self) -> None:
        """Copy the selected remote items into the local folder on show."""
        localDir = self.localPane.currentPath()
        pairs = [(entry.path, Path(localDir) / entry.name) for entry in self.remotePane.selectedEntries()]
        self._startDownloads(pairs)

    def _startUploads(self, pairs: list[tuple[Path, str]]) -> None:
        """Check the remote destinations, ask once if any exist, then queue the uploads."""
        if not pairs or not self._bridge.isConnected():
            return
        self._pendingUploads.append(pairs)
        self._showTransferStrip("Checking the remote folder...")
        self._bridge.checkExists([remote for _, remote in pairs])

    def _onExistenceChecked(self, exists: dict[str, bool]) -> None:
        if not self._pendingUploads:
            return
        pairs = self._pendingUploads.pop(0)
        clashing = [posixpath.basename(remote) for _, remote in pairs if exists.get(remote)]
        if clashing and not self._prompts.replace(clashing):
            self.transferStrip.setVisible(False)
            return
        self._showTransferStrip("Preparing...")
        for local, remote in pairs:
            self._bridge.upload(local, remote)

    def _startDownloads(self, pairs: list[tuple[str, Path]]) -> None:
        """Ask once if any local destination exists, then queue the downloads."""
        if not pairs or not self._bridge.isConnected():
            return
        clashing = [local.name for _, local in pairs if local.exists()]
        if clashing and not self._prompts.replace(clashing):
            return
        self._showTransferStrip("Preparing...")
        for remote, local in pairs:
            self._bridge.download(remote, local)

    # Drag and drop

    def _onEntriesDroppedOnRemote(self, token: str, paths: list[str], targetDir: str) -> None:
        if token != self.localPane.dragToken:
            return
        self._startUploads([(Path(path), posixpath.join(targetDir, Path(path).name)) for path in paths])

    def _onEntriesDroppedOnLocal(self, token: str, paths: list[str], targetDir: str) -> None:
        if token != self.remotePane.dragToken:
            return
        self._startDownloads([(path, Path(targetDir) / posixpath.basename(path)) for path in paths])

    def _onFilesDroppedOnRemote(self, paths: list[str], targetDir: str) -> None:
        """Upload files dropped from the OS, refusing drive roots, missing paths, and duplicate names."""
        nameCounts = Counter(Path(path).name for path in paths)
        accepted: list[Path] = []
        refused: list[str] = []
        for raw in paths:
            path = Path(raw)
            if path.parent == path:
                refused.append(f"{path} is a drive root")
            elif not path.exists():
                refused.append(f"{path.name} does not exist")
            elif nameCounts[path.name] > 1:
                refused.append(f"{path.name} appears more than once")
            else:
                accepted.append(path)
        self._startUploads([(path, posixpath.join(targetDir, path.name)) for path in accepted])
        if refused:
            self.showStatus("Not uploaded: " + "; ".join(refused))

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
        self.refresh()
