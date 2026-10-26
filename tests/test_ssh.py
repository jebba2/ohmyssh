"""Tests for the SSH client against a real in-process SSH server."""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import paramiko
import pytest

from ohmyssh.core.hosts import GlobalSettings, Host
from ohmyssh.core.keys import KeyType, generateKeyPair
from ohmyssh.core.ssh import SshAuthError, SshClient, SshCredentials, SshError, passphraseUnlocks
from tests.echoserver import EchoServer
from tests.sshserver import (
    EXEC_PREFIX,
    SHELL_BANNER,
    TEST_PASSWORD,
    TEST_USER,
    TestSshServer,
    hostFor as _hostFor,
)


def _readUntil(channel: paramiko.Channel, expected: bytes, timeout: float = 5.0) -> bytes:
    channel.settimeout(timeout)
    received = b""
    while expected not in received:
        chunk = channel.recv(1024)
        if not chunk:
            break
        received += chunk
    return received


def test_connect_with_password_and_run_command(sshServer: TestSshServer, tmp_path: Path) -> None:
    client = SshClient(
        _hostFor(sshServer),
        credentials=SshCredentials(password=TEST_PASSWORD),
        knownHostsPath=tmp_path / "known_hosts",
    )
    client.connect()
    try:
        assert client.isConnected()
        assert client.runCommand("uptime") == f"{EXEC_PREFIX}uptime\n"
        assert sshServer.commands == ["uptime"]
    finally:
        client.close()
    assert not client.isConnected()


def test_connect_with_identity_file(
    sshServer: TestSshServer, clientKeyFile: Path, tmp_path: Path
) -> None:
    client = SshClient(
        _hostFor(sshServer, identityFile=clientKeyFile), knownHostsPath=tmp_path / "known_hosts"
    )
    client.connect()
    try:
        assert ("publickey", TEST_USER) in sshServer.authAttempts
        assert ("password", TEST_USER) not in sshServer.authAttempts
    finally:
        client.close()


def test_wrong_password_raises_auth_error(sshServer: TestSshServer, tmp_path: Path) -> None:
    client = SshClient(
        _hostFor(sshServer),
        credentials=SshCredentials(password="nope"),
        knownHostsPath=tmp_path / "known_hosts",
    )
    with pytest.raises(SshAuthError):
        client.connect()
    assert not client.isConnected()


def test_no_credentials_raises_auth_error(sshServer: TestSshServer, tmp_path: Path) -> None:
    client = SshClient(_hostFor(sshServer), knownHostsPath=tmp_path / "known_hosts")
    with pytest.raises(SshAuthError):
        client.connect()


def test_unknown_host_key_is_accepted_and_remembered(
    sshServer: TestSshServer, tmp_path: Path
) -> None:
    knownHosts = tmp_path / "known_hosts"
    client = SshClient(
        _hostFor(sshServer),
        credentials=SshCredentials(password=TEST_PASSWORD),
        knownHostsPath=knownHosts,
    )
    client.connect()
    client.close()
    assert not knownHosts.exists()


def test_changed_host_key_is_rejected(sshServer: TestSshServer, tmp_path: Path) -> None:
    knownHosts = tmp_path / "known_hosts"
    otherKey = paramiko.RSAKey.generate(1024)
    entries = paramiko.HostKeys()
    entries.add(f"[127.0.0.1]:{sshServer.port}", otherKey.get_name(), otherKey)
    entries.save(str(knownHosts))

    client = SshClient(
        _hostFor(sshServer),
        credentials=SshCredentials(password=TEST_PASSWORD),
        knownHostsPath=knownHosts,
    )
    with pytest.raises(SshError, match="host key"):
        client.connect()


def test_connection_refused_raises_ssh_error(tmp_path: Path) -> None:
    host = Host(name="dead", hostname="127.0.0.1", user=TEST_USER, port=1)
    client = SshClient(host, knownHostsPath=tmp_path / "known_hosts")
    with pytest.raises(SshError):
        client.connect(timeout=2)


def test_run_command_before_connect_raises(sshServer: TestSshServer, tmp_path: Path) -> None:
    client = SshClient(_hostFor(sshServer), knownHostsPath=tmp_path / "known_hosts")
    with pytest.raises(SshError, match="not connected"):
        client.runCommand("uptime")


def test_open_shell_requests_pty_and_echoes(sshServer: TestSshServer, tmp_path: Path) -> None:
    client = SshClient(
        _hostFor(sshServer),
        credentials=SshCredentials(password=TEST_PASSWORD),
        knownHostsPath=tmp_path / "known_hosts",
    )
    client.connect()
    try:
        channel = client.openShell(cols=100, rows=30)
        assert sshServer.ptyRequests == [("xterm-256color", 100, 30)]
        assert _readUntil(channel, SHELL_BANNER).endswith(SHELL_BANNER)

        channel.sendall(b"ls\r")
        assert _readUntil(channel, b"ls\r").endswith(b"ls\r")

        channel.resize_pty(width=120, height=40)
        channel.sendall(b"x")
        _readUntil(channel, b"x")
        assert sshServer.windowChanges == [(120, 40)]
        channel.close()
    finally:
        client.close()


def test_proxy_jump_routes_through_bastion(
    sshServer: TestSshServer, jumpServer: TestSshServer, tmp_path: Path
) -> None:
    bastion = _hostFor(jumpServer, name="bastion")
    target = _hostFor(sshServer, name="inner", proxyJump="bastion")
    client = SshClient(
        target,
        credentials=SshCredentials(password=TEST_PASSWORD),
        jumpHosts=[bastion],
        knownHostsPath=tmp_path / "known_hosts",
    )
    client.connect()
    try:
        assert client.runCommand("whoami") == f"{EXEC_PREFIX}whoami\n"
        assert jumpServer.directTcpipRequests == [("127.0.0.1", sshServer.port)]
        assert sshServer.commands == ["whoami"]
        assert jumpServer.commands == []
    finally:
        client.close()
    assert not client.isConnected()


def test_close_is_idempotent(sshServer: TestSshServer, tmp_path: Path) -> None:
    client = SshClient(_hostFor(sshServer), knownHostsPath=tmp_path / "known_hosts")
    client.close()
    client.close()
    assert not client.isConnected()


def test_open_direct_tcpip_channel_reaches_a_service(
    sshServer: TestSshServer, echoServer: EchoServer, tmp_path: Path
) -> None:
    client = SshClient(
        _hostFor(sshServer),
        credentials=SshCredentials(password=TEST_PASSWORD),
        knownHostsPath=tmp_path / "known_hosts",
    )
    client.connect()
    try:
        channel = client.openDirectTcpip(("127.0.0.1", echoServer.port), ("10.1.1.1", 4444))
        channel.sendall(b"ping")
        assert _readUntil(channel, b"ping") == b"ping"
        channel.close()
        assert sshServer.directTcpipRequests[-1] == ("127.0.0.1", echoServer.port)
    finally:
        client.close()


def test_open_direct_tcpip_to_unreachable_destination_raises(
    sshServer: TestSshServer, tmp_path: Path
) -> None:
    sshServer.refuseDirectTcpip = True
    client = SshClient(
        _hostFor(sshServer),
        credentials=SshCredentials(password=TEST_PASSWORD),
        knownHostsPath=tmp_path / "known_hosts",
    )
    client.connect()
    try:
        with pytest.raises(SshError, match="box could not reach 127.0.0.1:1"):
            client.openDirectTcpip(("127.0.0.1", 1), ("127.0.0.1", 0))
    finally:
        client.close()


def test_remote_forward_delivers_server_side_connections(
    sshServer: TestSshServer, tmp_path: Path
) -> None:
    client = SshClient(
        _hostFor(sshServer),
        credentials=SshCredentials(password=TEST_PASSWORD),
        knownHostsPath=tmp_path / "known_hosts",
    )
    client.connect()
    received: list[tuple[paramiko.Channel, tuple[str, int], tuple[str, int]]] = []
    arrived = threading.Event()

    def handler(channel: paramiko.Channel, origin: tuple[str, int], server: tuple[str, int]) -> None:
        received.append((channel, origin, server))
        channel.sendall(b"hello from the client side")
        arrived.set()

    try:
        port = _freePort()
        client.requestRemoteForward("localhost", port, handler)
        assert ("localhost", port) in sshServer.remoteForwardRequests
        with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
            assert arrived.wait(5)
            assert connection.recv(1024) == b"hello from the client side"
        assert received[0][2] == ("localhost", port)
        client.cancelRemoteForward("localhost", port)
        assert ("localhost", port) in sshServer.cancelledRemoteForwards
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
    finally:
        client.close()


def test_remote_forward_refused_by_server_raises(sshServer: TestSshServer, tmp_path: Path) -> None:
    sshServer.refuseRemoteForwards = True
    client = SshClient(
        _hostFor(sshServer),
        credentials=SshCredentials(password=TEST_PASSWORD),
        knownHostsPath=tmp_path / "known_hosts",
    )
    client.connect()
    try:
        with pytest.raises(SshError, match="box refused to listen on localhost:9999"):
            client.requestRemoteForward("localhost", 9999, lambda *_: None)
    finally:
        client.close()


def _freePort() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_passphrase_unlocks_only_an_encrypted_key_it_opens(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    generateKeyPair(locked, KeyType.ED25519, "c", passphrase="right")
    plain = tmp_path / "plain"
    generateKeyPair(plain, KeyType.ED25519, "c", passphrase=None)
    assert passphraseUnlocks(locked, "right")
    assert not passphraseUnlocks(locked, "wrong")
    assert not passphraseUnlocks(plain, "anything")
    assert not passphraseUnlocks(tmp_path / "missing", "x")
    (tmp_path / "garbage").write_text("not a key\n")
    assert not passphraseUnlocks(tmp_path / "garbage", "x")


def _connected(server: TestSshServer, tmp_path: Path, host: Host, settings: GlobalSettings) -> SshClient:
    client = SshClient(
        host,
        credentials=SshCredentials(password=TEST_PASSWORD),
        knownHostsPath=tmp_path / "known_hosts",
        globalSettings=settings,
    )
    client.connect()
    return client


def test_keepalives_follow_the_host_then_the_global_interval(sshServer: TestSshServer, tmp_path: Path) -> None:
    host = _hostFor(sshServer)
    host.serverAliveInterval = 1
    client = _connected(sshServer, tmp_path, host, GlobalSettings(serverAliveInterval=600))
    try:
        assert client.keepaliveSeconds() == 1
        def keepalives() -> list[str]:
            return [kind for kind in sshServer.globalRequests if kind.startswith("keepalive@")]

        deadline = time.monotonic() + 6
        while not keepalives() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert keepalives()
    finally:
        client.close()


def test_keepalive_is_off_without_any_setting(sshServer: TestSshServer, tmp_path: Path) -> None:
    client = _connected(sshServer, tmp_path, _hostFor(sshServer), GlobalSettings())
    try:
        assert client.keepaliveSeconds() is None
    finally:
        client.close()


def test_compression_is_negotiated_from_global_and_overridden_per_host(
    sshServer: TestSshServer, tmp_path: Path
) -> None:
    plain = _connected(sshServer, tmp_path, _hostFor(sshServer), GlobalSettings(compression=True))
    try:
        assert plain.compressionInUse()
    finally:
        plain.close()
    host = _hostFor(sshServer)
    host.compression = False
    overridden = _connected(sshServer, tmp_path, host, GlobalSettings(compression=True))
    try:
        assert not overridden.compressionInUse()
    finally:
        overridden.close()
    default = _connected(sshServer, tmp_path, _hostFor(sshServer), GlobalSettings())
    try:
        assert not default.compressionInUse()
    finally:
        default.close()


def test_global_identity_file_is_used_when_the_host_has_none(
    sshServer: TestSshServer, clientKeyFile: Path, tmp_path: Path
) -> None:
    client = SshClient(
        _hostFor(sshServer),
        knownHostsPath=tmp_path / "known_hosts",
        globalSettings=GlobalSettings(identityFile=clientKeyFile),
    )
    client.connect()
    try:
        assert ("publickey", TEST_USER) in sshServer.authAttempts
        assert ("password", TEST_USER) not in sshServer.authAttempts
    finally:
        client.close()


def test_close_from_another_thread_aborts_a_connect_still_dialing(blackholeHost: Host, tmp_path: Path) -> None:
    """Quitting must not wait out the connect timeout of a host that never answers."""
    client = SshClient(blackholeHost, knownHostsPath=tmp_path / "known_hosts")
    errors: list[SshError] = []

    def connect() -> None:
        try:
            client.connect(timeout=10.0)
        except SshError as error:
            errors.append(error)

    thread = threading.Thread(target=connect)
    thread.start()
    time.sleep(0.3)
    started = time.monotonic()
    client.close()
    thread.join(5.0)
    assert not thread.is_alive(), "connect() kept dialing after close()"
    assert time.monotonic() - started < 2.0
    assert len(errors) == 1 and "closed" in str(errors[0]).lower()
    assert not client.isConnected()


def test_connect_after_close_does_not_dial(blackholeHost: Host, tmp_path: Path) -> None:
    client = SshClient(blackholeHost, knownHostsPath=tmp_path / "known_hosts")
    client.close()
    started = time.monotonic()
    with pytest.raises(SshError, match="Closed"):
        client.connect(timeout=10.0)
    assert time.monotonic() - started < 1.0


def test_closing_a_client_under_a_pending_command_raises_ssh_error(sshServer: TestSshServer, tmp_path: Path) -> None:
    """Shutdown closes connections under running workers; paramiko's bare EOFError must not leak out."""
    sshServer.execGate = threading.Event()
    client = SshClient(
        _hostFor(sshServer),
        credentials=SshCredentials(password=TEST_PASSWORD),
        knownHostsPath=tmp_path / "known_hosts",
    )
    client.connect()
    errors: list[SshError] = []

    def run() -> None:
        try:
            client.runCommand("uptime")
        except SshError as error:
            errors.append(error)

    thread = threading.Thread(target=run)
    thread.start()
    try:
        time.sleep(0.3)
        client.close()
        thread.join(5.0)
    finally:
        sshServer.execGate.set()
    assert not thread.is_alive()
    assert len(errors) == 1 and "closed" in str(errors[0]).lower()
