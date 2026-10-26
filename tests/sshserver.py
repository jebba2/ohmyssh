"""A minimal in-process SSH server for exercising the real SSH client.

It accepts one password user and one public key, answers exec requests with
a canned reply, echoes shell input, proxies direct-tcpip channels so
ProxyJump and local forwards can be tested end to end, and serves
tcpip-forward requests by really listening on the requested port.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import paramiko
from paramiko.common import (
    AUTH_FAILED,
    AUTH_SUCCESSFUL,
    OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED,
    OPEN_FAILED_CONNECT_FAILED,
    OPEN_SUCCEEDED,
)

from ohmyssh.core.hosts import Host
from tests.sftpserver import DirectorySftpServer

TEST_USER = "tester"
TEST_PASSWORD = "secret"
EXEC_PREFIX = "you ran: "
SHELL_BANNER = b"welcome\r\n$ "


def _pipeSockets(channel: paramiko.Channel, target: socket.socket) -> None:
    """Copy bytes both ways between a channel and a socket until either closes."""

    def pump(readFrom: Any, writeTo: Any) -> None:
        try:
            while True:
                data = readFrom.recv(4096)
                if not data:
                    break
                writeTo.sendall(data)
        except OSError:
            pass
        finally:
            try:
                writeTo.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    pumps = [
        threading.Thread(target=pump, args=(channel, target), daemon=True),
        threading.Thread(target=pump, args=(target, channel), daemon=True),
    ]

    def closeWhenDone() -> None:
        for thread in pumps:
            thread.join()
        target.close()
        channel.close()

    for thread in pumps:
        thread.start()
    threading.Thread(target=closeWhenDone, daemon=True).start()


class _Handler(paramiko.ServerInterface):
    def __init__(self, server: TestSshServer) -> None:
        self._server = server
        self._shellChannels: list[paramiko.Channel] = []
        # Set by the accept loop before the handshake starts.
        self.transport: paramiko.Transport | None = None
        self._remoteListeners: dict[tuple[str, int], socket.socket] = {}

    def check_auth_password(self, username: str, password: str) -> int:
        self._server.authAttempts.append(("password", username))
        if username == TEST_USER and password == TEST_PASSWORD:
            return AUTH_SUCCESSFUL
        return AUTH_FAILED

    def check_auth_publickey(self, username: str, key: paramiko.PKey) -> int:
        self._server.authAttempts.append(("publickey", username))
        if username == TEST_USER and self._server.acceptedKey is not None:
            if key.get_base64() == self._server.acceptedKey.get_base64():
                return AUTH_SUCCESSFUL
        return AUTH_FAILED

    def get_allowed_auths(self, username: str) -> str:
        return "password,publickey"

    def check_channel_request(self, kind: str, chanid: int) -> int:
        return OPEN_SUCCEEDED if kind == "session" else OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_exec_request(self, channel: paramiko.Channel, command: bytes) -> bool:
        text = command.decode()
        self._server.commands.append(text)
        execOutput = self._server.execOutput
        output = execOutput(text) if execOutput is not None else f"{EXEC_PREFIX}{text}\n"

        def reply() -> None:
            # Send EOF rather than closing: a close can overtake paramiko's own
            # exec acknowledgement and the client then sees "Channel closed".
            channel.sendall(output.encode())
            channel.send_exit_status(0)
            channel.shutdown_write()

        threading.Thread(target=reply, daemon=True).start()
        return True

    def check_channel_pty_request(
        self,
        channel: paramiko.Channel,
        term: bytes,
        width: int,
        height: int,
        pixelwidth: int,
        pixelheight: int,
        modes: bytes,
    ) -> bool:
        self._server.ptyRequests.append((term.decode(), width, height))
        return True

    def check_channel_window_change_request(
        self, channel: paramiko.Channel, width: int, height: int, pixelwidth: int, pixelheight: int
    ) -> bool:
        self._server.windowChanges.append((width, height))
        return True

    def check_channel_shell_request(self, channel: paramiko.Channel) -> bool:
        def echo() -> None:
            channel.sendall(SHELL_BANNER)
            try:
                while True:
                    data = channel.recv(1024)
                    if not data:
                        break
                    channel.sendall(data)
            except OSError:
                pass

        threading.Thread(target=echo, daemon=True).start()
        return True

    def check_global_request(self, kind: str, msg: paramiko.Message) -> bool:
        """Record keepalives and other global requests; none need a reply payload."""
        self._server.globalRequests.append(kind)
        return False

    def check_port_forward_request(self, address: str, port: int) -> int:
        """Listen on the requested port and open a forwarded-tcpip channel per connection.

        Every bind address is treated as loopback so tests never open a port
        on a real interface. Returns the port, or False to refuse.
        """
        self._server.remoteForwardRequests.append((address, port))
        if self._server.refuseRemoteForwards:
            return False
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError:
            listener.close()
            return False
        listener.listen(5)
        listener.settimeout(0.2)
        self._remoteListeners[(address, port)] = listener
        threading.Thread(
            target=self._serveRemoteForward, args=(listener, (address, port)), daemon=True
        ).start()
        return port

    def cancel_port_forward_request(self, address: str, port: int) -> None:
        self._server.cancelledRemoteForwards.append((address, port))
        listener = self._remoteListeners.pop((address, port), None)
        if listener is not None:
            listener.close()

    def _serveRemoteForward(self, listener: socket.socket, serverAddress: tuple[str, int]) -> None:
        while True:
            try:
                connection, peer = listener.accept()
            except socket.timeout:
                if self.transport is None or not self.transport.is_active():
                    listener.close()
                    return
                continue
            except OSError:
                return
            assert self.transport is not None
            try:
                channel = self.transport.open_forwarded_tcpip_channel(peer, serverAddress)
            except paramiko.SSHException:
                connection.close()
                continue
            _pipeSockets(channel, connection)

    def check_channel_direct_tcpip_request(
        self, chanid: int, origin: tuple[str, int], destination: tuple[str, int]
    ) -> int:
        self._server.directTcpipRequests.append(destination)
        if self._server.refuseDirectTcpip:
            return OPEN_FAILED_CONNECT_FAILED
        self._server.forwardDestinations[chanid] = destination
        return OPEN_SUCCEEDED


def hostFor(
    server: TestSshServer,
    name: str = "box",
    identityFile: Path | None = None,
    proxyJump: str | None = None,
) -> Host:
    """Build a Host that points at a running test server."""
    return Host(
        name=name,
        hostname="127.0.0.1",
        user=TEST_USER,
        port=server.port,
        identityFile=identityFile,
        proxyJump=proxyJump,
    )


class TestSshServer:
    """An SSH server bound to a random localhost port. Use ``start``/``stop``."""

    __test__ = False  # Not a pytest test class despite the name.

    def __init__(
        self, hostKey: paramiko.PKey, acceptedKey: paramiko.PKey | None = None, sftpRoot: Path | None = None
    ) -> None:
        self.hostKey = hostKey
        self.acceptedKey = acceptedKey
        # When set, an SFTP subsystem serves this directory as "/".
        self.sftpRoot = sftpRoot
        # Files with these names are refused with "permission denied" over SFTP.
        self.sftpRefusedNames: set[str] = set()
        self.authAttempts: list[tuple[str, str]] = []
        self.commands: list[str] = []
        self.ptyRequests: list[tuple[str, int, int]] = []
        self.windowChanges: list[tuple[int, int]] = []
        self.directTcpipRequests: list[tuple[str, int]] = []
        self.forwardDestinations: dict[int, tuple[str, int]] = {}
        self.remoteForwardRequests: list[tuple[str, int]] = []
        self.cancelledRemoteForwards: list[tuple[str, int]] = []
        self.refuseDirectTcpip = False
        self.refuseRemoteForwards = False
        # Global requests seen on any session, e.g. paramiko's "keepalive@lag.net".
        self.globalRequests: list[str] = []
        # When set, exec requests answer with this instead of the canned echo.
        self.execOutput: Callable[[str], str] | None = None
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(5)
        self._transports: list[paramiko.Transport] = []
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._acceptLoop, daemon=True)

    @property
    def port(self) -> int:
        return self._listener.getsockname()[1]

    def start(self) -> None:
        self._thread.start()

    def dropConnections(self) -> None:
        """Close every live session while staying up, so clients can reconnect."""
        for transport in self._transports:
            transport.close()
        self._transports = []

    def stop(self) -> None:
        self._stopping.set()
        try:
            self._listener.close()
        except OSError:
            pass
        for transport in self._transports:
            transport.close()
        self._thread.join(timeout=5)

    def _acceptLoop(self) -> None:
        while not self._stopping.is_set():
            try:
                client, _ = self._listener.accept()
            except OSError:
                return
            transport = paramiko.Transport(client)
            transport.add_server_key(self.hostKey)
            # Offer compression so a client that asks for it can negotiate it.
            transport.use_compression(True)
            if self.sftpRoot is not None:
                transport.set_subsystem_handler(
                    "sftp", paramiko.SFTPServer, DirectorySftpServer,
                    root=self.sftpRoot, refusedNames=self.sftpRefusedNames,
                )
            handler = _Handler(self)
            handler.transport = transport
            try:
                transport.start_server(server=handler)
            except (paramiko.SSHException, EOFError, OSError):
                # The client gave up mid-handshake, e.g. on a host key mismatch.
                transport.close()
                client.close()
                continue
            self._transports.append(transport)
            threading.Thread(target=self._serveForwards, args=(transport,), daemon=True).start()

    def _serveForwards(self, transport: paramiko.Transport) -> None:
        """Accept direct-tcpip channels and proxy them to their destination."""
        while transport.is_active():
            channel = transport.accept(timeout=0.5)
            if channel is None:
                continue
            destination = self.forwardDestinations.pop(channel.get_id(), None)
            if destination is not None:
                target = socket.create_connection(destination, timeout=5)
                _pipeSockets(channel, target)
