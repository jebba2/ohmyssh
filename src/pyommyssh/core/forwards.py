"""Port forward rules in OpenSSH's notation.

A host carries a list of rules of three kinds, matching ``ssh -L``, ``-R``
and ``-D``:

- local: ``[bind_address:]port:host:hostport`` listens on this machine and
  the server connects onward to ``host:hostport``.
- remote: ``[bind_address:]port:host:hostport`` makes the server listen and
  this machine connects onward to ``host:hostport``.
- dynamic: ``[bind_address:]port`` listens on this machine as a SOCKS proxy.

Rules are stored in ``hosts.toml`` in that same notation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

LOOPBACK = "127.0.0.1"
ALL_INTERFACES = "0.0.0.0"


class ForwardKind(Enum):
    """Which side listens and where connections go."""

    LOCAL = "local"
    REMOTE = "remote"
    DYNAMIC = "dynamic"


def _usage(kind: ForwardKind) -> str:
    if kind == ForwardKind.DYNAMIC:
        return "expected [bind_address:]port"
    return "expected [bind_address:]port:host:hostport"


def _splitFields(spec: str) -> list[str] | None:
    """Split on colons outside ``[...]``, unwrapping bracketed IPv6 addresses.

    Returns None when a bracket is left open.
    """
    fields: list[str] = []
    current: list[str] = []
    inBrackets = False
    for char in spec:
        if char == "[":
            inBrackets = True
        elif char == "]":
            inBrackets = False
        elif char == ":" and not inBrackets:
            fields.append("".join(current))
            current = []
            continue
        current.append(char)
    if inBrackets:
        return None
    fields.append("".join(current))
    return [_unbracket(field) for field in fields]


def _unbracket(field: str) -> str:
    if field.startswith("[") and field.endswith("]"):
        return field[1:-1]
    return field


def _bracketed(address: str) -> str:
    """An IPv6 address needs brackets to survive the colon-separated notation."""
    return f"[{address}]" if ":" in address else address


def _parsePort(value: str, spec: str) -> int:
    if not value.isdigit() or not 0 < int(value) < 65536:
        raise ValueError(f"'{value}' is not a port between 1 and 65535 in '{spec}'")
    return int(value)


@dataclass(frozen=True)
class PortForward:
    """One forwarding rule. ``remoteHost`` and ``remotePort`` are None for dynamic rules."""

    kind: ForwardKind
    bindPort: int
    bindAddress: str | None = None
    remoteHost: str | None = None
    remotePort: int | None = None

    @classmethod
    def parse(cls, kind: ForwardKind, spec: str) -> PortForward:
        """Parse a rule in OpenSSH notation; raises ValueError with the expected form."""
        spec = spec.strip()
        fields = _splitFields(spec)
        if fields is None:
            raise ValueError(f"{_usage(kind)}, got '{spec}'")
        expectedCount = 1 if kind == ForwardKind.DYNAMIC else 3
        if len(fields) == expectedCount + 1:
            bindAddress: str | None = fields.pop(0)
        else:
            bindAddress = None
        if len(fields) != expectedCount or any(not field for field in fields):
            raise ValueError(f"{_usage(kind)}, got '{spec}'")
        if kind == ForwardKind.DYNAMIC:
            return cls(kind=kind, bindPort=_parsePort(fields[0], spec), bindAddress=bindAddress)
        return cls(
            kind=kind,
            bindPort=_parsePort(fields[0], spec),
            bindAddress=bindAddress,
            remoteHost=fields[1],
            remotePort=_parsePort(fields[2], spec),
        )

    def _listenSpec(self) -> str:
        if self.bindAddress:
            return f"{_bracketed(self.bindAddress)}:{self.bindPort}"
        return str(self.bindPort)

    def spec(self) -> str:
        """Return the rule in the notation ``parse`` accepts."""
        listen = self._listenSpec()
        if self.kind == ForwardKind.DYNAMIC or self.remoteHost is None:
            return listen
        return f"{listen}:{_bracketed(self.remoteHost)}:{self.remotePort}"

    def listenAddress(self) -> str:
        """The address to bind on this machine: loopback unless the rule says otherwise."""
        address = self.bindAddress or ""
        if address in ("", "localhost"):
            return LOOPBACK
        if address == "*":
            return ALL_INTERFACES
        return address

    def describe(self) -> str:
        """A short label for the dashboard card."""
        listen = self._listenSpec()
        if self.kind == ForwardKind.DYNAMIC:
            return f"D {listen} (SOCKS)"
        letter = "L" if self.kind == ForwardKind.LOCAL else "R"
        return f"{letter} {listen} -> {self.remoteHost}:{self.remotePort}"
