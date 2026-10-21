# pyommyssh

A Python desktop port of [OmnySSH](https://github.com/timhartmann7/omnyssh): an SSH client with a live server dashboard, built with PySide6 (Qt), paramiko, and pyte. It runs from source on Windows, macOS, and Linux, and can be packaged as a standalone Windows executable with PyInstaller.

## What it does today (Phase 1)

- **Hosts from your SSH config.** `~/.ssh/config` is read at startup, including `Include` files and `ProxyJump`. It is never written to.
- **App-managed hosts.** Add, edit, and remove hosts inside the app with the pencil button on each card. They are stored separately in `hosts.toml`. Editing a host that came from `~/.ssh/config` saves an app-managed copy that overrides it; the config file itself is left alone.
- **Live dashboard.** Every host is a card with CPU, RAM, and disk bars, OS name, uptime, load average, a Docker badge with the running container count, and the top three processes. Bars turn yellow at 60% and red at 85%. Cards refresh on a timer and can be grouped by tag.
- **Real terminals.** Click the terminal button beside a host's name, or double-click the card, to open a tabbed terminal with a full PTY, colors, scrollback (mouse wheel), and paste with `Ctrl+Shift+V` or `Shift+Insert`.
- **Search.** `Ctrl+K` filters hosts and open terminal tabs by name, hostname, or tag. Enter opens or switches.
- **Port forwarding.** Each host can carry local (`ssh -L`), remote (`ssh -R`), and dynamic SOCKS (`ssh -D`) forwards, in OpenSSH's `[bind_address:]port:host:hostport` notation. `LocalForward`, `RemoteForward`, and `DynamicForward` lines in `~/.ssh/config` are picked up, and app-managed hosts edit theirs in the host dialog. The card lists a host's forwards with a Start/Stop tunnel button and a status line. One tunnel per host carries every forward; it binds its local ports up front, reconnects with a backoff when the connection drops, and keeps the ports while it does. SOCKS4, SOCKS4a, and SOCKS5 without authentication are accepted on dynamic forwards.
- **SFTP file browser.** The folder button beside a host's name opens a tab with your local disk on the left and the host on the right. Each pane shows name, size, and modified time, with a `..` row, an Up button, a path bar you can type into, and a drive switch on Windows. Both sides list in the background so a slow drive or a slow host never freezes the window.
- **Generate a key pair.** `Ctrl+G` or the Generate key button asks for the key type (Ed25519 by default, or RSA 4096), a comment, where to save the private key (defaulting to `~/.ssh/id_ed25519`), and an optional passphrase. The files are written in OpenSSH format, the private key with mode 600 and the public key beside it as `.pub`. Existing files are never overwritten. When a host asks for a secret, the one you type is tried both as the login password and as the key's passphrase, so a passphrase-protected key works with the same single prompt.
- **Install a public key.** The key button beside a host's name picks a `.pub` file from `~/.ssh` and appends it to the host's `~/.ssh/authorized_keys` over the existing connection, the way `ssh-copy-id` does. The key is added only if it is not already there, the directory is set to 700 and the file to 600, and nothing else on the server is touched. The outcome shows in the status bar. The private key never leaves your machine.
- **One connection per host.** The dashboard poll, every terminal tab, the tunnel, and key installs share a single SSH connection to each host.
- **ProxyJump.** Multi-hop chains such as `ProxyJump bastion,inner` are honored, including nested jumps.
- **Passwords stay in memory.** When key authentication fails you are asked once per host; the secret is kept only until the app exits. A passphrase that unlocks an identity file is also remembered for that file, so other hosts using the same key do not ask again. Nothing is ever written to disk. For a passphrase that survives restarts, load the key into your SSH agent (`ssh-add ~/.ssh/id_ed25519` with the OpenSSH agent running, or Pageant); the app uses agent keys automatically.

### Not yet ported

SFTP transfers and remote file operations (the rest of Phase 2, in progress), snippets, streamer mode, and themes (Phase 3). Upstream's key setup also turns off password login on the server after verifying the key; that part is not ported, and the app never edits `sshd_config`. Tunnels do not start on their own when the app opens; each is started from its card. Metrics are gathered with Linux commands first and fall back to macOS forms for CPU, processes, and OS; `free` is Linux-only so RAM shows "n/a" on macOS hosts. Unknown host keys are accepted and logged; a changed host key is rejected. Text selection and copy in the terminal are not implemented yet.

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
| `Ctrl+G` | Generate an SSH key pair |
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
local_forwards = ["8080:localhost:80", "127.0.0.1:5432:db.internal:5432"]
remote_forwards = ["9000:127.0.0.1:3000"]
dynamic_forwards = ["1080"]
```

A host here with the same name as one in `~/.ssh/config` takes precedence.

The three forward lists are optional. A local forward listens on this machine and the server connects onward to `host:hostport`. A remote forward makes the server listen and this machine connects onward. A dynamic forward listens on this machine as a SOCKS proxy and takes only `[bind_address:]port`. Without a bind address a forward listens on loopback only; `*` means every interface. IPv6 addresses go in brackets, as in `[::1]:8080:localhost:80`.

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
uv run python examples/forward_port.py myhost -L 8080:localhost:80   # run a tunnel until Ctrl+C
uv run python examples/generate_key.py ~/.ssh/id_ed25519             # write a new key pair
uv run python examples/install_key.py myhost ~/.ssh/id_ed25519.pub   # append a public key to authorized_keys
```

`forward_port.py` uses the host's own forwards when none are given on the command line, and takes any mix of `-L`, `-R`, and `-D` rules otherwise. `generate_key.py` makes an Ed25519 key unless given `--rsa`, and asks for a passphrase when given `--passphrase`. `install_key.py` defaults to `~/.ssh/id_ed25519.pub` when no key file is given.

## Development

```powershell
uv run pytest
```

The suite spins up an in-process SSH server (paramiko) so the SSH client, connection pool, workers, and main window are tested end to end without mocks. Widget tests run headless with the Qt offscreen platform. Warnings fail the suite.

See [TESTPLAN.md](TESTPLAN.md) for the manual checklist.

## Project layout

```
src/pyommyssh/core/   hosts, forwards, metrics, ssh, connections, tunnel, socks, keys, sftp, terminal, config (no Qt)
src/pyommyssh/ui/     terminalWidget, hostCard, dashboard, dialogs, filePane, sftpTab, sftpBridge, mainWindow, workers
tests/                pytest suite, including the in-process SSH test server
examples/             runnable usage examples
scripts/              build_windows.py
working/              logs, build artifacts (ignored by git)
```

## License

This project follows the upstream OmnySSH license, Apache-2.0.
