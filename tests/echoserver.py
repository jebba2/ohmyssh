"""A TCP echo server that stands in for the service at the far end of a forward."""

from __future__ import annotations

import socket
import threading


class EchoServer:
    """Echoes every byte back on each accepted connection until it closes."""

    def __init__(self) -> None:
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(5)
        self._listener.settimeout(0.2)
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._acceptLoop, daemon=True)
        self.connections = 0

    @property
    def port(self) -> int:
        return self._listener.getsockname()[1]

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        self._thread.join(timeout=5)
        self._listener.close()

    def _acceptLoop(self) -> None:
        while not self._stopping.is_set():
            try:
                connection, _ = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            self.connections += 1
            threading.Thread(target=self._echo, args=(connection,), daemon=True).start()

    @staticmethod
    def _echo(connection: socket.socket) -> None:
        with connection:
            try:
                while True:
                    data = connection.recv(4096)
                    if not data:
                        break
                    connection.sendall(data)
            except OSError:
                pass
