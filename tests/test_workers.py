"""Tests for the background workers against the in-process SSH server."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThreadPool
from pytestqt.qtbot import QtBot

from pyommyssh.core.connections import ConnectionPool
from pyommyssh.core.metrics import HostMetrics
from pyommyssh.core.ssh import SshCredentials
from pyommyssh.ui.workers import MetricsWorker, ShellOpener, TerminalReader
from tests.sshserver import SHELL_BANNER, TEST_PASSWORD, TestSshServer, hostFor


def test_metrics_worker_reports_metrics(qtbot: QtBot, sshServer: TestSshServer, tmp_path: Path) -> None:
    host = hostFor(sshServer)
    pool = ConnectionPool(lambda: [host], knownHostsPath=tmp_path / "known_hosts")
    pool.setCredentials(host.name, SshCredentials(password=TEST_PASSWORD))
    worker = MetricsWorker(host, pool)
    with qtbot.waitSignal(worker.signals.metricsReady, timeout=10000) as blocker:
        QThreadPool.globalInstance().start(worker)
    name, metrics = blocker.args
    assert name == "box"
    assert isinstance(metrics, HostMetrics)
    assert any("===PYOMMYSSH:CPU===" in command for command in sshServer.commands)
    pool.closeAll()


def test_metrics_worker_reports_auth_required(
    qtbot: QtBot, sshServer: TestSshServer, tmp_path: Path
) -> None:
    host = hostFor(sshServer)
    pool = ConnectionPool(lambda: [host], knownHostsPath=tmp_path / "known_hosts")
    worker = MetricsWorker(host, pool)
    with qtbot.waitSignal(worker.signals.authRequired, timeout=10000) as blocker:
        QThreadPool.globalInstance().start(worker)
    assert blocker.args == ["box"]


def test_metrics_worker_reports_failure(qtbot: QtBot, tmp_path: Path) -> None:
    from pyommyssh.core.hosts import Host

    host = Host(name="dead", hostname="127.0.0.1", user="x", port=1)
    pool = ConnectionPool(lambda: [host], knownHostsPath=tmp_path / "known_hosts")
    worker = MetricsWorker(host, pool)
    with qtbot.waitSignal(worker.signals.metricsFailed, timeout=10000) as blocker:
        QThreadPool.globalInstance().start(worker)
    name, message = blocker.args
    assert name == "dead"
    assert "Could not reach" in message


def test_shell_opener_and_reader_round_trip(
    qtbot: QtBot, sshServer: TestSshServer, tmp_path: Path
) -> None:
    host = hostFor(sshServer)
    pool = ConnectionPool(lambda: [host], knownHostsPath=tmp_path / "known_hosts")
    pool.setCredentials(host.name, SshCredentials(password=TEST_PASSWORD))
    opener = ShellOpener(host, pool, cols=90, rows=25)
    with qtbot.waitSignal(opener.signals.opened, timeout=10000) as blocker:
        QThreadPool.globalInstance().start(opener)
    channel = blocker.args[0]
    assert sshServer.ptyRequests == [("xterm-256color", 90, 25)]

    reader = TerminalReader(channel)
    received: list[bytes] = []
    reader.dataReceived.connect(received.append)
    reader.start()
    qtbot.waitUntil(lambda: SHELL_BANNER in b"".join(received), timeout=10000)

    channel.sendall(b"echo hi\r")
    qtbot.waitUntil(lambda: b"echo hi\r" in b"".join(received), timeout=10000)

    with qtbot.waitSignal(reader.closed, timeout=10000):
        reader.stop()
    assert reader.wait(5000)
    pool.closeAll()


def test_shell_opener_reports_auth_required(
    qtbot: QtBot, sshServer: TestSshServer, tmp_path: Path
) -> None:
    host = hostFor(sshServer)
    pool = ConnectionPool(lambda: [host], knownHostsPath=tmp_path / "known_hosts")
    opener = ShellOpener(host, pool, cols=80, rows=24)
    with qtbot.waitSignal(opener.signals.authRequired, timeout=10000):
        QThreadPool.globalInstance().start(opener)
