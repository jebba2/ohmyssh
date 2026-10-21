"""Tests for the dashboard host card."""

from __future__ import annotations

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from pyommyssh.core.forwards import ForwardKind, PortForward
from pyommyssh.core.hosts import Host, HostSource
from pyommyssh.core.metrics import HostMetrics, ProcessInfo
from pyommyssh.core.tunnel import TunnelState, TunnelStatus
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


def _nameRowWidgets(card: HostCard) -> list[object]:
    cardLayout = card.layout()
    assert cardLayout is not None
    nameRowItem = cardLayout.itemAt(0)
    assert nameRowItem is not None
    nameRow = nameRowItem.layout()
    assert nameRow is not None
    widgets: list[object] = []
    for index in range(nameRow.count()):
        item = nameRow.itemAt(index)
        assert item is not None
        widgets.append(item.widget())
    return widgets


def test_terminal_button_sits_beside_name_and_opens_terminal(qtbot: QtBot) -> None:
    card = HostCard(_host())
    qtbot.addWidget(card)
    assert card.terminalButton.toolTip() == "Open terminal"
    assert not card.terminalButton.icon().isNull()
    rowWidgets = _nameRowWidgets(card)
    assert card.nameLabel in rowWidgets
    assert card.terminalButton in rowWidgets
    with qtbot.waitSignal(card.openTerminalRequested) as blocker:
        qtbot.mouseClick(card.terminalButton, Qt.MouseButton.LeftButton)
    assert blocker.args == [_host()]


def test_edit_button_sits_beside_name_and_requests_edit(qtbot: QtBot) -> None:
    card = HostCard(_host())
    qtbot.addWidget(card)
    assert card.editButton.toolTip() == "Edit host"
    assert not card.editButton.icon().isNull()
    assert card.editButton in _nameRowWidgets(card)
    with qtbot.waitSignal(card.editRequested) as blocker:
        qtbot.mouseClick(card.editButton, Qt.MouseButton.LeftButton)
    assert blocker.args == [_host()]


def test_key_button_sits_beside_name_and_requests_key_install(qtbot: QtBot) -> None:
    card = HostCard(_host())
    qtbot.addWidget(card)
    assert card.keyButton.toolTip() == "Install SSH key"
    assert not card.keyButton.icon().isNull()
    assert card.keyButton in _nameRowWidgets(card)
    with qtbot.waitSignal(card.installKeyRequested) as blocker:
        qtbot.mouseClick(card.keyButton, Qt.MouseButton.LeftButton)
    assert blocker.args == [_host()]


def test_edit_button_is_offered_for_ssh_config_hosts_too(qtbot: QtBot) -> None:
    configHost = Host(name="cfg", hostname="cfg.local", source=HostSource.SSH_CONFIG)
    card = HostCard(configHost)
    qtbot.addWidget(card)
    assert not card.editButton.isHidden()
    with qtbot.waitSignal(card.editRequested) as blocker:
        qtbot.mouseClick(card.editButton, Qt.MouseButton.LeftButton)
    assert blocker.args == [configHost]


def test_usage_level_thresholds() -> None:
    assert usageLevel(0) == "ok"
    assert usageLevel(59.9) == "ok"
    assert usageLevel(60) == "warn"
    assert usageLevel(84.9) == "warn"
    assert usageLevel(85) == "critical"
    assert usageLevel(100) == "critical"


def _forwardingHost() -> Host:
    return Host(
        name="web",
        hostname="10.0.0.5",
        forwards=[
            PortForward.parse(ForwardKind.LOCAL, "8080:localhost:80"),
            PortForward.parse(ForwardKind.DYNAMIC, "1080"),
        ],
    )


def test_card_without_forwards_hides_the_tunnel_controls(qtbot: QtBot) -> None:
    card = HostCard(_host())
    qtbot.addWidget(card)
    assert card.forwardsLabel.isHidden()
    assert card.tunnelStatusLabel.isHidden()
    assert card.tunnelButton.isHidden()


def test_card_lists_forwards_and_offers_to_start_the_tunnel(qtbot: QtBot) -> None:
    card = HostCard(_forwardingHost())
    qtbot.addWidget(card)
    assert card.forwardsLabel.text() == "L 8080 -> localhost:80\nD 1080 (SOCKS)"
    assert not card.forwardsLabel.isHidden()
    assert card.tunnelStatusLabel.text() == "Tunnel off"
    assert card.tunnelButton.text() == "Start tunnel"
    with qtbot.waitSignal(card.startTunnelRequested) as blocker:
        qtbot.mouseClick(card.tunnelButton, Qt.MouseButton.LeftButton)
    assert blocker.args == [_forwardingHost()]


def test_tunnel_status_drives_label_and_button(qtbot: QtBot) -> None:
    card = HostCard(_forwardingHost())
    qtbot.addWidget(card)
    card.setTunnelStatus(TunnelStatus(TunnelState.CONNECTING))
    assert card.tunnelStatusLabel.text() == "Tunnel connecting..."
    assert card.tunnelButton.text() == "Stop tunnel"
    card.setTunnelStatus(TunnelStatus(TunnelState.UP))
    assert card.tunnelStatusLabel.text() == "Tunnel active"
    assert card.tunnelStatusLabel.property("tunnelState") == "up"
    with qtbot.waitSignal(card.stopTunnelRequested) as blocker:
        qtbot.mouseClick(card.tunnelButton, Qt.MouseButton.LeftButton)
    assert blocker.args == [_forwardingHost()]

    card.setTunnelStatus(TunnelStatus(TunnelState.RETRYING, "connection lost"))
    assert card.tunnelStatusLabel.text() == "Tunnel reconnecting: connection lost"
    assert card.tunnelButton.text() == "Stop tunnel"
    card.setTunnelStatus(TunnelStatus(TunnelState.FAILED, "Could not listen on 127.0.0.1:8080"))
    assert card.tunnelStatusLabel.text() == "Tunnel failed: Could not listen on 127.0.0.1:8080"
    assert card.tunnelStatusLabel.property("tunnelState") == "failed"
    assert card.tunnelButton.text() == "Start tunnel"
    card.setTunnelStatus(TunnelStatus(TunnelState.AUTH_REQUIRED, "Authentication failed"))
    assert card.tunnelStatusLabel.text() == "Tunnel: password required"
    card.setTunnelStatus(TunnelStatus(TunnelState.STOPPED))
    assert card.tunnelStatusLabel.text() == "Tunnel off"
    assert card.tunnelButton.text() == "Start tunnel"


def test_bars_carry_usage_level_property(qtbot: QtBot) -> None:
    card = HostCard(_host())
    qtbot.addWidget(card)
    card.setMetrics(METRICS)
    assert card.cpuBar.property("usageLevel") == "ok"
    assert card.diskBar.property("usageLevel") == "critical"
