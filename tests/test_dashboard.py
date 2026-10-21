"""Tests for the dashboard grid of host cards."""

from __future__ import annotations

from pytestqt.qtbot import QtBot

from pyommyssh.core.forwards import ForwardKind, PortForward
from pyommyssh.core.hosts import Host
from pyommyssh.core.metrics import HostMetrics
from pyommyssh.core.tunnel import TunnelState, TunnelStatus
from pyommyssh.ui.dashboard import CARD_MIN_WIDTH, DashboardView, columnsFor


def _hosts() -> list[Host]:
    return [
        Host(name="web", hostname="web.local", tags=["prod"]),
        Host(name="db", hostname="db.local", tags=["prod", "data"]),
        Host(name="lab", hostname="lab.local"),
    ]


def test_set_hosts_creates_one_card_per_host(qtbot: QtBot) -> None:
    view = DashboardView()
    qtbot.addWidget(view)
    view.setHosts(_hosts())
    assert [card.host.name for card in view.cards()] == ["web", "db", "lab"]
    assert view.cardFor("db") is not None
    assert view.cardFor("missing") is None


def test_set_hosts_again_replaces_cards_and_keeps_metrics(qtbot: QtBot) -> None:
    view = DashboardView()
    qtbot.addWidget(view)
    view.setHosts(_hosts())
    view.showMetrics("web", HostMetrics(cpuPercent=40.0))
    view.setHosts(_hosts()[:2])
    assert [card.host.name for card in view.cards()] == ["web", "db"]
    webCard = view.cardFor("web")
    assert webCard is not None
    assert webCard.cpuBar.value() == 40


def test_show_metrics_and_error_route_to_card(qtbot: QtBot) -> None:
    view = DashboardView()
    qtbot.addWidget(view)
    view.setHosts(_hosts())
    view.showConnecting("lab")
    labCard = view.cardFor("lab")
    assert labCard is not None
    assert labCard.statusLabel.text() == "Connecting..."
    view.showError("lab", "boom")
    assert labCard.statusLabel.text() == "boom"
    view.showMetrics("unknown-host", HostMetrics())  # ignored, no crash


def test_group_by_tag_adds_headers(qtbot: QtBot) -> None:
    view = DashboardView()
    qtbot.addWidget(view)
    view.setHosts(_hosts())
    assert view.groupHeaders() == []
    view.setGroupByTag(True)
    assert view.groupHeaders() == ["data", "prod", "Untagged"]
    assert [card.host.name for card in view.cards()] == ["db", "web", "db", "lab"]
    view.setGroupByTag(False)
    assert view.groupHeaders() == []
    assert [card.host.name for card in view.cards()] == ["web", "db", "lab"]


def test_card_signals_are_forwarded(qtbot: QtBot) -> None:
    view = DashboardView()
    qtbot.addWidget(view)
    view.setHosts(_hosts())
    card = view.cardFor("web")
    assert card is not None
    with qtbot.waitSignal(view.openTerminalRequested) as blocker:
        card.openTerminalRequested.emit(card.host)
    assert blocker.args == [card.host]
    with qtbot.waitSignal(view.installKeyRequested) as keyBlocker:
        card.installKeyRequested.emit(card.host)
    assert keyBlocker.args == [card.host]


def test_columns_scale_with_width() -> None:
    assert columnsFor(0) == 1
    assert columnsFor(CARD_MIN_WIDTH - 1) == 1
    assert columnsFor(CARD_MIN_WIDTH * 3) == 3
    assert columnsFor(CARD_MIN_WIDTH * 3 + 10) == 3


def test_resize_relayouts_cards(qtbot: QtBot) -> None:
    view = DashboardView()
    qtbot.addWidget(view)
    view.show()
    view.setHosts(_hosts())
    view.resize(CARD_MIN_WIDTH * 2 + 40, 400)
    assert view.columns() == 2
    view.resize(CARD_MIN_WIDTH * 3 + 40, 400)
    assert view.columns() == 3


def _forwardingHosts() -> list[Host]:
    hosts = _hosts()
    hosts[0].forwards = [PortForward.parse(ForwardKind.LOCAL, "8080:localhost:80")]
    return hosts


def test_tunnel_status_routes_to_card_and_survives_rebuild(qtbot: QtBot) -> None:
    view = DashboardView()
    qtbot.addWidget(view)
    view.setHosts(_forwardingHosts())
    view.showTunnelStatus("web", TunnelStatus(TunnelState.UP))
    card = view.cardFor("web")
    assert card is not None
    assert card.tunnelStatusLabel.text() == "Tunnel active"
    view.showTunnelStatus("unknown-host", TunnelStatus(TunnelState.UP))  # ignored, no crash

    view.setGroupByTag(True)
    rebuilt = view.cardFor("web")
    assert rebuilt is not None and rebuilt is not card
    assert rebuilt.tunnelStatusLabel.text() == "Tunnel active"


def test_tunnel_signals_are_forwarded(qtbot: QtBot) -> None:
    view = DashboardView()
    qtbot.addWidget(view)
    view.setHosts(_forwardingHosts())
    card = view.cardFor("web")
    assert card is not None
    with qtbot.waitSignal(view.startTunnelRequested) as started:
        card.startTunnelRequested.emit(card.host)
    assert started.args == [card.host]
    with qtbot.waitSignal(view.stopTunnelRequested) as stopped:
        card.stopTunnelRequested.emit(card.host)
    assert stopped.args == [card.host]
