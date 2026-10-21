"""Background work that must stay off the GUI thread: probes, shells, reads."""

from __future__ import annotations

from pathlib import Path

import paramiko
from PySide6.QtCore import QObject, QRunnable, QThread, Signal

from pyommyssh.core.connections import ConnectionPool
from pyommyssh.core.hosts import Host
from pyommyssh.core.keys import KeyGenerateRequest, KeyInstallError, generateKeyPair, installPublicKey
from pyommyssh.core.metrics import buildProbeScript, metricsFromProbeOutput
from pyommyssh.core.sftp import listLocalDir
from pyommyssh.core.ssh import SshAuthError, SshError

READ_CHUNK_BYTES = 4096


class LocalListSignals(QObject):
    """Outcome of listing a local folder, delivered on the GUI thread."""

    listed = Signal(str, object)
    failed = Signal(str, str)


class LocalListWorker(QRunnable):
    """Lists a local folder off the GUI thread; slow drives must not freeze the window."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self._path = path
        self.signals = LocalListSignals()

    def run(self) -> None:
        try:
            entries = listLocalDir(Path(self._path))
        except OSError as error:
            self.signals.failed.emit(self._path, f"Could not list {self._path}: {error}")
            return
        self.signals.listed.emit(self._path, entries)


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


class KeyInstallSignals(QObject):
    """Outcomes of installing a public key, delivered on the GUI thread."""

    installed = Signal(str, bool)
    failed = Signal(str, str)
    authRequired = Signal(str)


class KeyInstallWorker(QRunnable):
    """Connects to a host and appends a public key to its authorized_keys."""

    def __init__(self, host: Host, pool: ConnectionPool, publicKey: str) -> None:
        super().__init__()
        self.host = host
        self._pool = pool
        self._publicKey = publicKey
        self.signals = KeyInstallSignals()

    def run(self) -> None:
        try:
            client = self._pool.connection(self.host)
            newlyAdded = installPublicKey(client, self._publicKey)
        except SshAuthError:
            self.signals.authRequired.emit(self.host.name)
            return
        except (SshError, KeyInstallError) as error:
            self.signals.failed.emit(self.host.name, str(error))
            return
        self.signals.installed.emit(self.host.name, newlyAdded)


class KeyGenerateSignals(QObject):
    """Outcome of generating a key pair, delivered on the GUI thread."""

    generated = Signal(object, object)
    failed = Signal(str)


class KeyGenerateWorker(QRunnable):
    """Writes a new key pair; RSA generation takes long enough to keep off the GUI thread."""

    def __init__(self, request: KeyGenerateRequest) -> None:
        super().__init__()
        self._request = request
        self.signals = KeyGenerateSignals()

    def run(self) -> None:
        request = self._request
        try:
            publicPath = generateKeyPair(request.privatePath, request.keyType, request.comment, request.passphrase)
        except (OSError, ValueError) as error:
            self.signals.failed.emit(str(error))
            return
        self.signals.generated.emit(request.privatePath, publicPath)


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
