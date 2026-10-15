"""Host definitions: parsing ~/.ssh/config and storing app-managed hosts.

The SSH config is read-only. Hosts the user adds inside the app live in a
separate TOML file so we never rewrite the user's own SSH configuration.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import tomli_w

# Include directives deeper than this are ignored, matching OmnySSH.
MAX_INCLUDE_DEPTH = 3


class HostSource(Enum):
    """Where a host definition came from."""

    SSH_CONFIG = "ssh_config"
    APP = "app"


@dataclass
class Host:
    """A connectable SSH host."""

    name: str
    hostname: str
    user: str | None = None
    port: int = 22
    identityFile: Path | None = None
    proxyJump: str | None = None
    tags: list[str] = field(default_factory=list)
    source: HostSource = HostSource.SSH_CONFIG

    def displayAddress(self) -> str:
        """Return a compact user@host:port string, omitting defaults."""
        address = f"{self.user}@{self.hostname}" if self.user else self.hostname
        if self.port != 22:
            address = f"{address}:{self.port}"
        return address


def _isWildcard(pattern: str) -> bool:
    return "*" in pattern or "?" in pattern


def _stripComment(line: str) -> str:
    hashIndex = line.find("#")
    return line if hashIndex < 0 else line[:hashIndex]


_DIRECTIVE_PATTERN = re.compile(r"^(\S+?)\s*(?:=\s*|\s+)(.*)$")


def _splitDirective(line: str) -> tuple[str, str] | None:
    """Split 'Keyword value', 'Keyword=value' or 'Keyword = value' into parts."""
    stripped = _stripComment(line).strip()
    if not stripped:
        return None
    match = _DIRECTIVE_PATTERN.match(stripped)
    if match is None:
        return stripped.lower(), ""
    return match.group(1).lower(), match.group(2).strip()


def _expandHome(value: str, home: Path) -> Path:
    if value.startswith("~"):
        return home / value[1:].lstrip("/\\")
    return Path(value)


def _applyDirective(hosts: list[Host], keyword: str, value: str, home: Path) -> None:
    """Apply a directive to every host from the current Host line."""
    for host in hosts:
        if keyword == "hostname":
            host.hostname = value
        elif keyword == "user":
            host.user = value
        elif keyword == "port":
            if value.isdigit() and 0 < int(value) < 65536:
                host.port = int(value)
        elif keyword == "identityfile" and host.identityFile is None:
            host.identityFile = _expandHome(value, home)
        elif keyword == "proxyjump":
            host.proxyJump = value


def _includePatterns(value: str) -> list[str]:
    """Split an Include value into patterns, honoring double-quoted paths."""
    patterns: list[str] = []
    current: list[str] = []
    inQuotes = False
    for char in value:
        if char == '"':
            inQuotes = not inQuotes
        elif char == " " and not inQuotes:
            if current:
                patterns.append("".join(current))
                current = []
        else:
            current.append(char)
    if current:
        patterns.append("".join(current))
    return patterns


def _resolveIncludes(value: str, baseDir: Path, home: Path) -> list[Path]:
    """Expand Include globs relative to the SSH directory; directories are skipped."""
    resolved: list[Path] = []
    for pattern in _includePatterns(value):
        patternPath = _expandHome(pattern, home)
        if patternPath.is_absolute():
            anchor, glob = patternPath.anchor, str(patternPath.relative_to(patternPath.anchor))
            matches = sorted(Path(anchor).glob(glob))
        else:
            matches = sorted(baseDir.glob(str(patternPath)))
        resolved.extend(match for match in matches if match.is_file())
    return resolved


def _parseLines(
    text: str,
    home: Path,
    baseDir: Path,
    depth: int,
    visited: set[Path],
) -> list[Host]:
    """Parse config text, recursing into Include files up to MAX_INCLUDE_DEPTH."""
    hosts: list[Host] = []
    current: list[Host] = []
    skippingBlock = False

    for line in text.splitlines():
        parts = _splitDirective(line)
        if parts is None:
            continue
        keyword, value = parts

        if keyword == "host":
            patterns = [p for p in value.split() if not _isWildcard(p)]
            current = [Host(name=p, hostname=p) for p in patterns]
            hosts.extend(current)
            skippingBlock = not current
        elif keyword == "match":
            current = []
            skippingBlock = True
        elif keyword == "include":
            if depth < MAX_INCLUDE_DEPTH:
                for path in _resolveIncludes(value, baseDir, home):
                    hosts.extend(_loadFile(path, home, depth + 1, visited))
        elif not skippingBlock:
            _applyDirective(current, keyword, value, home)

    return hosts


def _loadFile(path: Path, home: Path, depth: int, visited: set[Path]) -> list[Host]:
    canonical = path.resolve()
    if canonical in visited or not path.is_file():
        return []
    visited.add(canonical)
    return _parseLines(path.read_text(encoding="utf-8"), home, path.parent, depth, visited)


def parseSshConfig(text: str, home: Path | None = None) -> list[Host]:
    """Parse SSH config text into concrete hosts.

    Wildcard Host blocks and Match blocks are skipped, and their directives
    do not attach to other hosts. Include directives resolve relative to
    ``home/.ssh``.
    """
    home = home or Path.home()
    return _parseLines(text, home, home / ".ssh", depth=0, visited=set())


def loadSshConfig(path: Path | None = None, home: Path | None = None) -> list[Host]:
    """Load hosts from an SSH config file. A missing file yields no hosts."""
    home = home or Path.home()
    path = path or home / ".ssh" / "config"
    return _loadFile(path, home, depth=0, visited=set())


def _hostToToml(host: Host) -> dict[str, object]:
    data: dict[str, object] = {"name": host.name, "hostname": host.hostname, "port": host.port}
    if host.user:
        data["user"] = host.user
    if host.identityFile:
        data["identity_file"] = str(host.identityFile)
    if host.proxyJump:
        data["proxy_jump"] = host.proxyJump
    if host.tags:
        data["tags"] = list(host.tags)
    return data


def _hostFromToml(data: dict[str, object]) -> Host:
    identity = data.get("identity_file")
    rawTags = data.get("tags")
    tags = [str(tag) for tag in rawTags] if isinstance(rawTags, list) else []
    return Host(
        name=str(data["name"]),
        hostname=str(data["hostname"]),
        user=str(data["user"]) if data.get("user") else None,
        port=int(str(data.get("port", 22))),
        identityFile=Path(str(identity)) if identity else None,
        proxyJump=str(data["proxy_jump"]) if data.get("proxy_jump") else None,
        tags=tags,
        source=HostSource.APP,
    )


class HostStore:
    """Hosts added inside the app, persisted to a TOML file."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._hosts: list[Host] = []

    def hosts(self) -> list[Host]:
        """Return a copy of the stored hosts."""
        return list(self._hosts)

    def find(self, name: str) -> Host | None:
        """Return the host with this name, or None."""
        return next((h for h in self._hosts if h.name == name), None)

    def add(self, host: Host) -> None:
        """Add a host; names must be unique within the store."""
        if self.find(host.name) is not None:
            raise ValueError(f"Host '{host.name}' already exists")
        host.source = HostSource.APP
        self._hosts.append(host)

    def update(self, name: str, host: Host) -> None:
        """Replace the host called ``name`` with ``host``."""
        host.source = HostSource.APP
        for index, existing in enumerate(self._hosts):
            if existing.name == name:
                self._hosts[index] = host
                return
        raise ValueError(f"Host '{name}' not found")

    def remove(self, name: str) -> None:
        """Remove the host called ``name``."""
        self._hosts = [h for h in self._hosts if h.name != name]

    def load(self) -> None:
        """Load hosts from disk. A missing file leaves the store empty."""
        if not self._path.is_file():
            self._hosts = []
            return
        with self._path.open("rb") as handle:
            data = tomllib.load(handle)
        self._hosts = [_hostFromToml(entry) for entry in data.get("hosts", [])]

    def save(self) -> None:
        """Write hosts to disk, creating the parent directory if needed."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("wb") as handle:
            tomli_w.dump({"hosts": [_hostToToml(h) for h in self._hosts]}, handle)


def resolveJumpChain(host: Host, hosts: list[Host]) -> list[Host]:
    """Return the jump hosts to pass through before ``host``, outermost first.

    ``ProxyJump`` may list several comma-separated names, and each jump host
    may itself declare a ProxyJump. Unknown names and cycles raise ValueError.
    """
    byName = {candidate.name: candidate for candidate in hosts}
    visited = {host.name}

    def expand(current: Host) -> list[Host]:
        chain: list[Host] = []
        names = [name.strip() for name in (current.proxyJump or "").split(",") if name.strip()]
        for name in names:
            if name in visited:
                raise ValueError(f"ProxyJump cycle through '{name}'")
            jump = byName.get(name)
            if jump is None:
                raise ValueError(f"ProxyJump host '{name}' is not a known host")
            visited.add(name)
            chain.extend(expand(jump))
            chain.append(jump)
        return chain

    return expand(host)


def mergeHosts(fromSshConfig: list[Host], fromApp: list[Host]) -> list[Host]:
    """Combine both host sources; an app host with the same name wins."""
    appByName = {h.name: h for h in fromApp}
    merged = [appByName.pop(h.name, h) for h in fromSshConfig]
    merged.extend(h for h in fromApp if h.name in appByName)
    return merged
