"""The dashboard card for one host: identity, health bars, and status."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QContextMenuEvent, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pyommyssh.core.hosts import Host, HostSource
from pyommyssh.core.metrics import HostMetrics
from pyommyssh.core.tunnel import TunnelState, TunnelStatus
from pyommyssh.ui.icons import loadIcon

WARN_THRESHOLD = 60.0
CRITICAL_THRESHOLD = 85.0
ICON_SIZE = 18
START_TUNNEL = "Start tunnel"
STOP_TUNNEL = "Stop tunnel"


def tunnelStatusText(status: TunnelStatus) -> str:
    """Describe a tunnel status in one short line for the card."""
    if status.state == TunnelState.CONNECTING:
        return "Tunnel connecting..."
    if status.state == TunnelState.UP:
        return "Tunnel active"
    if status.state == TunnelState.RETRYING:
        return f"Tunnel reconnecting: {status.message}"
    if status.state == TunnelState.FAILED:
        return f"Tunnel failed: {status.message}"
    if status.state == TunnelState.AUTH_REQUIRED:
        return "Tunnel: password required"
    return "Tunnel off"


def usageLevel(percent: float) -> str:
    """Classify a usage percentage for bar coloring."""
    if percent >= CRITICAL_THRESHOLD:
        return "critical"
    if percent >= WARN_THRESHOLD:
        return "warn"
    return "ok"


def _repolish(widget: QWidget) -> None:
    """Make the stylesheet re-evaluate dynamic properties on a widget."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


class HostCard(QFrame):
    """Shows one host's latest metrics and offers actions on it."""

    openTerminalRequested = Signal(Host)
    editRequested = Signal(Host)
    removeRequested = Signal(Host)
    startTunnelRequested = Signal(Host)
    stopTunnelRequested = Signal(Host)
    installKeyRequested = Signal(Host)
    openSftpRequested = Signal(Host)

    def __init__(self, host: Host, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.host = host
        self._tunnelStatus = TunnelStatus(TunnelState.STOPPED)
        self.setObjectName("hostCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.nameLabel = QLabel(host.name)
        self.nameLabel.setObjectName("hostName")
        self.terminalButton = self._makeIconButton("terminal", "Open terminal")
        self.terminalButton.clicked.connect(lambda: self.openTerminalRequested.emit(self.host))
        self.editButton = self._makeIconButton("edit", "Edit host")
        self.editButton.clicked.connect(lambda: self.editRequested.emit(self.host))
        self.keyButton = self._makeIconButton("key", "Install SSH key")
        self.keyButton.clicked.connect(lambda: self.installKeyRequested.emit(self.host))
        self.filesButton = self._makeIconButton("folder", "Browse files")
        self.filesButton.clicked.connect(lambda: self.openSftpRequested.emit(self.host))
        self.removeButton = self._makeIconButton("trash", self._removeLabel())
        self.removeButton.clicked.connect(lambda: self.removeRequested.emit(self.host))
        nameRow = QHBoxLayout()
        nameRow.addWidget(self.nameLabel)
        nameRow.addStretch(1)
        nameRow.addWidget(self.removeButton)
        nameRow.addWidget(self.filesButton)
        nameRow.addWidget(self.keyButton)
        nameRow.addWidget(self.editButton)
        nameRow.addWidget(self.terminalButton)
        self.addressLabel = QLabel(host.displayAddress())
        self.addressLabel.setObjectName("hostAddress")
        self.statusLabel = QLabel("Not checked yet")
        self.statusLabel.setObjectName("hostStatus")
        self.osLabel = QLabel("")
        self.uptimeLabel = QLabel("")
        self.loadLabel = QLabel("")
        self.cpuBar = self._makeBar("CPU")
        self.memBar = self._makeBar("RAM")
        self.diskBar = self._makeBar("Disk")
        self.dockerBadge = QLabel("")
        self.dockerBadge.setObjectName("dockerBadge")
        self.dockerBadge.setVisible(False)
        self.processesLabel = QLabel("")
        self.processesLabel.setObjectName("hostProcesses")
        self.forwardsLabel = QLabel("\n".join(forward.describe() for forward in host.forwards))
        self.forwardsLabel.setObjectName("hostForwards")
        self.tunnelStatusLabel = QLabel("")
        self.tunnelStatusLabel.setObjectName("tunnelStatus")
        self.tunnelButton = QPushButton(START_TUNNEL)
        self.tunnelButton.setObjectName("tunnelButton")
        self.tunnelButton.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tunnelButton.clicked.connect(self._toggleTunnel)
        tunnelRow = QHBoxLayout()
        tunnelRow.addWidget(self.tunnelStatusLabel, 1)
        tunnelRow.addWidget(self.tunnelButton)

        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.addLayout(nameRow)
        for widget in (
            self.addressLabel,
            self.statusLabel,
            self.osLabel,
            self.uptimeLabel,
            self.loadLabel,
            self.cpuBar,
            self.memBar,
            self.diskBar,
            self.dockerBadge,
            self.processesLabel,
            self.forwardsLabel,
        ):
            layout.addWidget(widget)
        layout.addLayout(tunnelRow)
        self._resetBars()
        for widget in (self.forwardsLabel, self.tunnelStatusLabel, self.tunnelButton):
            widget.setVisible(host.hasForwards())
        self.setTunnelStatus(self._tunnelStatus)

    def _removeLabel(self) -> str:
        """App hosts are deleted; SSH config hosts are only hidden from the dashboard."""
        return "Remove host" if self.host.source == HostSource.APP else "Hide host"

    def _makeIconButton(self, iconName: str, toolTip: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("cardButton")
        button.setIcon(loadIcon(iconName))
        button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        button.setToolTip(toolTip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setAutoRaise(True)
        return button

    def _makeBar(self, label: str) -> QProgressBar:
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setTextVisible(True)
        bar.setFormat(f"{label} %p%")
        bar.setProperty("metricLabel", label)
        return bar

    def _setBar(self, bar: QProgressBar, value: float | None) -> None:
        label = bar.property("metricLabel")
        if value is None:
            bar.setValue(0)
            bar.setFormat(f"{label} n/a")
            bar.setProperty("usageLevel", "unknown")
        else:
            bar.setValue(round(value))
            bar.setFormat(f"{label} %p%")
            bar.setProperty("usageLevel", usageLevel(value))
        _repolish(bar)

    def _resetBars(self) -> None:
        for bar in (self.cpuBar, self.memBar, self.diskBar):
            self._setBar(bar, None)

    def _setState(self, state: str) -> None:
        self.setProperty("state", state)
        _repolish(self)

    def setConnecting(self) -> None:
        """Show that a refresh is in flight."""
        self.statusLabel.setText("Connecting...")
        self._setState("connecting")

    def setMetrics(self, metrics: HostMetrics) -> None:
        """Display a fresh metrics snapshot."""
        self._setBar(self.cpuBar, metrics.cpuPercent)
        self._setBar(self.memBar, metrics.memPercent)
        self._setBar(self.diskBar, metrics.diskPercent)
        self.osLabel.setText(metrics.osName or "Unknown OS")
        self.uptimeLabel.setText(f"up {metrics.uptime}" if metrics.uptime else "")
        if metrics.loadAverage:
            one, five, fifteen = metrics.loadAverage
            self.loadLabel.setText(f"load {one:g} {five:g} {fifteen:g}")
        else:
            self.loadLabel.setText("")
        if metrics.dockerContainers is None:
            self.dockerBadge.setVisible(False)
        else:
            count = metrics.dockerContainers
            self.dockerBadge.setText(f"{count} container{'' if count == 1 else 's'}")
            self.dockerBadge.setVisible(True)
        self.processesLabel.setText(
            "  ".join(f"{process.name} {process.cpuPercent:g}%" for process in metrics.processes)
        )
        self.statusLabel.setText("Online")
        self._setState("online")

    def setError(self, message: str) -> None:
        """Show a failed refresh and clear stale numbers."""
        self._resetBars()
        self.statusLabel.setText(message)
        self._setState("error")

    def setTunnelStatus(self, status: TunnelStatus) -> None:
        """Show where the host's tunnel stands and offer the opposite action."""
        self._tunnelStatus = status
        self.tunnelStatusLabel.setText(tunnelStatusText(status))
        self.tunnelStatusLabel.setProperty("tunnelState", status.state.value)
        _repolish(self.tunnelStatusLabel)
        self.tunnelButton.setText(STOP_TUNNEL if status.isActive() else START_TUNNEL)

    def _toggleTunnel(self) -> None:
        if self._tunnelStatus.isActive():
            self.stopTunnelRequested.emit(self.host)
        else:
            self.startTunnelRequested.emit(self.host)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.openTerminalRequested.emit(self.host)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        menu = QMenu(self)
        menu.addAction("Open terminal", lambda: self.openTerminalRequested.emit(self.host))
        menu.addAction("Browse files", lambda: self.openSftpRequested.emit(self.host))
        menu.addAction("Edit host...", lambda: self.editRequested.emit(self.host))
        menu.addAction("Install SSH key...", lambda: self.installKeyRequested.emit(self.host))
        if self.host.hasForwards():
            menu.addAction(self.tunnelButton.text(), self._toggleTunnel)
        menu.addAction(self._removeLabel(), lambda: self.removeRequested.emit(self.host))
        menu.exec(event.globalPos())
