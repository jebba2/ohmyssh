"""End-to-end tests for the main window against the in-process SSH server."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from pyommyssh.core.config import AppSettings
from pyommyssh.core.hosts import Host, HostStore
from pyommyssh.ui.mainWindow import MainWindow
from tests.sshserver import SHELL_BANNER, TEST_PASSWORD, TestSshServer, hostFor

WAIT_MS = 10000


@pytest.fixture
def store(tmp_path: Path) -> HostStore:
    return HostStore(tmp_path / "hosts.toml")


def _storedNames(tmp_path: Path) -> list[str]:
    reloaded = HostStore(tmp_path / "hosts.toml")
    reloaded.load()
    return [host.name for host in reloaded.hosts()]


def _window(
    qtbot: QtBot,
    store: HostStore,
    tmp_path: Path,
    sshConfigHosts: list[Host] | None = None,
    prompts: list[str] | None = None,
    answer: str | None = None,
) -> MainWindow:
    def prompt(host: Host) -> str | None:
        if prompts is not None:
            prompts.append(host.name)
        return answer

    window = MainWindow(
        settings=AppSettings(refreshIntervalSeconds=3600),
        hostStore=store,
        sshConfigHosts=sshConfigHosts or [],
        knownHostsPath=tmp_path / "known_hosts",
        passwordPrompt=prompt,
    )
    qtbot.addWidget(window)
    return window


@pytest.fixture
def windows() -> Iterator[list[MainWindow]]:
    opened: list[MainWindow] = []
    yield opened
    for window in opened:
        window.shutdown()


def test_refresh_shows_host_online(
    qtbot: QtBot, sshServer: TestSshServer, clientKeyFile: Path, store: HostStore, tmp_path: Path,
    windows: list[MainWindow],
) -> None:
    store.add(hostFor(sshServer, identityFile=clientKeyFile))
    window = _window(qtbot, store, tmp_path)
    windows.append(window)
    card = window.dashboard.cardFor("box")
    assert card is not None
    window.refreshAll()
    qtbot.waitUntil(lambda: card.statusLabel.text() == "Online", timeout=WAIT_MS)
    assert any("===PYOMMYSSH:OS===" in command for command in sshServer.commands)


def test_refresh_failure_shows_error(
    qtbot: QtBot, store: HostStore, tmp_path: Path, windows: list[MainWindow]
) -> None:
    store.add(Host(name="dead", hostname="127.0.0.1", user="x", port=1))
    window = _window(qtbot, store, tmp_path)
    windows.append(window)
    card = window.dashboard.cardFor("dead")
    assert card is not None
    window.refreshAll()
    qtbot.waitUntil(lambda: card.statusLabel.text().startswith("Could not reach"), timeout=WAIT_MS)


def test_password_prompt_supplies_credentials(
    qtbot: QtBot, sshServer: TestSshServer, store: HostStore, tmp_path: Path,
    windows: list[MainWindow],
) -> None:
    store.add(hostFor(sshServer))
    prompts: list[str] = []
    window = _window(qtbot, store, tmp_path, prompts=prompts, answer=TEST_PASSWORD)
    windows.append(window)
    card = window.dashboard.cardFor("box")
    assert card is not None
    window.refreshAll()
    qtbot.waitUntil(lambda: card.statusLabel.text() == "Online", timeout=WAIT_MS)
    assert prompts == ["box"]
    # A later refresh reuses the stored password without asking again.
    window.refreshAll()
    qtbot.waitUntil(lambda: card.statusLabel.text() == "Online", timeout=WAIT_MS)
    assert prompts == ["box"]


def test_declined_password_shows_error_and_does_not_reprompt(
    qtbot: QtBot, sshServer: TestSshServer, store: HostStore, tmp_path: Path,
    windows: list[MainWindow],
) -> None:
    store.add(hostFor(sshServer))
    prompts: list[str] = []
    window = _window(qtbot, store, tmp_path, prompts=prompts, answer=None)
    windows.append(window)
    card = window.dashboard.cardFor("box")
    assert card is not None
    window.refreshAll()
    qtbot.waitUntil(lambda: card.statusLabel.text() == "Password required", timeout=WAIT_MS)
    window.refreshAll()
    qtbot.wait(300)
    assert prompts == ["box"]
    assert card.statusLabel.text() == "Password required"


def test_open_terminal_tab_round_trip(
    qtbot: QtBot, sshServer: TestSshServer, clientKeyFile: Path, store: HostStore, tmp_path: Path,
    windows: list[MainWindow],
) -> None:
    host = hostFor(sshServer, identityFile=clientKeyFile)
    store.add(host)
    window = _window(qtbot, store, tmp_path)
    windows.append(window)
    window.show()
    window.openTerminal(host)
    assert window.tabs.count() == 2
    assert window.tabs.tabText(1) == "box"
    tab = window.terminalTabs()[0]
    qtbot.waitUntil(lambda: "welcome" in "".join(tab.terminal.session.lines()), timeout=WAIT_MS)

    tab.terminal.inputBytes.emit(b"ls -la")
    qtbot.waitUntil(lambda: "ls -la" in "".join(tab.terminal.session.lines()), timeout=WAIT_MS)

    window.closeTab(1)
    qtbot.waitUntil(lambda: window.tabs.count() == 1, timeout=WAIT_MS)
    assert window.terminalTabs() == []


def test_terminal_tab_reports_connection_failure(
    qtbot: QtBot, store: HostStore, tmp_path: Path, windows: list[MainWindow]
) -> None:
    host = Host(name="dead", hostname="127.0.0.1", user="x", port=1)
    store.add(host)
    window = _window(qtbot, store, tmp_path)
    windows.append(window)
    window.openTerminal(host)
    tab = window.terminalTabs()[0]
    qtbot.waitUntil(lambda: "Could not reach" in tab.statusLabel.text(), timeout=WAIT_MS)


def test_search_entries_cover_hosts_and_tabs(
    qtbot: QtBot, sshServer: TestSshServer, clientKeyFile: Path, store: HostStore, tmp_path: Path,
    windows: list[MainWindow],
) -> None:
    host = hostFor(sshServer, identityFile=clientKeyFile)
    store.add(host)
    configHost = Host(name="cfg", hostname="cfg.local")
    window = _window(qtbot, store, tmp_path, sshConfigHosts=[configHost])
    windows.append(window)
    window.openTerminal(host)
    entries = window.searchEntries()
    assert [(entry.kind, entry.label) for entry in entries] == [
        ("host", "cfg"),
        ("host", "box"),
        ("session", "box (tab 1)"),
    ]
    assert entries[2].tabIndex == 1


def test_add_edit_remove_host(
    qtbot: QtBot, store: HostStore, tmp_path: Path, windows: list[MainWindow]
) -> None:
    window = _window(qtbot, store, tmp_path, sshConfigHosts=[Host(name="cfg", hostname="c")])
    windows.append(window)
    assert [h.name for h in window.hosts()] == ["cfg"]

    window.saveNewHost(Host(name="new", hostname="n.local"))
    assert [h.name for h in window.hosts()] == ["cfg", "new"]
    assert window.dashboard.cardFor("new") is not None
    assert _storedNames(tmp_path) == ["new"]

    window.saveEditedHost("new", Host(name="renamed", hostname="r.local"))
    assert [h.name for h in window.hosts()] == ["cfg", "renamed"]
    assert window.dashboard.cardFor("new") is None

    window.removeHost(Host(name="renamed", hostname="r.local"))
    assert [h.name for h in window.hosts()] == ["cfg"]
    assert _storedNames(tmp_path) == []


def test_group_by_tag_action_toggles_dashboard(
    qtbot: QtBot, store: HostStore, tmp_path: Path, windows: list[MainWindow]
) -> None:
    store.add(Host(name="a", hostname="a", tags=["prod"]))
    window = _window(qtbot, store, tmp_path)
    windows.append(window)
    assert window.dashboard.groupHeaders() == []
    window.groupByTagAction.trigger()
    assert window.dashboard.groupHeaders() == ["prod"]
    window.groupByTagAction.trigger()
    assert window.dashboard.groupHeaders() == []
