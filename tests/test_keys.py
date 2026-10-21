"""Tests for installing a public key into a host's authorized_keys."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from pyommyssh.core.keys import (
    KeyInstallError,
    buildInstallKeyCommand,
    installPublicKey,
    parseInstallOutput,
    readPublicKey,
)
from pyommyssh.core.ssh import SshClient, SshCredentials
from tests.sshserver import TEST_PASSWORD, TestSshServer, hostFor

ED25519_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGxkZXN0cmlwcGVkLWZha2Uta2V5LWJ5dGVzLWhlcmUx jeb@laptop"
RSA_KEY = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC7fakekeybytes jeb@desk"


def test_read_public_key_strips_whitespace(tmp_path: Path) -> None:
    path = tmp_path / "id_ed25519.pub"
    path.write_text(f"  {ED25519_KEY}\n\n")
    assert readPublicKey(path) == ED25519_KEY


def test_read_public_key_accepts_a_key_without_a_comment(tmp_path: Path) -> None:
    path = tmp_path / "id.pub"
    path.write_text("ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC7fakekeybytes\n")
    assert readPublicKey(path) == "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC7fakekeybytes"


@pytest.mark.parametrize(
    "contents, message",
    [
        ("", "is empty"),
        ("-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----\n", "is a private key"),
        (f"{ED25519_KEY}\n{RSA_KEY}\n", "holds more than one line"),
        ("hello world\n", "does not look like an OpenSSH public key"),
        ("ssh-ed25519\n", "does not look like an OpenSSH public key"),
        ("ssh-ed25519 not*base64 comment\n", "does not look like an OpenSSH public key"),
    ],
)
def test_read_public_key_rejects_bad_files(tmp_path: Path, contents: str, message: str) -> None:
    path = tmp_path / "key.pub"
    path.write_text(contents)
    with pytest.raises(ValueError, match=message):
        readPublicKey(path)


def test_read_public_key_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="could not be read"):
        readPublicKey(tmp_path / "nope.pub")


def test_install_command_appends_once_and_fixes_permissions() -> None:
    command = buildInstallKeyCommand(ED25519_KEY)
    assert "mkdir -p ~/.ssh" in command
    assert "chmod 700 ~/.ssh" in command
    assert "chmod 600 ~/.ssh/authorized_keys" in command
    # The lookup ignores the comment so a renamed copy of the same key is not added twice.
    assert "grep -qF 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGxkZXN0cmlwcGVkLWZha2Uta2V5LWJ5dGVzLWhlcmUx'" in command
    assert f"'{ED25519_KEY}'" in command
    # The markers are assembled by the shell, so a server echoing the command cannot fake success.
    assert "PYOMMYSSH:INSTALLED" not in command
    assert "PYOMMYSSH:PRESENT" not in command
    assert "echo PYOMMYSSH''" in command


def test_install_command_quotes_single_quotes_in_comments() -> None:
    command = buildInstallKeyCommand("ssh-rsa AAAAB3Nza jeb's key")
    assert "'ssh-rsa AAAAB3Nza jeb'\\''s key'" in command


def test_parse_install_output() -> None:
    assert parseInstallOutput("PYOMMYSSH:INSTALLED\n") is True
    assert parseInstallOutput("some noise\nPYOMMYSSH:PRESENT\n") is False
    with pytest.raises(KeyInstallError, match="Permission denied"):
        parseInstallOutput("bash: /home/x/.ssh/authorized_keys: Permission denied\n")
    with pytest.raises(KeyInstallError, match="no output"):
        parseInstallOutput("")


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs a POSIX shell to run the command")
def test_install_command_runs_idempotently_in_a_real_shell(tmp_path: Path) -> None:
    environment = {**os.environ, "HOME": str(tmp_path)}
    bash = shutil.which("bash")
    assert bash is not None

    def run(key: str) -> str:
        completed = subprocess.run(
            [bash, "-c", buildInstallKeyCommand(key)], capture_output=True, text=True, env=environment, check=False
        )
        return completed.stdout + completed.stderr

    assert parseInstallOutput(run(ED25519_KEY)) is True
    assert parseInstallOutput(run(ED25519_KEY)) is False
    sameKeyNewComment = ED25519_KEY.rsplit(" ", 1)[0] + " renamed"
    assert parseInstallOutput(run(sameKeyNewComment)) is False
    assert parseInstallOutput(run(RSA_KEY)) is True
    authorized = (tmp_path / ".ssh" / "authorized_keys").read_text()
    assert authorized == f"{ED25519_KEY}\n{RSA_KEY}\n"


def test_install_public_key_over_ssh(sshServer: TestSshServer, tmp_path: Path) -> None:
    sshServer.execOutput = lambda command: "PYOMMYSSH:INSTALLED\n" if "authorized_keys" in command else ""
    client = SshClient(
        hostFor(sshServer), credentials=SshCredentials(password=TEST_PASSWORD), knownHostsPath=tmp_path / "kh"
    )
    client.connect()
    try:
        assert installPublicKey(client, ED25519_KEY) is True
        assert sshServer.commands == [buildInstallKeyCommand(ED25519_KEY)]
    finally:
        client.close()


def test_install_public_key_reports_unexpected_output(sshServer: TestSshServer, tmp_path: Path) -> None:
    client = SshClient(
        hostFor(sshServer), credentials=SshCredentials(password=TEST_PASSWORD), knownHostsPath=tmp_path / "kh"
    )
    client.connect()
    try:
        with pytest.raises(KeyInstallError, match="you ran:"):
            installPublicKey(client, ED25519_KEY)
    finally:
        client.close()
