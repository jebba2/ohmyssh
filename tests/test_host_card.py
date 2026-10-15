"""Tests for the dashboard host card."""

from __future__ import annotations

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from pyommyssh.core.hosts import Host
from pyommyssh.core.metrics import HostMetrics, ProcessInfo
from pyommyssh.ui.hostCard import HostCard, usageLevel

METRICS = HostMetrics(
    osName="Ubuntu 24.04.1 LTS",
    cpuPercent=11.1,
    memPercent=53.83,
    memTotalBytes=16675868672,
    diskPercent=92.0,
    uptime="12 days",
    loadAverage=(0.52, 0.58, 0.59),
    dockerContainers=3,
    processes=[
        ProcessInfo(name="python3", cpuPercent=12.3, memPercent=4.5),
        ProcessInfo(name="postgres", cpuPercent=3.2, memPercent=10.1),
    ],
)


def _host() -> Host:
    return Host(name="web", hostname="10.0.0.5", user="deploy", port=2222, tags=["prod"])


def test_card_shows_name_and_address(qtbot: QtBot) -> None:
    card = HostCard(_host())
    qtbot.addWidget(card)
    assert card.nameLabel.text() == "web"
    assert card.addressLabel.text() == "deploy@10.0.0.5:2222"
    assert card.statusLabel.text() == "Not checked yet"


def test_set_metrics_fills_bars_and_labels(qtbot: QtBot) -> None:
    card = HostCard(_host())
    qtbot.addWidget(card)
    card.setMetrics(METRICS)
    assert card.cpuBar.value() == 11
    assert card.memBar.value() == 54
    assert card.diskBar.value() == 92
    assert card.osLabel.text() == "Ubuntu 24.04.1 LTS"
    assert card.uptimeLabel.text() == "up 12 days"
    assert card.loadLabel.text() == "load 0.52 0.58 0.59"
    assert card.dockerBadge.text() == "3 containers"
    assert not card.dockerBadge.isHidden()
    assert card.processesLabel.text() == "python3 12.3%  postgres 3.2%"
    assert card.statusLabel.text() == "Online"


def test_set_metrics_with_unknown_values(qtbot: QtBot) -> None:
    card = HostCard(_host())
    qtbot.addWidget(card)
    card.setMetrics(HostMetrics())
    assert card.cpuBar.value() == 0
    assert card.cpuBar.format() == "CPU n/a"
    assert card.osLabel.text() == "Unknown OS"
    assert card.uptimeLabel.text() == ""
    assert card.dockerBadge.isHidden()
    assert card.processesLabel.text() == ""
    assert card.statusLabel.text() == "Online"


def test_set_error_shows_message_and_resets_bars(qtbot: QtBot) -> None:
    card = HostCard(_host())
    qtbot.addWidget(card)
    card.setMetrics(METRICS)
    card.setError("Could not reach deploy@10.0.0.5:2222")
    assert card.statusLabel.text() == "Could not reach deploy@10.0.0.5:2222"
    assert card.cpuBar.value() == 0
    assert card.cpuBar.format() == "CPU n/a"


def test_set_connecting(qtbot: QtBot) -> None:
    card = HostCard(_host())
    qtbot.addWidget(card)
    card.setConnecting()
    assert card.statusLabel.text() == "Connecting..."


def test_double_click_requests_terminal(qtbot: QtBot) -> None:
    card = HostCard(_host())
    qtbot.addWidget(card)
    with qtbot.waitSignal(card.openTerminalRequested) as blocker:
        qtbot.mouseDClick(card, Qt.MouseButton.LeftButton)
    assert blocker.args == [_host()]


def test_usage_level_thresholds() -> None:
    assert usageLevel(0) == "ok"
    assert usageLevel(59.9) == "ok"
    assert usageLevel(60) == "warn"
    assert usageLevel(84.9) == "warn"
    assert usageLevel(85) == "critical"
    assert usageLevel(100) == "critical"


def test_bars_carry_usage_level_property(qtbot: QtBot) -> None:
    card = HostCard(_host())
    qtbot.addWidget(card)
    card.setMetrics(METRICS)
    assert card.cpuBar.property("usageLevel") == "ok"
    assert card.diskBar.property("usageLevel") == "critical"
