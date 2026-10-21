"""The dashboard: a responsive grid of host cards, optionally grouped by tag."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QGridLayout, QLabel, QScrollArea, QWidget

from pyommyssh.core.hosts import Host
from pyommyssh.core.metrics import HostMetrics
from pyommyssh.core.tunnel import TunnelStatus
from pyommyssh.ui.hostCard import HostCard

CARD_MIN_WIDTH = 300
UNTAGGED_GROUP = "Untagged"


def columnsFor(width: int) -> int:
    """Return how many cards of minimum width fit side by side."""
    return max(1, width // CARD_MIN_WIDTH)


class DashboardView(QScrollArea):
    """Shows every host as a card and routes metric updates to the right card."""

    openTerminalRequested = Signal(Host)
    editRequested = Signal(Host)
    removeRequested = Signal(Host)
    startTunnelRequested = Signal(Host)
    stopTunnelRequested = Signal(Host)
    installKeyRequested = Signal(Host)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hosts: list[Host] = []
        self._cards: list[HostCard] = []
        self._headers: list[QLabel] = []
        self._lastMetrics: dict[str, HostMetrics] = {}
        self._lastTunnelStatus: dict[str, TunnelStatus] = {}
        self._groupByTag = False
        self._columns = 1

        self._container = QWidget()
        self._grid = QGridLayout(self._container)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._grid.setSpacing(12)
        self.setWidget(self._container)
        self.setWidgetResizable(True)

    def cards(self) -> list[HostCard]:
        """Return the cards in display order."""
        return list(self._cards)

    def cardFor(self, name: str) -> HostCard | None:
        """Return the first card for a host name, or None."""
        return next((card for card in self._cards if card.host.name == name), None)

    def groupHeaders(self) -> list[str]:
        """Return the group header texts in display order."""
        return [header.text() for header in self._headers]

    def columns(self) -> int:
        """Return the current number of grid columns."""
        return self._columns

    def setHosts(self, hosts: list[Host]) -> None:
        """Replace the displayed hosts, keeping any metrics already shown."""
        self._hosts = list(hosts)
        self._rebuild()

    def setGroupByTag(self, enabled: bool) -> None:
        """Toggle tag group headers; a host appears once per tag it carries."""
        if enabled != self._groupByTag:
            self._groupByTag = enabled
            self._rebuild()

    def showConnecting(self, name: str) -> None:
        """Mark a host's cards as refreshing."""
        for card in self._cardsNamed(name):
            card.setConnecting()

    def showMetrics(self, name: str, metrics: HostMetrics) -> None:
        """Display fresh metrics on every card for a host."""
        self._lastMetrics[name] = metrics
        for card in self._cardsNamed(name):
            card.setMetrics(metrics)

    def showError(self, name: str, message: str) -> None:
        """Display a refresh failure on every card for a host."""
        self._lastMetrics.pop(name, None)
        for card in self._cardsNamed(name):
            card.setError(message)

    def showTunnelStatus(self, name: str, status: TunnelStatus) -> None:
        """Display a tunnel status on every card for a host."""
        self._lastTunnelStatus[name] = status
        for card in self._cardsNamed(name):
            card.setTunnelStatus(status)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        columns = columnsFor(self.viewport().width())
        if columns != self._columns:
            self._columns = columns
            self._place()

    def _cardsNamed(self, name: str) -> list[HostCard]:
        return [card for card in self._cards if card.host.name == name]

    def _makeCard(self, host: Host) -> HostCard:
        card = HostCard(host)
        card.openTerminalRequested.connect(self.openTerminalRequested)
        card.editRequested.connect(self.editRequested)
        card.removeRequested.connect(self.removeRequested)
        card.startTunnelRequested.connect(self.startTunnelRequested)
        card.stopTunnelRequested.connect(self.stopTunnelRequested)
        card.installKeyRequested.connect(self.installKeyRequested)
        if host.name in self._lastMetrics:
            card.setMetrics(self._lastMetrics[host.name])
        if host.name in self._lastTunnelStatus:
            card.setTunnelStatus(self._lastTunnelStatus[host.name])
        return card

    def _grouped(self) -> list[tuple[str, list[Host]]]:
        """Return (group name, hosts) pairs: tags alphabetically, untagged last."""
        tags = sorted({tag for host in self._hosts for tag in host.tags})
        groups = [(tag, [host for host in self._hosts if tag in host.tags]) for tag in tags]
        untagged = [host for host in self._hosts if not host.tags]
        if untagged:
            groups.append((UNTAGGED_GROUP, untagged))
        return groups

    def _clear(self) -> None:
        for widget in [*self._cards, *self._headers]:
            self._grid.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()
        self._cards = []
        self._headers = []

    def _rebuild(self) -> None:
        """Recreate cards and headers from the host list, then lay them out."""
        self._clear()
        if self._groupByTag:
            for groupName, hosts in self._grouped():
                header = QLabel(groupName)
                header.setObjectName("groupHeader")
                self._headers.append(header)
                self._cards.extend(self._makeCard(host) for host in hosts)
        else:
            self._cards = [self._makeCard(host) for host in self._hosts]
        self._place()

    def _place(self) -> None:
        """Position headers and cards in the grid for the current column count."""
        for index in reversed(range(self._grid.count())):
            item = self._grid.takeAt(index)
            del item
        row = 0
        column = 0
        remainingCards = list(self._cards)
        if self._groupByTag:
            for header, (_, hosts) in zip(self._headers, self._grouped()):
                if column:
                    row += 1
                    column = 0
                self._grid.addWidget(header, row, 0, 1, self._columns)
                row += 1
                for _ in hosts:
                    card = remainingCards.pop(0)
                    self._grid.addWidget(card, row, column)
                    column += 1
                    if column == self._columns:
                        column = 0
                        row += 1
            return
        for card in remainingCards:
            self._grid.addWidget(card, row, column)
            column += 1
            if column == self._columns:
                column = 0
                row += 1
