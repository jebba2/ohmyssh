"""Editing ``~/.ssh/config`` in place.

Only the directives the app manages inside one ``Host`` block are touched:
HostName, User, Port, IdentityFile, ProxyJump, the three forward kinds, and
the ``# tags:`` comment. Everything else in the file stays byte for byte:
comments, blank lines, indentation, unknown directives, ``Match`` and
wildcard blocks, and ``Include`` lines. A host whose block lives in an
included file is edited in that file.

Every write backs the file up first, goes through a temporary file, and is
read back before it is accepted.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ohmyssh.core.hosts import (
    GlobalSettings,
    Host,
    expandHome,
    loadSshConfig,
    parseSshConfig,
    parseTagsComment,
)

MAX_BACKUPS = 10
DEFAULT_INDENT = "    "
DEFAULT_PORT = 22
PRIVATE_FILE_MODE = 0o600
PRIVATE_DIR_MODE = 0o700
GLOBAL_PATTERN = "*"

# Lines the app owns inside a host's block.
MANAGED_KEYWORDS = frozenset(
    {
        "hostname", "user", "port", "identityfile", "proxyjump",
        "serveraliveinterval", "serveralivecountmax", "compression",
        "localforward", "remoteforward", "dynamicforward",
    }
)
# Lines the app owns inside the Host * block.
GLOBAL_KEYWORDS = frozenset({"serveraliveinterval", "serveralivecountmax", "identityfile", "compression"})
_UNSAFE_NAME = re.compile(r"[\s*?!#]")
_DIRECTIVE = re.compile(r"^(\s*)(\S+?)(?:\s*=\s*|\s+|$)")
_DIRECTIVE_WITH_VALUE = re.compile(r"^\s*(\S+?)\s*(?:=\s*|\s+)(.*?)\s*$")


class SshConfigError(Exception):
    """The config could not be changed safely; nothing was written."""


@dataclass(frozen=True)
class _Block:
    """One ``Host`` block: the Host line's index, the index after its last line, and its names."""

    start: int
    end: int
    names: list[str]


def _stripComment(line: str) -> str:
    hashIndex = line.find("#")
    return line if hashIndex < 0 else line[:hashIndex]


def _keywordOf(line: str) -> str:
    """The lowercase directive keyword on a line, or "" for blank and comment lines."""
    stripped = _stripComment(line).strip()
    if not stripped:
        return ""
    match = _DIRECTIVE.match(stripped)
    return match.group(2).lower() if match else stripped.lower()


def _indentOf(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _directiveValue(line: str) -> tuple[str, str] | None:
    """The lowercase keyword and its value on a directive line, or None."""
    match = _DIRECTIVE_WITH_VALUE.match(_stripComment(line))
    if match is None:
        return None
    return match.group(1).lower(), match.group(2)


def _yesNo(value: bool) -> str:
    return "yes" if value else "no"


def _blocks(lines: list[str]) -> list[_Block]:
    """Find every Host block; a block runs until the next Host or Match line."""
    blocks: list[_Block] = []
    start: int | None = None
    names: list[str] = []
    for index, line in enumerate(lines):
        keyword = _keywordOf(line)
        if keyword in ("host", "match"):
            if start is not None:
                blocks.append(_Block(start, index, names))
            start = index if keyword == "host" else None
            names = _stripComment(line).split()[1:] if keyword == "host" else []
    if start is not None:
        blocks.append(_Block(start, len(lines), names))
    return blocks


def _formatPath(path: Path, home: Path) -> str:
    """Write paths under the home folder as ``~/...``; quote anything with spaces."""
    try:
        text = "~/" + path.relative_to(home).as_posix()
    except ValueError:
        text = path.as_posix()
    return f'"{text}"' if any(char.isspace() for char in text) else text


def _managedLines(host: Host, indent: str, home: Path) -> list[str]:
    """The directive lines the app owns, in a fixed order."""
    lines = [f"HostName {host.hostname}"]
    if host.user:
        lines.append(f"User {host.user}")
    if host.port != DEFAULT_PORT:
        lines.append(f"Port {host.port}")
    if host.identityFile is not None:
        lines.append(f"IdentityFile {_formatPath(host.identityFile, home)}")
    if host.proxyJump:
        lines.append(f"ProxyJump {host.proxyJump}")
    if host.serverAliveInterval is not None:
        lines.append(f"ServerAliveInterval {host.serverAliveInterval}")
    if host.serverAliveCountMax is not None:
        lines.append(f"ServerAliveCountMax {host.serverAliveCountMax}")
    if host.compression is not None:
        lines.append(f"Compression {_yesNo(host.compression)}")
    lines.extend(forward.configDirective() for forward in host.forwards)
    if host.tags:
        lines.append(f"# tags: {' '.join(host.tags)}")
    return [indent + line for line in lines]


def _globalLines(settings: GlobalSettings, indent: str, home: Path) -> list[str]:
    """The Host * directive lines the app owns, in a fixed order."""
    lines: list[str] = []
    if settings.serverAliveInterval is not None:
        lines.append(f"ServerAliveInterval {settings.serverAliveInterval}")
    if settings.serverAliveCountMax is not None:
        lines.append(f"ServerAliveCountMax {settings.serverAliveCountMax}")
    if settings.identityFile is not None:
        lines.append(f"IdentityFile {_formatPath(settings.identityFile, home)}")
    if settings.compression is not None:
        lines.append(f"Compression {_yesNo(settings.compression)}")
    return [indent + line for line in lines]


def _globalsFromLines(lines: list[str], home: Path) -> GlobalSettings:
    """Read the app's global settings from the first Host * block."""
    block = next((candidate for candidate in _blocks(lines) if candidate.names == [GLOBAL_PATTERN]), None)
    if block is None:
        return GlobalSettings()
    values: dict[str, str] = {}
    for index in range(block.start + 1, block.end):
        directive = _directiveValue(lines[index])
        if directive is not None and directive[0] in GLOBAL_KEYWORDS and directive[0] not in values:
            values[directive[0]] = directive[1]
    interval = values.get("serveraliveinterval", "")
    countMax = values.get("serveralivecountmax", "")
    identity = values.get("identityfile", "").strip('"')
    compression = values.get("compression", "").lower()
    return GlobalSettings(
        serverAliveInterval=int(interval) if interval.isdigit() else None,
        serverAliveCountMax=int(countMax) if countMax.isdigit() else None,
        identityFile=expandHome(identity, home) if identity else None,
        compression=compression == "yes" if compression in ("yes", "no") else None,
    )


def _replaceManagedLines(
    lines: list[str], block: _Block, keywords: frozenset[str], newLines: list[str], includeTagComments: bool
) -> None:
    """Swap a block's managed lines for ``newLines`` where the first managed line was."""
    bodyRange = range(block.start + 1, block.end)
    indent = next((_indentOf(lines[i]) for i in bodyRange if _keywordOf(lines[i])), DEFAULT_INDENT)
    managed = [
        i
        for i in bodyRange
        if _keywordOf(lines[i]) in keywords or (includeTagComments and parseTagsComment(lines[i]) is not None)
    ]
    insertAt = managed[0] if managed else block.start + 1
    for index in reversed(managed):
        del lines[index]
    lines[insertAt:insertAt] = [indent + line.strip() for line in newLines]


def hostNameProblem(name: str) -> str | None:
    """Why ``name`` cannot be written as a Host name, with a legal spelling of it, or None when it can.

    ssh splits a Host line on whitespace and treats *, ?, ! and # specially,
    so a name must be a single plain word. The suggestion joins the words
    with hyphens, dropping parentheses so ``server (label)`` becomes
    ``server-label``.
    """
    if name and not _UNSAFE_NAME.search(name):
        return None
    suggestion = re.sub(r"[\s*?!#()]+", "-", name).strip("-")
    example = f", such as {suggestion}" if suggestion else ""
    return f"'{name}' cannot be used as a Host name in ~/.ssh/config: use one word with no spaces, *, ?, ! or #{example}"


def _validate(host: Host) -> None:
    problem = hostNameProblem(host.name)
    if problem:
        raise SshConfigError(problem)
    values = [host.hostname, host.user or "", host.proxyJump or "", str(host.identityFile or ""), *host.tags]
    values.extend(forward.spec() for forward in host.forwards)
    for value in values:
        if "\n" in value or "\r" in value:
            raise SshConfigError("A host setting must not contain a newline")
    for label, value in (("HostName", host.hostname), ("User", host.user or ""), ("ProxyJump", host.proxyJump or "")):
        if any(char.isspace() for char in value):
            raise SshConfigError(f"{label} must not contain spaces")
    if not host.hostname:
        raise SshConfigError("HostName is required")


class SshConfigEditor:
    """Reads hosts from an SSH config and writes single Host blocks back into it."""

    def __init__(self, path: Path, home: Path | None = None, backupDir: Path | None = None) -> None:
        self._path = path
        self._home = home or Path.home()
        self._backupDir = backupDir

    @property
    def path(self) -> Path:
        """The main config file."""
        return self._path

    def hosts(self) -> list[Host]:
        """Every concrete host in the config and its includes."""
        return loadSshConfig(self._path, home=self._home)

    def upsertHost(self, host: Host, previousName: str | None = None) -> None:
        """Write ``host`` into its block, renaming from ``previousName`` if given, or append a new block.

        Raises SshConfigError, with nothing written, if a value is unsafe or
        the result does not read back as intended.
        """
        _validate(host)
        lookupName = previousName or host.name
        targetFile = self._fileHolding(host, lookupName)
        lines, newline = self._readLines(targetFile)
        block = next((candidate for candidate in _blocks(lines) if lookupName in candidate.names), None)
        if block is None:
            self._appendBlock(lines, host)
        else:
            self._rewriteBlock(lines, block, host, previousName)
        newText = newline.join(lines) + newline
        self._verify(newText, host)
        self._backup(targetFile)
        self._writeAtomic(targetFile, newText)

    def globalSettings(self) -> GlobalSettings:
        """The defaults in the main file's ``Host *`` block; all None when there is none."""
        if not self._path.is_file():
            return GlobalSettings()
        lines, _ = self._readLines(self._path)
        return _globalsFromLines(lines, self._home)

    def upsertGlobal(self, settings: GlobalSettings) -> None:
        """Write the defaults into the ``Host *`` block, which is kept at the end of the file.

        ssh takes the first value it finds for a setting, so a ``Host *``
        block above the hosts would override them. An existing block that
        sits higher up is moved to the end, with its other lines intact.
        """
        if settings.identityFile is not None and any(c in str(settings.identityFile) for c in "\r\n"):
            raise SshConfigError("A host setting must not contain a newline")
        lines, newline = self._readLines(self._path)
        block = next((candidate for candidate in _blocks(lines) if candidate.names == [GLOBAL_PATTERN]), None)
        if block is None:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(f"Host {GLOBAL_PATTERN}")
            lines.extend(_globalLines(settings, DEFAULT_INDENT, self._home))
        else:
            if block.end != len(lines):
                block = self._moveBlockToEnd(lines, block)
            _replaceManagedLines(
                lines, block, GLOBAL_KEYWORDS, _globalLines(settings, "", self._home), includeTagComments=False
            )
        newText = newline.join(lines) + newline
        if _globalsFromLines(lines, self._home) != settings:
            raise SshConfigError("The global settings read back differently from what was written; nothing was written")
        self._backup(self._path)
        self._writeAtomic(self._path, newText)

    @staticmethod
    def _readLines(path: Path) -> tuple[list[str], str]:
        """The file's lines without their endings, plus the ending it uses."""
        # Bytes, not read_text: universal newlines would hide a CRLF file.
        text = path.read_bytes().decode("utf-8") if path.is_file() else ""
        newline = "\r\n" if "\r\n" in text else "\n"
        lines = text.replace("\r\n", "\n").split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        return lines, newline

    @staticmethod
    def _moveBlockToEnd(lines: list[str], block: _Block) -> _Block:
        segment = lines[block.start:block.end]
        while segment and not segment[-1].strip():
            segment.pop()
        del lines[block.start:block.end]
        while lines and not lines[-1].strip():
            lines.pop()
        if lines:
            lines.append("")
        start = len(lines)
        lines.extend(segment)
        return _Block(start, len(lines), block.names)

    # Locating

    def _fileHolding(self, host: Host, name: str) -> Path:
        if host.sourceFile is not None and host.sourceFile.is_file():
            return host.sourceFile
        for known in self.hosts():
            if known.name == name and known.sourceFile is not None:
                return known.sourceFile
        return self._path

    # Rewriting

    def _appendBlock(self, lines: list[str], host: Host) -> None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"Host {host.name}")
        lines.extend(_managedLines(host, DEFAULT_INDENT, self._home))

    def _rewriteBlock(self, lines: list[str], block: _Block, host: Host, previousName: str | None) -> None:
        if previousName and previousName != host.name:
            lines[block.start] = self._renamedHostLine(lines[block.start], previousName, host.name)
        _replaceManagedLines(
            lines, block, MANAGED_KEYWORDS, _managedLines(host, "", self._home), includeTagComments=True
        )

    @staticmethod
    def _renamedHostLine(line: str, previousName: str, newName: str) -> str:
        directive = _stripComment(line)
        comment = line[len(directive):]
        parts = directive.split()
        names = [newName if part == previousName else part for part in parts[1:]]
        return f"{_indentOf(line)}{parts[0]} {' '.join(names)}{comment}"

    # Writing

    def _verify(self, newText: str, host: Host) -> None:
        parsed = next((h for h in parseSshConfig(newText, home=self._home) if h.name == host.name), None)
        if parsed is None:
            raise SshConfigError(f"'{host.name}' did not read back from the new config; nothing was written")
        same = (
            parsed.hostname == host.hostname
            and (parsed.user or None) == (host.user or None)
            and parsed.port == host.port
            and parsed.identityFile == host.identityFile
            and (parsed.proxyJump or None) == (host.proxyJump or None)
            and parsed.forwards == list(host.forwards)
            and parsed.tags == list(host.tags)
            and parsed.serverAliveInterval == host.serverAliveInterval
            and parsed.serverAliveCountMax == host.serverAliveCountMax
            and parsed.compression == host.compression
        )
        if not same:
            raise SshConfigError(f"'{host.name}' read back differently from what was written; nothing was written")

    def _backup(self, path: Path) -> None:
        if self._backupDir is None or not path.is_file():
            return
        self._backupDir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        shutil.copy2(path, self._backupDir / f"{path.name}-{stamp}.bak")
        backups = sorted(self._backupDir.glob(f"{path.name}-*.bak"))
        for old in backups[:-MAX_BACKUPS]:
            old.unlink()

    @staticmethod
    def _writeAtomic(path: Path, text: str) -> None:
        if not path.parent.exists():
            path.parent.mkdir(parents=True, mode=PRIVATE_DIR_MODE)
        temporary = path.with_name(path.name + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, PRIVATE_FILE_MODE)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(text.encode("utf-8"))
        os.replace(temporary, path)
