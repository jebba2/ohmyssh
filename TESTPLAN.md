# pyommyssh test plan

Keep this file current with the features and commands that exist. Tick the boxes as you verify each item on a real machine.

## Automated

- [x] `uv run pytest` passes with zero warnings
- [x] No Pylance errors in `src/`, `tests/`, `examples/`, `scripts/`

## Running from source

- [x] `uv run pyommyssh` opens the main window with a Dashboard tab
- [ ] `uv run python -m pyommyssh` does the same
- [x] `working/logs/pyommyssh.log` is created and records the host counts loaded

## Hosts

- [ ] Hosts from `~/.ssh/config` appear as cards with the right `user@host:port`
- [ ] A host inside an `Include`d file appears
- [ ] Wildcard `Host *` and `Match` blocks do not create cards
- [ ] `~/.ssh/config` is byte-for-byte unchanged after running the app
- [ ] `Ctrl+N` opens Add host; leaving Name blank shows "Name is required"
- [ ] Reusing an existing name shows "A host named '...' already exists"
- [ ] Saving a new host adds a card and writes `%APPDATA%\pyommyssh\hosts.toml`
- [ ] The pencil button beside the name opens Edit host prefilled; saving changes the card
- [ ] Editing an SSH config host saves an app host with the same name that replaces it on the dashboard, and `~/.ssh/config` is unchanged
- [ ] Right-click an app host: Edit host changes the card; Remove host asks to confirm and removes it
- [ ] Right-click an SSH config host: Open terminal and Edit host are offered, Remove host is not
- [ ] An app host with the same name as an SSH config host replaces it on the dashboard
- [ ] In Add host, a bad line in Local forwards shows "Local forward: expected [bind_address:]port:host:hostport, got '...'" and the dialog stays open
- [ ] Saving a host with forwards writes `local_forwards`, `remote_forwards`, and `dynamic_forwards` lists to `hosts.toml`; empty lists are omitted
- [ ] Edit host shows the saved forwards, one per line, in the box for their kind

## Dashboard

- [ ] After startup every card shows "Connecting..." then "Online" or an error
- [ ] CPU, RAM, and Disk bars show percentages on a Linux host
- [ ] Bars are green under 60%, yellow from 60%, red from 85%
- [ ] OS name, "up N days", and load average are shown
- [ ] A host with Docker shows "N containers"; a host without Docker shows no badge
- [ ] The top three processes are listed
- [ ] An unreachable host shows "Could not reach ..." and empty bars
- [ ] Cards refresh automatically after `refresh_interval` seconds
- [ ] `F5` refreshes immediately
- [ ] Group by tag shows a header per tag, hosts without tags under "Untagged", and a host appears once per tag
- [ ] Narrowing the window reduces the number of card columns

## Passwords

- [ ] A host whose key is not accepted prompts for a password once
- [ ] Entering the right password brings the card Online and later refreshes do not prompt again
- [ ] Cancelling the prompt shows "Password required" and the timer refresh does not prompt again
- [ ] `F5` after cancelling prompts again
- [ ] A wrong password prompts again
- [ ] Two hosts sharing a passphrase-protected identity file prompt only once; the second comes Online without a prompt
- [ ] A host whose identity file is a different passphrase-protected key still prompts
- [ ] With the key loaded in the SSH agent (`ssh-add`), a passphrase-protected key connects without any prompt

## Terminal

- [ ] Double-clicking a card opens a tab named after the host with a shell prompt
- [ ] Clicking the terminal icon beside the host name opens the same kind of tab; hovering shows "Open terminal"
- [ ] Both card icons render in the packaged exe (not blank squares)
- [ ] Typing, Enter, Backspace, arrows, Tab completion, and `Ctrl+C` behave as in a normal terminal
- [ ] `vim` or `htop` renders with colors and redraws correctly
- [ ] Resizing the window resizes the remote PTY (`tput cols` matches)
- [ ] Mouse wheel scrolls back through history; new output snaps back to the bottom
- [ ] `Ctrl+Shift+V` and `Shift+Insert` paste multi-line text with each line executed
- [ ] `exit` in the shell shows "Connection closed" and renames the tab "(closed)"
- [ ] Closing the tab with its X closes the channel; the Dashboard tab has no X
- [ ] Two tabs on the same host share one SSH connection (one login line in the server's auth log)

## ProxyJump

- [ ] A host with `ProxyJump bastion` connects through the bastion
- [ ] A chain `ProxyJump a,b` and a nested jump (b itself has a ProxyJump) both work
- [ ] A ProxyJump naming an unknown host shows an error mentioning that name

## SSH keys

- [ ] `Ctrl+G` and the Generate key toolbar button open "Generate SSH key" with Ed25519 selected and Save as pointing at `~/.ssh/id_ed25519`
- [ ] Switching the type to RSA 4096 changes Save as to `~/.ssh/id_rsa`; a path you typed yourself is left alone
- [ ] Browse... opens a save dialog and fills Save as with the chosen path
- [ ] Mismatched passphrases show "Passphrases do not match"; a path whose private or `.pub` file exists shows "... already exists"
- [ ] OK shows "Generated id_ed25519 and id_ed25519.pub in ..." in the status bar; `ssh-keygen -y -f ~/.ssh/id_ed25519` prints the same key as the `.pub` file
- [ ] An RSA key takes a moment but the window stays responsive while it is generated
- [ ] A key generated with a passphrase prompts for it on first connect; typing the passphrase into the prompt brings the card Online
- [ ] The prompt title reads "Password or key passphrase for user@host"
- [ ] Every card has a key button beside the pencil; hovering shows "Install SSH key"; right-click offers "Install SSH key..."
- [ ] Clicking it opens a file picker in `~/.ssh` filtered to `*.pub`
- [ ] Choosing a public key on a host that can log in shows "Installed <file> on <host>" in the status bar, and `cat ~/.ssh/authorized_keys` on the server ends with that key
- [ ] Choosing the same key again shows "<file> is already on <host>" and the file on the server gains no line
- [ ] The same key with a different comment is also reported as already there
- [ ] On the server `~/.ssh` is mode 700 and `authorized_keys` is mode 600 afterwards; other lines in the file are untouched
- [ ] After installing, a host that was using a password connects with the key on the next `F5` when the key has a default name or is the host's identity file
- [ ] Choosing the private key file shows "Could not install ... is a private key; choose the matching .pub file"
- [ ] On a host that needs a password, the prompt appears once; cancelling shows "Could not install ... Password required"
- [ ] A server-side failure (for example a read-only home) shows "Could not install ...: Unexpected reply from the server: ..." with the shell's error text
- [ ] All three card icons render in the packaged exe

## Port forwarding

- [ ] A host with `LocalForward 5081 localhost:81` in `~/.ssh/config` shows "L 5081 -> localhost:81" on its card with a "Start tunnel" button and "Tunnel off"
- [ ] A host with no forwards shows no forward list, status line, or tunnel button
- [ ] Start tunnel shows "Tunnel connecting..." then "Tunnel active" in green, and the button becomes "Stop tunnel"
- [ ] With a local forward active, `curl http://127.0.0.1:<port>/` reaches the service on the server side
- [ ] With a dynamic forward active, `curl --socks5-hostname 127.0.0.1:<port> http://<internal-host>/` reaches a host only the server can see
- [ ] With a remote forward active, `curl http://127.0.0.1:<port>/` on the server reaches a service running on this machine
- [ ] Stop tunnel shows "Tunnel off" and the local port can be bound by another program
- [ ] Right-click a host with forwards: the menu offers "Start tunnel" or "Stop tunnel" to match the button
- [ ] Killing the SSH session on the server (`pkill -u <user> sshd` or dropping the network) shows "Tunnel reconnecting: connection lost" in yellow, then "Tunnel active" once the server is back; the port stays bound meanwhile
- [ ] Starting a tunnel whose local port is in use shows "Tunnel failed: Could not listen on 127.0.0.1:<port>: ..." in red
- [ ] Starting a tunnel on a host that needs a password prompts once; cancelling shows "Tunnel: password required"
- [ ] Editing a host with a running tunnel restarts the tunnel with the new forwards; removing every forward stops it and hides the controls
- [ ] Removing a host with a running tunnel stops the tunnel
- [ ] Closing the app with tunnels running releases their ports
- [ ] Group by tag keeps each card's tunnel status

## SFTP

- [ ] The folder button beside a host's name (tooltip "Browse files") and the right-click "Browse files" open a tab named "<host> (files)"
- [ ] The left pane is titled "Local" and starts in your home folder; the right pane is titled after the host and starts in the remote home folder
- [ ] Folders are listed first, then files, both case-insensitively; sizes read like "1.5 KB" and dates like "2026-10-20 14:03"
- [ ] Double-clicking a folder enters it; double-clicking `..` or clicking Up goes to the parent; at a root there is no `..` and Up is disabled
- [ ] Typing a path in the path bar and pressing Enter navigates there; a bad path shows "Could not list ..." above the table and the old listing stays
- [ ] On Windows the local pane has a drive switch that lists every drive and changes the listing; on a single-root system there is none
- [ ] A host that needs a password prompts once; cancelling shows "Password required" above the panes
- [ ] An unreachable host shows "Could not reach ..." above the panes
- [ ] Upload and Download are disabled until something is selected on their side and the host is connected
- [ ] Selecting a file and a folder on the left and pressing Upload shows the strip ("Checking the remote folder...", then the file name with bytes and "n/m files"), then both appear on the right with the folder's contents intact
- [ ] Selecting items on the right and pressing Download copies them into the local folder on show
- [ ] Uploading over existing files asks "Replace N item(s)?" once, listing the names; No leaves the server untouched, Yes replaces them
- [ ] Uploading a large file shows a moving progress bar; Cancel removes the partial file on the server, shows "Transfer cancelled", and drops any queued transfers
- [ ] Opening a remote folder while a transfer runs shows "Loading..." then the folder
- [ ] A transfer that skips an item (for example a symlink in a folder) finishes and shows "skipped 1 item(s)" with the reason above the panes
- [ ] Closing the tab mid-transfer stops the transfer
- [ ] New folder asks for a name and the folder appears on the right; a blank or cancelled name does nothing
- [ ] Rename is enabled only with exactly one remote item selected; it asks with the current name prefilled and the listing shows the new name
- [ ] Delete asks "Delete N items from <host>?" listing the names; No leaves them, Yes removes files and empty folders
- [ ] Deleting a folder with contents shows "Could not remove ..." above the panes and leaves it
- [ ] Refresh relists both panes and picks up files created outside the app
- [ ] `Ctrl+K` lists the SFTP tab as "<host> (files, tab N)" and Enter switches to it
- [ ] Closing the tab closes its SFTP channels (two fewer sessions in the server's log)

## Search

- [ ] `Ctrl+K` opens the palette listing hosts then open tabs
- [ ] Typing filters by name, hostname, and tag, case-insensitively
- [ ] Up and Down wrap around; Enter on a host opens a terminal; Enter on a session switches tabs
- [ ] Escape closes the palette

## Configuration

- [ ] `refresh_interval = 5` in `config.toml` speeds up refreshes
- [ ] `terminal_font_size = 14` enlarges terminal text
- [ ] `refresh_interval = 0` shows a warning at startup and defaults are used

## Standalone build

- [x] `uv run python scripts/build_windows.py` finishes and prints the output path and size
- [ ] `dist/pyommyssh/pyommyssh.exe` starts on a machine without Python
- [ ] The packaged app reads `~/.ssh/config`, shows cards, and opens a terminal
- [x] Logs appear in `working/logs/` beside the executable
- [ ] `--onefile` produces `dist/pyommyssh.exe` that starts
- [ ] A failed build prints the last log lines and the log path

## Examples

- [x] `uv run python examples/list_hosts.py` lists the same hosts the app shows
- [ ] `uv run python examples/probe_host.py <host>` prints metrics for a reachable host
- [x] `uv run python examples/probe_host.py` with no argument prints usage
- [x] `uv run python examples/forward_port.py` with no argument prints usage; a bad `-L` rule prints "Bad rule: ..." and exits 2
- [ ] `uv run python examples/forward_port.py <host> -L 18080:localhost:80` prints the rule, "connecting", "up", and `curl http://127.0.0.1:18080/` works until Ctrl+C prints "Stopping"
- [x] `uv run python examples/generate_key.py` with no argument prints usage; `generate_key.py <tmp>/k` writes `k` and `k.pub`, and running it again prints "already exists" and exits 1
- [x] `uv run python examples/install_key.py` with no argument prints usage; a private key file prints "is a private key" and exits 2
- [ ] `uv run python examples/install_key.py <host> ~/.ssh/id_rsa.pub` prints "Installed ..." the first time and "already" the second
