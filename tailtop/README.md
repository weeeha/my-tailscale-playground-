# tailtop

A terminal UI for Tailscale — *htop for your tailnet.*

`tailtop` is a second front-end to the `tailscaled` daemon already running on
your machine (the same daemon the official GUI uses). It installs nothing on
the Tailscale side, needs no root, and runs entirely in your terminal.

## Modes

`Tab` cycles between three modes, each tuned to one intent:

| Mode | Intent | View | Theme |
|------|--------|------|-------|
| **Comfort** | manage | List (GUI parity) | Studio |
| **Cockpit** | operate | Live cards + sparklines | Mission Control |
| **Observatory** | observe | Network topology | Brutalist |

## Keys

| Key | Action |
|-----|--------|
| `Tab` | cycle modes (Comfort → Cockpit → Observatory) |
| `j` / `k` / `↑` / `↓` | navigate devices |
| `⌘P` / `Ctrl+P` | command palette (all verbs for the selected device) |
| `p` | ping · `c` copy IP · `w` whois · `n` netcheck |
| `e` | toggle exit node · `f` send file · `s` SSH |
| `r` | refresh · `?` help · `q` quit |

Mutating actions (exit node, funnel, send) confirm first. SSH suspends the
TUI, hands the terminal to `tailscale ssh`, and resumes on exit.

## Fleet vitals

`tailtop fleet` prints a one-shot table of hardware vitals for every Pi in your
tailnet and exits with code 0 (all healthy) or 1 (at least one host critical):

```sh
uv run tailtop fleet
```

Telemetry is collected by piping a small POSIX-sh script (`agent/fleet_collect.sh`)
over `tailscale ssh`. The Pis themselves need nothing pre-installed — the script
is streamed at collection time, runs read-only, and produces one JSON object of
temp, CPU, memory, disk, throttle flags, display connectors, and app-health.

The interactive TUI also polls vitals in the background every ~30 s:
device cards show a temperature/health badge, the DeviceDetail panel adds
Vitals and Hardware sections, and the alert strip surfaces overheating,
throttling, and app-down events.

## Alert — out-of-band notifications

`tailtop alert` collects one round of Pi vitals and sends a message to every
configured notification channel when any host is in a `warn` or `crit` state.
If all hosts are healthy it prints `all clear` and exits 0. No TUI is opened.

```sh
uv run tailtop alert
```

### Notification channels

Channels are enabled by exporting the corresponding env vars before running
`tailtop alert` (or filling them into the launchd plist's
`EnvironmentVariables` dict):

| Channel | Required env vars |
|---------|-------------------|
| **Telegram** | `TAILTOP_TELEGRAM_TOKEN` + `TAILTOP_TELEGRAM_CHAT_ID` |
| **Slack** | `TAILTOP_SLACK_WEBHOOK` (incoming-webhook URL) |
| **ntfy** | `TAILTOP_NTFY_TOPIC` (+ optional `TAILTOP_NTFY_SERVER`, default `https://ntfy.sh`) |

A channel is silently skipped when its env var(s) are absent or empty.

### Running on a schedule (launchd)

A ready-made launchd agent plist is included at
`tailtop/com.weeeha.tailtop-alert.plist`. It fires every 15 minutes
(`StartInterval 900`).

1. Copy the plist to your LaunchAgents folder and edit the paths and secrets:
   ```sh
   cp tailtop/com.weeeha.tailtop-alert.plist ~/Library/LaunchAgents/
   # Edit ProgramArguments (--directory path) and EnvironmentVariables
   # (TAILTOP_* secrets) before loading.
   open ~/Library/LaunchAgents/com.weeeha.tailtop-alert.plist
   ```

2. Load the agent:
   ```sh
   launchctl load ~/Library/LaunchAgents/com.weeeha.tailtop-alert.plist
   ```

3. Logs are written to:
   - `~/Library/Logs/tailtop-alert.log` (stdout)
   - `~/Library/Logs/tailtop-alert.err` (stderr)

To unload: `launchctl unload ~/Library/LaunchAgents/com.weeeha.tailtop-alert.plist`

## Requirements

- The `tailscale` CLI on your `PATH` (the daemon must be running).
- Python ≥ 3.13.

## Run

```sh
uv run tailtop
```

## Develop

```sh
uv venv --python 3.13
uv pip install -e ".[dev]"
uv run pytest
```

## Design

See [the design spec](../docs/superpowers/specs/2026-06-05-tailtop-tui-design.md).

Visual inspiration from [Bagels](https://github.com/EnhancedJax/Bagels); no
code is copied (Bagels is GPL-3, tailtop is BSD-3).
