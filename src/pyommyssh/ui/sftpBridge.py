"""Runs an SFTP session on worker threads and reports back through Qt signals.

Browsing and transfers each get their own thread, matching the session's
two channels, so folders still open while a transfer runs. Every signal is
emitted from a worker thread and lands on the GUI thread through Qt's
queued delivery.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, Signal

from pyommyssh.core.connections import ConnectionPool
from pyommyssh.core.hosts import Host
from pyommyssh.core.sftp import SftpError, SftpSession
from pyommyssh.core.ssh import SshAuthError, SshError

logger = logging.getLogger(__name__)

THREAD_STOP_TIMEOUT_MS = 5000


class WorkQueueThread(QThread):
    """Runs submitted callables one after another until stopped."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._queue: queue.Queue[Callable[[], None] | None] = queue.Queue()

    def submit(self, work: Callable[[], None]) -> None:
        """Queue a callable to run on this thread."""
        self._queue.put(work)

    def clearPending(self) -> None:
        """Drop everything queued but not yet started."""
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    def stop(self) -> None:
        """Finish the running callable, drop the rest, and end the thread."""
        self.clearPending()
        self._queue.put(None)
        if self.isRunning():
            self.wait(THREAD_STOP_TIMEOUT_MS)

    def run(self) -> None:
        while True:
            work = self._queue.get()
            if work is None:
                return
            try:
                work()
            except Exception:
                logger.exception("Unhandled error in SFTP work")


class SftpBridge(QObject):
    """The GUI's handle on one host's SFTP session."""

    connected = Signal(str)
    connectFailed = Signal(str)
    authRequired = Signal()
    listed = Signal(str, object)
    listFailed = Signal(str, str)
    operationDone = Signal(str)
    operationFailed = Signal(str)

    def __init__(self, host: Host, pool: ConnectionPool, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.host = host
        self._pool = pool
        self._session: SftpSession | None = None
        self._cancel = threading.Event()
        self._browse = WorkQueueThread(self)
        self._transfer = WorkQueueThread(self)
        self._shutDown = False

    def isConnected(self) -> bool:
        """True once the session is open."""
        return self._session is not None

    def start(self) -> None:
        """Connect in the background; safe to call again after a password was supplied."""
        for thread in (self._browse, self._transfer):
            if not thread.isRunning():
                thread.start()
        self._browse.submit(self._connect)

    def listDir(self, path: str) -> None:
        """List a remote folder; answers with ``listed`` or ``listFailed``."""
        self._browse.submit(lambda: self._list(path))

    def mkdir(self, path: str) -> None:
        """Create a remote folder; answers with ``operationDone`` or ``operationFailed``."""
        self._browse.submit(lambda: self._operate(lambda s: s.mkdir(path), f"Created {path}"))

    def remove(self, path: str) -> None:
        """Delete a remote file or empty folder."""
        self._browse.submit(lambda: self._operate(lambda s: s.remove(path), f"Removed {path}"))

    def rename(self, source: str, destination: str) -> None:
        """Rename or move a remote path."""
        self._browse.submit(
            lambda: self._operate(lambda s: s.rename(source, destination), f"Renamed {source} to {destination}")
        )

    def shutdown(self) -> None:
        """Stop both threads and close the session. Safe to call repeatedly."""
        if self._shutDown:
            return
        self._shutDown = True
        self._cancel.set()
        self._browse.stop()
        self._transfer.stop()
        if self._session is not None:
            self._session.close()
            self._session = None

    # Worker-thread side

    def _connect(self) -> None:
        if self._shutDown:
            return
        try:
            client = self._pool.connection(self.host)
            session = SftpSession(client)
            home = session.home()
        except SshAuthError:
            self.authRequired.emit()
            return
        except SshError as error:
            self.connectFailed.emit(str(error))
            return
        self._session = session
        self.connected.emit(home)

    def _list(self, path: str) -> None:
        session = self._session
        if session is None:
            self.listFailed.emit(path, "Not connected")
            return
        try:
            entries = session.listDir(path)
        except SftpError as error:
            self.listFailed.emit(path, str(error))
            return
        self.listed.emit(path, entries)

    def _operate(self, operation: Callable[[SftpSession], None], doneMessage: str) -> None:
        session = self._session
        if session is None:
            self.operationFailed.emit("Not connected")
            return
        try:
            operation(session)
        except SftpError as error:
            self.operationFailed.emit(str(error))
            return
        self.operationDone.emit(doneMessage)
