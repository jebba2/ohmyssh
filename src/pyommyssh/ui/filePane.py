"""One side of the SFTP tab: a path bar and a table of files.

The pane only shows what it is given. Whoever owns it listens for
``navigateRequested`` and answers with ``setEntries``, so the same widget
serves the local disk and the remote host.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
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

from pyommyssh.core.sftp import FileEntry

PARENT_ROW_LABEL = ".."
COLUMNS = ("Name", "Size", "Modified")
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


class FilePane(QWidget):
    """A titled file listing with a path bar, an Up button, and optional drive switch."""

    navigateRequested = Signal(str)
    fileActivated = Signal(object)
    selectionChanged = Signal()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = ""
        self._parentPath: str | None = None
        self._entries: list[FileEntry] = []

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

        self.table = QTableWidget(0, len(COLUMNS))
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
