"""A pool of one live SSH connection per host, shared by metrics and terminals.

Credentials are held in memory only, for the lifetime of the process.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from pyommyssh.core.hosts import Host, resolveJumpChain
from pyommyssh.core.ssh import SshClient, SshCredentials, SshError


class ConnectionPool:
    """Opens connections on demand and reuses them while they stay up."""

    def __init__(self, hostsProvider: Callable[[], list[Host]], knownHostsPath: Path | None) -> None:
        self._hostsProvider = hostsProvider
        self._knownHostsPath = knownHostsPath
        self._clients: dict[str, SshClient] = {}
        self._credentials: dict[str, SshCredentials] = {}
        self._hostLocks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()

    def setCredentials(self, name: str, credentials: SshCredentials) -> None:
        """Remember a password or passphrase for a host until the app exits."""
        with self._lock:
            self._credentials[name] = credentials

    def hasCredentials(self, name: str) -> bool:
        """Return True if the user has already supplied secrets for a host."""
        with self._lock:
            return name in self._credentials

    def _lockFor(self, name: str) -> threading.Lock:
        with self._lock:
            return self._hostLocks.setdefault(name, threading.Lock())

    def connection(self, host: Host) -> SshClient:
        """Return a connected client for ``host``, connecting if needed."""
        with self._lockFor(host.name):
            existing = self._clients.get(host.name)
            if existing is not None and existing.isConnected():
                return existing
            try:
                jumps = resolveJumpChain(host, self._hostsProvider())
            except ValueError as error:
                raise SshError(str(error)) from error
            client = SshClient(
                host,
                credentials=self._credentials.get(host.name),
                jumpHosts=jumps,
                knownHostsPath=self._knownHostsPath,
            )
            client.connect()
            self._clients[host.name] = client
            return client

    def forget(self, name: str) -> None:
        """Close and drop the connection for one host."""
        with self._lockFor(name):
            client = self._clients.pop(name, None)
            if client is not None:
                client.close()

    def closeAll(self) -> None:
        """Close every connection; used at shutdown."""
        with self._lock:
            clients = list(self._clients.values())
            self._clients = {}
        for client in clients:
            client.close()
