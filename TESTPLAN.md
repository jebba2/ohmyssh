# ohmyssh test plan

Keep this file current with the features and commands that exist. Tick the boxes as you verify each item on a real machine.

## Automated

- [x] `uv run pytest` passes with zero warnings
- [x] No Pylance errors in `src/`, `tests/`, `examples/`, `scripts/`

## Running from source

- [x] `uv run ohmyssh` opens the main window with a Dashboard tab
- [ ] `uv run python -m ohmyssh` does the same
- [ ] The window title bar and the taskbar show the logo with "oh" and "my" in the top corners, a gold ring in the center, and "ssh" under it on a teal-to-blue tile, including when run from source with `uv run ohmyssh` (not the Python icon)
- [ ] Pinning the running app to the taskbar keeps the logo on the pinned button
- [ ] The packaged `ohmyssh.exe` shows the same icon in Explorer and the taskbar
- [x] `uv run python scripts/build_icon.py` regenerates `app.ico` with seven sizes and prints what it wrote
- [x] `working/logs/ohmyssh.log` is created and records the host counts loaded
- [x] Quitting while an unreachable host is still being probed closes the window within about a second instead of waiting out the connect timeout
- [ ] With `%APPDATA%\pyommyssh\` present from an older version and no `%APPDATA%\ohmyssh\`, the first start moves the folder, keeps every host, and logs the move; with both present nothing is moved

## Hosts

- [ ] Hosts from `~/.ssh/config` appear as cards with the right `user@host:port`
- [ ] A host inside an `Include`d file appears
- [ ] Wildcard `Host *` and `Match` blocks do not create cards
- [ ] `~/.ssh/config` is byte-for-byte unchanged after running the app without saving a host
- [ ] `Ctrl+N` opens Add host with "Save in" set to `~/.ssh/config`; leaving Name blank shows "Name is required"
- [ ] Reusing an existing name shows "A host named '...' already exists"
- [ ] Naming an SSH config host `web (prod)` pops up a warning that says to use one word, such as `web-prod`, and the dialog stays open after dismissing it; the same name is accepted when Save in is the app
- [ ] Saving a new host appends a `Host` block at the end of `~/.ssh/config` (tags as a `# tags:` comment), the card appears, and `ssh <name>` in a terminal works
- [ ] Choosing "App only (hosts.toml)" instead writes `%APPDATA%\ohmyssh\hosts.toml` and leaves `~/.ssh/config` alone
- [ ] The pencil button beside the name opens Edit host prefilled with "Save in" disabled; saving changes the card
- [ ] Editing an SSH config host changes only its own block's HostName, User, Port, IdentityFile, ProxyJump, forwards, and tags comment; every other line in the file, including comments and `Host *`, is unchanged (`diff` against the backup)
- [ ] Before each save a copy lands in `working/backups/config-<timestamp>.bak`; only the last ten are kept
- [ ] Editing `Hermes` shows "Also applies to (jebba): they share this Host line in ~/.ssh/config", and the saved change shows on both cards
- [ ] A host defined in an `Include`d file is edited in that file; the main config is untouched
- [ ] A name with a space or `*` is refused with "cannot be used as a Host name" and nothing is written
- [ ] Right-click an app host: Edit host changes the card; Remove host asks "Remove '...'? Its settings are deleted from hosts.toml." and removes it
- [ ] Right-click an SSH config host: Hide host asks to confirm, explains that `~/.ssh/config` is not changed, and the card disappears; `hosts.toml` gains `hidden_hosts = ["..."]` and the host stays hidden after a restart
- [ ] Removing the name from `hidden_hosts` and restarting brings the host back
- [ ] Edit host has a "Remove host" button for app hosts and a "Hide host" button for SSH config hosts; Add host has neither; the button asks the same confirmation
- [ ] Every card has a red trash button beside the name whose tooltip reads "Remove host" or "Hide host" to match; clicking it asks the same confirmation
- [ ] An app host with the same name as an SSH config host replaces it on the dashboard
- [ ] In Add host, a bad line in Local forwards shows "Local forward: expected [bind_address:]port:host:hostport, got '...'" and the dialog stays open
- [ ] Saving a host with forwards writes `local_forwards`, `remote_forwards`, and `dynamic_forwards` lists to `hosts.toml`; empty lists are omitted
- [ ] Edit host shows the saved forwards, one per line, in the box for their kind

## SSH defaults

- [ ] `Ctrl+,` and the Settings button open "SSH defaults" showing the current `Host *` values, or "Not set" where there are none
- [ ] Saving writes a `Host *` block at the end of `~/.ssh/config` with only the set values; an existing `Host *` block at the top of the file is moved to the end with its other lines intact (`diff` against the backup)
- [ ] A host dialog's Keepalive interval, Keepalive count, and Compression default to "Use global"; set values appear as `ServerAliveInterval`, `ServerAliveCountMax`, and `Compression` lines in that host's block
- [ ] Opening the Compression drop-down (and any other drop-down, including on macOS) lists "Use global", "On", and "Off" in full as light text on a dark list below the box; nothing is cut off or invisible until highlighted
- [ ] With a global keepalive of 10 and `sshd` logging at debug level, the server sees keepalive requests about every 10 seconds on an idle connection; a host set to 3 sends them every 3 seconds
- [ ] With global compression on, `ssh -v <host>` shows compression enabled, and a host with Compression "Off" does not

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
- [x] Cards in a row share one width however long their address or forwards are, and a shorter card keeps its rows at the top beside a taller one

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
- [ ] On a Mac the typed text follows the colored prompt with normal spacing and the cursor sits directly after the last character, at font sizes 10 through 13 (no gap or overlap at style boundaries)
- [ ] Tab and Shift+Tab reach the shell (completion works, `Shift+Tab` cycles back in menus such as `fzf`) and never move focus or switch the app's tabs; `Ctrl+Tab` still switches tabs
- [ ] `vim` or `htop` renders with colors and redraws correctly
- [ ] Resizing the window resizes the remote PTY (`tput cols` matches)
- [ ] Mouse wheel scrolls back through history; new output snaps back to the bottom
- [ ] `Ctrl+Shift+V` and `Shift+Insert` paste multi-line text with each line executed
- [ ] Dragging across text highlights it; `Ctrl+Shift+C` and `Ctrl+Insert` copy it with trailing padding removed and one line per row
- [ ] Double-click selects the word under the pointer; a third click selects the whole line
- [ ] Right-click offers Copy (only with a selection) and Paste
- [ ] A selection stays on the same text while scrolling back with the wheel and while new output scrolls the screen; a plain click clears it
- [ ] `Ctrl+C` with a selection still interrupts the running program and leaves the clipboard alone
- [ ] `exit` in the shell shows "Connection closed" and renames the tab "(closed)"
- [ ] Closing the tab with its X closes the channel; the Dashboard tab has no X
- [ ] Two tabs on the same host share one SSH connection (one login line in the server's auth log)

## ProxyJump

- [ ] A host with `ProxyJump bastion` connects through the bastion
- [ ] A chain `ProxyJump a,b` and a nested jump (b itself has a ProxyJump) both work
- [ ] A ProxyJump naming an unknown host shows an error mentioning that name

## First launch

- [ ] With `%APPDATA%\ohmyssh\first_run_done` deleted and no private key in `~/.ssh` (move them aside), starting the app creates `~/.ssh` if missing and shows "Welcome to ohmyssh" explaining that no key was found
- [ ] Yes opens Generate SSH key with Save as `~/.ssh/id_ed25519`; OK writes the pair and the status bar reports it
- [ ] No, or cancelling the key dialog, leaves `~/.ssh` without a key, and the next start does not ask again
- [ ] With a key already present, starting the app shows no welcome; `first_run_done` is still written

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
- [ ] With an `authorized_keys` whose last key has no newline after it (`printf 'ssh-rsa AAAA... old' > ~/.ssh/authorized_keys`), installing a key leaves the old key on its own line, the new key on the next, and both still log in
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
- [ ] A remote symlink to a folder is listed among the folders and double-clicking it enters the folder it points at; a symlink to a file shows the file's size
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
- [ ] Transferring a file with a very long name keeps the progress bar and Cancel button at full size; the name is shortened in the middle with an ellipsis and the full text shows in a tooltip
- [ ] A transfer that skips an item (for example a symlink in a folder) finishes and shows "skipped 1 item(s)" with the reason above the panes
- [ ] Closing the tab mid-transfer stops the transfer
- [ ] New folder asks for a name and the folder appears on the right; a blank or cancelled name does nothing
- [ ] Rename is enabled only with exactly one remote item selected; it asks with the current name prefilled and the listing shows the new name
- [ ] Delete asks "Delete N items from <host>?" listing the names; No leaves them, Yes removes files and empty folders
- [ ] Deleting a folder with contents shows "Could not remove ..." above the panes and leaves it
- [ ] Refresh under the remote pane relists the remote pane and picks up files created outside the app; Refresh under the local pane does the same for the local pane
- [ ] Under the local pane, New folder asks for a name and the folder appears on the left; Rename is enabled only with exactly one local item selected and asks with the current name prefilled; renaming onto a name that is taken shows "Could not rename ..." and changes nothing
- [ ] Under the local pane, Delete asks "Delete N items from this computer?" listing the names; No leaves them, Yes removes files and empty folders; a folder with contents shows "Could not remove ..." and stays
- [ ] Dragging a local file and a folder onto the remote pane uploads them into the folder on show; dragging onto a remote folder row puts them inside that folder
- [ ] Dragging a remote file onto the local pane downloads it; onto a local folder row downloads into that folder
- [ ] Dragging rows and dropping them back on the same pane does nothing; the `..` row cannot be dragged
- [ ] Dragging a file from the desktop onto the remote pane's list, its path bar, or the empty middle of the SFTP tab uploads it to the remote folder on show, and the file is still on the desktop afterwards
- [ ] Holding Shift while dragging from Explorer (a move) still uploads and still leaves the original in place
- [ ] Dropping a drive (`C:\`) or two files named alike from Explorer shows "Not uploaded: ..." naming them, and the rest upload
- [ ] A drag that would replace existing items asks "Replace N item(s)?" first
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
- [ ] On a Mac the terminal and the host card address lines use Menlo, and launching from a terminal prints no `qt.qpa.fonts` warning about a missing font family
- [ ] `refresh_interval = 0` shows a warning at startup and defaults are used

## Standalone build

- [x] `uv run python scripts/build_windows.py` finishes and prints the output path and size
- [ ] `dist/ohmyssh/ohmyssh.exe` starts on a machine without Python
- [ ] The packaged app reads `~/.ssh/config`, shows cards, and opens a terminal
- [x] Logs appear in `working/logs/` beside the executable
- [ ] `--onefile` produces `dist/ohmyssh.exe` that starts
- [ ] A failed build prints the last log lines and the log path
- [x] `uv run python scripts/build_macos.py` on a Mac finishes and prints the output path and size
- [x] `dist/ohmyssh.app` starts, shows the ohmyssh logo in the Dock, and `Info.plist` names `com.rev-x.ohmyssh`
- [ ] The packaged Mac app reads `~/.ssh/config`, shows cards, and opens a terminal
- [x] The packaged Mac app logs to `~/Library/Application Support/ohmyssh/working/logs/` and writes nothing inside the bundle
- [ ] `uv run python scripts/build_macos.py --dmg` writes `dist/ohmyssh.dmg`; double-clicking it mounts a volume showing `ohmyssh.app` beside an `Applications` link, and dragging the app onto the link installs it
- [ ] `uv run python scripts/build_linux.py` on Linux finishes and prints the output path and size
- [ ] `dist/ohmyssh/ohmyssh` starts on a Linux desktop without Python, shows the logo in its title bar, and logs to `working/logs/` beside the program
- [ ] The packaged Linux app reads `~/.ssh/config`, shows cards, and opens a terminal
- [x] `uv run python scripts/build_icon.py` writes `app.ico` and `app.icns`, and `iconutil -c iconset` reads the `.icns` back with every size intact

## Release workflow

- [ ] Publishing a release tagged `vX.Y.Z` starts the "Release builds" workflow under the Actions tab; saving it as a draft does not
- [ ] The Windows job attaches `ohmyssh-vX.Y.Z-windows-x64.zip` to the release; unzipping it gives an `ohmyssh/` folder whose `ohmyssh.exe` starts on a machine without Python
- [ ] The macOS job attaches `ohmyssh-vX.Y.Z-macos-arm64.dmg` to the release; it mounts and the app inside starts on an Apple Silicon Mac after right-click, Open
- [ ] The Linux job attaches `ohmyssh-vX.Y.Z-linux-x64.tar.gz` to the release; `tar xzf` gives an `ohmyssh/` folder whose `ohmyssh` program is executable and starts on an x64 Linux desktop
- [ ] All three files also appear as artifacts on the workflow run
- [ ] A failed build leaves the release without that asset and the Actions tab shows the PyInstaller log tail from the build script

## Examples

- [x] `uv run python examples/list_hosts.py` lists the same hosts the app shows
- [ ] `uv run python examples/probe_host.py <host>` prints metrics for a reachable host
- [x] `uv run python examples/probe_host.py` with no argument prints usage
- [x] `uv run python examples/forward_port.py` with no argument prints usage; a bad `-L` rule prints "Bad rule: ..." and exits 2
- [ ] `uv run python examples/forward_port.py <host> -L 18080:localhost:80` prints the rule, "connecting", "up", and `curl http://127.0.0.1:18080/` works until Ctrl+C prints "Stopping"
- [x] `uv run python examples/generate_key.py` with no argument prints usage; `generate_key.py <tmp>/k` writes `k` and `k.pub`, and running it again prints "already exists" and exits 1
- [x] `uv run python examples/install_key.py` with no argument prints usage; a private key file prints "is a private key" and exits 2
- [ ] `uv run python examples/install_key.py <host> ~/.ssh/id_rsa.pub` prints "Installed ..." the first time and "already" the second
