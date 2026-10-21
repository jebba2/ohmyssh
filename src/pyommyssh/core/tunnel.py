"""Port forwarding tunnels: one per host, carrying every forward the host defines.

A ``Tunnel`` rides the host's shared pool connection. Local and dynamic
forwards bind their ports here before the first dial and hold them until
the tunnel stops, so a dropped connection never hands a port to another
process. Remote forwards are requested from the server on every connect.
When the connection drops the tunnel reconnects with a backoff while
incoming connections wait in the listen backlog.

Status changes are reported through a callback, from tunnel threads.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

import paramiko

from pyommyssh.core.connections import ConnectionPool
from pyommyssh.core.forwards import ForwardKind, PortForward
from pyommyssh.core.hosts import Host
from pyommyssh.core.socks import SocksError, SocksRequest, readSocksRequest, sendSocksReply
from pyommyssh.core.ssh import Address, SshAuthError, SshClient, SshError

logger = logging.getLogger(__name__)

# Seconds to wait before each reconnect attempt; the last value repeats.
RETRY_DELAYS: tuple[float, ...] = (1, 2, 5, 10, 30)
# A connection that lasted this long resets the backoff.
STABLE_AFTER_SECONDS = 60.0
# How often a live tunnel checks that its connection still is.
LIVENESS_INTERVAL_SECONDS = 1.0
# How long accept loops wait between checks for a stop request.
ACCEPT_POLL_SECONDS = 0.5
SOCKS_HANDSHAKE_TIMEOUT_SECONDS = 10.0
CONNECT_TIMEOUT_SECONDS = 10.0
LISTEN_BACKLOG = 16
PUMP_CHUNK_BYTES = 32768
THREAD_JOIN_SECONDS = 5.0


class TunnelState(Enum):
    """Where a host's tunnel stands."""

    CONNECTING = "connecting"
    UP = "up"
    RETRYING = "retrying"
    AUTH_REQUIRED = "auth_required"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(frozen=True)
class TunnelStatus:
    """A state plus the reason behind it, for retrying and failed tunnels."""

    state: TunnelState
    message: str = ""

    def isActive(self) -> bool:
        """True while the tunnel is holding its ports and will keep trying."""
        return self.state in (TunnelState.CONNECTING, TunnelState.UP, TunnelState.RETRYING)


StatusCallback = Callable[[str, TunnelStatus], None]


class _Stream(Protocol):
    """What sockets and paramiko channels have in common for byte pumping."""

    def recv(self, size: int, /) -> bytes: ...

    def sendall(self, data: bytes, /) -> None: ...

    def shutdown(self, how: int, /) -> None: ...

    def close(self) -> None: ...


def _closeQuietly(stream: _Stream) -> None:
    try:
        stream.close()
    except (OSError, EOFError):
        pass


def _remoteBindAddress(forward: PortForward) -> str:
    """The address the server listens on: loopback by default, "" for every interface."""
    if forward.bindAddress in (None, "", "localhost"):
        return "localhost"
    if forward.bindAddress == "*":
        return ""
    return forward.bindAddress or ""


class Tunnel:
    """Runs every forward of one host until stopped or until it cannot go on."""

    def __init__(
        self,
        host: Host,
        pool: ConnectionPool,
        onStatus: StatusCallback,
        retryDelays: Sequence[float] = RETRY_DELAYS,
        previous: Tunnel | None = None,
    ) -> None:
        self.host = host
        self._pool = pool
        self._onStatus = onStatus
        self._retryDelays = tuple(retryDelays)
        self._previous = previous
        self._stopping = threading.Event()
        self._up = threading.Event()
        self._client: SshClient | None = None
        self._listeners: list[tuple[socket.socket, PortForward]] = []
        self._acceptThreads: list[threading.Thread] = []
        self._streams: set[_Stream] = set()
        self._streamsLock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name=f"tunnel-{host.name}", daemon=True)

    def start(self) -> None:
        """Begin serving in a background thread."""
        self._thread.start()

    def stop(self) -> None:
        """Ask the tunnel to end. It reports STOPPED once its ports are released."""
        self._stopping.set()

    def stopRequested(self) -> bool:
        """True once ``stop`` has been called."""
        return self._stopping.is_set()

    def join(self, timeout: float | None = None) -> None:
        """Wait for the tunnel thread to finish."""
        if self._thread.is_alive():
            self._thread.join(timeout)

    def isFinished(self) -> bool:
        """True once the thread has ended and the ports are free."""
        return self._thread.ident is not None and not self._thread.is_alive()

    # Supervisor

    def _report(self, state: TunnelState, message: str = "") -> None:
        self._onStatus(self.host.name, TunnelStatus(state, message))

    def _run(self) -> None:
        # A restart must not race its predecessor for the ports.
        if self._previous is not None:
            self._previous.join()
            self._previous = None
        status = TunnelStatus(TunnelState.STOPPED)
        try:
            status = self._serve()
        finally:
            self._cleanup()
            self._onStatus(self.host.name, status)

    def _serve(self) -> TunnelStatus:
        """Hold the ports and keep the connection up. Returns the final status."""
        if not self.host.forwards:
            return TunnelStatus(TunnelState.FAILED, f"No port forwards are set up for {self.host.name}")
        try:
            self._bindListeners()
        except OSError as error:
            return TunnelStatus(TunnelState.FAILED, str(error))
        self._report(TunnelState.CONNECTING)

        retryIndex = 0
        while not self._stopping.is_set():
            client: SshClient | None = None
            try:
                client = self._pool.connection(self.host)
                self._requestRemoteForwards(client)
            except SshAuthError as error:
                return TunnelStatus(TunnelState.AUTH_REQUIRED, str(error))
            except SshError as error:
                reason = str(error)
                if client is not None and client.isConnected():
                    # The server itself refused a forward; redialling will not help.
                    self._cancelRemoteForwards(client)
                    return TunnelStatus(TunnelState.FAILED, reason)
            else:
                connectedAt = time.monotonic()
                self._goUp(client)
                while not self._stopping.wait(LIVENESS_INTERVAL_SECONDS):
                    if not client.isConnected():
                        break
                self._goDown(client)
                if self._stopping.is_set():
                    break
                if time.monotonic() - connectedAt >= STABLE_AFTER_SECONDS:
                    retryIndex = 0
                reason = "connection lost"
            logger.info("Tunnel to %s is down: %s", self.host.name, reason)
            self._report(TunnelState.RETRYING, reason)
            if self._stopping.wait(self._retryDelays[retryIndex]):
                break
            retryIndex = min(retryIndex + 1, len(self._retryDelays) - 1)
        return TunnelStatus(TunnelState.STOPPED)

    def _goUp(self, client: SshClient) -> None:
        self._client = client
        self._up.set()
        self._report(TunnelState.UP)

    def _goDown(self, client: SshClient) -> None:
        self._up.clear()
        self._client = None
        self._cancelRemoteForwards(client)

    def _cleanup(self) -> None:
        """Release the ports and cut every connection the tunnel carried."""
        self._up.clear()
        client = self._client
        self._client = None
        if client is not None:
            self._cancelRemoteForwards(client)
        for listener, _ in self._listeners:
            _closeQuietly(listener)
        for thread in self._acceptThreads:
            thread.join(THREAD_JOIN_SECONDS)
        self._listeners = []
        self._acceptThreads = []
        with self._streamsLock:
            streams = list(self._streams)
            self._streams = set()
        for stream in streams:
            _closeQuietly(stream)

    # Local listeners

    def _bindListeners(self) -> None:
        """Bind every local and dynamic forward, or none of them."""
        try:
            for forward in self.host.forwards:
                if forward.kind == ForwardKind.REMOTE:
                    continue
                address = (forward.listenAddress(), forward.bindPort)
                listener = socket.socket(socket.AF_INET6 if ":" in address[0] else socket.AF_INET)
                try:
                    listener.bind(address)
                    listener.listen(LISTEN_BACKLOG)
                except OSError as error:
                    listener.close()
                    raise OSError(f"Could not listen on {address[0]}:{address[1]}: {error.strerror or error}") from error
                listener.settimeout(ACCEPT_POLL_SECONDS)
                self._listeners.append((listener, forward))
        except OSError:
            for listener, _ in self._listeners:
                _closeQuietly(listener)
            self._listeners = []
            raise
        for listener, forward in self._listeners:
            thread = threading.Thread(target=self._acceptLoop, args=(listener, forward), daemon=True)
            self._acceptThreads.append(thread)
            thread.start()

    def _acceptLoop(self, listener: socket.socket, forward: PortForward) -> None:
        """Accept connections while the tunnel is up; the backlog holds them while it is down."""
        while not self._stopping.is_set():
            if not self._up.wait(ACCEPT_POLL_SECONDS):
                continue
            try:
                connection, peer = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            peerAddress: Address = (str(peer[0]), int(peer[1]))
            if forward.kind == ForwardKind.DYNAMIC:
                target = self._serveSocksConnection
            else:
                target = self._serveLocalConnection
            threading.Thread(target=target, args=(connection, peerAddress, forward), daemon=True).start()

    def _openChannel(self, destination: Address, origin: Address) -> paramiko.Channel:
        client = self._client
        if client is None:
            raise SshError(f"{self.host.name} is not connected")
        return client.openDirectTcpip(destination, origin, CONNECT_TIMEOUT_SECONDS)

    def _serveLocalConnection(self, connection: socket.socket, peer: Address, forward: PortForward) -> None:
        destination: Address = (forward.remoteHost or "", forward.remotePort or 0)
        try:
            channel = self._openChannel(destination, peer)
        except SshError as error:
            logger.warning("Local forward %s on %s: %s", forward.spec(), self.host.name, error)
            _closeQuietly(connection)
            return
        self._pipe(connection, channel)

    def _serveSocksConnection(self, connection: socket.socket, peer: Address, forward: PortForward) -> None:
        connection.settimeout(SOCKS_HANDSHAKE_TIMEOUT_SECONDS)
        try:
            request = readSocksRequest(connection)
        except (SocksError, OSError) as error:
            logger.debug("SOCKS client on %s rejected: %s", forward.spec(), error)
            _closeQuietly(connection)
            return
        try:
            channel = self._openChannel((request.host, request.port), peer)
        except SshError as error:
            logger.warning("SOCKS connect to %s:%s via %s: %s", request.host, request.port, self.host.name, error)
            self._sendSocksReplyQuietly(connection, request, granted=False)
            _closeQuietly(connection)
            return
        try:
            sendSocksReply(connection, request, granted=True)
        except OSError:
            _closeQuietly(connection)
            _closeQuietly(channel)
            return
        connection.settimeout(None)
        self._pipe(connection, channel)

    @staticmethod
    def _sendSocksReplyQuietly(connection: socket.socket, request: SocksRequest, granted: bool) -> None:
        try:
            sendSocksReply(connection, request, granted)
        except OSError:
            pass

    # Remote forwards

    def _requestRemoteForwards(self, client: SshClient) -> None:
        for forward in self.host.forwards:
            if forward.kind != ForwardKind.REMOTE:
                continue

            def handler(channel: paramiko.Channel, origin: Address, server: Address, forward: PortForward = forward) -> None:
                # Runs on paramiko's transport thread; connect elsewhere.
                threading.Thread(
                    target=self._serveRemoteConnection, args=(channel, forward), daemon=True
                ).start()

            client.requestRemoteForward(_remoteBindAddress(forward), forward.bindPort, handler)

    def _cancelRemoteForwards(self, client: SshClient) -> None:
        for forward in self.host.forwards:
            if forward.kind == ForwardKind.REMOTE:
                client.cancelRemoteForward(_remoteBindAddress(forward), forward.bindPort)

    def _serveRemoteConnection(self, channel: paramiko.Channel, forward: PortForward) -> None:
        destination = (forward.remoteHost or "", forward.remotePort or 0)
        try:
            connection = socket.create_connection(destination, timeout=CONNECT_TIMEOUT_SECONDS)
        except OSError as error:
            logger.warning("Remote forward %s on %s: %s", forward.spec(), self.host.name, error)
            _closeQuietly(channel)
            return
        connection.settimeout(None)
        self._pipe(channel, connection)

    # Byte pumping

    def _pipe(self, first: _Stream, second: _Stream) -> None:
        """Copy bytes both ways until either side closes, then close both."""
        with self._streamsLock:
            self._streams.update((first, second))

        def pump(readFrom: _Stream, writeTo: _Stream) -> None:
            try:
                while True:
                    data = readFrom.recv(PUMP_CHUNK_BYTES)
                    if not data:
                        break
                    writeTo.sendall(data)
            except (OSError, EOFError, paramiko.SSHException):
                pass
            finally:
                try:
                    writeTo.shutdown(socket.SHUT_WR)
                except (OSError, EOFError):
                    pass

        pumps = [
            threading.Thread(target=pump, args=(first, second), daemon=True),
            threading.Thread(target=pump, args=(second, first), daemon=True),
        ]

        def closeWhenDone() -> None:
            for thread in pumps:
                thread.join()
            _closeQuietly(first)
            _closeQuietly(second)
            with self._streamsLock:
                self._streams.difference_update((first, second))

        for thread in pumps:
            thread.start()
        threading.Thread(target=closeWhenDone, daemon=True).start()


class TunnelManager:
    """Keeps one tunnel per host name and remembers each one's latest status."""

    def __init__(
        self, pool: ConnectionPool, onStatus: StatusCallback, retryDelays: Sequence[float] = RETRY_DELAYS
    ) -> None:
        self._pool = pool
        self._onStatus = onStatus
        self._retryDelays = tuple(retryDelays)
        self._tunnels: dict[str, Tunnel] = {}
        self._statuses: dict[str, TunnelStatus] = {}
        self._lock = threading.Lock()

    def start(self, host: Host) -> None:
        """Start the host's tunnel, replacing one that is already running."""
        with self._lock:
            previous = self._tunnels.get(host.name)
            if previous is not None:
                previous.stop()
            tunnel = Tunnel(host, self._pool, self._record, self._retryDelays, previous=previous)
            self._tunnels[host.name] = tunnel
        tunnel.start()

    def stop(self, name: str) -> None:
        """Stop the host's tunnel. Nothing happens when there is none."""
        with self._lock:
            tunnel = self._tunnels.get(name)
        if tunnel is not None:
            tunnel.stop()

    def isRunning(self, name: str) -> bool:
        """True while the host has a tunnel that has neither ended nor been told to stop."""
        with self._lock:
            tunnel = self._tunnels.get(name)
        return tunnel is not None and not tunnel.stopRequested() and not tunnel.isFinished()

    def status(self, name: str) -> TunnelStatus | None:
        """The latest status reported for the host, or None if it never had a tunnel."""
        with self._lock:
            return self._statuses.get(name)

    def shutdown(self) -> None:
        """Stop every tunnel and wait for their ports to be released."""
        with self._lock:
            tunnels = list(self._tunnels.values())
        for tunnel in tunnels:
            tunnel.stop()
        for tunnel in tunnels:
            tunnel.join(THREAD_JOIN_SECONDS)

    def _record(self, name: str, status: TunnelStatus) -> None:
        with self._lock:
            self._statuses[name] = status
        self._onStatus(name, status)
