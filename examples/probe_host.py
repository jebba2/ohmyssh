"""Connect to one host and print the dashboard metrics for it.

Run from the project root, naming a host from ~/.ssh/config or hosts.toml:

    uv run python examples/probe_host.py myserver

If key authentication is not enough, you are asked for a password.
"""

from __future__ import annotations

import getpass
import sys
from pathlib import Path

from ohmyssh.core.config import AppPaths
from ohmyssh.core.connections import ConnectionPool
from ohmyssh.core.hosts import HostStore, loadSshConfig, mergeHosts
from ohmyssh.core.metrics import buildProbeScript, metricsFromProbeOutput
from ohmyssh.core.ssh import SshAuthError, SshCredentials, SshError


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    name = sys.argv[1]
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
        metrics = metricsFromProbeOutput(client.runCommand(buildProbeScript()))
    except SshError as error:
        print(f"Failed: {error}")
        return 1
    finally:
        pool.closeAll()

    print(f"{host.name} ({host.displayAddress()})")
    print(f"  OS:      {metrics.osName or 'unknown'}")
    print(f"  CPU:     {metrics.cpuPercent if metrics.cpuPercent is not None else 'n/a'}%")
    print(f"  RAM:     {metrics.memPercent if metrics.memPercent is not None else 'n/a'}%")
    print(f"  Disk:    {metrics.diskPercent if metrics.diskPercent is not None else 'n/a'}%")
    print(f"  Uptime:  {metrics.uptime or 'n/a'}")
    print(f"  Load:    {metrics.loadAverage or 'n/a'}")
    print(f"  Docker:  {metrics.dockerContainers if metrics.dockerContainers is not None else 'not installed'}")
    for process in metrics.processes:
        print(f"  Process: {process.name} cpu {process.cpuPercent}% mem {process.memPercent}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
