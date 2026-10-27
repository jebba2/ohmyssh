"""End-to-end tests for the main window against the in-process SSH server."""

from __future__ import annotations

import socket
import time
import tomllib
from collections.abc import Iterator
from pathlib import Path

import paramiko
import pytest
from PySide6.QtCore import QItemSelectionModel, QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from pytestqt.qtbot import QtBot

from ohmyssh.core.config import AppSettings
from ohmyssh.core.forwards import ForwardKind, PortForward
from ohmyssh.core.hosts import GlobalSettings, Host, HostSource, HostStore
from ohmyssh.core.keys import KeyType, generateKeyPair, readPublicKey
from ohmyssh.core.sshconfig import SshConfigEditor
from ohmyssh.core.tunnel import TunnelState, TunnelStatus
from ohmyssh.ui.filePane import FilePane
from ohmyssh.ui.keyGenerateDialog import KeyGenerateRequest
from ohmyssh.ui.mainWindow import MainWindow
from ohmyssh.ui.sftpTab import PROGRESS_BAR_MIN_WIDTH, SftpTab
from tests.echoserver import EchoServer
from tests.sshserver import SHELL_BANNER, TEST_PASSWORD, TEST_USER, TestSshServer, hostFor

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

    editor = _sshConfig(tmp_path)
    for configHost in sshConfigHosts or []:
        editor.upsertHost(configHost)
    window = MainWindow(
        settings=AppSettings(refreshIntervalSeconds=3600),
        hostStore=store,
        sshConfig=editor,
        knownHostsPath=tmp_path / "known_hosts",
        passwordPrompt=prompt,
    )
    qtbot.addWidget(window)
    return window


def _sshConfig(tmp_path: Path) -> SshConfigEditor:
    return SshConfigEditor(tmp_path / ".ssh" / "config", home=tmp_path, backupDir=tmp_path / "backups")


def _configText(tmp_path: Path) -> str:
    return (tmp_path / ".ssh" / "config").read_text()


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
    assert any("===OHMYSSH:OS===" in command for command in sshServer.commands)


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


def test_removing_an_ssh_config_host_hides_it_and_keeps_the_config_file(
    qtbot: QtBot, store: HostStore, tmp_path: Path, windows: list[MainWindow]
) -> None:
    configHost = Host(name="cfg", hostname="c.local", source=HostSource.SSH_CONFIG)
    other = Host(name="other", hostname="o.local", source=HostSource.SSH_CONFIG)
    window = _window(qtbot, store, tmp_path, sshConfigHosts=[configHost, other])
    windows.append(window)
    assert [h.name for h in window.hosts()] == ["cfg", "other"]

    window.removeHost(configHost)
    assert [h.name for h in window.hosts()] == ["other"]
    assert window.dashboard.cardFor("cfg") is None
    with (tmp_path / "hosts.toml").open("rb") as handle:
        assert tomllib.load(handle)["hidden_hosts"] == ["cfg"]
    assert _storedNames(tmp_path) == []

    # A fresh window built from the same store keeps the host hidden.
    reloaded = HostStore(tmp_path / "hosts.toml")
    reloaded.load()
    again = _window(qtbot, reloaded, tmp_path, sshConfigHosts=[configHost, other])
    windows.append(again)
    assert [h.name for h in again.hosts()] == ["other"]


def test_removal_prompt_text_differs_for_config_and_app_hosts(
    qtbot: QtBot, store: HostStore, tmp_path: Path, windows: list[MainWindow]
) -> None:
    window = _window(qtbot, store, tmp_path)
    windows.append(window)
    appText = window.removalQuestion(Host(name="mine", hostname="m", source=HostSource.APP))
    configText = window.removalQuestion(Host(name="cfg", hostname="c", source=HostSource.SSH_CONFIG))
    assert appText == "Remove 'mine'? Its settings are deleted from hosts.toml."
    assert configText == (
        "Hide 'cfg'? It comes from ~/.ssh/config, which is never changed; it is only hidden from the "
        "dashboard. To bring it back, remove it from hidden_hosts in hosts.toml."
    )


def test_new_host_can_be_saved_to_ssh_config_or_kept_in_the_app(
    qtbot: QtBot, store: HostStore, tmp_path: Path, windows: list[MainWindow]
) -> None:
    window = _window(qtbot, store, tmp_path, sshConfigHosts=[Host(name="cfg", hostname="c.local")])
    windows.append(window)

    window.saveNewHost(Host(name="shared", hostname="s.local", user="me", tags=["lab"]), toSshConfig=True)
    assert "Host shared\n    HostName s.local\n    User me\n    # tags: lab\n" in _configText(tmp_path)
    assert _storedNames(tmp_path) == []
    saved = next(h for h in window.hosts() if h.name == "shared")
    assert saved.source == HostSource.SSH_CONFIG and saved.tags == ["lab"]
    assert window.dashboard.cardFor("shared") is not None

    window.saveNewHost(Host(name="private", hostname="p.local"), toSshConfig=False)
    assert "private" not in _configText(tmp_path)
    assert _storedNames(tmp_path) == ["private"]


def test_editing_an_ssh_config_host_rewrites_its_block_in_place(
    qtbot: QtBot, store: HostStore, tmp_path: Path, windows: list[MainWindow]
) -> None:
    window = _window(qtbot, store, tmp_path, sshConfigHosts=[Host(name="cfg", hostname="old.local")])
    windows.append(window)
    configHost = next(h for h in window.hosts() if h.name == "cfg")
    assert configHost.sourceFile == tmp_path / ".ssh" / "config"

    edited = Host(name="cfg", hostname="new.local", tags=["lab"], sourceFile=configHost.sourceFile)
    window.applyEdit(configHost, edited)
    assert _configText(tmp_path) == "Host cfg\n    HostName new.local\n    # tags: lab\n"
    hosts = window.hosts()
    assert [(h.name, h.hostname, h.source, h.tags) for h in hosts] == [("cfg", "new.local", HostSource.SSH_CONFIG, ["lab"])]
    assert _storedNames(tmp_path) == []
    card = window.dashboard.cardFor("cfg")
    assert card is not None
    assert card.addressLabel.text() == "new.local"
    assert list((tmp_path / "backups").iterdir())


def test_renaming_a_host_on_a_shared_line_keeps_the_other_alias(
    qtbot: QtBot, store: HostStore, tmp_path: Path, windows: list[MainWindow]
) -> None:
    configPath = tmp_path / ".ssh" / "config"
    configPath.parent.mkdir()
    configPath.write_text("Host Hermes (jebba)\n    HostName hermes.local\n")
    window = _window(qtbot, store, tmp_path)
    windows.append(window)
    hermes = next(h for h in window.hosts() if h.name == "Hermes")
    assert hermes.sharedWith == ["(jebba)"]

    window.applyEdit(hermes, Host(name="hermes2", hostname="hermes.local", sourceFile=hermes.sourceFile))
    assert _configText(tmp_path) == "Host hermes2 (jebba)\n    HostName hermes.local\n"
    assert sorted(h.name for h in window.hosts()) == ["(jebba)", "hermes2"]


def test_global_settings_are_saved_to_a_host_star_block_at_the_end(
    qtbot: QtBot, store: HostStore, tmp_path: Path, windows: list[MainWindow]
) -> None:
    configPath = tmp_path / ".ssh" / "config"
    configPath.parent.mkdir()
    configPath.write_text("Host *\n    Compression yes\n\nHost web\n    HostName w.local\n")
    window = _window(qtbot, store, tmp_path)
    windows.append(window)
    assert window.settingsAction.text() == "Settings"
    assert window.globalSettings() == GlobalSettings(compression=True)

    window.saveGlobalSettings(GlobalSettings(serverAliveInterval=60, serverAliveCountMax=3, compression=True))
    assert _configText(tmp_path) == (
        "Host web\n    HostName w.local\n\nHost *\n    ServerAliveInterval 60\n    ServerAliveCountMax 3\n    Compression yes\n"
    )
    assert window.globalSettings() == GlobalSettings(serverAliveInterval=60, serverAliveCountMax=3, compression=True)
    assert window.statusBar().currentMessage() == "Saved SSH defaults to ~/.ssh/config"
    assert [h.name for h in window.hosts()] == ["web"]


def test_global_settings_reach_new_connections(
    qtbot: QtBot, sshServer: TestSshServer, clientKeyFile: Path, store: HostStore, tmp_path: Path,
    windows: list[MainWindow],
) -> None:
    store.add(hostFor(sshServer))
    window = _window(qtbot, store, tmp_path)
    windows.append(window)
    window.saveGlobalSettings(GlobalSettings(identityFile=clientKeyFile, compression=True))
    card = window.dashboard.cardFor("box")
    assert card is not None
    window.refreshAll()
    qtbot.waitUntil(lambda: card.statusLabel.text() == "Online", timeout=WAIT_MS)
    assert ("publickey", TEST_USER) in sshServer.authAttempts


def _firstLaunchWindow(
    qtbot: QtBot,
    store: HostStore,
    tmp_path: Path,
    welcomeAnswer: bool,
    request: KeyGenerateRequest | None,
) -> tuple[MainWindow, list[str], list[Path]]:
    window = _window(qtbot, store, tmp_path)
    welcomed: list[str] = []
    asked: list[Path] = []
    window.firstRunPrompts.welcome = lambda message: (welcomed.append(message), welcomeAnswer)[1]
    window.firstRunPrompts.keyRequest = lambda sshDir: (asked.append(sshDir), request)[1]
    window.firstRunMarker = tmp_path / "config" / "first_run_done"
    return window, welcomed, asked


def test_first_launch_creates_ssh_dir_and_walks_through_generating_a_key(
    qtbot: QtBot, store: HostStore, tmp_path: Path, windows: list[MainWindow]
) -> None:
    sshDir = tmp_path / ".ssh"
    request = KeyGenerateRequest(sshDir / "id_ed25519", KeyType.ED25519, "me@here", None)
    window, welcomed, asked = _firstLaunchWindow(qtbot, store, tmp_path, welcomeAnswer=True, request=request)
    windows.append(window)
    assert window.runFirstLaunchSetup() == "generated"
    assert sshDir.is_dir()
    assert len(welcomed) == 1 and "No SSH key was found" in welcomed[0] and str(sshDir) in welcomed[0]
    assert asked == [sshDir]
    qtbot.waitUntil(lambda: (sshDir / "id_ed25519.pub").exists(), timeout=WAIT_MS)
    qtbot.waitUntil(lambda: window.statusBar().currentMessage().startswith("Generated id_ed25519"), timeout=WAIT_MS)
    assert (tmp_path / "config" / "first_run_done").is_file()
    # Only the first launch asks.
    assert window.runFirstLaunchSetup() == "skipped"
    assert len(welcomed) == 1


def test_first_launch_declined_is_not_asked_again(
    qtbot: QtBot, store: HostStore, tmp_path: Path, windows: list[MainWindow]
) -> None:
    window, welcomed, asked = _firstLaunchWindow(qtbot, store, tmp_path, welcomeAnswer=False, request=None)
    windows.append(window)
    assert window.runFirstLaunchSetup() == "declined"
    assert len(welcomed) == 1 and asked == []
    assert not list((tmp_path / ".ssh").glob("id_*"))
    assert (tmp_path / "config" / "first_run_done").is_file()
    assert window.runFirstLaunchSetup() == "skipped"


def test_first_launch_with_an_existing_key_stays_quiet(
    qtbot: QtBot, store: HostStore, tmp_path: Path, windows: list[MainWindow]
) -> None:
    sshDir = tmp_path / ".ssh"
    generateKeyPair(sshDir / "id_rsa", KeyType.RSA, "c", passphrase=None)
    window, welcomed, _ = _firstLaunchWindow(qtbot, store, tmp_path, welcomeAnswer=True, request=None)
    windows.append(window)
    assert window.runFirstLaunchSetup() == "has-keys"
    assert welcomed == []
    assert (tmp_path / "config" / "first_run_done").is_file()


def test_first_launch_setup_is_off_without_a_marker_path(
    qtbot: QtBot, store: HostStore, tmp_path: Path, windows: list[MainWindow]
) -> None:
    window, welcomed, _ = _firstLaunchWindow(qtbot, store, tmp_path, welcomeAnswer=True, request=None)
    windows.append(window)
    window.firstRunMarker = None
    assert window.runFirstLaunchSetup() == "skipped"
    assert welcomed == []


def test_failed_config_save_is_reported_and_changes_nothing(
    qtbot: QtBot, store: HostStore, tmp_path: Path, windows: list[MainWindow]
) -> None:
    window = _window(qtbot, store, tmp_path, sshConfigHosts=[Host(name="cfg", hostname="c.local")])
    windows.append(window)
    before = _configText(tmp_path)
    configHost = next(h for h in window.hosts() if h.name == "cfg")
    window.applyEdit(configHost, Host(name="bad name", hostname="c.local", sourceFile=configHost.sourceFile))
    assert _configText(tmp_path) == before
    assert window.statusBar().currentMessage().startswith("Could not save 'bad name' to ")
    assert [h.name for h in window.hosts()] == ["cfg"]


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


def _freePort() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _echoThrough(port: int, payload: bytes = b"ping") -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
        connection.sendall(payload)
        return connection.recv(1024)


def _echoes(port: int) -> bool:
    """True once a forward on ``port`` carries a ping to the echo server; False while nothing listens yet."""
    try:
        return _echoThrough(port) == b"ping"
    except ConnectionRefusedError:
        return False


def _forwardingHost(
    sshServer: TestSshServer, echoPort: int, localPort: int, identityFile: Path | None = None
) -> Host:
    host = hostFor(sshServer, identityFile=identityFile)
    host.forwards = [PortForward.parse(ForwardKind.LOCAL, f"{localPort}:127.0.0.1:{echoPort}")]
    return host


def _tunnelText(window: MainWindow, name: str) -> str:
    card = window.dashboard.cardFor(name)
    assert card is not None
    return card.tunnelStatusLabel.text()


def test_tunnel_starts_and_stops_from_the_card(
    qtbot: QtBot, sshServer: TestSshServer, echoServer: EchoServer, clientKeyFile: Path,
    store: HostStore, tmp_path: Path, windows: list[MainWindow],
) -> None:
    port = _freePort()
    host = _forwardingHost(sshServer, echoServer.port, port, clientKeyFile)
    store.add(host)
    window = _window(qtbot, store, tmp_path)
    windows.append(window)
    card = window.dashboard.cardFor("box")
    assert card is not None
    assert card.tunnelStatusLabel.text() == "Tunnel off"

    qtbot.mouseClick(card.tunnelButton, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: _tunnelText(window, "box") == "Tunnel active", timeout=WAIT_MS)
    assert window.tunnels.isRunning("box")
    assert _echoThrough(port) == b"ping"

    qtbot.mouseClick(card.tunnelButton, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: _tunnelText(window, "box") == "Tunnel off", timeout=WAIT_MS)
    assert not window.tunnels.isRunning("box")


def test_tunnel_prompts_for_a_password_and_retries(
    qtbot: QtBot, sshServer: TestSshServer, echoServer: EchoServer, store: HostStore, tmp_path: Path,
    windows: list[MainWindow],
) -> None:
    port = _freePort()
    store.add(_forwardingHost(sshServer, echoServer.port, port))
    prompts: list[str] = []
    window = _window(qtbot, store, tmp_path, prompts=prompts, answer=TEST_PASSWORD)
    windows.append(window)
    window.startTunnel(window.hosts()[0])
    qtbot.waitUntil(lambda: _tunnelText(window, "box") == "Tunnel active", timeout=WAIT_MS)
    assert prompts == ["box"]
    assert _echoThrough(port) == b"ping"


def test_declined_tunnel_password_shows_on_the_card(
    qtbot: QtBot, sshServer: TestSshServer, echoServer: EchoServer, store: HostStore, tmp_path: Path,
    windows: list[MainWindow],
) -> None:
    store.add(_forwardingHost(sshServer, echoServer.port, _freePort()))
    window = _window(qtbot, store, tmp_path, prompts=[], answer=None)
    windows.append(window)
    window.startTunnel(window.hosts()[0])
    qtbot.waitUntil(lambda: _tunnelText(window, "box") == "Tunnel: password required", timeout=WAIT_MS)
    assert not window.tunnels.isRunning("box")


def test_editing_a_host_restarts_its_tunnel_with_the_new_forwards(
    qtbot: QtBot, sshServer: TestSshServer, echoServer: EchoServer, clientKeyFile: Path,
    store: HostStore, tmp_path: Path, windows: list[MainWindow],
) -> None:
    oldPort, newPort = _freePort(), _freePort()
    host = _forwardingHost(sshServer, echoServer.port, oldPort, clientKeyFile)
    store.add(host)
    window = _window(qtbot, store, tmp_path)
    windows.append(window)
    window.startTunnel(host)
    qtbot.waitUntil(lambda: _tunnelText(window, "box") == "Tunnel active", timeout=WAIT_MS)

    edited = _forwardingHost(sshServer, echoServer.port, newPort, clientKeyFile)
    window.saveEditedHost("box", edited)
    qtbot.waitUntil(lambda: _echoes(newPort), timeout=WAIT_MS)
    # The restarted tunnel carries data a moment before its status reaches the card.
    qtbot.waitUntil(lambda: _tunnelText(window, "box") == "Tunnel active", timeout=WAIT_MS)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", oldPort))

    # Dropping every forward stops the tunnel instead of restarting it.
    window.saveEditedHost("box", hostFor(sshServer, identityFile=clientKeyFile))
    qtbot.waitUntil(lambda: not window.tunnels.isRunning("box"), timeout=WAIT_MS)
    card = window.dashboard.cardFor("box")
    assert card is not None
    assert card.tunnelButton.isHidden()


def test_removing_a_host_stops_its_tunnel(
    qtbot: QtBot, sshServer: TestSshServer, echoServer: EchoServer, clientKeyFile: Path,
    store: HostStore, tmp_path: Path, windows: list[MainWindow],
) -> None:
    port = _freePort()
    host = _forwardingHost(sshServer, echoServer.port, port, clientKeyFile)
    store.add(host)
    window = _window(qtbot, store, tmp_path)
    windows.append(window)
    window.startTunnel(host)
    qtbot.waitUntil(lambda: _tunnelText(window, "box") == "Tunnel active", timeout=WAIT_MS)
    window.removeHost(host)
    qtbot.waitUntil(
        lambda: window.tunnels.status("box") == TunnelStatus(TunnelState.STOPPED), timeout=WAIT_MS
    )
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))


PUBLIC_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGxkZXN0cmlwcGVkLWZha2Uta2V5LWJ5dGVzLWhlcmUx jeb@laptop"


def _publicKeyFile(tmp_path: Path) -> Path:
    path = tmp_path / "id_ed25519.pub"
    path.write_text(f"{PUBLIC_KEY}\n")
    return path


def test_install_key_reports_success_in_the_status_bar(
    qtbot: QtBot, sshServer: TestSshServer, clientKeyFile: Path, store: HostStore, tmp_path: Path,
    windows: list[MainWindow],
) -> None:
    sshServer.execOutput = lambda command: "OHMYSSH:INSTALLED\n" if "authorized_keys" in command else ""
    host = hostFor(sshServer, identityFile=clientKeyFile)
    store.add(host)
    window = _window(qtbot, store, tmp_path)
    windows.append(window)
    window.installKey(host, _publicKeyFile(tmp_path))
    qtbot.waitUntil(
        lambda: window.statusBar().currentMessage() == "Installed id_ed25519.pub on box", timeout=WAIT_MS
    )
    assert any(PUBLIC_KEY in command for command in sshServer.commands)

    sshServer.execOutput = lambda command: "OHMYSSH:PRESENT\n"
    window.installKey(host, _publicKeyFile(tmp_path))
    qtbot.waitUntil(
        lambda: window.statusBar().currentMessage() == "id_ed25519.pub is already on box", timeout=WAIT_MS
    )


def test_install_key_prompts_for_a_password(
    qtbot: QtBot, sshServer: TestSshServer, store: HostStore, tmp_path: Path, windows: list[MainWindow]
) -> None:
    sshServer.execOutput = lambda command: "OHMYSSH:INSTALLED\n"
    host = hostFor(sshServer)
    store.add(host)
    prompts: list[str] = []
    window = _window(qtbot, store, tmp_path, prompts=prompts, answer=TEST_PASSWORD)
    windows.append(window)
    window.installKey(host, _publicKeyFile(tmp_path))
    qtbot.waitUntil(
        lambda: window.statusBar().currentMessage() == "Installed id_ed25519.pub on box", timeout=WAIT_MS
    )
    assert prompts == ["box"]


def test_install_key_with_declined_password(
    qtbot: QtBot, sshServer: TestSshServer, store: HostStore, tmp_path: Path, windows: list[MainWindow]
) -> None:
    host = hostFor(sshServer)
    store.add(host)
    window = _window(qtbot, store, tmp_path, prompts=[], answer=None)
    windows.append(window)
    window.installKey(host, _publicKeyFile(tmp_path))
    qtbot.waitUntil(
        lambda: window.statusBar().currentMessage()
        == "Could not install id_ed25519.pub on box: Password required",
        timeout=WAIT_MS,
    )


def test_install_key_rejects_a_private_key_file(
    qtbot: QtBot, sshServer: TestSshServer, clientKeyFile: Path, store: HostStore, tmp_path: Path,
    windows: list[MainWindow],
) -> None:
    host = hostFor(sshServer, identityFile=clientKeyFile)
    store.add(host)
    window = _window(qtbot, store, tmp_path)
    windows.append(window)
    window.installKey(host, clientKeyFile)
    message = window.statusBar().currentMessage()
    assert message.startswith(f"Could not install {clientKeyFile.name} on box: ")
    assert "is a private key" in message
    assert sshServer.commands == []


def test_install_key_reports_a_server_failure(
    qtbot: QtBot, sshServer: TestSshServer, clientKeyFile: Path, store: HostStore, tmp_path: Path,
    windows: list[MainWindow],
) -> None:
    sshServer.execOutput = lambda command: "bash: authorized_keys: Permission denied\n"
    host = hostFor(sshServer, identityFile=clientKeyFile)
    store.add(host)
    window = _window(qtbot, store, tmp_path)
    windows.append(window)
    window.installKey(host, _publicKeyFile(tmp_path))
    qtbot.waitUntil(
        lambda: window.statusBar().currentMessage()
        == "Could not install id_ed25519.pub on box: Unexpected reply from the server: "
        "bash: authorized_keys: Permission denied",
        timeout=WAIT_MS,
    )


def test_generate_key_writes_files_and_reports(
    qtbot: QtBot, store: HostStore, tmp_path: Path, windows: list[MainWindow]
) -> None:
    window = _window(qtbot, store, tmp_path)
    windows.append(window)
    assert window.generateKeyAction.text() == "Generate key"
    keyDir = tmp_path / "keys"
    window.generateKey(KeyGenerateRequest(keyDir / "id_ed25519", KeyType.ED25519, "me@here", None))
    qtbot.waitUntil(
        lambda: window.statusBar().currentMessage() == f"Generated id_ed25519 and id_ed25519.pub in {keyDir}",
        timeout=WAIT_MS,
    )
    assert readPublicKey(keyDir / "id_ed25519.pub").endswith(" me@here")

    window.generateKey(KeyGenerateRequest(keyDir / "id_ed25519", KeyType.ED25519, "me@here", None))
    qtbot.waitUntil(
        lambda: window.statusBar().currentMessage()
        == f"Could not generate key: {keyDir / 'id_ed25519'} already exists",
        timeout=WAIT_MS,
    )


def test_password_prompt_also_unlocks_a_passphrase_protected_key(
    qtbot: QtBot, hostKey: paramiko.PKey, store: HostStore, tmp_path: Path, windows: list[MainWindow]
) -> None:
    privatePath = tmp_path / "locked_key"
    generateKeyPair(privatePath, KeyType.ED25519, "c", passphrase="open sesame")
    accepted = paramiko.Ed25519Key.from_private_key_file(str(privatePath), password="open sesame")
    server = TestSshServer(hostKey, acceptedKey=accepted)
    server.start()
    try:
        store.add(hostFor(server, identityFile=privatePath))
        prompts: list[str] = []
        window = _window(qtbot, store, tmp_path, prompts=prompts, answer="open sesame")
        windows.append(window)
        card = window.dashboard.cardFor("box")
        assert card is not None
        window.refreshAll()
        qtbot.waitUntil(lambda: card.statusLabel.text() == "Online", timeout=WAIT_MS)
        assert prompts == ["box"]
        assert ("publickey", TEST_USER) in server.authAttempts
    finally:
        server.stop()


def _sftpRoot(server: TestSshServer) -> Path:
    assert server.sftpRoot is not None
    return server.sftpRoot


def test_open_sftp_tab_lists_both_sides_and_navigates(
    qtbot: QtBot, sftpServer: TestSshServer, clientKeyFile: Path, store: HostStore, tmp_path: Path,
    windows: list[MainWindow],
) -> None:
    root = _sftpRoot(sftpServer)
    (root / "docs").mkdir()
    (root / "docs" / "inner.txt").write_bytes(b"inner")
    (root / "top.txt").write_bytes(b"top")
    host = hostFor(sftpServer, identityFile=clientKeyFile)
    store.add(host)
    window = _window(qtbot, store, tmp_path)
    windows.append(window)
    window.show()

    window.openSftp(host)
    assert window.tabs.count() == 2
    assert window.tabs.tabText(1) == "box (files)"
    tab = window.sftpTabs()[0]
    qtbot.waitUntil(lambda: tab.remotePane.currentPath() == "/", timeout=WAIT_MS)
    assert tab.remotePane.names() == ["docs", "top.txt"]
    qtbot.waitUntil(lambda: tab.localPane.currentPath() == str(Path.home()), timeout=WAIT_MS)
    assert tab.statusLabel.isHidden()

    tab.remotePane.navigateRequested.emit("/docs")
    qtbot.waitUntil(lambda: tab.remotePane.currentPath() == "/docs", timeout=WAIT_MS)
    assert tab.remotePane.names() == ["..", "inner.txt"]

    tab.remotePane.navigateRequested.emit("/nowhere")
    qtbot.waitUntil(lambda: "Could not list /nowhere" in tab.remotePane.statusLabel.text(), timeout=WAIT_MS)
    assert tab.remotePane.currentPath() == "/docs"

    localTarget = tmp_path / "localdir"
    localTarget.mkdir()
    (localTarget / "l.txt").write_bytes(b"l")
    tab.localPane.navigateRequested.emit(str(localTarget))
    qtbot.waitUntil(lambda: tab.localPane.currentPath() == str(localTarget), timeout=WAIT_MS)
    assert tab.localPane.names() == ["..", "l.txt"]

    entries = window.searchEntries()
    assert ("session", "box (files, tab 1)") in [(entry.kind, entry.label) for entry in entries]

    window.closeTab(1)
    qtbot.waitUntil(lambda: window.tabs.count() == 1, timeout=WAIT_MS)
    assert window.sftpTabs() == []


def _openSftpTab(
    qtbot: QtBot, window: MainWindow, host: Host, localDir: Path
) -> SftpTab:
    window.openSftp(host)
    tab = window.sftpTabs()[0]
    qtbot.waitUntil(lambda: tab.remotePane.currentPath() == "/", timeout=WAIT_MS)
    tab.localPane.navigateRequested.emit(str(localDir))
    qtbot.waitUntil(lambda: tab.localPane.currentPath() == str(localDir), timeout=WAIT_MS)
    return tab


def _selectNamed(pane: FilePane, name: str) -> None:
    """Add the named row to the selection, as a Ctrl+click would."""
    row = pane.names().index(name)
    index = pane.table.model().index(row, 0)
    pane.table.selectionModel().select(
        index, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    )


def test_upload_and_download_buttons_move_files_and_show_progress(
    qtbot: QtBot, sftpServer: TestSshServer, clientKeyFile: Path, store: HostStore, tmp_path: Path,
    windows: list[MainWindow],
) -> None:
    root = _sftpRoot(sftpServer)
    (root / "remote.txt").write_bytes(b"from the server")
    localDir = tmp_path / "local"
    localDir.mkdir()
    (localDir / "notes.txt").write_bytes(b"from the laptop")
    (localDir / "work").mkdir()
    (localDir / "work" / "deep.txt").write_bytes(b"deep")
    host = hostFor(sftpServer, identityFile=clientKeyFile)
    store.add(host)
    window = _window(qtbot, store, tmp_path)
    windows.append(window)
    window.show()
    tab = _openSftpTab(qtbot, window, host, localDir)
    assert not tab.uploadButton.isEnabled()
    assert tab.transferStrip.isHidden()

    _selectNamed(tab.localPane, "notes.txt")
    _selectNamed(tab.localPane, "work")
    assert tab.uploadButton.isEnabled()
    qtbot.mouseClick(tab.uploadButton, Qt.MouseButton.LeftButton)
    assert not tab.transferStrip.isHidden()
    qtbot.waitUntil(lambda: tab.transferStrip.isHidden(), timeout=WAIT_MS)
    qtbot.waitUntil(lambda: tab.remotePane.names() == ["work", "notes.txt", "remote.txt"], timeout=WAIT_MS)
    assert (root / "notes.txt").read_bytes() == b"from the laptop"
    assert (root / "work" / "deep.txt").read_bytes() == b"deep"

    _selectNamed(tab.remotePane, "remote.txt")
    assert tab.downloadButton.isEnabled()
    qtbot.mouseClick(tab.downloadButton, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: tab.transferStrip.isHidden(), timeout=WAIT_MS)
    qtbot.waitUntil(lambda: "remote.txt" in tab.localPane.names(), timeout=WAIT_MS)
    assert (localDir / "remote.txt").read_bytes() == b"from the server"


def test_replacing_files_asks_once_per_batch(
    qtbot: QtBot, sftpServer: TestSshServer, clientKeyFile: Path, store: HostStore, tmp_path: Path,
    windows: list[MainWindow],
) -> None:
    root = _sftpRoot(sftpServer)
    (root / "a.txt").write_bytes(b"old a")
    (root / "b.txt").write_bytes(b"old b")
    localDir = tmp_path / "local"
    localDir.mkdir()
    (localDir / "a.txt").write_bytes(b"new a")
    (localDir / "b.txt").write_bytes(b"new b")
    (localDir / "c.txt").write_bytes(b"new c")
    host = hostFor(sftpServer, identityFile=clientKeyFile)
    store.add(host)
    asked: list[list[str]] = []
    answers = [False, True]
    window = _window(qtbot, store, tmp_path)
    window.sftpPrompts.replace = lambda names: (asked.append(names), answers.pop(0))[1]
    windows.append(window)
    window.show()
    tab = _openSftpTab(qtbot, window, host, localDir)

    for name in ("a.txt", "b.txt", "c.txt"):
        _selectNamed(tab.localPane, name)
    qtbot.mouseClick(tab.uploadButton, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: len(asked) == 1, timeout=WAIT_MS)
    assert asked[0] == ["a.txt", "b.txt"]
    qtbot.wait(300)
    assert (root / "a.txt").read_bytes() == b"old a"
    assert not (root / "c.txt").exists()

    qtbot.mouseClick(tab.uploadButton, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: len(asked) == 2, timeout=WAIT_MS)
    qtbot.waitUntil(lambda: (root / "c.txt").exists() and tab.transferStrip.isHidden(), timeout=WAIT_MS)
    assert (root / "a.txt").read_bytes() == b"new a"


def test_new_folder_rename_and_delete_on_the_remote_side(
    qtbot: QtBot, sftpServer: TestSshServer, clientKeyFile: Path, store: HostStore, tmp_path: Path,
    windows: list[MainWindow],
) -> None:
    root = _sftpRoot(sftpServer)
    (root / "a.txt").write_bytes(b"a")
    (root / "b.txt").write_bytes(b"b")
    (root / "full").mkdir()
    (root / "full" / "inside.txt").write_bytes(b"x")
    localDir = tmp_path / "local"
    localDir.mkdir()
    host = hostFor(sftpServer, identityFile=clientKeyFile)
    store.add(host)
    window = _window(qtbot, store, tmp_path)
    textAsked: list[tuple[str, str, str]] = []
    textAnswers: list[str | None] = ["made", "renamed.txt", None]
    confirmAsked: list[str] = []
    confirmAnswers = [False, True, True]
    window.sftpPrompts.text = lambda title, label, default: (textAsked.append((title, label, default)), textAnswers.pop(0))[1]
    window.sftpPrompts.confirm = lambda message: (confirmAsked.append(message), confirmAnswers.pop(0))[1]
    windows.append(window)
    window.show()
    tab = _openSftpTab(qtbot, window, host, localDir)
    assert not tab.renameButton.isEnabled()
    assert not tab.deleteButton.isEnabled()
    assert tab.newFolderButton.isEnabled()

    qtbot.mouseClick(tab.newFolderButton, Qt.MouseButton.LeftButton)
    assert textAsked[-1] == ("New folder", "Folder name", "")
    qtbot.waitUntil(lambda: "made" in tab.remotePane.names(), timeout=WAIT_MS)
    assert (root / "made").is_dir()

    _selectNamed(tab.remotePane, "a.txt")
    assert tab.renameButton.isEnabled()
    qtbot.mouseClick(tab.renameButton, Qt.MouseButton.LeftButton)
    assert textAsked[-1] == ("Rename", "New name", "a.txt")
    qtbot.waitUntil(lambda: "renamed.txt" in tab.remotePane.names(), timeout=WAIT_MS)
    assert (root / "renamed.txt").read_bytes() == b"a" and not (root / "a.txt").exists()

    # Rename needs exactly one item; a cancelled prompt changes nothing.
    _selectNamed(tab.remotePane, "renamed.txt")
    _selectNamed(tab.remotePane, "b.txt")
    assert not tab.renameButton.isEnabled()
    tab.remotePane.table.clearSelection()
    _selectNamed(tab.remotePane, "b.txt")
    qtbot.mouseClick(tab.renameButton, Qt.MouseButton.LeftButton)
    qtbot.wait(200)
    assert (root / "b.txt").exists()

    # Deleting asks once for the batch; No leaves everything, Yes removes files and empty folders.
    _selectNamed(tab.remotePane, "made")
    assert tab.deleteButton.isEnabled()
    qtbot.mouseClick(tab.deleteButton, Qt.MouseButton.LeftButton)
    assert confirmAsked[-1] == "Delete 2 items from box?\n\nmade\nb.txt"
    qtbot.wait(200)
    assert (root / "b.txt").exists() and (root / "made").exists()
    qtbot.mouseClick(tab.deleteButton, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: tab.remotePane.names() == ["full", "renamed.txt"], timeout=WAIT_MS)

    # A folder with contents is refused, and the reason is shown.
    tab.remotePane.table.clearSelection()
    _selectNamed(tab.remotePane, "full")
    qtbot.mouseClick(tab.deleteButton, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: tab.statusLabel.text().startswith("Could not remove /full"), timeout=WAIT_MS)
    assert (root / "full" / "inside.txt").exists()


def test_refresh_relists_both_panes(
    qtbot: QtBot, sftpServer: TestSshServer, clientKeyFile: Path, store: HostStore, tmp_path: Path,
    windows: list[MainWindow],
) -> None:
    root = _sftpRoot(sftpServer)
    localDir = tmp_path / "local"
    localDir.mkdir()
    host = hostFor(sftpServer, identityFile=clientKeyFile)
    store.add(host)
    window = _window(qtbot, store, tmp_path)
    windows.append(window)
    tab = _openSftpTab(qtbot, window, host, localDir)
    (root / "appeared.txt").write_bytes(b"r")
    (localDir / "appeared.txt").write_bytes(b"l")
    qtbot.mouseClick(tab.refreshButton, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: tab.remotePane.names() == ["appeared.txt"], timeout=WAIT_MS)
    qtbot.waitUntil(lambda: tab.localPane.names() == ["..", "appeared.txt"], timeout=WAIT_MS)


def _dropOn(pane: FilePane, mime: QMimeData, rowName: str | None) -> None:
    """Drop ``mime`` on the named row, or on the empty area below the rows."""
    if rowName is None:
        point = QPoint(5, pane.table.viewport().height() - 2)
    else:
        item = pane.table.item(pane.names().index(rowName), 0)
        assert item is not None
        point = pane.table.visualItemRect(item).center()
    event = QDropEvent(
        QPointF(point), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    )
    pane.table.dropEvent(event)


def test_drag_and_drop_between_the_panes_transfers_files(
    qtbot: QtBot, sftpServer: TestSshServer, clientKeyFile: Path, store: HostStore, tmp_path: Path,
    windows: list[MainWindow],
) -> None:
    root = _sftpRoot(sftpServer)
    (root / "inbox").mkdir()
    (root / "remote.txt").write_bytes(b"from the server")
    localDir = tmp_path / "local"
    localDir.mkdir()
    (localDir / "notes.txt").write_bytes(b"from the laptop")
    (localDir / "work").mkdir()
    (localDir / "work" / "deep.txt").write_bytes(b"deep")
    host = hostFor(sftpServer, identityFile=clientKeyFile)
    store.add(host)
    window = _window(qtbot, store, tmp_path)
    windows.append(window)
    window.show()
    tab = _openSftpTab(qtbot, window, host, localDir)

    # Local entries dropped on a remote folder row land inside that folder.
    _selectNamed(tab.localPane, "notes.txt")
    _selectNamed(tab.localPane, "work")
    localMime = tab.localPane.dragMimeData()
    assert localMime is not None
    _dropOn(tab.remotePane, localMime, "inbox")
    qtbot.waitUntil(lambda: (root / "inbox" / "work" / "deep.txt").exists(), timeout=WAIT_MS)
    qtbot.waitUntil(lambda: tab.transferStrip.isHidden(), timeout=WAIT_MS)
    assert (root / "inbox" / "notes.txt").read_bytes() == b"from the laptop"
    assert not (root / "notes.txt").exists()

    # A remote entry dropped on the local pane's empty area lands in the folder on show.
    _selectNamed(tab.remotePane, "remote.txt")
    remoteMime = tab.remotePane.dragMimeData()
    assert remoteMime is not None
    _dropOn(tab.localPane, remoteMime, None)
    qtbot.waitUntil(lambda: (localDir / "remote.txt").exists(), timeout=WAIT_MS)
    qtbot.waitUntil(lambda: tab.transferStrip.isHidden(), timeout=WAIT_MS)

    # Dropping back on the source pane transfers nothing.
    qtbot.waitUntil(lambda: "remote.txt" in tab.localPane.names(), timeout=WAIT_MS)
    _dropOn(tab.localPane, localMime, "work")
    qtbot.wait(300)
    assert tab.transferStrip.isHidden()
    assert not (localDir / "work" / "notes.txt").exists()


def test_dropping_explorer_files_uploads_them_and_refuses_roots_and_duplicates(
    qtbot: QtBot, sftpServer: TestSshServer, clientKeyFile: Path, store: HostStore, tmp_path: Path,
    windows: list[MainWindow],
) -> None:
    root = _sftpRoot(sftpServer)
    localDir = tmp_path / "local"
    localDir.mkdir()
    dropped = tmp_path / "dropped.txt"
    dropped.write_bytes(b"from explorer")
    (tmp_path / "one").mkdir()
    (tmp_path / "two").mkdir()
    (tmp_path / "one" / "same.txt").write_bytes(b"1")
    (tmp_path / "two" / "same.txt").write_bytes(b"2")
    driveRoot = Path(tmp_path.anchor)
    host = hostFor(sftpServer, identityFile=clientKeyFile)
    store.add(host)
    window = _window(qtbot, store, tmp_path)
    windows.append(window)
    window.show()
    tab = _openSftpTab(qtbot, window, host, localDir)

    mime = QMimeData()
    mime.setUrls(
        [
            QUrl.fromLocalFile(str(dropped)),
            QUrl.fromLocalFile(str(driveRoot)),
            QUrl.fromLocalFile(str(tmp_path / "one" / "same.txt")),
            QUrl.fromLocalFile(str(tmp_path / "two" / "same.txt")),
            QUrl.fromLocalFile(str(tmp_path / "does-not-exist.txt")),
        ]
    )
    _dropOn(tab.remotePane, mime, None)
    qtbot.waitUntil(lambda: (root / "dropped.txt").exists(), timeout=WAIT_MS)
    qtbot.waitUntil(lambda: tab.transferStrip.isHidden(), timeout=WAIT_MS)
    assert not (root / "same.txt").exists()
    status = tab.statusLabel.text()
    assert status.startswith("Not uploaded:")
    assert str(driveRoot) in status and "same.txt" in status and "does-not-exist.txt" in status


def test_explorer_files_dropped_anywhere_on_the_sftp_tab_upload_to_the_remote_folder(
    qtbot: QtBot, sftpServer: TestSshServer, clientKeyFile: Path, store: HostStore, tmp_path: Path,
    windows: list[MainWindow],
) -> None:
    root = _sftpRoot(sftpServer)
    (root / "inbox").mkdir()
    localDir = tmp_path / "local"
    localDir.mkdir()
    dropped = tmp_path / "from-desktop.txt"
    dropped.write_bytes(b"desktop file")
    host = hostFor(sftpServer, identityFile=clientKeyFile)
    store.add(host)
    window = _window(qtbot, store, tmp_path)
    windows.append(window)
    window.show()
    tab = _openSftpTab(qtbot, window, host, localDir)
    tab.remotePane.navigateRequested.emit("/inbox")
    qtbot.waitUntil(lambda: tab.remotePane.currentPath() == "/inbox", timeout=WAIT_MS)

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(dropped))])
    assert tab.acceptDrops()
    offered = Qt.DropAction.CopyAction | Qt.DropAction.MoveAction
    event = QDropEvent(QPointF(1, 1), offered, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    tab.dropEvent(event)
    assert event.isAccepted() and event.dropAction() == Qt.DropAction.CopyAction
    qtbot.waitUntil(lambda: (root / "inbox" / "from-desktop.txt").exists(), timeout=WAIT_MS)
    assert dropped.exists()


def test_transfer_strip_keeps_its_bar_when_the_file_name_is_long(
    qtbot: QtBot, sftpServer: TestSshServer, clientKeyFile: Path, store: HostStore, tmp_path: Path,
    windows: list[MainWindow],
) -> None:
    localDir = tmp_path / "local"
    localDir.mkdir()
    longName = "n" * 240 + ".bin"
    (localDir / longName).write_bytes(b"\x00" * (8 * 1024 * 1024))
    host = hostFor(sftpServer, identityFile=clientKeyFile)
    store.add(host)
    window = _window(qtbot, store, tmp_path)
    windows.append(window)
    window.show()
    tab = _openSftpTab(qtbot, window, host, localDir)
    _selectNamed(tab.localPane, longName)
    qtbot.mouseClick(tab.uploadButton, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: longName in tab.transferLabel.text(), timeout=WAIT_MS)
    assert tab.transferBar.width() >= PROGRESS_BAR_MIN_WIDTH
    assert tab.transferLabel.elidedText() != tab.transferLabel.text()
    assert tab.transferLabel.width() + tab.transferBar.width() + tab.cancelButton.width() <= tab.transferStrip.width()
    qtbot.waitUntil(lambda: tab.transferStrip.isHidden(), timeout=WAIT_MS)


def test_cancel_button_stops_a_transfer(
    qtbot: QtBot, sftpServer: TestSshServer, clientKeyFile: Path, store: HostStore, tmp_path: Path,
    windows: list[MainWindow],
) -> None:
    localDir = tmp_path / "local"
    localDir.mkdir()
    (localDir / "huge.bin").write_bytes(b"\x00" * (16 * 1024 * 1024))
    host = hostFor(sftpServer, identityFile=clientKeyFile)
    store.add(host)
    window = _window(qtbot, store, tmp_path)
    windows.append(window)
    window.show()
    tab = _openSftpTab(qtbot, window, host, localDir)
    _selectNamed(tab.localPane, "huge.bin")
    qtbot.mouseClick(tab.uploadButton, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: tab.transferBar.value() > 0, timeout=WAIT_MS)
    qtbot.mouseClick(tab.cancelButton, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: tab.statusLabel.text() == "Transfer cancelled", timeout=WAIT_MS)
    qtbot.waitUntil(lambda: tab.transferStrip.isHidden(), timeout=WAIT_MS)
    assert not (_sftpRoot(sftpServer) / "huge.bin").exists()


def test_sftp_tab_prompts_for_a_password(
    qtbot: QtBot, sftpServer: TestSshServer, store: HostStore, tmp_path: Path, windows: list[MainWindow]
) -> None:
    host = hostFor(sftpServer)
    store.add(host)
    prompts: list[str] = []
    window = _window(qtbot, store, tmp_path, prompts=prompts, answer=TEST_PASSWORD)
    windows.append(window)
    window.openSftp(host)
    tab = window.sftpTabs()[0]
    qtbot.waitUntil(lambda: tab.remotePane.currentPath() == "/", timeout=WAIT_MS)
    assert prompts == ["box"]


def test_sftp_tab_reports_connection_failure(
    qtbot: QtBot, store: HostStore, tmp_path: Path, windows: list[MainWindow]
) -> None:
    host = Host(name="dead", hostname="127.0.0.1", user="x", port=1)
    store.add(host)
    window = _window(qtbot, store, tmp_path)
    windows.append(window)
    window.openSftp(host)
    tab = window.sftpTabs()[0]
    qtbot.waitUntil(lambda: "Could not reach" in tab.statusLabel.text(), timeout=WAIT_MS)


def test_shutdown_stops_tunnels(
    qtbot: QtBot, sshServer: TestSshServer, echoServer: EchoServer, clientKeyFile: Path,
    store: HostStore, tmp_path: Path,
) -> None:
    port = _freePort()
    host = _forwardingHost(sshServer, echoServer.port, port, clientKeyFile)
    store.add(host)
    window = _window(qtbot, store, tmp_path)
    window.startTunnel(host)
    qtbot.waitUntil(lambda: _tunnelText(window, "box") == "Tunnel active", timeout=WAIT_MS)
    window.shutdown()
    assert not window.tunnels.isRunning("box")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))


def test_shutdown_does_not_wait_for_a_host_that_never_answers(
    qtbot: QtBot, blackholeHost: Host, store: HostStore, tmp_path: Path, windows: list[MainWindow],
) -> None:
    """Two refreshes in a row leave one probe dialing and a second queued behind it; neither may delay exit."""
    store.add(blackholeHost)
    window = _window(qtbot, store, tmp_path)
    windows.append(window)
    window.refreshAll()
    window.refreshAll()
    qtbot.wait(300)
    started = time.monotonic()
    window.shutdown()
    assert time.monotonic() - started < 3.0
