"""Tests for the SFTP bridge that runs the session on worker threads for the GUI."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from ohmyssh.core.connections import ConnectionPool
from ohmyssh.core.hosts import Host
from ohmyssh.core.sftp import FileEntry, TransferProgress, TransferResult
from ohmyssh.core.ssh import SshCredentials
from ohmyssh.ui.sftpBridge import SftpBridge
from tests.sshserver import TEST_PASSWORD, TestSshServer, hostFor

WAIT_MS = 10000


def _root(server: TestSshServer) -> Path:
    assert server.sftpRoot is not None
    return server.sftpRoot


@pytest.fixture
def pool(sftpServer: TestSshServer, tmp_path: Path) -> Iterator[ConnectionPool]:
    host = hostFor(sftpServer)
    pool = ConnectionPool(lambda: [host], tmp_path / "kh")
    pool.setCredentials("box", SshCredentials(password=TEST_PASSWORD))
    yield pool
    pool.closeAll()


@pytest.fixture
def bridge(sftpServer: TestSshServer, pool: ConnectionPool) -> Iterator[SftpBridge]:
    bridge = SftpBridge(hostFor(sftpServer), pool)
    yield bridge
    bridge.shutdown()


def test_connects_and_reports_home(qtbot: QtBot, bridge: SftpBridge) -> None:
    with qtbot.waitSignal(bridge.connected, timeout=WAIT_MS) as blocker:
        bridge.start()
    assert blocker.args == ["/"]
    assert bridge.isConnected()


def test_lists_folders_and_reports_failures(qtbot: QtBot, sftpServer: TestSshServer, bridge: SftpBridge) -> None:
    (_root(sftpServer) / "docs").mkdir()
    (_root(sftpServer) / "docs" / "a.txt").write_bytes(b"abc")
    with qtbot.waitSignal(bridge.connected, timeout=WAIT_MS):
        bridge.start()
    with qtbot.waitSignal(bridge.listed, timeout=WAIT_MS) as listed:
        bridge.listDir("/docs")
    assert listed.args is not None
    path, entries = listed.args
    assert path == "/docs"
    assert [(entry.name, entry.size, entry.isDir) for entry in entries] == [("a.txt", 3, False)]
    assert isinstance(entries[0], FileEntry)
    with qtbot.waitSignal(bridge.listFailed, timeout=WAIT_MS) as failed:
        bridge.listDir("/missing")
    assert failed.args is not None
    assert failed.args[0] == "/missing"
    assert "Could not list /missing" in failed.args[1]


def test_remote_operations_report_outcomes(qtbot: QtBot, sftpServer: TestSshServer, bridge: SftpBridge) -> None:
    with qtbot.waitSignal(bridge.connected, timeout=WAIT_MS):
        bridge.start()
    with qtbot.waitSignal(bridge.operationDone, timeout=WAIT_MS) as made:
        bridge.mkdir("/new")
    assert made.args == ["Created /new"]
    assert (_root(sftpServer) / "new").is_dir()
    with qtbot.waitSignal(bridge.operationDone, timeout=WAIT_MS) as renamed:
        bridge.rename("/new", "/renamed")
    assert renamed.args == ["Renamed /new to /renamed"]
    with qtbot.waitSignal(bridge.operationDone, timeout=WAIT_MS) as removed:
        bridge.remove("/renamed")
    assert removed.args == ["Removed /renamed"]
    with qtbot.waitSignal(bridge.operationFailed, timeout=WAIT_MS) as failed:
        bridge.remove("/renamed")
    assert failed.args is not None
    assert "Could not remove /renamed" in failed.args[0]


def test_missing_credentials_report_auth_required(
    qtbot: QtBot, sftpServer: TestSshServer, tmp_path: Path
) -> None:
    pool = ConnectionPool(lambda: [], tmp_path / "kh")
    bridge = SftpBridge(hostFor(sftpServer), pool)
    try:
        with qtbot.waitSignal(bridge.authRequired, timeout=WAIT_MS):
            bridge.start()
        assert not bridge.isConnected()
    finally:
        bridge.shutdown()
        pool.closeAll()


def test_unreachable_host_reports_connect_failure(qtbot: QtBot, tmp_path: Path) -> None:
    host = Host(name="dead", hostname="127.0.0.1", user="x", port=1)
    pool = ConnectionPool(lambda: [host], tmp_path / "kh")
    bridge = SftpBridge(host, pool)
    try:
        with qtbot.waitSignal(bridge.connectFailed, timeout=WAIT_MS) as failed:
            bridge.start()
        assert failed.args is not None
        assert failed.args[0].startswith("Could not reach")
    finally:
        bridge.shutdown()
        pool.closeAll()


def test_upload_and_download_report_progress_finish_and_idle(
    qtbot: QtBot, sftpServer: TestSshServer, bridge: SftpBridge, tmp_path: Path
) -> None:
    with qtbot.waitSignal(bridge.connected, timeout=WAIT_MS):
        bridge.start()
    local = tmp_path / "up.bin"
    local.write_bytes(b"x" * 300_000)
    progress: list[TransferProgress] = []
    started: list[str] = []
    finished: list[tuple[str, TransferResult]] = []
    bridge.transferProgress.connect(progress.append)
    bridge.transferStarted.connect(started.append)
    bridge.transferFinished.connect(lambda label, result: finished.append((label, result)))
    with qtbot.waitSignal(bridge.transfersIdle, timeout=WAIT_MS):
        bridge.upload(local, "/up.bin")
    assert started == ["Uploading up.bin"]
    assert len(finished) == 1 and finished[0][0] == "Uploading up.bin"
    assert finished[0][1].filesDone == 1
    assert (_root(sftpServer) / "up.bin").read_bytes() == b"x" * 300_000
    assert progress[0].bytesTotal == 300_000 and progress[-1].bytesDone == 300_000

    with qtbot.waitSignal(bridge.transfersIdle, timeout=WAIT_MS):
        bridge.download("/up.bin", tmp_path / "down.bin")
    assert started[-1] == "Downloading up.bin"
    assert finished[-1][0] == "Downloading up.bin"
    assert (tmp_path / "down.bin").read_bytes() == b"x" * 300_000


def test_transfer_failure_is_reported(qtbot: QtBot, bridge: SftpBridge, tmp_path: Path) -> None:
    with qtbot.waitSignal(bridge.connected, timeout=WAIT_MS):
        bridge.start()
    with qtbot.waitSignal(bridge.transferFailed, timeout=WAIT_MS) as failed:
        bridge.upload(tmp_path / "missing.txt", "/missing.txt")
    assert failed.args is not None
    assert failed.args[0] == "Uploading missing.txt"
    assert "missing" in failed.args[1]


def test_cancel_stops_the_running_transfer_and_drops_queued_ones(
    qtbot: QtBot, sftpServer: TestSshServer, bridge: SftpBridge, tmp_path: Path
) -> None:
    with qtbot.waitSignal(bridge.connected, timeout=WAIT_MS):
        bridge.start()
    big = tmp_path / "big.bin"
    big.write_bytes(b"\x00" * (8 * 1024 * 1024))
    small = tmp_path / "small.txt"
    small.write_bytes(b"later")

    def cancelOnFirstBytes(progress: TransferProgress) -> None:
        if progress.bytesDone > 0:
            bridge.cancelTransfers()

    bridge.transferProgress.connect(cancelOnFirstBytes)
    with qtbot.waitSignals([bridge.transferCancelled, bridge.transfersIdle], timeout=WAIT_MS):
        bridge.upload(big, "/big.bin")
        bridge.upload(small, "/small.txt")
    qtbot.wait(200)
    assert not (_root(sftpServer) / "big.bin").exists()
    assert not (_root(sftpServer) / "small.txt").exists()

    # A transfer started after the cancel runs normally.
    bridge.transferProgress.disconnect(cancelOnFirstBytes)
    with qtbot.waitSignal(bridge.transferFinished, timeout=WAIT_MS):
        bridge.upload(small, "/small.txt")
    assert (_root(sftpServer) / "small.txt").read_bytes() == b"later"


def test_check_exists_reports_each_remote_path(qtbot: QtBot, sftpServer: TestSshServer, bridge: SftpBridge) -> None:
    (_root(sftpServer) / "there.txt").write_bytes(b"x")
    with qtbot.waitSignal(bridge.connected, timeout=WAIT_MS):
        bridge.start()
    with qtbot.waitSignal(bridge.existenceChecked, timeout=WAIT_MS) as checked:
        bridge.checkExists(["/there.txt", "/not-there.txt"])
    assert checked.args == [{"/there.txt": True, "/not-there.txt": False}]


def test_shutdown_is_safe_before_and_after_connecting(qtbot: QtBot, sftpServer: TestSshServer, pool: ConnectionPool) -> None:
    early = SftpBridge(hostFor(sftpServer), pool)
    early.shutdown()
    late = SftpBridge(hostFor(sftpServer), pool)
    with qtbot.waitSignal(late.connected, timeout=WAIT_MS):
        late.start()
    late.shutdown()
    assert not late.isConnected()
    late.shutdown()
