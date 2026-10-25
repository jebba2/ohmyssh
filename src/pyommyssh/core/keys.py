"""SSH key pairs: generating them locally and installing public keys on hosts.

Installing is the ``ssh-copy-id`` idea over an existing connection: the key
line is appended once, never overwriting the file, and the directory and
file permissions are tightened to what sshd insists on. The private key
never leaves this machine.

Generation writes OpenSSH-format files, so ``ssh`` and ``ssh-keygen`` read
them as their own. Existing files are never overwritten.
"""

from __future__ import annotations

import getpass
import os
import re
import socket
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa

from pyommyssh.core.ssh import SshClient

INSTALLED_MARKER = "PYOMMYSSH:INSTALLED"
PRESENT_MARKER = "PYOMMYSSH:PRESENT"
RSA_BITS = 4096
PRIVATE_KEY_MODE = 0o600
PUBLIC_KEY_MODE = 0o644
KEY_DIR_MODE = 0o700

_KEY_TYPE_PATTERN = re.compile(r"^(sk-)?(ssh|ecdsa)-[A-Za-z0-9@.\-]+$")
_BASE64_PATTERN = re.compile(r"^[A-Za-z0-9+/]+=*$")


class KeyInstallError(Exception):
    """The server did not confirm that the key was installed."""


class KeyType(Enum):
    """Key algorithms we can generate. Ed25519 is the modern default; RSA for old servers."""

    ED25519 = "ed25519"
    RSA = "rsa"


@dataclass(frozen=True)
class KeyGenerateRequest:
    """Everything ``generateKeyPair`` needs, as collected from the user."""

    privatePath: Path
    keyType: KeyType
    comment: str
    passphrase: str | None


def defaultKeyFileName(keyType: KeyType) -> str:
    """The file name ``ssh`` looks for by default: ``id_ed25519`` or ``id_rsa``."""
    return f"id_{keyType.value}"


def defaultKeyComment() -> str:
    """``user@machine``, as ssh-keygen would write it."""
    return f"{getpass.getuser()}@{socket.gethostname()}"


def _newPrivateKey(keyType: KeyType) -> ed25519.Ed25519PrivateKey | rsa.RSAPrivateKey:
    if keyType == KeyType.RSA:
        return rsa.generate_private_key(public_exponent=65537, key_size=RSA_BITS)
    return ed25519.Ed25519PrivateKey.generate()


def _writeNewFile(path: Path, data: bytes, mode: int) -> None:
    """Create ``path`` with ``mode``, failing if it already exists."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)


def generateKeyPair(privatePath: Path, keyType: KeyType, comment: str, passphrase: str | None) -> Path:
    """Write a new key pair to ``privatePath`` and ``privatePath.pub``; returns the public path.

    Raises FileExistsError if either file is already there, ValueError for a
    bad comment, and OSError if the files cannot be written.
    """
    if "\n" in comment or "\r" in comment:
        raise ValueError("The comment must be a single line")
    publicPath = privatePath.with_name(privatePath.name + ".pub")
    for path in (privatePath, publicPath):
        if path.exists():
            raise FileExistsError(f"{path} already exists")

    privateKey = _newPrivateKey(keyType)
    encryption: serialization.KeySerializationEncryption
    if passphrase:
        encryption = serialization.BestAvailableEncryption(passphrase.encode("utf-8"))
    else:
        encryption = serialization.NoEncryption()
    privateBytes = privateKey.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, encryption
    )
    publicLine = privateKey.public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
    ).decode("ascii")
    if comment.strip():
        publicLine = f"{publicLine} {comment.strip()}"

    privatePath.parent.mkdir(parents=True, exist_ok=True, mode=KEY_DIR_MODE)
    _writeNewFile(privatePath, privateBytes, PRIVATE_KEY_MODE)
    _writeNewFile(publicPath, (publicLine + "\n").encode("ascii"), PUBLIC_KEY_MODE)
    return publicPath


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
    another comment is recognised as already present. A file whose last key
    has no newline after it gets one first, so the new key never runs into
    the old one's line. Errors are folded into stdout so the caller sees them.
    """
    keyIdentity = " ".join(publicKey.split()[:2])
    authorized = "~/.ssh/authorized_keys"
    # tail -c 1 prints the last byte; a newline disappears in the substitution, anything else does not.
    endWithNewline = f'if [ -s {authorized} ] && [ -n "$(tail -c 1 {authorized})" ]; then echo >> {authorized}; fi'
    return (
        f"{{ umask 077; mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch {authorized} && "
        f"if grep -qF {_shellQuote(keyIdentity)} {authorized}; then echo {_splitMarker(PRESENT_MARKER)}; "
        f"else {endWithNewline} && printf '%s\\n' {_shellQuote(publicKey)} >> {authorized} && "
        f"echo {_splitMarker(INSTALLED_MARKER)}; fi && chmod 600 {authorized}; }} 2>&1"
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
