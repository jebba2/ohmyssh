"""Tests for the SFTP session and local listing against the in-process SFTP server."""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from ohmyssh.core.sftp import (
    FileEntry,
    SftpError,
    SftpSession,
    TransferCancelled,
    TransferProgress,
    listLocalDir,
    localRoots,
)
from ohmyssh.core.ssh import SshClient, SshCredentials
from tests.sshserver import TEST_PASSWORD, TestSshServer, hostFor


def _root(server: TestSshServer) -> Path:
    assert server.sftpRoot is not None
    return server.sftpRoot


@pytest.fixture
def session(sftpServer: TestSshServer, tmp_path: Path) -> Iterator[SftpSession]:
    client = SshClient(
        hostFor(sftpServer), credentials=SshCredentials(password=TEST_PASSWORD), knownHostsPath=tmp_path / "kh"
    )
    client.connect()
    sftp = SftpSession(client)
    yield sftp
    sftp.close()
    client.close()


def _never() -> threading.Event:
    return threading.Event()


def _ignoreProgress(_: TransferProgress) -> None:
    pass


# Local listing


def test_list_local_dir_sorts_folders_first_then_names(tmp_path: Path) -> None:
    (tmp_path / "b.txt").write_bytes(b"12345")
    (tmp_path / "A.txt").write_bytes(b"")
    (tmp_path / "zdir").mkdir()
    (tmp_path / "Adir").mkdir()
    (tmp_path / ".hidden").write_bytes(b"x")
    entries = listLocalDir(tmp_path)
    assert [entry.name for entry in entries] == ["Adir", "zdir", ".hidden", "A.txt", "b.txt"]
    byName = {entry.name: entry for entry in entries}
    assert byName["b.txt"].size == 5
    assert byName["b.txt"].path == str(tmp_path / "b.txt")
    assert not byName["b.txt"].isDir
    assert byName["Adir"].isDir
    assert byName["b.txt"].modified is not None


def test_list_local_dir_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        listLocalDir(tmp_path / "missing")


def test_local_roots() -> None:
    roots = localRoots()
    if os.name == "nt":
        assert roots and all(root.endswith(":\\") for root in roots)
    else:
        assert roots == ["/"]


# Remote browsing


def test_home_and_list_remote(sftpServer: TestSshServer, session: SftpSession) -> None:
    root = _root(sftpServer)
    (root / "docs").mkdir()
    (root / "docs" / "a.txt").write_bytes(b"hello")
    (root / "b.bin").write_bytes(b"\x00" * 10)
    assert session.home() == "/"
    assert [entry.name for entry in session.listDir("/")] == ["docs", "b.bin"]
    entries = session.listDir("/docs")
    assert entries == [
        FileEntry(
            name="a.txt", path="/docs/a.txt", size=5, isDir=False,
            modified=entries[0].modified, permissions=entries[0].permissions,
        )
    ]
    assert entries[0].modified is not None
    assert entries[0].permissions is not None


def test_list_remote_follows_symlinks(sftpServer: TestSshServer, session: SftpSession) -> None:
    root = _root(sftpServer)
    (root / "real").mkdir()
    (root / "real" / "inside.txt").write_bytes(b"inside")
    (root / "file.txt").write_bytes(b"12345")
    try:
        os.symlink(root / "real", root / "linkdir")
        os.symlink(root / "file.txt", root / "linkfile")
        os.symlink(root / "gone", root / "dangling")
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symlinks here")
    byName = {entry.name: entry for entry in session.listDir("/")}
    assert byName["linkdir"].isDir and byName["linkdir"].size == 0
    assert not byName["linkfile"].isDir and byName["linkfile"].size == 5
    assert "dangling" in byName and not byName["dangling"].isDir
    assert [entry.name for entry in session.listDir("/")][:2] == ["linkdir", "real"]
    assert [entry.name for entry in session.listDir("/linkdir")] == ["inside.txt"]


def test_stat_remote(sftpServer: TestSshServer, session: SftpSession) -> None:
    (_root(sftpServer) / "docs").mkdir()
    folder = session.stat("/docs")
    assert folder is not None and folder.isDir and folder.name == "docs"
    assert session.stat("/nope") is None


def test_mkdir_rename_remove(sftpServer: TestSshServer, session: SftpSession) -> None:
    root = _root(sftpServer)
    session.mkdir("/new")
    assert (root / "new").is_dir()
    session.rename("/new", "/renamed")
    assert (root / "renamed").is_dir() and not (root / "new").exists()
    (root / "renamed" / "file.txt").write_bytes(b"x")
    with pytest.raises(SftpError):
        session.remove("/renamed")
    session.remove("/renamed/file.txt")
    session.remove("/renamed")
    assert not (root / "renamed").exists()


def test_remote_errors_are_sftp_errors(sftpServer: TestSshServer, session: SftpSession) -> None:
    with pytest.raises(SftpError, match="/missing"):
        session.listDir("/missing")
    (_root(sftpServer) / "taken").mkdir()
    with pytest.raises(SftpError, match="/taken"):
        session.mkdir("/taken")


# Transfers


def test_upload_and_download_a_file(sftpServer: TestSshServer, session: SftpSession, tmp_path: Path) -> None:
    payload = os.urandom(100_000)
    local = tmp_path / "up.bin"
    local.write_bytes(payload)
    result = session.upload(local, "/up.bin", _ignoreProgress, _never())
    assert (_root(sftpServer) / "up.bin").read_bytes() == payload
    assert (result.filesDone, result.bytesDone, result.skipped) == (1, len(payload), [])

    target = tmp_path / "down.bin"
    result = session.download("/up.bin", target, _ignoreProgress, _never())
    assert target.read_bytes() == payload
    assert (result.filesDone, result.bytesDone) == (1, len(payload))


def test_upload_folder_recursively_merging_into_an_existing_one(
    sftpServer: TestSshServer, session: SftpSession, tmp_path: Path
) -> None:
    source = tmp_path / "dir"
    (source / "sub").mkdir(parents=True)
    (source / "a.txt").write_bytes(b"a")
    (source / "sub" / "b.txt").write_bytes(b"bb")
    remote = _root(sftpServer) / "dir"
    remote.mkdir()
    (remote / "existing.txt").write_bytes(b"keep")

    result = session.upload(source, "/dir", _ignoreProgress, _never())
    assert (remote / "a.txt").read_bytes() == b"a"
    assert (remote / "sub" / "b.txt").read_bytes() == b"bb"
    assert (remote / "existing.txt").read_bytes() == b"keep"
    assert (result.filesDone, result.bytesDone, result.skipped) == (2, 3, [])


def test_download_folder_recursively(sftpServer: TestSshServer, session: SftpSession, tmp_path: Path) -> None:
    root = _root(sftpServer)
    (root / "tree" / "deep").mkdir(parents=True)
    (root / "tree" / "one.txt").write_bytes(b"1")
    (root / "tree" / "deep" / "two.txt").write_bytes(b"22")
    target = tmp_path / "local" / "tree"
    result = session.download("/tree", target, _ignoreProgress, _never())
    assert (target / "one.txt").read_bytes() == b"1"
    assert (target / "deep" / "two.txt").read_bytes() == b"22"
    assert result.filesDone == 2


def test_upload_replaces_an_existing_file(sftpServer: TestSshServer, session: SftpSession, tmp_path: Path) -> None:
    remote = _root(sftpServer) / "f.txt"
    remote.write_bytes(b"old content that is longer")
    local = tmp_path / "f.txt"
    local.write_bytes(b"new")
    session.upload(local, "/f.txt", _ignoreProgress, _never())
    assert remote.read_bytes() == b"new"


def test_progress_reports_totals_and_current_file(
    sftpServer: TestSshServer, session: SftpSession, tmp_path: Path
) -> None:
    source = tmp_path / "batch"
    source.mkdir()
    for name, size in (("a", 1000), ("b", 2000), ("c", 3000)):
        (source / name).write_bytes(b"x" * size)
    reports: list[TransferProgress] = []
    session.upload(source, "/batch", reports.append, _never())
    assert reports[0].bytesTotal == 6000
    assert reports[0].filesTotal == 3
    assert reports[-1].bytesDone == 6000
    assert reports[-1].filesDone == 3
    assert {report.currentFile for report in reports} >= {"a", "b", "c"}
    assert all(report.bytesDone <= report.bytesTotal for report in reports)


def test_cancel_stops_the_transfer_and_removes_the_partial_file(
    sftpServer: TestSshServer, session: SftpSession, tmp_path: Path
) -> None:
    local = tmp_path / "big.bin"
    local.write_bytes(os.urandom(5 * 1024 * 1024))
    cancel = threading.Event()
    seen: list[TransferProgress] = []

    def cancelAfterFirstChunk(progress: TransferProgress) -> None:
        seen.append(progress)
        if progress.bytesDone > 0:
            cancel.set()

    with pytest.raises(TransferCancelled):
        session.upload(local, "/big.bin", cancelAfterFirstChunk, cancel)
    assert seen[-1].bytesDone < seen[-1].bytesTotal
    assert not (_root(sftpServer) / "big.bin").exists()

    (_root(sftpServer) / "big.bin").write_bytes(os.urandom(5 * 1024 * 1024))
    cancel.clear()
    seen.clear()
    with pytest.raises(TransferCancelled):
        session.download("/big.bin", tmp_path / "partial.bin", cancelAfterFirstChunk, cancel)
    assert not (tmp_path / "partial.bin").exists()


def test_refused_files_are_skipped_and_the_rest_transferred(
    sftpServer: TestSshServer, session: SftpSession, tmp_path: Path
) -> None:
    sftpServer.sftpRefusedNames.add("secret.txt")
    source = tmp_path / "mixed"
    source.mkdir()
    (source / "ok.txt").write_bytes(b"ok")
    (source / "secret.txt").write_bytes(b"shh")
    result = session.upload(source, "/mixed", _ignoreProgress, _never())
    assert (_root(sftpServer) / "mixed" / "ok.txt").read_bytes() == b"ok"
    assert not (_root(sftpServer) / "mixed" / "secret.txt").exists()
    assert result.filesDone == 1
    assert len(result.skipped) == 1 and "secret.txt" in result.skipped[0]

    (_root(sftpServer) / "mixed" / "secret.txt").write_bytes(b"shh")
    result = session.download("/mixed", tmp_path / "got", _ignoreProgress, _never())
    assert (tmp_path / "got" / "ok.txt").read_bytes() == b"ok"
    assert not (tmp_path / "got" / "secret.txt").exists()
    assert result.filesDone == 1 and "secret.txt" in result.skipped[0]


def test_upload_skips_symlinks_inside_a_folder(
    sftpServer: TestSshServer, session: SftpSession, tmp_path: Path
) -> None:
    source = tmp_path / "links"
    source.mkdir()
    (source / "real.txt").write_bytes(b"real")
    try:
        os.symlink(source / "real.txt", source / "link.txt")
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symlinks here")
    result = session.upload(source, "/links", _ignoreProgress, _never())
    assert (_root(sftpServer) / "links" / "real.txt").exists()
    assert not (_root(sftpServer) / "links" / "link.txt").exists()
    assert result.filesDone == 1 and "link.txt" in result.skipped[0]


@pytest.mark.skipif(os.name == "nt", reason="permission bits are not meaningful on Windows")
def test_transfers_preserve_permission_bits(
    sftpServer: TestSshServer, session: SftpSession, tmp_path: Path
) -> None:
    local = tmp_path / "run.sh"
    local.write_bytes(b"#!/bin/sh\n")
    local.chmod(0o750)
    session.upload(local, "/run.sh", _ignoreProgress, _never())
    assert (_root(sftpServer) / "run.sh").stat().st_mode & 0o777 == 0o750
    session.download("/run.sh", tmp_path / "back.sh", _ignoreProgress, _never())
    assert (tmp_path / "back.sh").stat().st_mode & 0o777 == 0o750


def test_upload_of_a_missing_source_is_an_error(session: SftpSession, tmp_path: Path) -> None:
    with pytest.raises(SftpError, match="missing"):
        session.upload(tmp_path / "missing", "/x", _ignoreProgress, _never())
