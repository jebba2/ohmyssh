<p align="center"><img src="src/ohmyssh/ui/icons/app.svg" width="128" alt="ohmyssh logo: oh and my in the top corners, a gold ring in the center, and ssh under it"></p>

# ohmyssh

A Python desktop port of [OmnySSH](https://github.com/timhartmann7/omnyssh): an SSH client with a live server dashboard, built with PySide6 (Qt), paramiko, and pyte. It runs from source on Windows, macOS, and Linux, and can be packaged as a standalone Windows executable or macOS app bundle with PyInstaller.

## What it does today (Phases 1 and 2)

- **Hosts from your SSH config.** `~/.ssh/config` is read at startup, including `Include` files and `ProxyJump`.
- **Saving to your SSH config.** New hosts go into `~/.ssh/config` by default, so plain `ssh` sees them too; the Add host dialog's "Save in" choice can keep a host in the app instead. Editing a host from the config rewrites only the lines the app manages inside its own `Host` block: `HostName`, `User`, `Port`, `IdentityFile`, `ProxyJump`, the forwards, and a `# tags:` comment that carries the app's tags. Comments, blank lines, indentation, other directives, `Match` and wildcard blocks, and `Include` lines are left byte for byte as they were, and a host defined in an included file is edited in that file. A `Host` line with several names, such as `Host Hermes (jebba)`, is one block, so the dialog warns that the edit applies to the other names too. Every write first copies the file to `working/backups/` (the last ten are kept), goes through a temporary file, and is read back before it is accepted.
- **App-managed hosts.** Hosts kept in the app live in `hosts.toml` and are edited there.
- **Defaults the hosts can override.** `Ctrl+,` or the Settings button edits the keepalive interval, keepalive count, identity file, and compression that every host inherits. They are saved as the `Host *` block at the end of `~/.ssh/config`; `ssh` takes the first value it finds for a setting, so a `Host *` block that sits above the hosts would override them, and an existing one higher up is moved to the end when you save. Each host dialog has its own keepalive and compression rows that default to "Use global". The app's connections use the same host-first precedence: the interval becomes the paramiko keepalive, compression is negotiated, and the global identity file is tried when a host has none. `ServerAliveCountMax` is written for `ssh` only, since paramiko has no equivalent.
- **Removing hosts.** The red trash button beside a host's name, the Edit host dialog, and the card's right-click menu all offer it, each asking first. A host kept in the app is deleted from `hosts.toml`. A host from `~/.ssh/config` is hidden from the dashboard rather than deleted from the file; its name goes into `hidden_hosts` in `hosts.toml`, and removing it from that list brings the host back.
- **Live dashboard.** Every host is a card with CPU, RAM, and disk bars, OS name, uptime, load average, a Docker badge with the running container count, and the top three processes. Bars turn yellow at 60% and red at 85%. Cards refresh on a timer and can be grouped by tag.
- **Real terminals.** Click the terminal button beside a host's name, or double-click the card, to open a tabbed terminal with a full PTY, colors, scrollback (mouse wheel), and paste with `Ctrl+Shift+V` or `Shift+Insert`.
- **Select and copy.** Drag to select, double-click a word, triple-click a line. `Ctrl+Shift+C` or `Ctrl+Insert` copies, and the right-click menu has Copy and Paste. A selection stays on its lines while you scroll back and while new output arrives, because it is anchored to the scrollback buffer, not the screen. `Ctrl+C` is still the interrupt.
- **Search.** `Ctrl+K` filters hosts and open terminal tabs by name, hostname, or tag. Enter opens or switches.
- **Port forwarding.** Each host can carry local (`ssh -L`), remote (`ssh -R`), and dynamic SOCKS (`ssh -D`) forwards, in OpenSSH's `[bind_address:]port:host:hostport` notation. `LocalForward`, `RemoteForward`, and `DynamicForward` lines in `~/.ssh/config` are picked up, and app-managed hosts edit theirs in the host dialog. The card lists a host's forwards with a Start/Stop tunnel button and a status line. One tunnel per host carries every forward; it binds its local ports up front, reconnects with a backoff when the connection drops, and keeps the ports while it does. SOCKS4, SOCKS4a, and SOCKS5 without authentication are accepted on dynamic forwards.
- **SFTP file browser.** The folder button beside a host's name opens a tab with your local disk on the left and the host on the right. Each pane shows name, size, and modified time, with a `..` row, an Up button, a path bar you can type into, and a drive switch on Windows. Both sides list in the background so a slow drive or a slow host never freezes the window. Select items on one side and press Upload or Download to copy them, folders included, into the folder shown on the other side. A strip at the bottom shows the current file, bytes, and file count, with Cancel stopping the running transfer and dropping the queued ones. A transfer that would replace existing items asks once per batch. Existing folders are merged into, symlinks and special files are skipped, and a file that fails is skipped while the rest continues. Browsing keeps working during a transfer because the tab uses two SFTP channels on the one connection. Under the remote pane, New folder, Rename, and Delete act on the host; Delete asks once per batch and removes files and empty folders only. Refresh lists both sides again. Rows can also be dragged: dropping local rows on the remote pane uploads them, dropping remote rows on the local pane downloads them, and dropping onto a folder row puts them inside that folder. Files dragged in from Explorer or Finder, the desktop included, upload to the remote folder on show when dropped anywhere on the SFTP tab, or into a folder row when dropped on one; drive roots, missing paths, and two items with the same name are refused and named above the panes. A drop is always taken as a copy, so the original on your disk is never moved. On Windows, drops from Explorer cannot reach an app that is running as administrator; run ohmyssh as a normal user.
- **Generate a key pair.** `Ctrl+G` or the Generate key button asks for the key type (Ed25519 by default, or RSA 4096), a comment, where to save the private key (defaulting to `~/.ssh/id_ed25519`), and an optional passphrase. The files are written in OpenSSH format, the private key with mode 600 and the public key beside it as `.pub`. Existing files are never overwritten. When a host asks for a secret, the one you type is tried both as the login password and as the key's passphrase, so a passphrase-protected key works with the same single prompt.
- **Install a public key.** The key button beside a host's name picks a `.pub` file from `~/.ssh` and appends it to the host's `~/.ssh/authorized_keys` over the existing connection, the way `ssh-copy-id` does. The key is added only if it is not already there, the directory is set to 700 and the file to 600, and nothing else on the server is touched. The outcome shows in the status bar. The private key never leaves your machine.
- **One connection per host.** The dashboard poll, every terminal tab, the tunnel, and key installs share a single SSH connection to each host.
- **ProxyJump.** Multi-hop chains such as `ProxyJump bastion,inner` are honored, including nested jumps.
- **Passwords stay in memory.** When key authentication fails you are asked once per host; the secret is kept only until the app exits. A passphrase that unlocks an identity file is also remembered for that file, so other hosts using the same key do not ask again. Nothing is ever written to disk. For a passphrase that survives restarts, load the key into your SSH agent (`ssh-add ~/.ssh/id_ed25519` with the OpenSSH agent running, or Pageant); the app uses agent keys automatically.

### Not yet ported

Snippets, streamer mode, and themes (Phase 3). In SFTP, a file's text preview and dragging rows out to Explorer are not implemented. Upstream's key setup also turns off password login on the server after verifying the key; that part is not ported, and the app never edits `sshd_config`. Tunnels do not start on their own when the app opens; each is started from its card. Metrics are gathered with Linux commands first and fall back to macOS forms for CPU, processes, and OS; `free` is Linux-only so RAM shows "n/a" on macOS hosts. Unknown host keys are accepted and logged; a changed host key is rejected.

## Setup

1. Install [uv](https://docs.astral.sh/uv/): see https://docs.astral.sh/uv/getting-started/installation/
2. Clone this repository and install dependencies:

```powershell
uv sync
```

Python 3.13 is used automatically (see `.python-version`).

## Running

```powershell
uv run ohmyssh
```

or

```powershell
uv run python -m ohmyssh
```

**First launch.** The app makes sure `~/.ssh` exists, and if it holds no private key it offers to generate one, opening the same Generate key dialog with `~/.ssh/id_ed25519` as the default. Whatever you answer, it asks only once; a `first_run_done` marker in the config directory records that, and deleting it brings the offer back. The key button on a host's card installs the new key on that host.

On Windows the app registers its own taskbar identity at startup, so the taskbar shows the ohmyssh logo rather than Python's icon even when run from source.

### Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+N` | Add host |
| `F5` | Refresh every host now, including hosts whose password prompt was cancelled |
| `Ctrl+K` | Search hosts and open sessions |
| `Ctrl+G` | Generate an SSH key pair |
| `Ctrl+,` | SSH defaults (the `Host *` block) |
| `Ctrl+Shift+V`, `Shift+Insert` | Paste into the terminal |
| `Ctrl+Shift+C`, `Ctrl+Insert` | Copy the terminal selection |
| Drag, double-click, triple-click | Select text, a word, or a line in the terminal |
| Mouse wheel | Scroll the terminal back through history |

## Configuration

Files live in the per-user config directory: `%APPDATA%\ohmyssh\` on Windows, `~/.config/ohmyssh/` elsewhere. The app was called pyommyssh until October 2026; a folder left under that name is moved to the new one on the next start, as long as the new folder does not exist yet.

### `config.toml`

Every key is optional. These are the defaults:

```toml
[general]
refresh_interval = 30      # seconds between dashboard refreshes, at least 1

[ui]
theme = "dark"             # only "dark" exists yet
terminal_font_size = 11    # points, at least 6
```

The terminal and the host card details use the first of these fonts that is installed: Menlo or Monaco on macOS, Consolas or Cascadia Mono on Windows, DejaVu Sans Mono or Liberation Mono on Linux, and otherwise the system's fixed-pitch font.

### `~/.ssh/config`

The app writes hosts here in plain OpenSSH form, one `Host` block each, appended at the end of the file. A name saved here must be one word with no spaces, `*`, `?`, `!` or `#`, because `ssh` reads `Host web (prod)` as two separate patterns; the host dialog refuses such a name and suggests a hyphenated one like `web-prod`. A host kept in the app can be called anything. Tags are kept as a comment inside the block, which `ssh` ignores:

```
Host web
    HostName 10.0.0.5
    User deploy
    Port 2222
    IdentityFile ~/.ssh/web_key
    ProxyJump bastion
    LocalForward 8080 localhost:80
    # tags: prod web
```

The defaults live in a `Host *` block kept at the end of the file:

```
Host *
    ServerAliveInterval 60
    ServerAliveCountMax 3
    IdentityFile ~/.ssh/id_rsa
    Compression yes
```

Backups of the file from before each save are in `working/backups/`.

### `hosts.toml`

Written by the app when you choose "App only" for a host. You can also edit it by hand:

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
server_alive_interval = 30     # omit any of these three to inherit the Host * default
server_alive_count_max = 5
compression = false
```

A host here with the same name as one in `~/.ssh/config` takes precedence. A top-level `hidden_hosts = ["name", ...]` list keeps those SSH config hosts off the dashboard.

The three forward lists are optional. A local forward listens on this machine and the server connects onward to `host:hostport`. A remote forward makes the server listen and this machine connects onward. A dynamic forward listens on this machine as a SOCKS proxy and takes only `[bind_address:]port`. Without a bind address a forward listens on loopback only; `*` means every interface. IPv6 addresses go in brackets, as in `[::1]:8080:localhost:80`.

### Logs

Logs go to `working/logs/ohmyssh.log` under the project root when running from source, or beside the executable when packaged. The packaged macOS app cannot write inside its own bundle, so it uses `~/Library/Application Support/ohmyssh/working/logs/ohmyssh.log` instead.

## Building a standalone Windows executable

```powershell
uv run python scripts/build_windows.py
```

That produces `dist/ohmyssh/ohmyssh.exe` with its support files beside it, using `src/ohmyssh/ui/icons/app.ico` as the executable's icon. Add `--onefile` for a single `dist/ohmyssh.exe`, and `--clean` to discard PyInstaller's cache. The full build log is in `working/build/pyinstaller.log`.

One-directory builds start faster and are less likely to be quarantined by antivirus software than one-file builds, which unpack to a temp directory on every launch.

## Building a standalone macOS app

```sh
uv run python scripts/build_macos.py
```

Run that on a Mac; PyInstaller cannot cross-compile, and the bundle is built for the architecture of the Mac doing the build. It produces `dist/ohmyssh.app`, using `src/ohmyssh/ui/icons/app.icns` as the app icon and `com.rev-x.ohmyssh` as the bundle identifier. The same `--onefile` and `--clean` flags apply, and the log is in `working/build/pyinstaller.log` as on Windows.

Add `--dmg` to also produce `dist/ohmyssh.dmg`. The app is staged in `working/build/dmg` beside a link to `/Applications` and compressed with `hdiutil`, so opening the image shows the app and the Applications folder side by side for a drag-to-install. The image does not change how Gatekeeper treats the app: it is still ad-hoc signed, so a copy from another Mac needs right-click, Open the first time.

The bundle is ad-hoc signed, which is enough to run it on the Mac that built it. On another Mac, Gatekeeper quarantines it until the user right-clicks the app and chooses Open the first time.

## Regenerating the icons

After changing the logo in `src/ohmyssh/ui/icons/app.svg`, regenerate both icon files and commit them:

```sh
uv run python scripts/build_icon.py
```

That writes `app.ico` for Windows and `app.icns` for macOS next to the SVG. `--png working/preview.png` also writes a 256 px preview to look at.

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
src/ohmyssh/core/   hosts, sshconfig, forwards, metrics, ssh, connections, tunnel, socks, keys, sftp, terminal, config (no Qt)
src/ohmyssh/ui/     terminalWidget, hostCard, dashboard, dialogs, filePane, sftpTab, sftpBridge, mainWindow, workers
tests/                pytest suite, including the in-process SSH test server
examples/             runnable usage examples
scripts/              build_windows.py, build_macos.py, build_icon.py
working/              logs, build artifacts (ignored by git)
```

## License

This project follows the upstream OmnySSH license, Apache-2.0.
