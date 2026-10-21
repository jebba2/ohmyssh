"""Tests for the SOCKS4/4a/5 CONNECT handshake used by dynamic forwards."""

from __future__ import annotations

import socket
import struct
from collections.abc import Iterator

import pytest

from pyommyssh.core.socks import SocksError, SocksRequest, readSocksRequest, sendSocksReply


@pytest.fixture
def pair() -> Iterator[tuple[socket.socket, socket.socket]]:
    client, server = socket.socketpair()
    client.settimeout(5)
    server.settimeout(5)
    yield client, server
    client.close()
    server.close()


def test_socks5_connect_to_domain(pair: tuple[socket.socket, socket.socket]) -> None:
    client, server = pair
    client.sendall(b"\x05\x02\x00\x02")
    client.sendall(b"\x05\x01\x00\x03" + bytes([len(b"example.com")]) + b"example.com" + struct.pack(">H", 443))
    request = readSocksRequest(server)
    assert request == SocksRequest(version=5, host="example.com", port=443)
    assert client.recv(2) == b"\x05\x00"
    sendSocksReply(server, request, granted=True)
    assert client.recv(10) == b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00"


def test_socks5_connect_to_ipv4_and_ipv6(pair: tuple[socket.socket, socket.socket]) -> None:
    client, server = pair
    client.sendall(b"\x05\x01\x00")
    client.sendall(b"\x05\x01\x00\x01" + socket.inet_aton("10.0.0.5") + struct.pack(">H", 80))
    assert readSocksRequest(server) == SocksRequest(version=5, host="10.0.0.5", port=80)
    client.recv(2)

    client.sendall(b"\x05\x01\x00")
    client.sendall(b"\x05\x01\x00\x04" + socket.inet_pton(socket.AF_INET6, "fe80::1") + struct.pack(">H", 22))
    assert readSocksRequest(server) == SocksRequest(version=5, host="fe80::1", port=22)


def test_socks5_rejects_when_no_auth_is_not_offered(pair: tuple[socket.socket, socket.socket]) -> None:
    client, server = pair
    client.sendall(b"\x05\x01\x02")
    with pytest.raises(SocksError, match="no acceptable authentication method"):
        readSocksRequest(server)
    assert client.recv(2) == b"\x05\xff"


def test_socks5_rejects_commands_other_than_connect(pair: tuple[socket.socket, socket.socket]) -> None:
    client, server = pair
    client.sendall(b"\x05\x01\x00")
    client.sendall(b"\x05\x02\x00\x01" + socket.inet_aton("10.0.0.5") + struct.pack(">H", 80))
    with pytest.raises(SocksError, match="only CONNECT is supported"):
        readSocksRequest(server)
    client.recv(2)
    assert client.recv(10) == b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00"


def test_socks5_failure_reply(pair: tuple[socket.socket, socket.socket]) -> None:
    client, server = pair
    sendSocksReply(server, SocksRequest(version=5, host="x", port=1), granted=False)
    assert client.recv(10) == b"\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00"


def test_socks4_connect_to_ip(pair: tuple[socket.socket, socket.socket]) -> None:
    client, server = pair
    client.sendall(b"\x04\x01" + struct.pack(">H", 8080) + socket.inet_aton("192.168.1.9") + b"user\x00")
    request = readSocksRequest(server)
    assert request == SocksRequest(version=4, host="192.168.1.9", port=8080)
    sendSocksReply(server, request, granted=True)
    assert client.recv(8) == b"\x00\x5a" + struct.pack(">H", 8080) + socket.inet_aton("192.168.1.9")


def test_socks4a_connect_to_domain(pair: tuple[socket.socket, socket.socket]) -> None:
    client, server = pair
    client.sendall(b"\x04\x01" + struct.pack(">H", 80) + b"\x00\x00\x00\x01" + b"\x00" + b"example.org\x00")
    request = readSocksRequest(server)
    assert request == SocksRequest(version=4, host="example.org", port=80)
    sendSocksReply(server, request, granted=False)
    assert client.recv(8) == b"\x00\x5b" + struct.pack(">H", 80) + b"\x00\x00\x00\x01"


def test_socks4_rejects_bind_command(pair: tuple[socket.socket, socket.socket]) -> None:
    client, server = pair
    client.sendall(b"\x04\x02" + struct.pack(">H", 80) + socket.inet_aton("10.0.0.1") + b"\x00")
    with pytest.raises(SocksError, match="only CONNECT is supported"):
        readSocksRequest(server)
    assert client.recv(8)[:2] == b"\x00\x5b"


def test_unknown_version_is_rejected(pair: tuple[socket.socket, socket.socket]) -> None:
    client, server = pair
    client.sendall(b"GET / HTTP/1.1\r\n")
    with pytest.raises(SocksError, match="not a SOCKS request"):
        readSocksRequest(server)


def test_closed_connection_mid_handshake_is_an_error(pair: tuple[socket.socket, socket.socket]) -> None:
    client, server = pair
    client.sendall(b"\x05\x01")
    client.close()
    with pytest.raises(SocksError, match="connection closed"):
        readSocksRequest(server)
