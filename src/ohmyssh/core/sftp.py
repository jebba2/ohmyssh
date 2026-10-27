"""SFTP browsing and transfers on top of a host's shared connection.

An ``SftpSession`` opens two SFTP channels: one for browsing, so folders
still open while a transfer runs, and one for transfers. Each channel is
meant to be driven from a single thread.

Listings follow symlinks, so a link to a folder opens like the folder and a
link to a file shows the file's size; a dangling link is listed as itself.

Transfers copy a file, or a folder with everything in it. An existing
folder is merged into and an existing file replaced. Symlinks and special
files are skipped, as is any file that fails; the transfer goes on and the
result lists what was skipped. A cancel event stops it between chunks and
the half-written file is removed.
"""

from __future__ import annotations

import os
import posixpath
import stat
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import paramiko

from ohmyssh.core.ssh import SshClient, SshError

CHUNK_BYTES = 256 * 1024


class SftpError(SshError):
    """A remote file operation failed."""


class TransferCancelled(Exception):
    """The cancel event was set while a transfer was running."""


@dataclass(frozen=True)
class FileEntry:
    """One row of a file listing. ``modified`` is seconds since the epoch."""

    name: str
    path: str
    size: int
    isDir: bool
    modified: float | None
    permissions: int | None


@dataclass(frozen=True)
class TransferProgress:
    """A snapshot of a running transfer. ``bytesTotal`` is known from the start."""

    currentFile: str
    bytesDone: int
    bytesTotal: int
    filesDone: int
    filesTotal: int


@dataclass
class TransferResult:
    """What a finished transfer managed, and what it had to skip."""

    filesDone: int = 0
    bytesDone: int = 0
    skipped: list[str] = field(default_factory=list)


ProgressCallback = Callable[[TransferProgress], None]


@dataclass(frozen=True)
class _Item:
    """One thing to create at the destination: a folder, or a file of ``size`` bytes."""

    name: str
    source: str
    destination: str
    isDir: bool
    size: int
    permissions: int | None


def _sortKey(entry: FileEntry) -> tuple[bool, str, str]:
    return (not entry.isDir, entry.name.lower(), entry.name)


def listLocalDir(path: Path) -> list[FileEntry]:
    """List a local folder, folders first then names case-insensitively. Raises OSError."""
    entries: list[FileEntry] = []
    for child in path.iterdir():
        try:
            info = child.stat()
        except OSError:
            try:
                info = child.lstat()
            except OSError:
                continue
        entries.append(
            FileEntry(
                name=child.name,
                path=str(child),
                size=0 if stat.S_ISDIR(info.st_mode) else info.st_size,
                isDir=stat.S_ISDIR(info.st_mode),
                modified=info.st_mtime,
                permissions=stat.S_IMODE(info.st_mode),
            )
        )
    return sorted(entries, key=_sortKey)


def renameLocal(source: Path, destination: Path) -> None:
    """Rename a local path, refusing to replace whatever is already at ``destination``. Raises OSError."""
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"{destination} already exists")
    source.rename(destination)


def removeLocal(path: Path) -> None:
    """Delete a local file, symlink, or empty folder. Raises OSError, including for a folder with contents."""
    if path.is_dir() and not path.is_symlink():
        path.rmdir()
    else:
        path.unlink()


def localRoots() -> list[str]:
    """The top-level places a local pane can start from: drives on Windows, ``/`` elsewhere."""
    if os.name == "nt":
        return list(os.listdrives())
    return ["/"]


def _entryFromAttributes(name: str, path: str, attributes: paramiko.SFTPAttributes) -> FileEntry:
    mode = attributes.st_mode
    return FileEntry(
        name=name,
        path=path,
        size=0 if mode is not None and stat.S_ISDIR(mode) else (attributes.st_size or 0),
        isDir=mode is not None and stat.S_ISDIR(mode),
        modified=float(attributes.st_mtime) if attributes.st_mtime is not None else None,
        permissions=stat.S_IMODE(mode) if mode is not None else None,
    )


def _followLink(channel: paramiko.SFTPClient, path: str, attributes: paramiko.SFTPAttributes) -> paramiko.SFTPAttributes:
    """What a symlink points at, so a link to a folder opens as one. A dangling link keeps its own attributes."""
    if attributes.st_mode is None or not stat.S_ISLNK(attributes.st_mode):
        return attributes
    try:
        return channel.stat(path)
    except (OSError, paramiko.SSHException):
        return attributes


def _checkCancel(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise TransferCancelled()


def _removeQuietly(remove: Callable[[], None]) -> None:
    try:
        remove()
    except OSError:
        pass


class SftpSession:
    """Browsing and transfers for one host. Close it when the tab goes away."""

    def __init__(self, client: SshClient) -> None:
        self._browse = client.openSftp()
        self._transfer = client.openSftp()

    def close(self) -> None:
        """Close both channels. Safe to call repeatedly."""
        for channel in (self._browse, self._transfer):
            try:
                channel.close()
            except (OSError, EOFError, paramiko.SSHException):
                pass

    # Browsing

    def home(self) -> str:
        """The remote path the server starts us in."""
        try:
            return self._browse.normalize(".")
        except (OSError, paramiko.SSHException) as error:
            raise SftpError(f"Could not resolve the home folder: {error}") from error

    def listDir(self, path: str) -> list[FileEntry]:
        """List a remote folder, folders first then names case-insensitively."""
        return self._listWith(self._browse, path)

    def stat(self, path: str) -> FileEntry | None:
        """Describe a remote path, or None when nothing is there."""
        try:
            attributes = self._browse.stat(path)
        except FileNotFoundError:
            return None
        except (OSError, paramiko.SSHException) as error:
            raise SftpError(f"Could not read {path}: {error}") from error
        return _entryFromAttributes(posixpath.basename(path), path, attributes)

    def mkdir(self, path: str) -> None:
        """Create a remote folder."""
        try:
            self._browse.mkdir(path)
        except (OSError, paramiko.SSHException) as error:
            raise SftpError(f"Could not create {path}: {error}") from error

    def remove(self, path: str) -> None:
        """Delete a remote file or an empty folder."""
        entry = self.stat(path)
        if entry is None:
            raise SftpError(f"Could not remove {path}: it does not exist")
        try:
            if entry.isDir:
                self._browse.rmdir(path)
            else:
                self._browse.remove(path)
        except (OSError, paramiko.SSHException) as error:
            raise SftpError(f"Could not remove {path}: {error}") from error

    def rename(self, source: str, destination: str) -> None:
        """Rename or move a remote path."""
        try:
            self._browse.rename(source, destination)
        except (OSError, paramiko.SSHException) as error:
            raise SftpError(f"Could not rename {source} to {destination}: {error}") from error

    @staticmethod
    def _listWith(channel: paramiko.SFTPClient, path: str) -> list[FileEntry]:
        try:
            attributes = channel.listdir_attr(path)
        except (OSError, paramiko.SSHException) as error:
            raise SftpError(f"Could not list {path}: {error}") from error
        entries: list[FileEntry] = []
        for attr in attributes:
            childPath = posixpath.join(path, attr.filename)
            entries.append(_entryFromAttributes(attr.filename, childPath, _followLink(channel, childPath, attr)))
        return sorted(entries, key=_sortKey)

    # Transfers

    def upload(self, local: Path, remote: str, onProgress: ProgressCallback, cancel: threading.Event) -> TransferResult:
        """Copy a local file or folder to the remote path ``remote``."""
        if not local.exists():
            raise SftpError(f"{local} is missing")
        skipped: list[str] = []
        items = self._planLocal(local, remote, skipped)
        return self._run(items, skipped, onProgress, cancel, self._uploadFile, self._ensureRemoteDir, self._removeRemote)

    def download(self, remote: str, local: Path, onProgress: ProgressCallback, cancel: threading.Event) -> TransferResult:
        """Copy a remote file or folder to the local path ``local``."""
        try:
            attributes = self._transfer.stat(remote)
        except (OSError, paramiko.SSHException) as error:
            raise SftpError(f"{remote} is missing: {error}") from error
        skipped: list[str] = []
        items = self._planRemote(remote, attributes, local, skipped)
        local.parent.mkdir(parents=True, exist_ok=True)
        return self._run(items, skipped, onProgress, cancel, self._downloadFile, self._ensureLocalDir, self._removeLocal)

    def _planLocal(self, local: Path, remote: str, skipped: list[str]) -> list[_Item]:
        """Everything under ``local`` in creation order, folders before their contents."""
        info = local.lstat()
        if stat.S_ISREG(info.st_mode):
            return [_Item(local.name, str(local), remote, False, info.st_size, stat.S_IMODE(info.st_mode))]
        if not stat.S_ISDIR(info.st_mode):
            skipped.append(f"{local}: not a regular file or folder")
            return []
        items = [_Item(local.name, str(local), remote, True, 0, stat.S_IMODE(info.st_mode))]
        for child in sorted(local.iterdir(), key=lambda p: p.name.lower()):
            try:
                childInfo = child.lstat()
            except OSError as error:
                skipped.append(f"{child}: {error}")
                continue
            if stat.S_ISLNK(childInfo.st_mode):
                skipped.append(f"{child}: symlinks are skipped")
            elif stat.S_ISDIR(childInfo.st_mode) or stat.S_ISREG(childInfo.st_mode):
                items.extend(self._planLocal(child, posixpath.join(remote, child.name), skipped))
            else:
                skipped.append(f"{child}: not a regular file or folder")
        return items

    def _planRemote(
        self, remote: str, attributes: paramiko.SFTPAttributes, local: Path, skipped: list[str]
    ) -> list[_Item]:
        """Everything under ``remote`` in creation order, folders before their contents."""
        mode = attributes.st_mode or 0
        name = posixpath.basename(remote)
        permissions = stat.S_IMODE(mode) if attributes.st_mode is not None else None
        if stat.S_ISREG(mode):
            return [_Item(name, remote, str(local), False, attributes.st_size or 0, permissions)]
        if not stat.S_ISDIR(mode):
            skipped.append(f"{remote}: not a regular file or folder")
            return []
        items = [_Item(name, remote, str(local), True, 0, permissions)]
        try:
            children = self._transfer.listdir_attr(remote)
        except (OSError, paramiko.SSHException) as error:
            skipped.append(f"{remote}: {error}")
            return items
        for child in sorted(children, key=lambda attr: attr.filename.lower()):
            childPath = posixpath.join(remote, child.filename)
            childMode = child.st_mode or 0
            if stat.S_ISLNK(childMode):
                skipped.append(f"{childPath}: symlinks are skipped")
            elif stat.S_ISDIR(childMode) or stat.S_ISREG(childMode):
                items.extend(self._planRemote(childPath, child, local / child.filename, skipped))
            else:
                skipped.append(f"{childPath}: not a regular file or folder")
        return items

    def _run(
        self,
        items: list[_Item],
        skipped: list[str],
        onProgress: ProgressCallback,
        cancel: threading.Event,
        copyFile: Callable[[_Item, Callable[[int], None], threading.Event], None],
        ensureDir: Callable[[_Item], None],
        removePartial: Callable[[_Item], None],
    ) -> TransferResult:
        files = [item for item in items if not item.isDir]
        bytesTotal = sum(item.size for item in files)
        result = TransferResult(skipped=skipped)

        def report(current: str, bytesDone: int) -> None:
            onProgress(TransferProgress(current, bytesDone, bytesTotal, result.filesDone, len(files)))

        report("", 0)
        for item in items:
            _checkCancel(cancel)
            if item.isDir:
                try:
                    ensureDir(item)
                except OSError as error:
                    skipped.append(f"{item.destination}: {error}")
                continue
            try:
                copyFile(item, lambda done: report(item.name, result.bytesDone + done), cancel)
            except TransferCancelled:
                removePartial(item)
                raise
            except OSError as error:
                removePartial(item)
                skipped.append(f"{item.source}: {error}")
                continue
            result.filesDone += 1
            result.bytesDone += item.size
            report(item.name, result.bytesDone)
        return result

    # Upload primitives

    def _ensureRemoteDir(self, item: _Item) -> None:
        try:
            existing = self._transfer.stat(item.destination)
        except FileNotFoundError:
            self._transfer.mkdir(item.destination)
            if item.permissions is not None:
                _removeQuietly(lambda: self._transfer.chmod(item.destination, item.permissions or 0))
            return
        if existing.st_mode is None or not stat.S_ISDIR(existing.st_mode):
            raise OSError(f"{item.destination} exists and is not a folder")

    def _uploadFile(self, item: _Item, onBytes: Callable[[int], None], cancel: threading.Event) -> None:
        with open(item.source, "rb") as source, self._transfer.open(item.destination, "wb") as destination:
            destination.set_pipelined(True)
            done = 0
            while True:
                _checkCancel(cancel)
                chunk = source.read(CHUNK_BYTES)
                if not chunk:
                    break
                destination.write(chunk)
                done += len(chunk)
                onBytes(done)
        if item.permissions is not None:
            _removeQuietly(lambda: self._transfer.chmod(item.destination, item.permissions or 0))

    def _removeRemote(self, item: _Item) -> None:
        _removeQuietly(lambda: self._transfer.remove(item.destination))

    # Download primitives

    @staticmethod
    def _ensureLocalDir(item: _Item) -> None:
        path = Path(item.destination)
        if path.exists() and not path.is_dir():
            raise OSError(f"{path} exists and is not a folder")
        path.mkdir(parents=True, exist_ok=True)
        if item.permissions is not None and os.name != "nt":
            _removeQuietly(lambda: os.chmod(path, item.permissions or 0))

    def _downloadFile(self, item: _Item, onBytes: Callable[[int], None], cancel: threading.Event) -> None:
        with self._transfer.open(item.source, "rb") as source, open(item.destination, "wb") as destination:
            source.prefetch(item.size)
            done = 0
            while True:
                _checkCancel(cancel)
                chunk = source.read(CHUNK_BYTES)
                if not chunk:
                    break
                destination.write(chunk)
                done += len(chunk)
                onBytes(done)
        if item.permissions is not None and os.name != "nt":
            _removeQuietly(lambda: os.chmod(item.destination, item.permissions or 0))

    @staticmethod
    def _removeLocal(item: _Item) -> None:
        _removeQuietly(lambda: os.remove(item.destination))
