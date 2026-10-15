# pyommyssh

A Python desktop port of [OmnySSH](https://github.com/timhartmann7/omnyssh): an SSH client with a live server dashboard, built with PySide6 (Qt), paramiko, and pyte. It runs from source on Windows, macOS, and Linux, and can be packaged as a standalone Windows executable with PyInstaller.

## What it does today (Phase 1)

- **Hosts from your SSH config.** `~/.ssh/config` is read at startup, including `Include` files and `ProxyJump`. It is never written to.
- **App-managed hosts.** Add, edit, and remove hosts inside the app. They are stored separately in `hosts.toml`.
- **Live dashboard.** Every host is a card with CPU, RAM, and disk bars, OS name, uptime, load average, a Docker badge with the running container count, and the top three processes. Bars turn yellow at 60% and red at 85%. Cards refresh on a timer and can be grouped by tag.
- **Real terminals.** Click the `>_` button beside a host's name, or double-click the card, to open a tabbed terminal with a full PTY, colors, scrollback (mouse wheel), and paste with `Ctrl+Shift+V` or `Shift+Insert`.
- **Search.** `Ctrl+K` filters hosts and open terminal tabs by name, hostname, or tag. Enter opens or switches.
- **One connection per host.** The dashboard poll and every terminal tab share a single SSH connection to each host.
- **ProxyJump.** Multi-hop chains such as `ProxyJump bastion,inner` are honored, including nested jumps.
- **Passwords stay in memory.** When key authentication fails you are asked once per host; the password is kept only until the app exits.

### Not yet ported

SFTP (Phase 2), snippets, one-click key setup, streamer mode, port forwarding, and themes (Phase 3). Metrics are gathered with Linux commands first and fall back to macOS forms for CPU, processes, and OS; `free` is Linux-only so RAM shows "n/a" on macOS hosts. Unknown host keys are accepted and logged; a changed host key is rejected. Text selection and copy in the terminal are not implemented yet.

## Setup

1. Install [uv](https://docs.astral.sh/uv/): see https://docs.astral.sh/uv/getting-started/installation/
2. Clone this repository and install dependencies:

```powershell
uv sync
```

Python 3.13 is used automatically (see `.python-version`).

## Running

```powershell
uv run pyommyssh
```

or

```powershell
uv run python -m pyommyssh
```

### Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+N` | Add host |
| `F5` | Refresh every host now, including hosts whose password prompt was cancelled |
| `Ctrl+K` | Search hosts and open sessions |
| `Ctrl+Shift+V`, `Shift+Insert` | Paste into the terminal |
| Mouse wheel | Scroll the terminal back through history |

## Configuration

Files live in the per-user config directory: `%APPDATA%\pyommyssh\` on Windows, `~/.config/pyommyssh/` elsewhere.

### `config.toml`

Every key is optional. These are the defaults:

```toml
[general]
refresh_interval = 30      # seconds between dashboard refreshes, at least 1

[ui]
theme = "dark"             # only "dark" exists yet
terminal_font_size = 11    # points, at least 6
```

### `hosts.toml`

Written by the app when you add hosts. You can also edit it by hand:

```toml
[[hosts]]
name = "web"
hostname = "10.0.0.5"
user = "deploy"
port = 2222
identity_file = "C:/Users/you/.ssh/web_key"
proxy_jump = "bastion"
tags = ["prod", "web"]
```

A host here with the same name as one in `~/.ssh/config` takes precedence.

### Logs

Logs go to `working/logs/pyommyssh.log` under the project root when running from source, or beside the executable when packaged.

## Building a standalone Windows executable

```powershell
uv run python scripts/build_windows.py
```

That produces `dist/pyommyssh/pyommyssh.exe` with its support files beside it. Add `--onefile` for a single `dist/pyommyssh.exe`, and `--clean` to discard PyInstaller's cache. The full build log is in `working/build/pyinstaller.log`.

One-directory builds start faster and are less likely to be quarantined by antivirus software than one-file builds, which unpack to a temp directory on every launch.

## Examples

Runnable scripts that use the core library without the GUI:

```powershell
uv run python examples/list_hosts.py          # print every known host
uv run python examples/probe_host.py myhost   # connect and print dashboard metrics
```

## Development

```powershell
uv run pytest
```

The suite spins up an in-process SSH server (paramiko) so the SSH client, connection pool, workers, and main window are tested end to end without mocks. Widget tests run headless with the Qt offscreen platform. Warnings fail the suite.

See [TESTPLAN.md](TESTPLAN.md) for the manual checklist.

## Project layout

```
src/pyommyssh/core/   hosts, metrics, ssh, connections, terminal, config (no Qt)
src/pyommyssh/ui/     terminalWidget, hostCard, dashboard, dialogs, mainWindow, workers
tests/                pytest suite, including the in-process SSH test server
examples/             runnable usage examples
scripts/              build_windows.py
working/              logs, build artifacts (ignored by git)
```

## License

This project follows the upstream OmnySSH license, Apache-2.0.
