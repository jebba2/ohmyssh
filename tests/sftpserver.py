"""An SFTP subsystem for the test SSH server, rooted in a local directory.

Remote paths are POSIX and absolute; ``/`` maps to the root directory. A
set of refused names lets tests simulate server-side permission errors on
particular files.
"""

from __future__ import annotations

import os
import posixpath
from pathlib import Path
from typing import BinaryIO

import paramiko
from paramiko import SFTPAttributes, SFTPHandle, SFTPServer, SFTPServerInterface
from paramiko.sftp import SFTP_FAILURE, SFTP_NO_SUCH_FILE, SFTP_OK, SFTP_OP_UNSUPPORTED, SFTP_PERMISSION_DENIED


def _statusFor(error: OSError) -> int:
    if isinstance(error, FileNotFoundError):
        return SFTP_NO_SUCH_FILE
    if isinstance(error, PermissionError):
        return SFTP_PERMISSION_DENIED
    return SFTP_FAILURE


class _FileHandle(SFTPHandle):
    """An open file; paramiko's base class reads and writes through these attributes."""

    def __init__(self, flags: int, path: Path, handle: BinaryIO) -> None:
        super().__init__(flags)
        self.filename = str(path)
        self.readfile = handle
        self.writefile = handle

    def stat(self) -> SFTPAttributes | int:
        try:
            return SFTPAttributes.from_stat(os.fstat(self.readfile.fileno()))
        except OSError as error:
            return _statusFor(error)

    def chattr(self, attr: SFTPAttributes) -> int:
        try:
            SFTPServer.set_file_attr(self.filename, attr)
            return SFTP_OK
        except OSError as error:
            return _statusFor(error)


class DirectorySftpServer(SFTPServerInterface):
    """Serves a directory tree over SFTP, refusing any file whose name is in ``refusedNames``."""

    def __init__(self, server: paramiko.ServerInterface, root: Path, refusedNames: set[str]) -> None:
        super().__init__(server)
        self._root = root
        self._refusedNames = refusedNames

    def canonicalize(self, path: str) -> str:
        return posixpath.normpath(posixpath.join("/", path))

    def _realpath(self, path: str) -> Path:
        relative = self.canonicalize(path).lstrip("/")
        return self._root.joinpath(*relative.split("/")) if relative else self._root

    def _refused(self, path: str) -> bool:
        return posixpath.basename(self.canonicalize(path)) in self._refusedNames

    def list_folder(self, path: str) -> list[SFTPAttributes] | int:
        try:
            entries: list[SFTPAttributes] = []
            for child in self._realpath(path).iterdir():
                attributes = SFTPAttributes.from_stat(os.lstat(child))
                attributes.filename = child.name
                entries.append(attributes)
            return entries
        except OSError as error:
            return _statusFor(error)

    def stat(self, path: str) -> SFTPAttributes | int:
        try:
            return SFTPAttributes.from_stat(os.stat(self._realpath(path)))
        except OSError as error:
            return _statusFor(error)

    def lstat(self, path: str) -> SFTPAttributes | int:
        try:
            return SFTPAttributes.from_stat(os.lstat(self._realpath(path)))
        except OSError as error:
            return _statusFor(error)

    def open(self, path: str, flags: int, attr: SFTPAttributes) -> SFTPHandle | int:
        if self._refused(path):
            return SFTP_PERMISSION_DENIED
        realPath = self._realpath(path)
        flags |= getattr(os, "O_BINARY", 0)
        mode = getattr(attr, "st_mode", None) or 0o666
        try:
            descriptor = os.open(realPath, flags, mode)
            if flags & os.O_WRONLY:
                openMode = "ab" if flags & os.O_APPEND else "wb"
            elif flags & os.O_RDWR:
                openMode = "a+b" if flags & os.O_APPEND else "r+b"
            else:
                openMode = "rb"
            handle = os.fdopen(descriptor, openMode)
        except OSError as error:
            return _statusFor(error)
        return _FileHandle(flags, realPath, handle)

    def remove(self, path: str) -> int:
        try:
            os.remove(self._realpath(path))
            return SFTP_OK
        except OSError as error:
            return _statusFor(error)

    def rename(self, oldpath: str, newpath: str) -> int:
        try:
            os.rename(self._realpath(oldpath), self._realpath(newpath))
            return SFTP_OK
        except OSError as error:
            return _statusFor(error)

    def posix_rename(self, oldpath: str, newpath: str) -> int:
        return self.rename(oldpath, newpath)

    def mkdir(self, path: str, attr: SFTPAttributes) -> int:
        try:
            realPath = self._realpath(path)
            os.mkdir(realPath)
            if attr is not None:
                SFTPServer.set_file_attr(str(realPath), attr)
            return SFTP_OK
        except OSError as error:
            return _statusFor(error)

    def rmdir(self, path: str) -> int:
        try:
            os.rmdir(self._realpath(path))
            return SFTP_OK
        except OSError as error:
            return _statusFor(error)

    def chattr(self, path: str, attr: SFTPAttributes) -> int:
        try:
            SFTPServer.set_file_attr(str(self._realpath(path)), attr)
            return SFTP_OK
        except OSError as error:
            return _statusFor(error)

    def symlink(self, target_path: str, path: str) -> int:
        return SFTP_OP_UNSUPPORTED

    def readlink(self, path: str) -> str | int:
        return SFTP_OP_UNSUPPORTED
