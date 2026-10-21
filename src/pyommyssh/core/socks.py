"""The server half of a SOCKS CONNECT handshake, for dynamic port forwards.

SOCKS5 without authentication (RFC 1928) and SOCKS4/4a are accepted, which
is what browsers and ``curl --socks5-hostname`` speak. Only CONNECT is
served; BIND and UDP ASSOCIATE are refused with the protocol's own reply.
"""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass

SOCKS4 = 4
SOCKS5 = 5

_SOCKS5_NO_AUTH = 0x00
_SOCKS5_NO_ACCEPTABLE_METHOD = 0xFF
_SOCKS5_CONNECT = 0x01
_SOCKS5_ATYP_IPV4 = 0x01
_SOCKS5_ATYP_DOMAIN = 0x03
_SOCKS5_ATYP_IPV6 = 0x04
_SOCKS5_REPLY_SUCCESS = 0x00
_SOCKS5_REPLY_REFUSED = 0x05
_SOCKS5_REPLY_COMMAND_NOT_SUPPORTED = 0x07

_SOCKS4_CONNECT = 0x01
_SOCKS4_GRANTED = 0x5A
_SOCKS4_REJECTED = 0x5B

MAX_SOCKS4_STRING = 256


class SocksError(Exception):
    """The client did not send a CONNECT request we can serve."""


@dataclass(frozen=True)
class SocksRequest:
    """Where a SOCKS client asked to be connected."""

    version: int
    host: str
    port: int


def _recvExactly(sock: socket.socket, count: int) -> bytes:
    data = b""
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise SocksError("connection closed during the SOCKS handshake")
        data += chunk
    return data


def _recvUntilNul(sock: socket.socket) -> bytes:
    data = b""
    while len(data) < MAX_SOCKS4_STRING:
        byte = _recvExactly(sock, 1)
        if byte == b"\x00":
            return data
        data += byte
    raise SocksError("SOCKS4 string too long")


def readSocksRequest(sock: socket.socket) -> SocksRequest:
    """Read a SOCKS4, SOCKS4a or SOCKS5 CONNECT request from a fresh connection.

    For SOCKS5 the method negotiation is answered here too. A request that
    is refused gets the protocol's failure reply before SocksError is raised.
    """
    version = _recvExactly(sock, 1)[0]
    if version == SOCKS5:
        return _readSocks5(sock)
    if version == SOCKS4:
        return _readSocks4(sock)
    raise SocksError("not a SOCKS request")


def _readSocks5(sock: socket.socket) -> SocksRequest:
    methodCount = _recvExactly(sock, 1)[0]
    methods = _recvExactly(sock, methodCount)
    if _SOCKS5_NO_AUTH not in methods:
        sock.sendall(bytes([SOCKS5, _SOCKS5_NO_ACCEPTABLE_METHOD]))
        raise SocksError("no acceptable authentication method offered")
    sock.sendall(bytes([SOCKS5, _SOCKS5_NO_AUTH]))

    _, command, _, addressType = _recvExactly(sock, 4)
    if addressType == _SOCKS5_ATYP_IPV4:
        host = socket.inet_ntoa(_recvExactly(sock, 4))
    elif addressType == _SOCKS5_ATYP_DOMAIN:
        length = _recvExactly(sock, 1)[0]
        host = _recvExactly(sock, length).decode("utf-8", errors="replace")
    elif addressType == _SOCKS5_ATYP_IPV6:
        host = socket.inet_ntop(socket.AF_INET6, _recvExactly(sock, 16))
    else:
        raise SocksError(f"unsupported SOCKS5 address type {addressType}")
    (port,) = struct.unpack(">H", _recvExactly(sock, 2))
    request = SocksRequest(version=SOCKS5, host=host, port=port)
    if command != _SOCKS5_CONNECT:
        _sendSocks5Reply(sock, _SOCKS5_REPLY_COMMAND_NOT_SUPPORTED)
        raise SocksError("only CONNECT is supported")
    return request


def _readSocks4(sock: socket.socket) -> SocksRequest:
    command = _recvExactly(sock, 1)[0]
    (port,) = struct.unpack(">H", _recvExactly(sock, 2))
    rawAddress = _recvExactly(sock, 4)
    _recvUntilNul(sock)  # user id, unused
    # SOCKS4a signals a domain name with an address of 0.0.0.x.
    if rawAddress[:3] == b"\x00\x00\x00" and rawAddress[3] != 0:
        host = _recvUntilNul(sock).decode("utf-8", errors="replace")
    else:
        host = socket.inet_ntoa(rawAddress)
    request = SocksRequest(version=SOCKS4, host=host, port=port)
    if command != _SOCKS4_CONNECT:
        sendSocksReply(sock, request, granted=False)
        raise SocksError("only CONNECT is supported")
    return request


def _sendSocks5Reply(sock: socket.socket, code: int) -> None:
    # The bound address is not meaningful for a proxy; send the zero IPv4 form.
    sock.sendall(bytes([SOCKS5, code, 0x00, _SOCKS5_ATYP_IPV4]) + b"\x00" * 4 + b"\x00\x00")


def sendSocksReply(sock: socket.socket, request: SocksRequest, granted: bool) -> None:
    """Tell the client whether its CONNECT succeeded, in its own protocol version."""
    if request.version == SOCKS5:
        _sendSocks5Reply(sock, _SOCKS5_REPLY_SUCCESS if granted else _SOCKS5_REPLY_REFUSED)
        return
    try:
        address = socket.inet_aton(request.host)
    except OSError:
        address = b"\x00\x00\x00\x01"
    status = _SOCKS4_GRANTED if granted else _SOCKS4_REJECTED
    sock.sendall(bytes([0x00, status]) + struct.pack(">H", request.port) + address)
