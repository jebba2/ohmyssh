"""Append a public key to a host's ~/.ssh/authorized_keys, like ssh-copy-id.

Run from the project root, naming a host from ~/.ssh/config or hosts.toml
and optionally the public key file. Without one, ~/.ssh/id_ed25519.pub is
used:

    uv run python examples/install_key.py myserver
    uv run python examples/install_key.py myserver ~/.ssh/id_rsa.pub

The key is added only if it is not already there, and the directory and
file permissions are tightened. If key authentication is not enough yet,
you are asked for a password.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

from ohmyssh.core.config import AppPaths
from ohmyssh.core.connections import ConnectionPool
from ohmyssh.core.hosts import HostStore, loadSshConfig, mergeHosts
from ohmyssh.core.keys import KeyInstallError, installPublicKey, readPublicKey
from ohmyssh.core.ssh import SshAuthError, SshCredentials, SshError

DEFAULT_PUBLIC_KEY = Path.home() / ".ssh" / "id_ed25519.pub"


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print(__doc__)
        return 2
    name = sys.argv[1]
    keyPath = Path(sys.argv[2]).expanduser() if len(sys.argv) == 3 else DEFAULT_PUBLIC_KEY
    try:
        publicKey = readPublicKey(keyPath)
    except ValueError as error:
        print(f"Bad key file: {error}")
        return 2

    paths = AppPaths.default()
    store = HostStore(paths.hostsFile)
    store.load()
    hosts = mergeHosts(loadSshConfig(), store.hosts(), store.hiddenNames())
    host = next((candidate for candidate in hosts if candidate.name == name), None)
    if host is None:
        print(f"No host named '{name}'. Known hosts: {', '.join(h.name for h in hosts)}")
        return 1

    pool = ConnectionPool(lambda: hosts, Path.home() / ".ssh" / "known_hosts")
    try:
        try:
            client = pool.connection(host)
        except SshAuthError:
            password = getpass.getpass(f"Password for {host.displayAddress()}: ")
            pool.setCredentials(host.name, SshCredentials(password=password))
            client = pool.connection(host)
        newlyAdded = installPublicKey(client, publicKey)
    except (SshError, KeyInstallError) as error:
        print(f"Failed: {error}")
        return 1
    finally:
        pool.closeAll()

    if newlyAdded:
        print(f"Installed {keyPath.name} on {host.name}")
    else:
        print(f"{keyPath.name} is already on {host.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
