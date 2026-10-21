"""Print every host pyommyssh knows about, from ~/.ssh/config and hosts.toml.

Run from the project root:

    uv run python examples/list_hosts.py
"""

from __future__ import annotations

from pyommyssh.core.config import AppPaths
from pyommyssh.core.hosts import HostStore, loadSshConfig, mergeHosts


def main() -> None:
    paths = AppPaths.default()
    store = HostStore(paths.hostsFile)
    store.load()
    hosts = mergeHosts(loadSshConfig(), store.hosts(), store.hiddenNames())
    if not hosts:
        print("No hosts found. Add some in ~/.ssh/config or through the app.")
        return
    width = max(len(host.name) for host in hosts)
    for host in hosts:
        jump = f" via {host.proxyJump}" if host.proxyJump else ""
        tags = f"  [{', '.join(host.tags)}]" if host.tags else ""
        print(f"{host.name:<{width}}  {host.displayAddress()}{jump}  ({host.source.value}){tags}")


if __name__ == "__main__":
    main()
