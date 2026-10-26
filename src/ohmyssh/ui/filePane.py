"""One side of the SFTP tab: a path bar and a table of files.

The pane only shows what it is given. Whoever owns it listens for
``navigateRequested`` and answers with ``setEntries``, so the same widget
serves the local disk and the remote host.

Rows can be dragged out and dropped on another pane. A drag carries the
selected paths and a token naming the pane they came from, so the owner
can tell an upload from a download, and files dropped from the OS arrive
as ``urlsDropped``.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QDrag, QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ohmyssh.core.sftp import FileEntry

PARENT_ROW_LABEL = ".."
COLUMNS = ("Name", "Size", "Modified")
ENTRIES_MIME_TYPE = "application/x-ohmyssh-entries"
_SIZE_UNITS = ("B", "KB", "MB", "GB", "TB")


def formatSize(size: int) -> str:
    """Human-readable size: whole bytes, otherwise one decimal."""
    value = float(size)
    unit = 0
    while value >= 1024 and unit < len(_SIZE_UNITS) - 1:
        value /= 1024
        unit += 1
    if unit == 0:
        return f"{size} B"
    return f"{value:.1f} {_SIZE_UNITS[unit]}"


def formatModified(epoch: float | None) -> str:
    """Local date and time to the minute, or blank when unknown."""
    if epoch is None:
        return ""
    return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M")


class _FileTable(QTableWidget):
    """The pane's table; drags start from and drops land on the pane."""

    def __init__(self, pane: FilePane) -> None:
        super().__init__(0, len(COLUMNS))
        self._pane = pane
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)

    def startDrag(self, supportedActions: Qt.DropAction) -> None:
        mime = self._pane.dragMimeData()
        if mime is None:
            return
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        acceptAsCopy(event, self._pane.acceptsDrop(event.mimeData()))

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        acceptAsCopy(event, self._pane.acceptsDrop(event.mimeData()))

    def dropEvent(self, event: QDropEvent) -> None:
        if not acceptAsCopy(event, self._pane.acceptsDrop(event.mimeData())):
            return
        self._pane.handleDrop(event.mimeData(), event.position().toPoint())


def acceptAsCopy(event: QDropEvent, wanted: bool) -> bool:
    """Accept a drag or drop as a copy, never as the move the source may have proposed.

    Answering "move" would let Explorer delete the dropped file afterwards,
    so a source that allows only a move is refused.
    """
    if not wanted or not (event.possibleActions() & Qt.DropAction.CopyAction):
        event.ignore()
        return False
    event.setDropAction(Qt.DropAction.CopyAction)
    event.accept()
    return True


class FilePane(QWidget):
    """A titled file listing with a path bar, an Up button, and optional drive switch."""

    navigateRequested = Signal(str)
    fileActivated = Signal(object)
    selectionChanged = Signal()
    entriesDropped = Signal(str, object, str)
    urlsDropped = Signal(object, str)

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = ""
        self._parentPath: str | None = None
        self._entries: list[FileEntry] = []
        # Names this pane in drags so a drop can tell where the rows came from.
        self.dragToken = f"pane-{id(self)}"
        # A drop anywhere on the pane, not only on the table, lands in the folder on show.
        self.setAcceptDrops(True)

        self.titleLabel = QLabel(title)
        self.titleLabel.setObjectName("paneTitle")
        self.rootsCombo = QComboBox()
        self.rootsCombo.setVisible(False)
        self.rootsCombo.currentIndexChanged.connect(self._onRootChosen)
        self.upButton = QToolButton()
        self.upButton.setText("Up")
        self.upButton.setToolTip("Go to the parent folder")
        self.upButton.setEnabled(False)
        self.upButton.clicked.connect(self._goUp)
        self.pathEdit = QLineEdit()
        self.pathEdit.returnPressed.connect(self._onPathEntered)
        self.statusLabel = QLabel("")
        self.statusLabel.setObjectName("paneStatus")
        self.statusLabel.setVisible(False)

        self.table = _FileTable(self)
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellDoubleClicked.connect(self._onDoubleClick)
        self.table.itemSelectionChanged.connect(self.selectionChanged)

        titleRow = QHBoxLayout()
        titleRow.addWidget(self.titleLabel)
        titleRow.addStretch(1)
        titleRow.addWidget(self.rootsCombo)
        pathRow = QHBoxLayout()
        pathRow.addWidget(self.upButton)
        pathRow.addWidget(self.pathEdit, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(titleRow)
        layout.addLayout(pathRow)
        layout.addWidget(self.statusLabel)
        layout.addWidget(self.table, 1)

    # State

    def currentPath(self) -> str:
        """The folder on show."""
        return self._path

    def parentPath(self) -> str | None:
        """The folder above the one on show, or None at a root."""
        return self._parentPath

    def names(self) -> list[str]:
        """Every row's name in order, including the parent row when present."""
        return [self._nameAt(row) for row in range(self.table.rowCount())]

    def entryAt(self, row: int) -> FileEntry | None:
        """The entry behind a table row; None for the parent row."""
        index = row - self._parentRows()
        if 0 <= index < len(self._entries):
            return self._entries[index]
        return None

    def selectedEntries(self) -> list[FileEntry]:
        """The selected entries in row order, never including the parent row."""
        rows = sorted(index.row() for index in self.table.selectionModel().selectedRows())
        return [entry for entry in (self.entryAt(row) for row in rows) if entry is not None]

    def setRoots(self, roots: list[str]) -> None:
        """Offer a drive switch when there is more than one place to start from."""
        self.rootsCombo.blockSignals(True)
        self.rootsCombo.clear()
        self.rootsCombo.addItems(roots)
        self.rootsCombo.blockSignals(False)
        self.rootsCombo.setVisible(len(roots) > 1)

    def setEntries(self, path: str, entries: list[FileEntry], parentPath: str | None) -> None:
        """Show a listing. ``parentPath`` None means ``path`` is a root."""
        self._path = path
        self._parentPath = parentPath
        self._entries = list(entries)
        self.pathEdit.setText(path)
        self.statusLabel.setVisible(False)
        self.upButton.setEnabled(parentPath is not None)
        self._syncRoot(path)
        self.table.setRowCount(0)
        self.table.setRowCount(self._parentRows() + len(entries))
        if parentPath is not None:
            self._setRow(0, PARENT_ROW_LABEL, "", "")
        for offset, entry in enumerate(entries):
            self._setRow(
                offset + self._parentRows(),
                entry.name,
                "" if entry.isDir else formatSize(entry.size),
                formatModified(entry.modified),
            )

    def setLoading(self, path: str) -> None:
        """Show that ``path`` is being listed; the previous listing stays visible."""
        self.statusLabel.setText("Loading...")
        self.statusLabel.setVisible(True)

    def setError(self, message: str) -> None:
        """Show why a listing failed; the previous listing stays visible."""
        self.statusLabel.setText(message)
        self.statusLabel.setVisible(True)

    # Drag and drop

    def dragMimeData(self) -> QMimeData | None:
        """The payload for dragging the selected rows, or None when nothing is selected."""
        paths = [entry.path for entry in self.selectedEntries()]
        if not paths:
            return None
        mime = QMimeData()
        mime.setData(ENTRIES_MIME_TYPE, json.dumps({"token": self.dragToken, "paths": paths}).encode("utf-8"))
        return mime

    def acceptsDrop(self, mime: QMimeData) -> bool:
        """True for rows from another pane or files from the OS, never for our own rows."""
        if mime.hasFormat(ENTRIES_MIME_TYPE):
            return self._payloadOf(mime).get("token") != self.dragToken
        return mime.hasUrls()

    def dropTargetAt(self, point: QPoint) -> str:
        """The folder a drop at ``point`` means: a folder row under it, else the folder on show."""
        index = self.table.indexAt(point)
        entry = self.entryAt(index.row()) if index.isValid() else None
        if entry is not None and entry.isDir:
            return entry.path
        return self._path

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        acceptAsCopy(event, self.acceptsDrop(event.mimeData()))

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        acceptAsCopy(event, self.acceptsDrop(event.mimeData()))

    def dropEvent(self, event: QDropEvent) -> None:
        if acceptAsCopy(event, self.acceptsDrop(event.mimeData())):
            self.handleDrop(event.mimeData(), None)

    def handleDrop(self, mime: QMimeData, point: QPoint | None) -> None:
        """Turn a drop into ``entriesDropped`` or ``urlsDropped``.

        ``point`` is a table position that may pick a folder row; None means
        the folder on show.
        """
        target = self.dropTargetAt(point) if point is not None else self._path
        if mime.hasFormat(ENTRIES_MIME_TYPE):
            payload = self._payloadOf(mime)
            token = str(payload.get("token", ""))
            if token == self.dragToken:
                return
            rawPaths = payload.get("paths")
            paths = [str(path) for path in rawPaths] if isinstance(rawPaths, list) else []
            self.entriesDropped.emit(token, paths, target)
            return
        localPaths = [str(Path(url.toLocalFile())) for url in mime.urls() if url.isLocalFile()]
        if localPaths:
            self.urlsDropped.emit(localPaths, target)

    @staticmethod
    def _payloadOf(mime: QMimeData) -> dict[str, object]:
        try:
            payload = json.loads(bytes(mime.data(ENTRIES_MIME_TYPE).data()).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    # Internals

    def _parentRows(self) -> int:
        return 1 if self._parentPath is not None else 0

    def _nameAt(self, row: int) -> str:
        item = self.table.item(row, 0)
        return item.text() if item is not None else ""

    def _setRow(self, row: int, name: str, size: str, modified: str) -> None:
        sizeItem = QTableWidgetItem(size)
        sizeItem.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        for column, item in enumerate((QTableWidgetItem(name), sizeItem, QTableWidgetItem(modified))):
            self.table.setItem(row, column, item)

    def _syncRoot(self, path: str) -> None:
        for index in range(self.rootsCombo.count()):
            if path.lower().startswith(self.rootsCombo.itemText(index).lower()):
                self.rootsCombo.blockSignals(True)
                self.rootsCombo.setCurrentIndex(index)
                self.rootsCombo.blockSignals(False)
                return

    def _onRootChosen(self, index: int) -> None:
        if index >= 0:
            self.navigateRequested.emit(self.rootsCombo.itemText(index))

    def _goUp(self) -> None:
        if self._parentPath is not None:
            self.navigateRequested.emit(self._parentPath)

    def _onPathEntered(self) -> None:
        path = self.pathEdit.text().strip()
        if path:
            self.navigateRequested.emit(path)

    def _onDoubleClick(self, row: int, column: int) -> None:
        entry = self.entryAt(row)
        if entry is None:
            self._goUp()
        elif entry.isDir:
            self.navigateRequested.emit(entry.path)
        else:
            self.fileActivated.emit(entry)
