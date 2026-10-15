"""Tests for the SSH client against a real in-process SSH server."""

from __future__ import annotations

from pathlib import Path

import paramiko
import pytest

from pyommyssh.core.hosts import Host
from pyommyssh.core.ssh import SshAuthError, SshClient, SshCredentials, SshError
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
        _readUntil  # the resize is acknowledged asynchronously by the server
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
