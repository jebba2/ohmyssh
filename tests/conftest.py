"""Shared fixtures: in-process SSH servers and generated keys."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import paramiko
import pytest

# Widget tests must not need a display; this has to be set before Qt loads.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.echoserver import EchoServer
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


@pytest.fixture
def echoServer() -> Iterator[EchoServer]:
    """A plain TCP echo service for the far end of a port forward."""
    server = EchoServer()
    server.start()
    yield server
    server.stop()
