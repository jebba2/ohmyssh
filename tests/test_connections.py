"""Tests for jump-chain resolution and the shared connection pool."""

from __future__ import annotations

from pathlib import Path

import pytest

from pyommyssh.core.connections import ConnectionPool
from pyommyssh.core.hosts import Host, resolveJumpChain
from pyommyssh.core.ssh import SshAuthError, SshCredentials, SshError
from tests.sshserver import EXEC_PREFIX, TEST_PASSWORD, TEST_USER, TestSshServer, hostFor as _host


def test_resolve_jump_chain_follows_comma_separated_names() -> None:
    outer = Host(name="outer", hostname="o")
    inner = Host(name="inner", hostname="i")
    target = Host(name="target", hostname="t", proxyJump="outer,inner")
    assert resolveJumpChain(target, [outer, inner, target]) == [outer, inner]


def test_resolve_jump_chain_without_proxy_is_empty() -> None:
    host = Host(name="plain", hostname="p")
    assert resolveJumpChain(host, [host]) == []


def test_resolve_jump_chain_unknown_name_raises() -> None:
    target = Host(name="target", hostname="t", proxyJump="ghost")
    with pytest.raises(ValueError, match="ghost"):
        resolveJumpChain(target, [target])


def test_resolve_jump_chain_rejects_cycles() -> None:
    a = Host(name="a", hostname="a", proxyJump="b")
    b = Host(name="b", hostname="b", proxyJump="a")
    with pytest.raises(ValueError, match="cycle"):
        resolveJumpChain(a, [a, b])


def test_resolve_jump_chain_expands_nested_proxies() -> None:
    bastion = Host(name="bastion", hostname="b")
    middle = Host(name="middle", hostname="m", proxyJump="bastion")
    target = Host(name="target", hostname="t", proxyJump="middle")
    assert resolveJumpChain(target, [bastion, middle, target]) == [bastion, middle]


def test_pool_reuses_one_connection_per_host(sshServer: TestSshServer, tmp_path: Path) -> None:
    host = _host(sshServer)
    pool = ConnectionPool(lambda: [host], knownHostsPath=tmp_path / "known_hosts")
    pool.setCredentials(host.name, SshCredentials(password=TEST_PASSWORD))
    first = pool.connection(host)
    second = pool.connection(host)
    assert first is second
    assert first.runCommand("uptime") == f"{EXEC_PREFIX}uptime\n"
    # One connection: default keys may be tried first, but only one password auth.
    assert sshServer.authAttempts.count(("password", TEST_USER)) == 1
    pool.closeAll()
    assert not first.isConnected()


def test_pool_reconnects_after_drop(sshServer: TestSshServer, tmp_path: Path) -> None:
    host = _host(sshServer)
    pool = ConnectionPool(lambda: [host], knownHostsPath=tmp_path / "known_hosts")
    pool.setCredentials(host.name, SshCredentials(password=TEST_PASSWORD))
    first = pool.connection(host)
    first.close()
    second = pool.connection(host)
    assert second is not first
    assert second.isConnected()
    pool.closeAll()


def test_pool_without_credentials_raises_auth_error(
    sshServer: TestSshServer, tmp_path: Path
) -> None:
    host = _host(sshServer)
    pool = ConnectionPool(lambda: [host], knownHostsPath=tmp_path / "known_hosts")
    with pytest.raises(SshAuthError):
        pool.connection(host)
    pool.closeAll()


def test_pool_uses_identity_file_without_credentials(
    sshServer: TestSshServer, clientKeyFile: Path, tmp_path: Path
) -> None:
    host = _host(sshServer, identityFile=clientKeyFile)
    pool = ConnectionPool(lambda: [host], knownHostsPath=tmp_path / "known_hosts")
    client = pool.connection(host)
    assert client.isConnected()
    pool.closeAll()


def test_pool_resolves_jump_hosts(
    sshServer: TestSshServer, jumpServer: TestSshServer, tmp_path: Path
) -> None:
    bastion = _host(jumpServer, name="bastion")
    target = _host(sshServer, name="target", proxyJump="bastion")
    pool = ConnectionPool(lambda: [bastion, target], knownHostsPath=tmp_path / "known_hosts")
    creds = SshCredentials(password=TEST_PASSWORD)
    pool.setCredentials("bastion", creds)
    pool.setCredentials("target", creds)
    client = pool.connection(target)
    assert client.runCommand("id") == f"{EXEC_PREFIX}id\n"
    assert jumpServer.directTcpipRequests == [("127.0.0.1", sshServer.port)]
    pool.closeAll()


def test_pool_unknown_jump_name_is_ssh_error(sshServer: TestSshServer, tmp_path: Path) -> None:
    target = _host(sshServer, name="target", proxyJump="ghost")
    pool = ConnectionPool(lambda: [target], knownHostsPath=tmp_path / "known_hosts")
    with pytest.raises(SshError, match="ghost"):
        pool.connection(target)


def test_pool_forget_closes_one_host(sshServer: TestSshServer, tmp_path: Path) -> None:
    host = _host(sshServer)
    pool = ConnectionPool(lambda: [host], knownHostsPath=tmp_path / "known_hosts")
    pool.setCredentials(host.name, SshCredentials(password=TEST_PASSWORD))
    client = pool.connection(host)
    pool.forget(host.name)
    assert not client.isConnected()
    pool.closeAll()
