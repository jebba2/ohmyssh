"""Background work that must stay off the GUI thread: probes, shells, reads."""

from __future__ import annotations

import paramiko
from PySide6.QtCore import QObject, QRunnable, QThread, Signal

from pyommyssh.core.connections import ConnectionPool
from pyommyssh.core.hosts import Host
from pyommyssh.core.metrics import buildProbeScript, metricsFromProbeOutput
from pyommyssh.core.ssh import SshAuthError, SshError

READ_CHUNK_BYTES = 4096


class TunnelSignals(QObject):
    """Carries tunnel status changes from tunnel threads onto the GUI thread."""

    statusChanged = Signal(str, object)


class MetricsSignals(QObject):
    """Outcomes of one metrics probe, delivered on the GUI thread."""

    metricsReady = Signal(str, object)
    metricsFailed = Signal(str, str)
    authRequired = Signal(str)


class MetricsWorker(QRunnable):
    """Connects to a host, runs the probe script, and parses the result."""

    def __init__(self, host: Host, pool: ConnectionPool) -> None:
        super().__init__()
        self.host = host
        self._pool = pool
        self.signals = MetricsSignals()

    def run(self) -> None:
        try:
            client = self._pool.connection(self.host)
            output = client.runCommand(buildProbeScript())
        except SshAuthError:
            self.signals.authRequired.emit(self.host.name)
            return
        except SshError as error:
            self.signals.metricsFailed.emit(self.host.name, str(error))
            return
        self.signals.metricsReady.emit(self.host.name, metricsFromProbeOutput(output))


class ShellSignals(QObject):
    """Outcomes of opening an interactive shell."""

    opened = Signal(object)
    failed = Signal(str)
    authRequired = Signal()


class ShellOpener(QRunnable):
    """Connects to a host and opens a PTY shell channel."""

    def __init__(self, host: Host, pool: ConnectionPool, cols: int, rows: int) -> None:
        super().__init__()
        self.host = host
        self._pool = pool
        self._cols = cols
        self._rows = rows
        self.signals = ShellSignals()

    def run(self) -> None:
        try:
            client = self._pool.connection(self.host)
            channel = client.openShell(self._cols, self._rows)
        except SshAuthError:
            self.signals.authRequired.emit()
            return
        except SshError as error:
            self.signals.failed.emit(str(error))
            return
        self.signals.opened.emit(channel)


class TerminalReader(QThread):
    """Pumps bytes from a shell channel to the GUI until the channel ends."""

    dataReceived = Signal(bytes)
    closed = Signal()

    def __init__(self, channel: paramiko.Channel) -> None:
        super().__init__()
        self._channel = channel

    def run(self) -> None:
        try:
            while True:
                data = self._channel.recv(READ_CHUNK_BYTES)
                if not data:
                    break
                self.dataReceived.emit(data)
        except (OSError, EOFError):
            pass
        self.closed.emit()

    def stop(self) -> None:
        """Close the channel, which ends the read loop."""
        self._channel.close()
