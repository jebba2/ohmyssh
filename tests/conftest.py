"""Shared fixtures: in-process SSH servers and generated keys."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import paramiko
import pytest

from tests.sshserver import TestSshServer


@pytest.fixture(scope="session")
def hostKey() -> paramiko.PKey:
    """The server's host key, generated once per test session."""
    return paramiko.RSAKey.generate(2048)


@pytest.fixture(scope="session")
def clientKey() -> paramiko.PKey:
    """A client key the servers accept for public-key auth."""
    return paramiko.RSAKey.generate(2048)


@pytest.fixture(scope="session")
def clientKeyFile(clientKey: paramiko.PKey, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The client key written to disk for use as an IdentityFile."""
    path = tmp_path_factory.mktemp("keys") / "id_test"
    clientKey.write_private_key_file(str(path))
    return path


@pytest.fixture
def sshServer(hostKey: paramiko.PKey, clientKey: paramiko.PKey) -> Iterator[TestSshServer]:
    """A running test SSH server, stopped after the test."""
    server = TestSshServer(hostKey, acceptedKey=clientKey)
    server.start()
    yield server
    server.stop()


@pytest.fixture
def jumpServer(hostKey: paramiko.PKey, clientKey: paramiko.PKey) -> Iterator[TestSshServer]:
    """A second server that acts as a ProxyJump bastion."""
    server = TestSshServer(hostKey, acceptedKey=clientKey)
    server.start()
    yield server
    server.stop()
