"""End-to-end tests for port forwarding tunnels against the in-process SSH server."""

from __future__ import annotations

import socket
import struct
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from pyommyssh.core.connections import ConnectionPool
from pyommyssh.core.forwards import ForwardKind, PortForward
from pyommyssh.core.hosts import Host
from pyommyssh.core.ssh import SshCredentials
from pyommyssh.core.tunnel import Tunnel, TunnelManager, TunnelState, TunnelStatus
from tests.echoserver import EchoServer
from tests.sshserver import TEST_PASSWORD, TestSshServer, hostFor

WAIT_SECONDS = 15.0
FAST_RETRY = (0.1,)


def freePort() -> int:
    """Return a port nothing is listening on right now."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class StatusLog:
    """Collects status reports and lets tests wait for a particular state."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, TunnelStatus]] = []
        self._changed = threading.Condition()

    def record(self, name: str, status: TunnelStatus) -> None:
        with self._changed:
            self.entries.append((name, status))
            self._changed.notify_all()

    def states(self, name: str = "box") -> list[TunnelState]:
        with self._changed:
            return [status.state for entry, status in self.entries if entry == name]

    def waitFor(self, state: TunnelState, name: str = "box", after: int = 0) -> TunnelStatus:
        """Block until ``state`` is reported for ``name`` at an index >= ``after``."""
        deadline = time.monotonic() + WAIT_SECONDS
        with self._changed:
            while True:
                matches = [
                    status
                    for index, (entry, status) in enumerate(self.entries)
                    if entry == name and status.state == state and index >= after
                ]
                if matches:
                    return matches[0]
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AssertionError(f"{name} never reached {state}; saw {self.entries}")
                self._changed.wait(remaining)

    def count(self) -> int:
        with self._changed:
            return len(self.entries)


def waitUntil(predicate: Callable[[], bool], message: str) -> None:
    deadline = time.monotonic() + WAIT_SECONDS
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(message)
        time.sleep(0.05)


def echoThrough(address: tuple[str, int], payload: bytes = b"ping") -> bytes:
    with socket.create_connection(address, timeout=5) as connection:
        connection.sendall(payload)
        received = b""
        while len(received) < len(payload):
            chunk = connection.recv(1024)
            if not chunk:
                break
            received += chunk
        return received


def hostWith(server: TestSshServer, *specs: tuple[ForwardKind, str]) -> Host:
    host = hostFor(server)
    host.forwards = [PortForward.parse(kind, spec) for kind, spec in specs]
    return host


@pytest.fixture
def pool(tmp_path: Path) -> Iterator[ConnectionPool]:
    hosts: list[Host] = []
    pool = ConnectionPool(lambda: hosts, tmp_path / "known_hosts")
    pool.setCredentials("box", SshCredentials(password=TEST_PASSWORD))
    yield pool
    pool.closeAll()


@pytest.fixture
def log() -> StatusLog:
    return StatusLog()


@pytest.fixture
def tunnels(pool: ConnectionPool, log: StatusLog) -> Iterator[TunnelManager]:
    manager = TunnelManager(pool, log.record, retryDelays=FAST_RETRY)
    yield manager
    manager.shutdown()


def test_local_forward_carries_connections_to_the_far_service(
    sshServer: TestSshServer, echoServer: EchoServer, tunnels: TunnelManager, log: StatusLog
) -> None:
    port = freePort()
    host = hostWith(sshServer, (ForwardKind.LOCAL, f"{port}:127.0.0.1:{echoServer.port}"))
    tunnels.start(host)
    log.waitFor(TunnelState.UP)
    assert log.states() == [TunnelState.CONNECTING, TunnelState.UP]
    assert tunnels.isRunning("box")

    assert echoThrough(("127.0.0.1", port)) == b"ping"
    assert sshServer.directTcpipRequests[-1] == ("127.0.0.1", echoServer.port)

    tunnels.stop("box")
    log.waitFor(TunnelState.STOPPED)
    assert not tunnels.isRunning("box")
    # The local port is released once the tunnel has stopped.
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))


def test_dynamic_forward_serves_socks5_clients(
    sshServer: TestSshServer, echoServer: EchoServer, tunnels: TunnelManager, log: StatusLog
) -> None:
    port = freePort()
    tunnels.start(hostWith(sshServer, (ForwardKind.DYNAMIC, f"{port}")))
    log.waitFor(TunnelState.UP)

    with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
        client.sendall(b"\x05\x01\x00")
        assert client.recv(2) == b"\x05\x00"
        target = b"127.0.0.1"
        client.sendall(b"\x05\x01\x00\x03" + bytes([len(target)]) + target + struct.pack(">H", echoServer.port))
        assert client.recv(10) == b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00"
        client.sendall(b"through socks")
        assert client.recv(1024) == b"through socks"
    assert sshServer.directTcpipRequests[-1] == ("127.0.0.1", echoServer.port)


def test_dynamic_forward_reports_unreachable_destination_to_the_client(
    sshServer: TestSshServer, tunnels: TunnelManager, log: StatusLog
) -> None:
    sshServer.refuseDirectTcpip = True
    port = freePort()
    tunnels.start(hostWith(sshServer, (ForwardKind.DYNAMIC, f"{port}")))
    log.waitFor(TunnelState.UP)

    with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
        client.sendall(b"\x05\x01\x00")
        assert client.recv(2) == b"\x05\x00"
        client.sendall(b"\x05\x01\x00\x01" + socket.inet_aton("10.0.0.1") + struct.pack(">H", 80))
        assert client.recv(10) == b"\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00"
        assert client.recv(1) == b""


def test_remote_forward_carries_server_side_connections_back(
    sshServer: TestSshServer, echoServer: EchoServer, tunnels: TunnelManager, log: StatusLog
) -> None:
    serverPort = freePort()
    tunnels.start(hostWith(sshServer, (ForwardKind.REMOTE, f"{serverPort}:127.0.0.1:{echoServer.port}")))
    log.waitFor(TunnelState.UP)
    assert sshServer.remoteForwardRequests == [("localhost", serverPort)]

    assert echoThrough(("127.0.0.1", serverPort), b"backwards") == b"backwards"
    assert echoServer.connections == 1

    tunnels.stop("box")
    log.waitFor(TunnelState.STOPPED)
    waitUntil(lambda: ("localhost", serverPort) in sshServer.cancelledRemoteForwards, "forward not cancelled")


def test_remote_forward_refused_by_server_is_fatal(
    sshServer: TestSshServer, tunnels: TunnelManager, log: StatusLog
) -> None:
    sshServer.refuseRemoteForwards = True
    tunnels.start(hostWith(sshServer, (ForwardKind.REMOTE, "9999:127.0.0.1:80")))
    status = log.waitFor(TunnelState.FAILED)
    assert "refused to listen on localhost:9999" in status.message
    assert not tunnels.isRunning("box")


def test_tunnel_reconnects_after_the_connection_drops(
    sshServer: TestSshServer, echoServer: EchoServer, tunnels: TunnelManager, log: StatusLog
) -> None:
    port = freePort()
    tunnels.start(hostWith(sshServer, (ForwardKind.LOCAL, f"{port}:127.0.0.1:{echoServer.port}")))
    log.waitFor(TunnelState.UP)
    assert echoThrough(("127.0.0.1", port)) == b"ping"

    sshServer.dropConnections()
    retrying = log.waitFor(TunnelState.RETRYING)
    assert retrying.message == "connection lost"
    log.waitFor(TunnelState.UP, after=2)
    assert echoThrough(("127.0.0.1", port), b"again") == b"again"
    assert tunnels.status("box") == TunnelStatus(TunnelState.UP)


def test_unreachable_host_keeps_retrying_until_stopped(
    tunnels: TunnelManager, log: StatusLog
) -> None:
    host = Host(name="box", hostname="127.0.0.1", user="x", port=1)
    host.forwards = [PortForward.parse(ForwardKind.LOCAL, f"{freePort()}:127.0.0.1:80")]
    tunnels.start(host)
    status = log.waitFor(TunnelState.RETRYING)
    assert status.message.startswith("Could not reach")
    assert tunnels.isRunning("box")
    tunnels.stop("box")
    log.waitFor(TunnelState.STOPPED)
    assert TunnelState.UP not in log.states()


def test_port_already_in_use_is_fatal(
    sshServer: TestSshServer, tunnels: TunnelManager, log: StatusLog
) -> None:
    with socket.socket() as occupant:
        occupant.bind(("127.0.0.1", 0))
        occupant.listen(1)
        port = occupant.getsockname()[1]
        tunnels.start(hostWith(sshServer, (ForwardKind.LOCAL, f"{port}:127.0.0.1:80")))
        status = log.waitFor(TunnelState.FAILED)
    assert f"Could not listen on 127.0.0.1:{port}" in status.message
    assert log.states() == [TunnelState.FAILED]


def test_host_without_forwards_is_fatal(sshServer: TestSshServer, tunnels: TunnelManager, log: StatusLog) -> None:
    tunnels.start(hostFor(sshServer))
    status = log.waitFor(TunnelState.FAILED)
    assert status.message == "No port forwards are set up for box"


def test_missing_credentials_report_auth_required(
    sshServer: TestSshServer, tmp_path: Path, log: StatusLog
) -> None:
    pool = ConnectionPool(lambda: [], tmp_path / "known_hosts")
    manager = TunnelManager(pool, log.record, retryDelays=FAST_RETRY)
    try:
        manager.start(hostWith(sshServer, (ForwardKind.LOCAL, f"{freePort()}:127.0.0.1:80")))
        log.waitFor(TunnelState.AUTH_REQUIRED)
        assert not manager.isRunning("box")
    finally:
        manager.shutdown()
        pool.closeAll()


def test_starting_again_replaces_the_running_tunnel(
    sshServer: TestSshServer, echoServer: EchoServer, tunnels: TunnelManager, log: StatusLog
) -> None:
    port = freePort()
    first = hostWith(sshServer, (ForwardKind.LOCAL, f"{port}:127.0.0.1:{echoServer.port}"))
    tunnels.start(first)
    log.waitFor(TunnelState.UP)

    second = hostWith(sshServer, (ForwardKind.LOCAL, f"{port}:127.0.0.1:{echoServer.port}"))
    tunnels.start(second)
    log.waitFor(TunnelState.UP, after=3)
    # The old tunnel stopped before the new one started, so the same port could be bound.
    assert log.states() == [
        TunnelState.CONNECTING,
        TunnelState.UP,
        TunnelState.STOPPED,
        TunnelState.CONNECTING,
        TunnelState.UP,
    ]
    assert echoThrough(("127.0.0.1", port)) == b"ping"


def test_shutdown_stops_every_tunnel(
    sshServer: TestSshServer, jumpServer: TestSshServer, pool: ConnectionPool, log: StatusLog
) -> None:
    pool.setCredentials("other", SshCredentials(password=TEST_PASSWORD))
    manager = TunnelManager(pool, log.record, retryDelays=FAST_RETRY)
    manager.start(hostWith(sshServer, (ForwardKind.LOCAL, f"{freePort()}:127.0.0.1:80")))
    other = hostFor(jumpServer, name="other")
    other.forwards = [PortForward.parse(ForwardKind.LOCAL, f"{freePort()}:127.0.0.1:80")]
    manager.start(other)
    log.waitFor(TunnelState.UP, name="box")
    log.waitFor(TunnelState.UP, name="other")

    manager.shutdown()
    assert log.states("box")[-1] == TunnelState.STOPPED
    assert log.states("other")[-1] == TunnelState.STOPPED
    assert not manager.isRunning("box")
    assert manager.status("box") == TunnelStatus(TunnelState.STOPPED)


def test_stop_is_a_no_op_for_unknown_hosts(tunnels: TunnelManager) -> None:
    tunnels.stop("nobody")
    assert tunnels.status("nobody") is None
    assert not tunnels.isRunning("nobody")


def test_tunnel_status_activity() -> None:
    assert TunnelStatus(TunnelState.CONNECTING).isActive()
    assert TunnelStatus(TunnelState.UP).isActive()
    assert TunnelStatus(TunnelState.RETRYING, "lost").isActive()
    assert not TunnelStatus(TunnelState.FAILED, "x").isActive()
    assert not TunnelStatus(TunnelState.AUTH_REQUIRED).isActive()
    assert not TunnelStatus(TunnelState.STOPPED).isActive()


def test_tunnel_connections_are_closed_when_it_stops(
    sshServer: TestSshServer, echoServer: EchoServer, pool: ConnectionPool, log: StatusLog
) -> None:
    port = freePort()
    tunnel = Tunnel(
        hostWith(sshServer, (ForwardKind.LOCAL, f"{port}:127.0.0.1:{echoServer.port}")),
        pool,
        log.record,
        retryDelays=FAST_RETRY,
    )
    tunnel.start()
    log.waitFor(TunnelState.UP)
    with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
        client.sendall(b"hold")
        assert client.recv(4) == b"hold"
        tunnel.stop()
        tunnel.join(WAIT_SECONDS)
        # Windows reports the cut connection as a reset rather than a clean end of stream.
        try:
            assert client.recv(1024) == b""
        except ConnectionResetError:
            pass
    assert log.states()[-1] == TunnelState.STOPPED
