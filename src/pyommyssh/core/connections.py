"""A pool of one live SSH connection per host, shared by metrics and terminals.

Credentials are held in memory only, for the lifetime of the process. A
passphrase that unlocked an identity file is also remembered for that file,
so other hosts using the same key do not ask again.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from pyommyssh.core.hosts import GlobalSettings, Host, resolveJumpChain
from pyommyssh.core.ssh import SshClient, SshCredentials, SshError, passphraseUnlocks


class ConnectionPool:
    """Opens connections on demand and reuses them while they stay up."""

    def __init__(
        self,
        hostsProvider: Callable[[], list[Host]],
        knownHostsPath: Path | None,
        globalSettingsProvider: Callable[[], GlobalSettings] | None = None,
    ) -> None:
        self._hostsProvider = hostsProvider
        self._knownHostsPath = knownHostsPath
        self._globalSettingsProvider = globalSettingsProvider or GlobalSettings
        self._clients: dict[str, SshClient] = {}
        self._credentials: dict[str, SshCredentials] = {}
        self._passphrasesByKey: dict[Path, str] = {}
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

    def knownPassphrases(self) -> dict[Path, str]:
        """Passphrases proven to unlock an identity file, keyed by its resolved path."""
        with self._lock:
            return dict(self._passphrasesByKey)

    def _credentialsFor(self, host: Host) -> SshCredentials | None:
        """The host's own secrets, or the passphrase known for its identity file."""
        with self._lock:
            credentials = self._credentials.get(host.name)
            if credentials is not None or host.identityFile is None:
                return credentials
            passphrase = self._passphrasesByKey.get(host.identityFile.resolve())
        return SshCredentials(passphrase=passphrase) if passphrase else None

    def _rememberPassphrase(self, host: Host, credentials: SshCredentials | None) -> None:
        """After a login, keep the passphrase if it really decrypts the host's key file."""
        if credentials is None or not credentials.passphrase or host.identityFile is None:
            return
        keyPath = host.identityFile.resolve()
        with self._lock:
            alreadyKnown = self._passphrasesByKey.get(keyPath) == credentials.passphrase
        if alreadyKnown or not passphraseUnlocks(keyPath, credentials.passphrase):
            return
        with self._lock:
            self._passphrasesByKey[keyPath] = credentials.passphrase

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
            credentials = self._credentialsFor(host)
            client = SshClient(
                host,
                credentials=credentials,
                jumpHosts=jumps,
                knownHostsPath=self._knownHostsPath,
                globalSettings=self._globalSettingsProvider(),
            )
            client.connect()
            self._clients[host.name] = client
            self._rememberPassphrase(host, credentials)
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
