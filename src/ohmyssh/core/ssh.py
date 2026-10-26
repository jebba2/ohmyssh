"""SSH connections built on paramiko, including ProxyJump chains.

One ``SshClient`` owns one connection to one host. Jump hosts are opened
first and each hop is tunneled through a direct-tcpip channel on the hop
before it, which is how ``ssh -J`` behaves.
"""

from __future__ import annotations

import logging
import os
import select
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import paramiko

from ohmyssh.core.hosts import GlobalSettings, Host, effectiveSettings

logger = logging.getLogger(__name__)

# How often a dial in progress checks whether close() was called.
CONNECT_POLL_SECONDS = 0.25


def _describeFailure(error: Exception) -> str:
    """Text for a paramiko or socket failure; paramiko's bare EOFError carries no message of its own."""
    return str(error) or "connection closed"


def _closeQuietly(stream: socket.socket | paramiko.Channel) -> None:
    """Shut down and close a socket or channel from any thread, waking a reader blocked on it."""
    try:
        stream.shutdown(socket.SHUT_RDWR)
    except (OSError, EOFError, paramiko.SSHException):
        pass
    try:
        stream.close()
    except (OSError, EOFError, paramiko.SSHException):
        pass

DEFAULT_TERM = "xterm-256color"

Address = tuple[str, int]
# Called with the channel, the connecting peer, and the server-side address it reached.
ForwardedConnectionHandler = Callable[[paramiko.Channel, Address, Address], None]


class SshError(Exception):
    """A connection or command failed."""


class SshAuthError(SshError):
    """The server rejected every authentication method we had."""


@dataclass(frozen=True)
class SshCredentials:
    """Secrets supplied by the user for one connection attempt."""

    password: str | None = None
    passphrase: str | None = None


# Tried in turn when loading a key file, as paramiko's own client does.
_KEY_CLASSES: tuple[type[paramiko.PKey], ...] = (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey)


def passphraseUnlocks(identityFile: Path, passphrase: str) -> bool:
    """True only if ``identityFile`` is an encrypted key that ``passphrase`` decrypts.

    An unencrypted key, a wrong passphrase, or an unreadable file all give False.
    """
    encrypted = False
    for keyClass in _KEY_CLASSES:
        try:
            keyClass.from_private_key_file(str(identityFile))
            return False
        except paramiko.PasswordRequiredException:
            encrypted = True
        except (paramiko.SSHException, OSError, ValueError):
            continue
    if not encrypted:
        return False
    for keyClass in _KEY_CLASSES:
        try:
            keyClass.from_private_key_file(str(identityFile), password=passphrase)
            return True
        except (paramiko.SSHException, OSError, ValueError):
            continue
    return False


def _loadKnownHosts(client: paramiko.SSHClient, path: Path | None) -> None:
    """Load known_hosts for verification without ever writing back to it."""
    if path is not None and path.is_file():
        client.load_system_host_keys(str(path))


class SshClient:
    """A connection to one host, optionally routed through jump hosts."""

    def __init__(
        self,
        host: Host,
        credentials: SshCredentials | None = None,
        jumpHosts: list[Host] | None = None,
        knownHostsPath: Path | None = None,
        globalSettings: GlobalSettings | None = None,
    ) -> None:
        self.host = host
        self._credentials = credentials or SshCredentials()
        self._jumpHosts = list(jumpHosts or [])
        self._knownHostsPath = knownHostsPath
        self._globalSettings = globalSettings or GlobalSettings()
        self._settings = effectiveSettings(host, self._globalSettings)
        self._client: paramiko.SSHClient | None = None
        self._jumpClients: list[SshClient] = []
        # Set by close(); a connect in progress on another thread stops at its next check.
        self._closing = threading.Event()
        # The socket (or jump channel) being dialed or handshaken, so close() can cut it off.
        self._pendingSocket: socket.socket | paramiko.Channel | None = None

    def isConnected(self) -> bool:
        """Return True while the transport is up."""
        if self._client is None:
            return False
        transport = self._client.get_transport()
        return transport is not None and transport.is_active()

    def keepaliveSeconds(self) -> int | None:
        """The keepalive interval this connection uses, or None when off."""
        return self._settings.keepaliveSeconds

    def compressionInUse(self) -> bool:
        """True when the open connection negotiated compression."""
        if self._client is None:
            return False
        transport = self._client.get_transport()
        if transport is None:
            return False
        return getattr(transport, "local_compression", "none") not in (None, "none")

    def connect(self, timeout: float = 10.0) -> None:
        """Open the connection, walking the jump chain first.

        ``close`` from another thread cuts the attempt short within a fraction
        of a second instead of letting it run out its timeout.
        """
        if self._closing.is_set():
            raise SshError(self._closedMessage())
        sock: paramiko.Channel | None = None
        try:
            hops = self._jumpHosts + [self.host]
            for index, hop in enumerate(self._jumpHosts):
                jumpClient = SshClient(
                    hop, self._credentials, knownHostsPath=self._knownHostsPath, globalSettings=self._globalSettings
                )
                # Registered before dialing so close() reaches a hop still being opened.
                self._jumpClients.append(jumpClient)
                jumpClient._openTransport(sock, timeout)
                nextHop = hops[index + 1]
                sock = jumpClient._openTunnel(nextHop, timeout)
            self._openTransport(sock, timeout)
        except SshError:
            self.close()
            raise

    def _openTunnel(self, destination: Host, timeout: float) -> paramiko.Channel:
        """Open a direct-tcpip channel from this hop to the next one."""
        return self.openDirectTcpip((destination.hostname, destination.port), ("127.0.0.1", 0), timeout)

    def _requireTransport(self) -> paramiko.Transport:
        transport = self._requireClient().get_transport()
        if transport is None:
            raise SshError(f"No transport to {self.host.name}")
        return transport

    def openDirectTcpip(
        self, destination: Address, origin: Address, timeout: float = 10.0
    ) -> paramiko.Channel:
        """Ask the server to connect to ``destination`` and return the channel carrying it.

        ``origin`` is reported to the server as where the connection came
        from, as ``ssh -L`` does.
        """
        transport = self._requireTransport()
        try:
            return transport.open_channel("direct-tcpip", destination, origin, timeout=timeout)
        except paramiko.SSHException as error:
            raise SshError(
                f"{self.host.name} could not reach {destination[0]}:{destination[1]}: {error}"
            ) from error

    def requestRemoteForward(self, address: str, port: int, handler: ForwardedConnectionHandler) -> None:
        """Make the server listen on ``address:port`` and hand each connection to ``handler``.

        The handler runs on paramiko's transport thread, so it must return
        quickly and move any blocking work elsewhere.
        """
        transport = self._requireTransport()
        try:
            transport.request_port_forward(address, port, handler)
        except paramiko.SSHException as error:
            raise SshError(f"{self.host.name} refused to listen on {address}:{port}: {error}") from error

    def cancelRemoteForward(self, address: str, port: int) -> None:
        """Stop a remote forward. Nothing happens if the connection is already gone."""
        if not self.isConnected() or self._client is None:
            return
        transport = self._client.get_transport()
        if transport is None:
            return
        try:
            transport.cancel_port_forward(address, port)
        except (paramiko.SSHException, OSError, EOFError):
            logger.debug("Could not cancel remote forward %s:%s on %s", address, port, self.host.name)

    def _closedMessage(self) -> str:
        return f"Closed while connecting to {self.host.displayAddress()}"

    def _openSocket(self, timeout: float) -> socket.socket:
        """Dial the host ourselves so close() can cut the dial short and the socket is closed on any failure."""
        try:
            candidates = socket.getaddrinfo(self.host.hostname, self.host.port, type=socket.SOCK_STREAM)
        except OSError as error:
            raise SshError(f"Could not reach {self.host.displayAddress()}: {error}") from error
        deadline = time.monotonic() + timeout
        failure: OSError | None = None
        for family, kind, proto, _, sockaddr in candidates:
            sock = socket.socket(family, kind, proto)
            self._pendingSocket = sock
            try:
                self._dial(sock, sockaddr, deadline)
            except OSError as error:
                failure = error
                sock.close()
                continue
            sock.settimeout(timeout)
            return sock
        if self._closing.is_set():
            raise SshError(self._closedMessage())
        raise SshError(f"Could not reach {self.host.displayAddress()}: {failure}") from failure

    def _dial(self, sock: socket.socket, sockaddr: tuple[Any, ...], deadline: float) -> None:
        """Connect without blocking past close(): a non-blocking connect watched in short slices."""
        sock.setblocking(False)
        try:
            sock.connect(sockaddr)
        except BlockingIOError:
            pass
        while True:
            if self._closing.is_set():
                raise OSError("closed while connecting")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("timed out")
            try:
                _, writable, failed = select.select([], [sock], [sock], min(CONNECT_POLL_SECONDS, remaining))
            except (OSError, ValueError) as error:
                # The socket was closed under us.
                raise OSError("closed while connecting") from error
            if writable or failed:
                # A socket shut down by close() can report ready with no error; the flag settles it.
                if self._closing.is_set():
                    raise OSError("closed while connecting")
                code = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if code:
                    raise OSError(code, os.strerror(code))
                sock.setblocking(True)
                return

    def _translateError(self, error: Exception) -> SshError:
        """Map a paramiko or socket failure onto our exception types."""
        address = self.host.displayAddress()
        if isinstance(error, paramiko.BadHostKeyException):
            return SshError(f"The host key for {address} does not match known_hosts")
        if isinstance(error, paramiko.AuthenticationException):
            return SshAuthError(f"Authentication failed for {address}")
        if isinstance(error, paramiko.SSHException) and "authentication" in str(error).lower():
            return SshAuthError(str(error))
        if isinstance(error, OSError):
            return SshError(f"Could not reach {address}: {error}")
        return SshError(f"SSH error for {address}: {_describeFailure(error)}")

    def _openTransport(self, sock: paramiko.Channel | None, timeout: float) -> None:
        client = paramiko.SSHClient()
        _loadKnownHosts(client, self._knownHostsPath)
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        identity = self._settings.identityFile
        keyFilename = str(identity) if identity is not None and identity.is_file() else None
        logger.info("Connecting to %s (%s)", self.host.name, self.host.displayAddress())
        connection: socket.socket | paramiko.Channel = sock if sock is not None else self._openSocket(timeout)
        self._pendingSocket = connection
        try:
            client.connect(
                hostname=self.host.hostname,
                port=self.host.port,
                username=self.host.user,
                password=self._credentials.password,
                passphrase=self._credentials.passphrase,
                key_filename=keyFilename,
                sock=connection,
                timeout=timeout,
                auth_timeout=timeout,
                banner_timeout=timeout,
                compress=self._settings.compression,
            )
        except (paramiko.SSHException, OSError, EOFError) as error:
            # paramiko raises a bare EOFError when the socket dies during the handshake.
            client.close()
            connection.close()
            self._pendingSocket = None
            if self._closing.is_set():
                raise SshError(self._closedMessage()) from error
            raise self._translateError(error) from error
        transport = client.get_transport()
        if transport is not None and self._settings.keepaliveSeconds:
            transport.set_keepalive(self._settings.keepaliveSeconds)
        self._client = client
        self._pendingSocket = None
        if self._closing.is_set():
            # close() ran while the handshake finished; it may have missed the client.
            client.close()
            raise SshError(self._closedMessage())

    def _requireClient(self) -> paramiko.SSHClient:
        if self._client is None or not self.isConnected():
            raise SshError(f"{self.host.name} is not connected")
        return self._client

    def runCommand(self, command: str, timeout: float = 30.0) -> str:
        """Run a command and return its stdout as text."""
        client = self._requireClient()
        try:
            _, stdout, _ = client.exec_command(command, timeout=timeout)
            return stdout.read().decode("utf-8", errors="replace")
        except (paramiko.SSHException, OSError, EOFError) as error:
            raise SshError(f"Command failed on {self.host.name}: {_describeFailure(error)}") from error

    def openSftp(self) -> paramiko.SFTPClient:
        """Open an SFTP channel on this connection."""
        client = self._requireClient()
        try:
            return client.open_sftp()
        except (paramiko.SSHException, OSError, EOFError) as error:
            raise SshError(f"Could not open SFTP on {self.host.name}: {_describeFailure(error)}") from error

    def openShell(self, cols: int, rows: int, term: str = DEFAULT_TERM) -> paramiko.Channel:
        """Open an interactive shell with a PTY of the given size."""
        client = self._requireClient()
        try:
            return client.invoke_shell(term=term, width=cols, height=rows)
        except (paramiko.SSHException, OSError, EOFError) as error:
            raise SshError(f"Could not open a shell on {self.host.name}: {_describeFailure(error)}") from error

    def close(self) -> None:
        """Close this connection and every jump hop, cutting short a connect in progress. Safe to call repeatedly."""
        self._closing.set()
        pending = self._pendingSocket
        if pending is not None:
            _closeQuietly(pending)
        if self._client is not None:
            self._client.close()
            self._client = None
        for jumpClient in reversed(self._jumpClients):
            jumpClient.close()
        self._jumpClients = []
