"""One terminal tab: a shell on a host, with the plumbing to keep it alive."""

from __future__ import annotations

import paramiko
from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ohmyssh.core.connections import ConnectionPool
from ohmyssh.core.hosts import Host
from ohmyssh.ui.terminalWidget import TerminalWidget
from ohmyssh.ui.workers import ShellOpener, TerminalReader

READER_STOP_TIMEOUT_MS = 2000


class TerminalTab(QWidget):
    """Owns the shell channel, its reader thread, and the terminal widget."""

    titleChanged = Signal(str)
    authRequired = Signal()

    def __init__(
        self,
        host: Host,
        pool: ConnectionPool,
        threadPool: QThreadPool,
        fontSize: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.host = host
        self._pool = pool
        self._threadPool = threadPool
        self._channel: paramiko.Channel | None = None
        self._reader: TerminalReader | None = None
        self._opener: ShellOpener | None = None
        self._shutDown = False

        self.statusLabel = QLabel("Connecting...")
        self.statusLabel.setObjectName("terminalStatus")
        self.terminal = TerminalWidget(fontSize)
        self.terminal.inputBytes.connect(self._send)
        self.terminal.sizeChanged.connect(self._resizePty)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.statusLabel)
        layout.addWidget(self.terminal, 1)

    def isOpen(self) -> bool:
        """Return True while the shell channel is usable."""
        return self._channel is not None and not self._channel.closed

    def showStatus(self, message: str) -> None:
        """Show a message above the terminal."""
        self.statusLabel.setText(message)
        self.statusLabel.setVisible(True)

    def start(self) -> None:
        """Open the shell in the background."""
        self.showStatus("Connecting...")
        cols, rows = self.terminal.session.size()
        opener = ShellOpener(self.host, self._pool, cols, rows)
        opener.signals.opened.connect(self._onOpened)
        opener.signals.failed.connect(self.showStatus)
        opener.signals.authRequired.connect(self.authRequired)
        self._opener = opener
        self._threadPool.start(opener)

    def _onOpened(self, channel: paramiko.Channel) -> None:
        if self._shutDown:
            channel.close()
            return
        self._channel = channel
        self.statusLabel.setVisible(False)
        reader = TerminalReader(channel)
        reader.dataReceived.connect(self.terminal.feed)
        reader.closed.connect(self._onClosed)
        self._reader = reader
        reader.start()
        self._resizePty(*self.terminal.gridSize())
        self.terminal.setFocus()

    def _onClosed(self) -> None:
        self.showStatus("Connection closed")
        self.titleChanged.emit(f"{self.host.name} (closed)")

    def _send(self, data: bytes) -> None:
        if self.isOpen() and self._channel is not None:
            try:
                self._channel.sendall(data)
            except (OSError, paramiko.SSHException):
                self._onClosed()

    def _resizePty(self, cols: int, rows: int) -> None:
        if self.isOpen() and self._channel is not None:
            try:
                self._channel.resize_pty(width=cols, height=rows)
            except (OSError, paramiko.SSHException):
                pass

    def shutdown(self) -> None:
        """Close the channel and wait for the reader to finish.

        The reader's signals are disconnected first so nothing queued on the
        GUI thread lands on this widget after it has been deleted.
        """
        self._shutDown = True
        if self._reader is not None:
            self._reader.dataReceived.disconnect(self.terminal.feed)
            self._reader.closed.disconnect(self._onClosed)
            self._reader.stop()
            self._reader.wait(READER_STOP_TIMEOUT_MS)
            self._reader = None
        if self._channel is not None:
            self._channel.close()
            self._channel = None
