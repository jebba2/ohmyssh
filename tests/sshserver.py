"""A minimal in-process SSH server for exercising the real SSH client.

It accepts one password user and one public key, answers exec requests with
a canned reply, echoes shell input, and proxies direct-tcpip channels so
ProxyJump can be tested end to end without mocks.
"""

from __future__ import annotations

import socket
import threading
from pathlib import Path
from typing import Any

import paramiko

from pyommyssh.core.hosts import Host

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

    def check_auth_password(self, username: str, password: str) -> int:
        self._server.authAttempts.append(("password", username))
        if username == TEST_USER and password == TEST_PASSWORD:
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def check_auth_publickey(self, username: str, key: paramiko.PKey) -> int:
        self._server.authAttempts.append(("publickey", username))
        if username == TEST_USER and self._server.acceptedKey is not None:
            if key.get_base64() == self._server.acceptedKey.get_base64():
                return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username: str) -> str:
        return "password,publickey"

    def check_channel_request(self, kind: str, chanid: int) -> int:
        return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_exec_request(self, channel: paramiko.Channel, command: bytes) -> bool:
        text = command.decode()
        self._server.commands.append(text)

        def reply() -> None:
            # Send EOF rather than closing: a close can overtake paramiko's own
            # exec acknowledgement and the client then sees "Channel closed".
            channel.sendall(f"{EXEC_PREFIX}{text}\n".encode())
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

    def check_port_forward_request(self, address: str, port: int) -> int:
        return 0

    def check_channel_direct_tcpip_request(
        self, chanid: int, origin: tuple[str, int], destination: tuple[str, int]
    ) -> int:
        self._server.directTcpipRequests.append(destination)
        self._server.forwardDestinations[chanid] = destination
        return paramiko.OPEN_SUCCEEDED


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

    def __init__(self, hostKey: paramiko.PKey, acceptedKey: paramiko.PKey | None = None) -> None:
        self.hostKey = hostKey
        self.acceptedKey = acceptedKey
        self.authAttempts: list[tuple[str, str]] = []
        self.commands: list[str] = []
        self.ptyRequests: list[tuple[str, int, int]] = []
        self.windowChanges: list[tuple[int, int]] = []
        self.directTcpipRequests: list[tuple[str, int]] = []
        self.forwardDestinations: dict[int, tuple[str, int]] = {}
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
            handler = _Handler(self)
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
