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

from ohmyssh.core.forwards import ForwardKind, PortForward

# Include directives deeper than this are ignored, matching OmnySSH.
MAX_INCLUDE_DEPTH = 3

# SSH config keyword and hosts.toml key for each forward kind.
_FORWARD_DIRECTIVES = {
    "localforward": ForwardKind.LOCAL,
    "remoteforward": ForwardKind.REMOTE,
    "dynamicforward": ForwardKind.DYNAMIC,
}
_FORWARD_TOML_KEYS = {
    ForwardKind.LOCAL: "local_forwards",
    ForwardKind.REMOTE: "remote_forwards",
    ForwardKind.DYNAMIC: "dynamic_forwards",
}


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
    forwards: list[PortForward] = field(default_factory=list)
    source: HostSource = HostSource.SSH_CONFIG
    # For SSH config hosts: the file the Host block lives in, and the other
    # names on the same Host line, which share every directive with this one.
    sourceFile: Path | None = None
    sharedWith: list[str] = field(default_factory=list)
    # None means "not set here": the global Host * value, or ssh's default, applies.
    serverAliveInterval: int | None = None
    serverAliveCountMax: int | None = None
    compression: bool | None = None

    def hasForwards(self) -> bool:
        """Return True when the host defines at least one port forward."""
        return bool(self.forwards)

    def displayAddress(self) -> str:
        """Return a compact user@host:port string, omitting defaults."""
        address = f"{self.user}@{self.hostname}" if self.user else self.hostname
        if self.port != 22:
            address = f"{address}:{self.port}"
        return address


@dataclass(frozen=True)
class GlobalSettings:
    """Defaults every host inherits, kept in the ``Host *`` block of ~/.ssh/config."""

    serverAliveInterval: int | None = None
    serverAliveCountMax: int | None = None
    identityFile: Path | None = None
    compression: bool | None = None


@dataclass(frozen=True)
class EffectiveSettings:
    """What a connection actually uses once host and global values are combined."""

    keepaliveSeconds: int | None
    identityFile: Path | None
    compression: bool


def effectiveSettings(host: Host, globalSettings: GlobalSettings) -> EffectiveSettings:
    """Combine a host with the global defaults: the host's own value wins when set.

    A keepalive of 0 means off. ServerAliveCountMax has no paramiko
    equivalent, so it is left to ssh and not part of the result.
    """
    interval = host.serverAliveInterval if host.serverAliveInterval is not None else globalSettings.serverAliveInterval
    compression = host.compression if host.compression is not None else globalSettings.compression
    return EffectiveSettings(
        keepaliveSeconds=interval if interval else None,
        identityFile=host.identityFile or globalSettings.identityFile,
        compression=bool(compression),
    )


def _isWildcard(pattern: str) -> bool:
    return "*" in pattern or "?" in pattern


def _stripComment(line: str) -> str:
    hashIndex = line.find("#")
    return line if hashIndex < 0 else line[:hashIndex]


_DIRECTIVE_PATTERN = re.compile(r"^(\S+?)\s*(?:=\s*|\s+)(.*)$")
# A comment the app writes to keep its tags inside a Host block; ssh ignores it.
TAGS_COMMENT_PATTERN = re.compile(r"^\s*#\s*tags:\s*(.*)$", re.IGNORECASE)


def _unquote(value: str) -> str:
    """Strip one pair of surrounding double quotes, as OpenSSH does for a single value."""
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def parseTagsComment(line: str) -> list[str] | None:
    """Return the tags in a ``# tags: a, b`` comment, or None for any other line."""
    match = TAGS_COMMENT_PATTERN.match(line)
    if match is None:
        return None
    return [tag for tag in re.split(r"[\s,]+", match.group(1).strip()) if tag]


def _splitDirective(line: str) -> tuple[str, str] | None:
    """Split 'Keyword value', 'Keyword=value' or 'Keyword = value' into parts."""
    stripped = _stripComment(line).strip()
    if not stripped:
        return None
    match = _DIRECTIVE_PATTERN.match(stripped)
    if match is None:
        return stripped.lower(), ""
    return match.group(1).lower(), match.group(2).strip()


def expandHome(value: str, home: Path) -> Path:
    if value.startswith("~"):
        return home / value[1:].lstrip("/\\")
    return Path(value)


def _applyDirective(hosts: list[Host], keyword: str, value: str, home: Path) -> None:
    """Apply a directive to every host from the current Host line."""
    value = _unquote(value)
    for host in hosts:
        if keyword == "hostname":
            host.hostname = value
        elif keyword == "user":
            host.user = value
        elif keyword == "port":
            if value.isdigit() and 0 < int(value) < 65536:
                host.port = int(value)
        elif keyword == "identityfile" and host.identityFile is None:
            host.identityFile = expandHome(value, home)
        elif keyword == "proxyjump":
            host.proxyJump = value
        elif keyword == "serveraliveinterval" and value.isdigit():
            host.serverAliveInterval = int(value)
        elif keyword == "serveralivecountmax" and value.isdigit():
            host.serverAliveCountMax = int(value)
        elif keyword == "compression" and value.lower() in ("yes", "no"):
            host.compression = value.lower() == "yes"
        elif keyword in _FORWARD_DIRECTIVES:
            forward = _parseForwardDirective(_FORWARD_DIRECTIVES[keyword], value)
            if forward is not None:
                host.forwards.append(forward)


def _parseForwardDirective(kind: ForwardKind, value: str) -> PortForward | None:
    """Turn ``LocalForward 8080 localhost:80`` style arguments into a rule.

    OpenSSH separates the listen and destination parts with whitespace; the
    rule notation joins them with a colon. Unix socket paths and other forms
    we cannot serve are skipped.
    """
    try:
        return PortForward.parse(kind, ":".join(value.split()))
    except ValueError:
        return None


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
        patternPath = expandHome(pattern, home)
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
    sourceFile: Path | None = None,
) -> list[Host]:
    """Parse config text, recursing into Include files up to MAX_INCLUDE_DEPTH."""
    hosts: list[Host] = []
    current: list[Host] = []
    skippingBlock = False

    for line in text.splitlines():
        tags = parseTagsComment(line)
        if tags is not None:
            if not skippingBlock:
                for host in current:
                    host.tags = list(tags)
            continue
        parts = _splitDirective(line)
        if parts is None:
            continue
        keyword, value = parts

        if keyword == "host":
            patterns = [p for p in value.split() if not _isWildcard(p)]
            current = [
                Host(name=p, hostname=p, sourceFile=sourceFile, sharedWith=[q for q in patterns if q != p])
                for p in patterns
            ]
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
    return _parseLines(path.read_text(encoding="utf-8"), home, path.parent, depth, visited, sourceFile=path)


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
    if host.serverAliveInterval is not None:
        data["server_alive_interval"] = host.serverAliveInterval
    if host.serverAliveCountMax is not None:
        data["server_alive_count_max"] = host.serverAliveCountMax
    if host.compression is not None:
        data["compression"] = host.compression
    for kind, key in _FORWARD_TOML_KEYS.items():
        specs = [forward.spec() for forward in host.forwards if forward.kind == kind]
        if specs:
            data[key] = specs
    return data


def _forwardsFromToml(data: dict[str, object]) -> list[PortForward]:
    """Read the three forward lists; entries that do not parse are skipped."""
    forwards: list[PortForward] = []
    for kind, key in _FORWARD_TOML_KEYS.items():
        rawSpecs = data.get(key)
        if not isinstance(rawSpecs, list):
            continue
        for spec in rawSpecs:
            try:
                forwards.append(PortForward.parse(kind, str(spec)))
            except ValueError:
                continue
    return forwards


def _optionalInt(data: dict[str, object], key: str) -> int | None:
    value = data.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _hostFromToml(data: dict[str, object]) -> Host:
    identity = data.get("identity_file")
    rawTags = data.get("tags")
    tags = [str(tag) for tag in rawTags] if isinstance(rawTags, list) else []
    rawCompression = data.get("compression")
    return Host(
        serverAliveInterval=_optionalInt(data, "server_alive_interval"),
        serverAliveCountMax=_optionalInt(data, "server_alive_count_max"),
        compression=rawCompression if isinstance(rawCompression, bool) else None,
        name=str(data["name"]),
        hostname=str(data["hostname"]),
        user=str(data["user"]) if data.get("user") else None,
        port=int(str(data.get("port", 22))),
        identityFile=Path(str(identity)) if identity else None,
        proxyJump=str(data["proxy_jump"]) if data.get("proxy_jump") else None,
        tags=tags,
        forwards=_forwardsFromToml(data),
        source=HostSource.APP,
    )


class HostStore:
    """Hosts added inside the app, plus the names of SSH config hosts to hide, in one TOML file."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._hosts: list[Host] = []
        self._hiddenNames: set[str] = set()

    def hosts(self) -> list[Host]:
        """Return a copy of the stored hosts."""
        return list(self._hosts)

    def hiddenNames(self) -> set[str]:
        """Names of SSH config hosts the user removed from the dashboard."""
        return set(self._hiddenNames)

    def hide(self, name: str) -> None:
        """Keep an SSH config host off the dashboard; the config file itself is never touched."""
        self._hiddenNames.add(name)

    def unhide(self, name: str) -> None:
        """Show a hidden SSH config host again. Unknown names are ignored."""
        self._hiddenNames.discard(name)

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
        rawHidden = data.get("hidden_hosts")
        self._hiddenNames = {str(name) for name in rawHidden} if isinstance(rawHidden, list) else set()

    def save(self) -> None:
        """Write hosts and hidden names to disk, creating the parent directory if needed."""
        document: dict[str, object] = {"hosts": [_hostToToml(h) for h in self._hosts]}
        if self._hiddenNames:
            document["hidden_hosts"] = sorted(self._hiddenNames)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("wb") as handle:
            tomli_w.dump(document, handle)


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


def mergeHosts(fromSshConfig: list[Host], fromApp: list[Host], hidden: set[str] | None = None) -> list[Host]:
    """Combine both host sources; an app host with the same name wins.

    SSH config hosts named in ``hidden`` are left out. App hosts are never
    hidden; removing one deletes it instead.
    """
    hiddenNames = hidden or set()
    appByName = {h.name: h for h in fromApp}
    merged = [appByName.pop(h.name, h) for h in fromSshConfig if h.name not in hiddenNames or h.name in appByName]
    merged.extend(h for h in fromApp if h.name in appByName)
    return merged
