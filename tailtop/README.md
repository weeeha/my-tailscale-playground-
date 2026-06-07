# tailtop

A terminal UI for Tailscale — *htop for your tailnet.*

`tailtop` is a second front-end to the `tailscaled` daemon already running on
your machine (the same daemon the official GUI uses). It installs nothing on
the Tailscale side, needs no root, and runs entirely in your terminal.

## Modes

`Tab` cycles between three modes, each tuned to one intent:

| Mode | Intent | View | Theme | First-mount |
|------|--------|------|-------|-------------|
| **Comfort** | manage | List (GUI parity) | Studio | covered by boot |
| **Cockpit** | operate | Live cards + sparklines | Mission Control | beams curtain rise |
| **Observatory** | observe | Network topology | Brutalist | beams curtain rise |

## Animations

`tailtop` uses [terminaltexteffects](https://github.com/ChrisBuilds/terminaltexteffects)
for a few signature moments. Any keypress skips an animation in progress.

- **Boot:** beams assemble the title, print streams the connection status.
- **Mode mount:** first time you `Tab` into Cockpit or Observatory per session,
  beams play briefly over the mode's content.
- **Errors:** when a peer transitions to offline in Cockpit, its card burns
  in the theme's error color before settling on the offline state.

Sweep, Thunderstorm, and a lolcat-style rainbow gradient ship as an
unplaced library in `tailtop.widgets.effect_library` — wire them in when
a moment calls for them. See
[the animations design spec](../docs/superpowers/specs/2026-06-06-tailtop-animations.md)
and [implementation plan](../docs/superpowers/specs/2026-06-06-tailtop-animations-plan.md)
for the full picture.

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
