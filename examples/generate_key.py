"""Generate a new SSH key pair in OpenSSH format.

Run from the project root, naming where the private key should go. The
public key is written beside it with a .pub extension. Existing files are
never overwritten:

    uv run python examples/generate_key.py ~/.ssh/id_ed25519
    uv run python examples/generate_key.py ~/.ssh/id_rsa --rsa
    uv run python examples/generate_key.py ~/.ssh/work_key --comment jeb@work --passphrase

``--rsa`` makes a 4096-bit RSA key instead of Ed25519. ``--passphrase``
asks for a passphrase to encrypt the private key with.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

from pyommyssh.core.keys import KeyType, defaultKeyComment, generateKeyPair


def main() -> int:
    arguments = sys.argv[1:]
    if not arguments or arguments[0].startswith("--"):
        print(__doc__)
        return 2
    privatePath = Path(arguments.pop(0)).expanduser()
    keyType = KeyType.ED25519
    comment = defaultKeyComment()
    wantsPassphrase = False
    while arguments:
        flag = arguments.pop(0)
        if flag == "--rsa":
            keyType = KeyType.RSA
        elif flag == "--passphrase":
            wantsPassphrase = True
        elif flag == "--comment" and arguments:
            comment = arguments.pop(0)
        else:
            print(f"Unknown option: {flag}")
            print(__doc__)
            return 2

    passphrase: str | None = None
    if wantsPassphrase:
        passphrase = getpass.getpass("Passphrase: ")
        if passphrase != getpass.getpass("Confirm passphrase: "):
            print("Passphrases do not match")
            return 2
        passphrase = passphrase or None

    try:
        publicPath = generateKeyPair(privatePath, keyType, comment, passphrase)
    except (OSError, ValueError) as error:
        print(f"Failed: {error}")
        return 1
    print(f"Private key: {privatePath}")
    print(f"Public key:  {publicPath}")
    print(publicPath.read_text().strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
