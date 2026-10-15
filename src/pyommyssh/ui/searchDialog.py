"""The Ctrl+K palette: type to filter hosts and open sessions, Enter to jump."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QDialog, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from pyommyssh.core.hosts import Host


@dataclass(frozen=True)
class SearchEntry:
    """One selectable row: a host to open or a tab to switch to."""

    kind: str
    label: str
    host: Host
    tabIndex: int | None = None

    def matches(self, needle: str) -> bool:
        """Case-insensitive match on label, host name, hostname, or tags."""
        haystack = " ".join([self.label, self.host.name, self.host.hostname, *self.host.tags])
        return needle in haystack.lower()


class SearchDialog(QDialog):
    """A quick-switcher over hosts and open terminal tabs."""

    def __init__(self, entries: list[SearchEntry], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Search")
        self.setModal(True)
        self._entries = list(entries)
        self._selected: SearchEntry | None = None

        self.searchEdit = QLineEdit()
        self.searchEdit.setPlaceholderText("Search hosts and sessions")
        self.searchEdit.textChanged.connect(self._applyFilter)
        self.searchEdit.installEventFilter(self)
        self.listWidget = QListWidget()
        self.listWidget.itemActivated.connect(lambda _: self._chooseCurrent())

        layout = QVBoxLayout(self)
        layout.addWidget(self.searchEdit)
        layout.addWidget(self.listWidget)
        self.resize(480, 360)
        self._applyFilter("")

    def visibleLabels(self) -> list[str]:
        """Return the labels currently listed, top to bottom."""
        return [self.listWidget.item(i).text() for i in range(self.listWidget.count())]

    def selectedEntry(self) -> SearchEntry | None:
        """Return the entry chosen with Enter, or None."""
        return self._selected

    def _applyFilter(self, text: str) -> None:
        needle = text.strip().lower()
        self.listWidget.clear()
        for index, entry in enumerate(self._entries):
            if entry.matches(needle):
                item = QListWidgetItem(entry.label)
                item.setData(Qt.ItemDataRole.UserRole, index)
                self.listWidget.addItem(item)
        if self.listWidget.count():
            self.listWidget.setCurrentRow(0)

    def _moveSelection(self, delta: int) -> None:
        count = self.listWidget.count()
        if count:
            self.listWidget.setCurrentRow((self.listWidget.currentRow() + delta) % count)

    def _chooseCurrent(self) -> None:
        item = self.listWidget.currentItem()
        if item is None:
            return
        self._selected = self._entries[item.data(Qt.ItemDataRole.UserRole)]
        self.accept()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.searchEdit and isinstance(event, QKeyEvent):
            if event.type() == QEvent.Type.KeyPress:
                key = event.key()
                if key == Qt.Key.Key_Down:
                    self._moveSelection(1)
                    return True
                if key == Qt.Key.Key_Up:
                    self._moveSelection(-1)
                    return True
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._chooseCurrent()
                    return True
                if key == Qt.Key.Key_Escape:
                    self.reject()
                    return True
        return super().eventFilter(watched, event)
