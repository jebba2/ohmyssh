"""Tests for editing ~/.ssh/config in place without disturbing anything else in it."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pyommyssh.core.forwards import ForwardKind, PortForward
from pyommyssh.core.hosts import GlobalSettings, Host, parseSshConfig
from pyommyssh.core.sshconfig import MAX_BACKUPS, SshConfigEditor, SshConfigError

JEB_LAYOUT = (
    "Host *\n"
    "    ServerAliveInterval 60\n"
    "    ServerAliveCountMax 3\n"
    "    IdentityFile ~/.ssh/id_rsa\n"
    "    Compression yes\n"
    "    AddKeysToAgent yes\n"
    "\n"
    "Host web\n"
    "    HostName w.local\n"
)


def _editor(tmp_path: Path, text: str | None = None) -> tuple[SshConfigEditor, Path]:
    sshDir = tmp_path / ".ssh"
    sshDir.mkdir(exist_ok=True)
    configPath = sshDir / "config"
    if text is not None:
        configPath.write_text(text, newline="")
    return SshConfigEditor(configPath, home=tmp_path, backupDir=tmp_path / "backups"), configPath


def _webHost(tmp_path: Path) -> Host:
    return Host(
        name="web",
        hostname="10.0.0.5",
        user="deploy",
        port=2222,
        identityFile=tmp_path / ".ssh" / "web_key",
        proxyJump="bastion",
        tags=["prod", "web"],
        forwards=[
            PortForward.parse(ForwardKind.LOCAL, "8080:localhost:80"),
            PortForward.parse(ForwardKind.REMOTE, "9000:127.0.0.1:3000"),
            PortForward.parse(ForwardKind.DYNAMIC, "1080"),
        ],
    )


EXISTING = (
    "# my hosts\n"
    "Host *\n"
    "    ServerAliveInterval 30\n"
    "\n"
    "Host other\n"
    "    HostName other.local\n"
)


def test_new_host_is_appended_as_a_block(tmp_path: Path) -> None:
    editor, configPath = _editor(tmp_path, EXISTING)
    editor.upsertHost(_webHost(tmp_path))
    assert configPath.read_text() == EXISTING + (
        "\n"
        "Host web\n"
        "    HostName 10.0.0.5\n"
        "    User deploy\n"
        "    Port 2222\n"
        "    IdentityFile ~/.ssh/web_key\n"
        "    ProxyJump bastion\n"
        "    LocalForward 8080 localhost:80\n"
        "    RemoteForward 9000 127.0.0.1:3000\n"
        "    DynamicForward 1080\n"
        "    # tags: prod web\n"
    )
    saved = next(host for host in editor.hosts() if host.name == "web")
    expected = _webHost(tmp_path)
    assert (saved.hostname, saved.user, saved.port, saved.identityFile, saved.proxyJump) == (
        expected.hostname, expected.user, expected.port, expected.identityFile, expected.proxyJump
    )
    assert saved.tags == ["prod", "web"]
    assert saved.forwards == expected.forwards
    assert saved.sourceFile == configPath


def test_editing_a_block_touches_only_managed_lines(tmp_path: Path) -> None:
    original = (
        "Host *\n"
        "    ServerAliveInterval 30\n"
        "\n"
        "Host web   # the web box\n"
        "  HostName old.local\n"
        "  Port 22\n"
        "  ServerAliveInterval 10\n"
        "  # keep this comment\n"
        "  LocalForward 1111 localhost:1\n"
        "  LocalForward 2222 localhost:2\n"
        "  # tags: old\n"
        "\n"
        "Host other\n"
        "    HostName other.local\n"
    )
    editor, configPath = _editor(tmp_path, original)
    edited = Host(
        name="web",
        hostname="new.local",
        user="deploy",
        port=22,
        forwards=[PortForward.parse(ForwardKind.DYNAMIC, "1080")],
    )
    editor.upsertHost(edited)
    assert configPath.read_text() == (
        "Host *\n"
        "    ServerAliveInterval 30\n"
        "\n"
        "Host web   # the web box\n"
        "  HostName new.local\n"
        "  User deploy\n"
        "  DynamicForward 1080\n"
        "  ServerAliveInterval 10\n"
        "  # keep this comment\n"
        "\n"
        "Host other\n"
        "    HostName other.local\n"
    )


def test_clearing_optional_fields_removes_their_lines(tmp_path: Path) -> None:
    editor, configPath = _editor(tmp_path)
    editor.upsertHost(_webHost(tmp_path))
    editor.upsertHost(Host(name="web", hostname="10.0.0.5"))
    assert configPath.read_text() == "Host web\n    HostName 10.0.0.5\n"


def test_renaming_within_a_shared_host_line(tmp_path: Path) -> None:
    editor, configPath = _editor(tmp_path, "Host Hermes (jebba)\n    HostName hermes.local\n")
    hermes = next(host for host in editor.hosts() if host.name == "Hermes")
    assert hermes.sharedWith == ["(jebba)"]
    editor.upsertHost(Host(name="hermes2", hostname="hermes.local"), previousName="Hermes")
    assert configPath.read_text() == "Host hermes2 (jebba)\n    HostName hermes.local\n"
    assert sorted(host.name for host in editor.hosts()) == ["(jebba)", "hermes2"]


def test_host_in_an_included_file_is_edited_there(tmp_path: Path) -> None:
    editor, configPath = _editor(tmp_path, "Include conf.d/*.conf\nHost main\n    HostName main.local\n")
    included = tmp_path / ".ssh" / "conf.d" / "a.conf"
    included.parent.mkdir()
    included.write_text("Host inc\n    HostName inc.local\n")
    inc = next(host for host in editor.hosts() if host.name == "inc")
    assert inc.sourceFile == included
    editor.upsertHost(Host(name="inc", hostname="moved.local", user="u"))
    assert included.read_text() == "Host inc\n    HostName moved.local\n    User u\n"
    assert configPath.read_text() == "Include conf.d/*.conf\nHost main\n    HostName main.local\n"


def test_every_save_backs_up_the_file_and_keeps_the_last_few(tmp_path: Path) -> None:
    editor, configPath = _editor(tmp_path, EXISTING)
    backups = tmp_path / "backups"
    for index in range(MAX_BACKUPS + 2):
        editor.upsertHost(Host(name="web", hostname=f"host{index}.local"))
    saved = sorted(backups.iterdir())
    assert len(saved) == MAX_BACKUPS
    assert all(path.name.startswith("config-") and path.suffix == ".bak" for path in saved)
    # The newest backup holds the text from just before the last save.
    assert "host10.local" in saved[-1].read_text()
    assert "host11.local" in configPath.read_text()
    assert not list(configPath.parent.glob("*.tmp"))


def test_crlf_line_endings_are_kept(tmp_path: Path) -> None:
    editor, configPath = _editor(tmp_path, "Host other\r\n    HostName other.local\r\n")
    editor.upsertHost(Host(name="web", hostname="w.local"))
    assert configPath.read_bytes() == b"Host other\r\n    HostName other.local\r\n\r\nHost web\r\n    HostName w.local\r\n"


def test_paths_with_spaces_are_quoted_and_read_back(tmp_path: Path) -> None:
    editor, configPath = _editor(tmp_path)
    keyPath = tmp_path / "my keys" / "id_ed25519"
    editor.upsertHost(Host(name="web", hostname="w.local", identityFile=keyPath))
    assert 'IdentityFile "~/my keys/id_ed25519"' in configPath.read_text()
    assert editor.hosts()[0].identityFile == keyPath


def test_missing_config_file_is_created(tmp_path: Path) -> None:
    editor, configPath = _editor(tmp_path)
    assert editor.hosts() == []
    editor.upsertHost(Host(name="web", hostname="w.local"))
    assert configPath.read_text() == "Host web\n    HostName w.local\n"
    assert parseSshConfig(configPath.read_text(), home=tmp_path)[0].hostname == "w.local"


@pytest.mark.parametrize("name", ["has space", "wild*", "any?", "!neg", "hash#"])
def test_unsafe_names_are_refused_before_anything_is_written(tmp_path: Path, name: str) -> None:
    editor, configPath = _editor(tmp_path, EXISTING)
    with pytest.raises(SshConfigError, match="cannot be used as a Host name"):
        editor.upsertHost(Host(name=name, hostname="w.local"))
    assert configPath.read_text() == EXISTING
    assert not (tmp_path / "backups").exists()


def test_values_with_newlines_are_refused(tmp_path: Path) -> None:
    editor, configPath = _editor(tmp_path, EXISTING)
    with pytest.raises(SshConfigError, match="newline"):
        editor.upsertHost(Host(name="web", hostname="a\nHost evil"))
    assert configPath.read_text() == EXISTING


@pytest.mark.skipif(os.name == "nt", reason="permission bits are not meaningful on Windows")
def test_new_config_file_is_private(tmp_path: Path) -> None:
    editor, configPath = _editor(tmp_path)
    editor.upsertHost(Host(name="web", hostname="w.local"))
    assert configPath.stat().st_mode & 0o777 == 0o600


def test_global_settings_are_read_from_the_host_star_block(tmp_path: Path) -> None:
    editor, _ = _editor(tmp_path, JEB_LAYOUT)
    assert editor.globalSettings() == GlobalSettings(
        serverAliveInterval=60,
        serverAliveCountMax=3,
        identityFile=tmp_path / ".ssh" / "id_rsa",
        compression=True,
    )
    bare, _ = _editor(tmp_path, EXISTING)
    assert bare.globalSettings() == GlobalSettings()
    missing = SshConfigEditor(tmp_path / "nope" / "config", home=tmp_path)
    assert missing.globalSettings() == GlobalSettings()


def test_saving_global_settings_creates_a_host_star_block_at_the_end(tmp_path: Path) -> None:
    editor, configPath = _editor(tmp_path, "Host web\n    HostName w.local\n")
    editor.upsertGlobal(GlobalSettings(serverAliveInterval=60, serverAliveCountMax=3, compression=True))
    assert configPath.read_text() == (
        "Host web\n"
        "    HostName w.local\n"
        "\n"
        "Host *\n"
        "    ServerAliveInterval 60\n"
        "    ServerAliveCountMax 3\n"
        "    Compression yes\n"
    )
    assert editor.globalSettings() == GlobalSettings(serverAliveInterval=60, serverAliveCountMax=3, compression=True)


def test_saving_global_settings_moves_a_top_block_to_the_end_and_keeps_its_other_lines(tmp_path: Path) -> None:
    editor, configPath = _editor(tmp_path, JEB_LAYOUT)
    editor.upsertGlobal(
        GlobalSettings(serverAliveInterval=30, identityFile=tmp_path / ".ssh" / "id_rsa", compression=False)
    )
    assert configPath.read_text() == (
        "Host web\n"
        "    HostName w.local\n"
        "\n"
        "Host *\n"
        "    ServerAliveInterval 30\n"
        "    IdentityFile ~/.ssh/id_rsa\n"
        "    Compression no\n"
        "    AddKeysToAgent yes\n"
    )
    # Hosts are unaffected by the move.
    assert [host.name for host in editor.hosts()] == ["web"]


def test_saving_global_settings_leaves_a_block_already_at_the_end_in_place(tmp_path: Path) -> None:
    text = "Host web\n    HostName w.local\n\n# defaults\nHost *\n    Compression yes\n"
    editor, configPath = _editor(tmp_path, text)
    editor.upsertGlobal(GlobalSettings(compression=True, serverAliveInterval=15))
    assert configPath.read_text() == (
        "Host web\n    HostName w.local\n\n# defaults\nHost *\n    ServerAliveInterval 15\n    Compression yes\n"
    )


def test_host_keepalive_and_compression_lines_are_managed(tmp_path: Path) -> None:
    editor, configPath = _editor(tmp_path)
    host = Host(name="web", hostname="w.local", serverAliveInterval=30, serverAliveCountMax=5, compression=True)
    editor.upsertHost(host)
    assert configPath.read_text() == (
        "Host web\n"
        "    HostName w.local\n"
        "    ServerAliveInterval 30\n"
        "    ServerAliveCountMax 5\n"
        "    Compression yes\n"
    )
    saved = editor.hosts()[0]
    assert (saved.serverAliveInterval, saved.serverAliveCountMax, saved.compression) == (30, 5, True)
    editor.upsertHost(Host(name="web", hostname="w.local", compression=False))
    assert configPath.read_text() == "Host web\n    HostName w.local\n    Compression no\n"
    editor.upsertHost(Host(name="web", hostname="w.local"))
    assert configPath.read_text() == "Host web\n    HostName w.local\n"
