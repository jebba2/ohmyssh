"""Run a port forwarding tunnel to one host from the command line.

Run from the project root, naming a host from ~/.ssh/config or hosts.toml.
With no rules on the command line the host's own forwards are used;
otherwise each rule is ``-L``, ``-R`` or ``-D`` followed by its spec in
OpenSSH notation:

    uv run python examples/forward_port.py myserver
    uv run python examples/forward_port.py myserver -L 8080:localhost:80
    uv run python examples/forward_port.py myserver -D 1080 -R 9000:127.0.0.1:3000

The tunnel stays up, reconnecting if the connection drops, until Ctrl+C.
If key authentication is not enough, you are asked for a password.
"""

from __future__ import annotations

import getpass
import sys
import threading
import time
from pathlib import Path

from ohmyssh.core.config import AppPaths
from ohmyssh.core.connections import ConnectionPool
from ohmyssh.core.forwards import ForwardKind, PortForward
from ohmyssh.core.hosts import HostStore, loadSshConfig, mergeHosts
from ohmyssh.core.ssh import SshCredentials
from ohmyssh.core.tunnel import TunnelManager, TunnelState, TunnelStatus

FLAG_KINDS = {"-L": ForwardKind.LOCAL, "-R": ForwardKind.REMOTE, "-D": ForwardKind.DYNAMIC}


def parseRules(arguments: list[str]) -> list[PortForward]:
    """Turn ``-L spec -R spec -D spec`` arguments into rules; raises ValueError."""
    rules: list[PortForward] = []
    pending = list(arguments)
    while pending:
        flag = pending.pop(0)
        if flag not in FLAG_KINDS or not pending:
            raise ValueError(f"expected -L, -R or -D followed by a rule, got '{flag}'")
        rules.append(PortForward.parse(FLAG_KINDS[flag], pending.pop(0)))
    return rules


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    name = sys.argv[1]
    try:
        rules = parseRules(sys.argv[2:])
    except ValueError as error:
        print(f"Bad rule: {error}")
        return 2

    paths = AppPaths.default()
    store = HostStore(paths.hostsFile)
    store.load()
    hosts = mergeHosts(loadSshConfig(), store.hosts(), store.hiddenNames())
    host = next((candidate for candidate in hosts if candidate.name == name), None)
    if host is None:
        print(f"No host named '{name}'. Known hosts: {', '.join(h.name for h in hosts)}")
        return 1
    if rules:
        host.forwards = rules
    if not host.forwards:
        print(f"'{name}' has no port forwards; pass some with -L, -R or -D.")
        return 1

    finished = threading.Event()
    outcome: list[TunnelStatus] = []

    def onStatus(_: str, status: TunnelStatus) -> None:
        print(f"{status.state.value}{': ' + status.message if status.message else ''}")
        if not status.isActive():
            outcome.append(status)
            finished.set()

    pool = ConnectionPool(lambda: hosts, Path.home() / ".ssh" / "known_hosts")
    tunnels = TunnelManager(pool, onStatus)
    for forward in host.forwards:
        print(forward.describe())
    try:
        tunnels.start(host)
        while not finished.wait(0.5):
            pass
        if outcome and outcome[-1].state == TunnelState.AUTH_REQUIRED:
            password = getpass.getpass(f"Password for {host.displayAddress()}: ")
            pool.setCredentials(host.name, SshCredentials(password=password))
            finished.clear()
            tunnels.start(host)
            while not finished.wait(0.5):
                pass
    except KeyboardInterrupt:
        print("Stopping")
    finally:
        tunnels.shutdown()
        pool.closeAll()
        time.sleep(0.1)
    return 0 if not outcome or outcome[-1].state == TunnelState.STOPPED else 1


if __name__ == "__main__":
    sys.exit(main())
