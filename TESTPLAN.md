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
- [ ] Right-click an app host: Edit host changes the card; Remove host asks to confirm and removes it
- [ ] Right-click an SSH config host: only Open terminal is offered
- [ ] An app host with the same name as an SSH config host replaces it on the dashboard

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

## Terminal

- [ ] Double-clicking a card opens a tab named after the host with a shell prompt
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
