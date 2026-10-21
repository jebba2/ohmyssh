"""Installing a public key into a host's ``~/.ssh/authorized_keys``.

This is the ``ssh-copy-id`` idea over an existing connection: the key line
is appended once, never overwriting the file, and the directory and file
permissions are tightened to what sshd insists on. The private key never
leaves this machine.
"""

from __future__ import annotations

import re
from pathlib import Path

from pyommyssh.core.ssh import SshClient

INSTALLED_MARKER = "PYOMMYSSH:INSTALLED"
PRESENT_MARKER = "PYOMMYSSH:PRESENT"

_KEY_TYPE_PATTERN = re.compile(r"^(sk-)?(ssh|ecdsa)-[A-Za-z0-9@.\-]+$")
_BASE64_PATTERN = re.compile(r"^[A-Za-z0-9+/]+=*$")


class KeyInstallError(Exception):
    """The server did not confirm that the key was installed."""


def readPublicKey(path: Path) -> str:
    """Return the single public key line in ``path``; raises ValueError otherwise."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError(f"{path} could not be read: {error}") from error
    if "PRIVATE KEY" in text:
        raise ValueError(f"{path} is a private key; choose the matching .pub file")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError(f"{path} is empty")
    if len(lines) > 1:
        raise ValueError(f"{path} holds more than one line; a public key file has exactly one")
    parts = lines[0].split()
    if len(parts) < 2 or not _KEY_TYPE_PATTERN.match(parts[0]) or not _BASE64_PATTERN.match(parts[1]):
        raise ValueError(f"{path} does not look like an OpenSSH public key")
    return lines[0]


def _shellQuote(text: str) -> str:
    """Single-quote ``text`` for a POSIX shell."""
    return "'" + text.replace("'", "'\\''") + "'"


def _splitMarker(marker: str) -> str:
    """Write a marker as two shell-concatenated halves.

    The shell prints the whole marker, but the command text never contains
    it, so a server that echoes the command back cannot look like a success.
    """
    half = len(marker) // 2
    return f"{marker[:half]}''{marker[half:]}"


def buildInstallKeyCommand(publicKey: str) -> str:
    """Return a shell command that appends ``publicKey`` once and fixes permissions.

    The lookup matches the key type and material only, so the same key with
    another comment is recognised as already present. Errors are folded into
    stdout so the caller sees them.
    """
    keyIdentity = " ".join(publicKey.split()[:2])
    return (
        "{ umask 077; mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys && "
        f"if grep -qF {_shellQuote(keyIdentity)} ~/.ssh/authorized_keys; then echo {_splitMarker(PRESENT_MARKER)}; "
        f"else printf '%s\\n' {_shellQuote(publicKey)} >> ~/.ssh/authorized_keys && echo {_splitMarker(INSTALLED_MARKER)}; fi && "
        "chmod 600 ~/.ssh/authorized_keys; } 2>&1"
    )


def parseInstallOutput(output: str) -> bool:
    """Return True if the key was added, False if it was already there."""
    if INSTALLED_MARKER in output:
        return True
    if PRESENT_MARKER in output:
        return False
    if not output.strip():
        raise KeyInstallError("The server returned no output")
    raise KeyInstallError(f"Unexpected reply from the server: {output.strip()}")


def installPublicKey(client: SshClient, publicKey: str) -> bool:
    """Install ``publicKey`` for the connected user. Returns True if it was newly added."""
    return parseInstallOutput(client.runCommand(buildInstallKeyCommand(publicKey)))
