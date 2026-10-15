"""Remote host metrics: one probe command and the parsers for its output.

A single shell command is sent over SSH. It prints a marker line before each
section so one round trip yields OS, CPU, memory, disk, uptime, load, Docker
and top-process data. Every command suppresses stderr and tolerates missing
tools, so an unsupported host simply yields empty sections.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MARKER_PREFIX = "===PYOMMYSSH:"
MARKER_SUFFIX = "==="
MAX_PROCESSES = 3

# Section name -> POSIX shell command. Alternatives separated by || cover
# Linux first, then macOS where the flags differ.
PROBE_SECTIONS: list[tuple[str, str]] = [
    ("OS", "(cat /etc/os-release 2>/dev/null || uname -sr 2>/dev/null) | head -5"),
    ("CPU", "(top -bn1 2>/dev/null || top -l 1 -n 0 2>/dev/null) | head -5"),
    ("MEM", "free -b 2>/dev/null"),
    ("DISK", "df -k / 2>/dev/null"),
    ("UPTIME", "uptime 2>/dev/null"),
    ("LOAD", "cat /proc/loadavg 2>/dev/null"),
    ("DOCKER", "command -v docker >/dev/null 2>&1 && docker ps -q 2>/dev/null | wc -l"),
    (
        "PROCS",
        "(ps -eo pcpu,pmem,comm --sort=-pcpu 2>/dev/null"
        " || ps -eo pcpu,pmem,comm -r 2>/dev/null) | head -4",
    ),
]


@dataclass(frozen=True)
class ProcessInfo:
    """One row from the top-process list."""

    name: str
    cpuPercent: float
    memPercent: float


@dataclass
class HostMetrics:
    """A snapshot of a host's health. ``None`` means the value was unavailable."""

    osName: str | None = None
    cpuPercent: float | None = None
    memPercent: float | None = None
    memTotalBytes: int | None = None
    diskPercent: float | None = None
    uptime: str | None = None
    loadAverage: tuple[float, float, float] | None = None
    dockerContainers: int | None = None
    processes: list[ProcessInfo] = field(default_factory=list)


def buildProbeScript() -> str:
    """Return the shell command that prints every metrics section with markers."""
    parts = [
        f"echo '{MARKER_PREFIX}{name}{MARKER_SUFFIX}'; {command}" for name, command in PROBE_SECTIONS
    ]
    return "; ".join(parts)


def parseProbeOutput(text: str) -> dict[str, str]:
    """Split marked probe output into {section name: trimmed content}."""
    sections: dict[str, str] = {}
    currentName: str | None = None
    currentLines: list[str] = []

    def closeSection() -> None:
        if currentName is not None:
            sections[currentName] = "\n".join(currentLines).strip()

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(MARKER_PREFIX) and stripped.endswith(MARKER_SUFFIX):
            closeSection()
            currentName = stripped[len(MARKER_PREFIX) : -len(MARKER_SUFFIX)]
            currentLines = []
        elif currentName is not None:
            currentLines.append(line)
    closeSection()
    return sections


def _toFloat(value: str) -> float:
    return float(value.replace(",", "."))


_IDLE_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*%?\s*id(?:le)?\b")


def parseCpuPercent(text: str) -> float | None:
    """Return CPU usage as 100 minus the idle share reported by ``top``."""
    match = _IDLE_PATTERN.search(text)
    if match is None:
        return None
    return round(100.0 - _toFloat(match.group(1)), 2)


def parseMemory(text: str) -> tuple[float, int] | None:
    """Return (used percent, total bytes) from ``free -b`` output.

    The ``available`` column is preferred; older ``free`` builds only have
    ``free``, which is used instead.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    header = [column.lower() for column in lines[0].split()]
    memLine = next((line for line in lines[1:] if line.lower().startswith("mem")), None)
    if memLine is None or "total" not in header:
        return None
    values = memLine.split()[1:]
    freeColumn = "available" if "available" in header else "free"
    if freeColumn not in header:
        return None
    try:
        total = int(values[header.index("total")])
        unused = int(values[header.index(freeColumn)])
    except (IndexError, ValueError):
        return None
    if total <= 0:
        return None
    return round((total - unused) / total * 100.0, 2), total


def parseDiskPercent(text: str) -> float | None:
    """Return the root filesystem usage from the ``Use%`` or ``Capacity`` column."""
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    header = lines[0].split()
    columnIndex = next(
        (i for i, column in enumerate(header) if column.lower() in ("use%", "capacity")), None
    )
    if columnIndex is None:
        return None
    values = lines[1].split()
    try:
        return float(values[columnIndex].rstrip("%"))
    except (IndexError, ValueError):
        return None


_UPTIME_PATTERN = re.compile(r"\bup\s+(.*?)(?:,\s*\d+\s+users?|,\s*load average|$)")


def parseUptime(text: str) -> str | None:
    """Return the human uptime from ``uptime``; only the day count when days exist."""
    match = _UPTIME_PATTERN.search(text)
    if match is None:
        return None
    value = match.group(1).strip()
    if "day" in value:
        value = value.split(",", 1)[0].strip()
    return value or None


_NUMBER_PATTERN = re.compile(r"\d+(?:[.,]\d+)?")


def parseLoadAverage(text: str) -> tuple[float, float, float] | None:
    """Return the 1/5/15 minute load from ``/proc/loadavg`` or an ``uptime`` tail."""
    _, marker, tail = text.partition("load average")
    source = tail if marker else text
    numbers = _NUMBER_PATTERN.findall(source)
    if len(numbers) < 3:
        return None
    one, five, fifteen = (_toFloat(value) for value in numbers[:3])
    return one, five, fifteen


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parseOsName(text: str) -> str | None:
    """Return PRETTY_NAME, else NAME plus VERSION, else the first plain line."""
    fields: dict[str, str] = {}
    plainLines: list[str] = []
    for line in text.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            fields[key.strip()] = _unquote(value)
        elif line.strip():
            plainLines.append(line.strip())
    if fields.get("PRETTY_NAME"):
        return fields["PRETTY_NAME"]
    if fields.get("NAME"):
        return " ".join(part for part in (fields["NAME"], fields.get("VERSION", "")) if part)
    return plainLines[0] if plainLines else None


def parseDockerCount(text: str) -> int | None:
    """Return the running-container count; ``None`` when Docker is not installed."""
    stripped = text.strip()
    return int(stripped) if stripped.isdigit() else None


def parseProcesses(text: str) -> list[ProcessInfo]:
    """Parse ``%CPU %MEM COMMAND`` rows, skipping headers and malformed lines."""
    processes: list[ProcessInfo] = []
    for line in text.splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) != 3:
            continue
        try:
            cpu, mem = _toFloat(parts[0]), _toFloat(parts[1])
        except ValueError:
            continue
        processes.append(ProcessInfo(name=parts[2].strip(), cpuPercent=cpu, memPercent=mem))
        if len(processes) == MAX_PROCESSES:
            break
    return processes


def metricsFromProbeOutput(text: str) -> HostMetrics:
    """Turn raw probe output into a HostMetrics snapshot."""
    sections = parseProbeOutput(text)
    memory = parseMemory(sections.get("MEM", ""))
    uptimeText = sections.get("UPTIME", "")
    return HostMetrics(
        osName=parseOsName(sections.get("OS", "")),
        cpuPercent=parseCpuPercent(sections.get("CPU", "")),
        memPercent=memory[0] if memory else None,
        memTotalBytes=memory[1] if memory else None,
        diskPercent=parseDiskPercent(sections.get("DISK", "")),
        uptime=parseUptime(uptimeText),
        loadAverage=parseLoadAverage(sections.get("LOAD", "")) or parseLoadAverage(uptimeText),
        dockerContainers=parseDockerCount(sections.get("DOCKER", "")),
        processes=parseProcesses(sections.get("PROCS", "")),
    )
