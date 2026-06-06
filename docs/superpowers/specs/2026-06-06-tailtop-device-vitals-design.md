# tailtop — Device Vitals (fleet hardware telemetry) — Design Spec

**Status:** Approved direction (brainstorm complete)
**Date:** 2026-06-06
**Extends:** `2026-06-05-tailtop-tui-design.md`
**Builds on:** `2026-06-06-tailtop-device-detail-design.md` (the composite `DeviceDetail` it adds panels to — already merged at `d57a9775c`)
**Owner:** nickv

---

## 1. Summary

Tailscale tells you a node is *online and reachable*; it says nothing about the
node's *hardware* — temperature, throttling, disk pressure, attached displays,
or whether the device's actual job is still running. This feature adds a
**vitals layer** to `tailtop`: each Linux Pi on the tailnet runs a tiny,
dependency-free `fleet-collect` script that prints one JSON blob; `tailtop`
fetches it over `tailscale ssh`, parses it into a typed `Vitals` model in the
data layer, and renders it through the seams already built — Cockpit device
cards, the Comfort `DeviceDetail` panels, the disk table, and the alert strip —
plus a one-shot `tailtop fleet` table for the terminal.

It serves three intents at once from a single collection path: a **live
dashboard** (in tailtop), **health alerts** (in-TUI now; out-of-band push in
Phase 2), and an **inventory + history** record.

The fleet is **homogeneous Linux/ARM**, so there is one agent, no cross-OS
matrix. The mechanism reuses tailtop's existing philosophy: it installs nothing
on the Tailscale side, needs no root on the Mac, and shells out to the
`tailscale` CLI behind the data-layer boundary.

## 2. Goals

- A typed `Vitals` model fetched per Pi and merged into app state on a slow,
  independent cadence — without slowing the network UI.
- Render vitals through **existing** widgets: Cockpit `DeviceCard` (badge line +
  temperature sparkline), Comfort `DeviceDetail` (two new info panels), the
  `DiskTable`, and the `AlertStrip`.
- Health thresholds as a **pure, unit-tested** function, mirroring
  `summarise_alerts`.
- A `tailtop fleet` one-shot table that exits non-zero on a critical condition
  (scriptable).
- Honest data: a peer with no vitals (non-Pi, unreachable, or collect failed)
  shows its network info unchanged and **omits** the vitals panels — never fakes
  them.

## 3. Non-Goals

- **No daemon on the Pis.** The script is stateless and piped over SSH on each
  poll; nothing is installed or left running on a Pi (Phase 2 may add an
  optional pre-install for speed).
- **No new heavyweight stack** — no Prometheus/Grafana/node_exporter. Pure
  stdlib + the `tailscale` CLI, matching the project's constraints.
- **No macOS/Windows agent** in this feature. Scope is the Linux Pi fleet. (The
  Mac is the collector/viewer, not a target; the model is OS-agnostic so other
  OSes can be added later.)
- **No persistence or out-of-band push in Phase 1.** Live ring buffers only;
  SQLite history and the Telegram/Slack/ntfy notifier are Phase 2.
- **No changes to Observatory.**

## 4. Constraints & Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Transport | **Pull** over `tailscale ssh` | Pis stay dumb; all logic central; reuses the daemon tailtop already depends on. No listener to maintain. |
| Collection cadence | Separate **VitalsPoller**, ~30 s | Network poll stays 1–2 s; SSH to 8 Pis must not drag the live UI. |
| Script delivery | **Pipe on demand** (`ssh … sh -s < fleet_collect.sh`) | Zero install, single source of truth. 30 s × 8 hosts makes overhead negligible. |
| Script language | POSIX `sh` | Present on every Pi (RPi OS, Debian trixie, Armbian) with no interpreter assumptions. |
| Thermal source | `/sys/class/thermal/*` (universal), `vcgencmd` **only when present** | Orange Pi (Allwinner) has no `vcgencmd`; Broadcom Pis add throttle/under-voltage flags. |
| Vitals in models | App owns `vitals_by_id: dict[str, Vitals]`; threaded into widgets like `rates` | Keeps `models.py` parsing pure; mirrors how `RateHistory` is passed, not attached to `Peer`. |
| "Which peers are Pis" | `tag:pi` ACL tag, else a hostname allowlist (config) | Avoids SSHing every linux peer blindly; discovered dynamically so new Pis appear automatically. |
| Charts | Reuse `state.sparkline` (temp/cpu); plotext optional in detail | No new deps; consistent with RX/TX sparklines. |
| Script packaged as | package data `tailtop/agent/fleet_collect.sh`, loaded via `importlib.resources` | Ships with the wheel; one canonical copy. |

## 5. Architecture

Three layers, unchanged boundary — **the data layer is the only CLI-aware
code**. Vitals slot in as a second source feeding the same app state.

```
┌─ UI layer ───────────────────────────────────────────────────────────────┐
│ device_card (badge + temp spark) · detail_pane (#panel-vitals,            │
│ #panel-hardware) · disk_table (real disk) · alert_strip (+health)         │
│ reads vitals_by_id / VitalsHistory from app state — never raw JSON        │
└──────────────────────────▲────────────────────────────────────────────────┘
                           │  app threads vitals like it threads rates
┌─ Data layer ─────────────┴────────────────────────────────────────────────┐
│ vitals.py  (Vitals model + from_collect_json)                              │
│ vitals_poller.py  (slow async loop, concurrency-capped, per-host timeout)  │
│ client.collect_vitals(peer)  ── tailscale ssh <user>@<host> -- sh -s       │
│                                  < agent/fleet_collect.sh                   │
└──────────────────────────▲────────────────────────────────────────────────┘
                           │  one JSON object per host
┌─ Each Pi ────────────────┴────────────────────────────────────────────────┐
│ agent/fleet_collect.sh  → {config, thermal, health, side_things, app}      │
└────────────────────────────────────────────────────────────────────────────┘
```

Two pollers run concurrently:

- **network poller** (existing) — `tailscale status --json`, 2 s / 1 s / 250 ms
  by mode. Unchanged.
- **vitals poller** (new) — every ~30 s, for each Pi peer concurrently (capped,
  e.g. 5 at a time), runs the collect script over SSH with a per-host timeout
  (~8 s). One host failing/timing out updates nothing for that host and never
  kills the loop (errors routed like the existing poller's `on_error`). Results
  update `vitals_by_id` and append to `VitalsHistory`.

## 6. The collect script + data contract

`tailtop/agent/fleet_collect.sh` prints exactly one JSON object to stdout. It is
read-only, side-effect-free, and runs in well under a second. Portable across
Broadcom (SuperClock, e-paper Pi Zero 2 W) and Allwinner (Orange Pi).

```jsonc
{
  "schema": 1,
  "host": "fastclock",
  "collected_at": "2026-06-06T22:40:00Z",

  "config": {                       // rare-change → inventory snapshot
    "model": "Raspberry Pi 4 Model B Rev 1.4",   // /proc/device-tree/model
    "serial": "10000000abcd1234",                 // /proc/cpuinfo Serial
    "soc": "BCM2711",
    "cpu_cores": 4, "arch": "aarch64",
    "mem_total_mb": 3814,
    "os": "Debian GNU/Linux 12 (bookworm)",       // /etc/os-release
    "kernel": "6.6.31+rpt-rpi-v8",
    "rpi_connect": "2.11.0",                       // `rpi-connect --version` if present
    "disk_total_gb": 29.5,
    "tailscale_ip": "100.78.29.28"
  },

  "thermal": {                      // live
    "soc_temp_c": 47.2,                            // /sys/class/thermal/thermal_zone0/temp
    "vcgencmd_present": true,
    "throttled_hex": "0x0",                         // `vcgencmd get_throttled` (Broadcom only)
    "under_voltage_now": false, "throttled_now": false,
    "under_voltage_since_boot": false, "throttled_since_boot": false
  },

  "health": {                       // live
    "load1": 0.12, "load5": 0.08, "load15": 0.05,  // /proc/loadavg
    "cpu_pct": 3.1,                                 // /proc/stat delta (sampled in-script)
    "mem_used_mb": 512, "mem_pct": 13.4,            // /proc/meminfo
    "swap_used_mb": 0,
    "disk_used_pct": 41.0, "disk_free_gb": 17.4,    // statvfs of /
    "uptime_s": 884213, "procs": 142
  },

  "side_things": {                  // live
    "displays": [                                   // /sys/class/drm/*/status (HDMI kiosks)
      { "connector": "HDMI-A-1", "status": "connected", "mode": "1920x1080" }
    ],
    "usb": [ { "id": "1d6b:0002", "name": "Linux Foundation 2.0 root hub" } ],  // lsusb if present
    "battery": { "present": false }                 // /sys/class/power_supply/* if a UPS HAT exists
  },

  "app": {                          // live, per device-type
    "name": "superclock",
    "running": true, "pid": 712,
    "last_render": "2026-06-06T22:39:58Z",          // e-paper units: file mtime of last frame
    "log_tail": ["…", "…"]
  }
}
```

### Per-device-type `app` detection

`app` is resolved by a small, hostname-driven rule in the script (overridable by
an env var the SSH command sets):

| Device class | Hosts | `running` signal | `last_render` |
|---|---|---|---|
| SuperClock | `fastclock`, `slowclock`, `smallclock`, `squareclock` | clock process alive (`pgrep`) | — |
| e-paper (PiEink) | `dashboard-ink-bed`, `dashboard3eink`, (`dashboard-ink-kitchen` when enrolled) | render service alive | mtime of last frame file |
| kiosk display | `nickv-orangepizero2w`, `plantdashboard` | dashboard server alive (`python3 server.py`) | — |

Unknown hosts → `app: { name: null, running: null }` (omitted in render).

## 7. tailtop module changes

### New

| File | Purpose |
|---|---|
| `tailtop/agent/fleet_collect.sh` | The per-Pi collect script (package data). |
| `tailtop/tailtop/data/vitals.py` | `Vitals` dataclass + `from_collect_json()`; derived `health_level` (`ok`/`warn`/`crit`) + `reasons: list[str]`. Parsing lives here. |
| `tailtop/tailtop/data/vitals_poller.py` | `VitalsPoller`: slow async loop, concurrency cap, per-host timeout, `on_vitals({id: Vitals})` + `on_error`. Mirrors `poller.Poller`. |
| `tailtop/tests/fixtures/vitals_rpi.json`, `vitals_orangepi.json` | Captured collect outputs (Broadcom + Allwinner shapes). |
| `tailtop/tests/test_vitals.py`, `test_vitals_poller.py` | Parser + poller tests. |

### Edited

| File | Change |
|---|---|
| `data/client.py` | `async def collect_vitals(peer) -> Vitals`: shells `tailscale ssh <user>@<host> -- sh -s` piping the script; timeout + error normalization, consistent with existing subprocess wrappers. SSH user + mechanism (tailscale-ssh vs OpenSSH key) are config. |
| `state.py` | Add `VitalsHistory` (per-peer `temp_c` + `cpu_pct` deques, `maxlen=32`) — a near-copy of `RateHistory` minus counter-diffing (gauges append directly). |
| `app.py` | Own a `VitalsPoller`, a `vitals_by_id` map, and a `VitalsHistory`; start/stop with the app; thread vitals into widget updates the way `rates` is threaded. |
| `widgets/device_card.py` | New badge line: `temp · throttle? · cpu% · mem% · disk%` colored by `health_level`; a temperature sparkline from `VitalsHistory` beside the RX/TX ones. Signature gains `vitals`. |
| `widgets/detail_pane.py` | Two new `.dpanel` Statics in `#detail-info`: **`#panel-vitals`** (temp, throttle/under-voltage, load, cpu%, mem, disk, uptime) and **`#panel-hardware`** (displays, USB, battery, app health + log tail). Shown only when vitals present; omitted otherwise (existing "omit, never empty" rule). `update_peer` gains a `vitals` arg; `show_empty` hides the two panels too. |
| `widgets/disk_table.py` | Feed real `disk_used_pct` / `disk_free_gb` from vitals. |
| `widgets/alert_strip.py` | `summarise_alerts(status, vitals_by_id)` folds in a new pure `summarise_health(vitals_by_id)`. |
| `commands.py` / `app.py` | `tailtop fleet`: one-shot — collect all Pis once, print a color table (host · temp · cpu · mem · disk · app · health), exit non-zero if any peer is `crit`. |

## 8. Health thresholds & alerts

Pure `summarise_health(vitals_by_id) -> str` (empty when all clear), unit-tested
without Textual, then concatenated into the alert strip after the existing
offline/key-expiry summary. `Vitals.health_level` + `Vitals.reasons` are derived
from the same thresholds so cards/detail/CLI agree.

| Condition | warn | crit |
|---|---|---|
| SoC temperature | ≥ 70 °C | ≥ 80 °C |
| `throttled_now` / `under_voltage_now` | — | true |
| Disk used | ≥ 85 % | ≥ 95 % |
| Memory used | ≥ 90 % | — |
| Load1 vs cores | > 1.5×cores | > 3×cores |
| App `running` | — | false |
| e-paper `last_render` stale | > 2× expected interval | — |

Thresholds live in one module-level table so they're tunable in one place
(and, Phase 2, overridable from config).

## 9. Phasing

**Phase 1 (MVP — one implementation plan).** Everything in §6–§8: the collect
script, `Vitals` model + parser, `VitalsPoller`, `client.collect_vitals`,
`VitalsHistory` + app wiring, the four widget edits, `tailtop fleet`, tests +
fixtures. Delivers live vitals in tailtop, in-TUI health alerts, and a
scriptable terminal command — all three intents at a basic level.

**Phase 2 (separate plan).**

- **History/persistence:** `data/history.py` → SQLite (`temp`, `cpu`, etc. time
  series) for sparkline backfill on launch and trend queries.
- **Inventory export:** `tailtop fleet inventory` → update the `INFRASTRUCTURE.md`
  device table / an Affine page from `config` snapshots.
- **Out-of-band alerts:** `tailtop alert` subcommand on a launchd timer; pluggable
  notifier (`data/notify.py`) with **Telegram, Slack, ntfy/macOS** backends;
  ships a `.plist`.
- **Optimization:** `--fast` (thermal/health/app every 30 s) vs `--full` (adds
  config/side-things every ~5 min) collect split; optional pre-install deploy of
  the script for lower per-poll overhead.

## 10. Data flow

1. App start → network `Poller` (existing) + `VitalsPoller` (new) both start.
2. VitalsPoller every ~30 s: select Pi peers from the latest `Status`
   (`tag:pi`/allowlist), `collect_vitals` each concurrently (capped, timeout),
   build `{id: Vitals}`.
3. On results: replace `vitals_by_id`; `VitalsHistory.update(id, temp, cpu)`.
4. Widgets re-render from current `Status` + `rates` + `vitals_by_id` +
   `VitalsHistory` (cards every network poll; detail on selection/poll).
5. `alert_strip` recomputes from `status` + `vitals_by_id`.

## 11. Error / empty states

- **Non-Pi peer** (Mac, iPhone, iPad): `vitals_by_id` has no entry → cards show
  network info only; detail omits both vitals panels. Normal, not an error.
- **Pi unreachable / SSH denied / timeout:** that host keeps its last-known
  vitals marked **stale** (dimmed, "vitals N m ago"); after a staleness window,
  vitals are dropped and the panels omit. The loop continues for other hosts.
- **Partial JSON / unknown field:** parser tolerates missing sub-objects (each of
  `config`/`thermal`/`health`/`side_things`/`app` optional); absent sections
  render as omitted rows, not crashes.
- **`vcgencmd` absent** (Orange Pi): `thermal.vcgencmd_present=false`; throttle
  rows omitted, temperature still shown from `/sys/class/thermal`.

## 12. Testing

- **Parser** (`test_vitals.py`): both fixtures → typed `Vitals`; missing
  sub-objects tolerated; `health_level`/`reasons` correct at boundary values.
- **Thresholds:** table-driven cases for each warn/crit edge.
- **Poller** (`test_vitals_poller.py`): fake client — all-ok, one-host-timeout
  (others still update), all-fail (loop survives, prior vitals retained then
  expire).
- **Render:** headless mount of `DeviceCard` and `DeviceDetail` with vitals
  present (panels appear, colored) and absent (panels omitted); snapshot the
  enriched card.
- **CLI:** `tailtop fleet` against a stub returning mixed health → table content
  + non-zero exit when a peer is `crit`.

## 13. Module deltas

```
tailtop/agent/fleet_collect.sh           # new: the per-Pi collect script (package data)
tailtop/tailtop/data/vitals.py           # new: Vitals model + parser + thresholds
tailtop/tailtop/data/vitals_poller.py    # new: slow concurrency-capped SSH poll loop
tailtop/tailtop/data/client.py           # +collect_vitals()
tailtop/tailtop/state.py                 # +VitalsHistory
tailtop/tailtop/app.py                   # +VitalsPoller wiring, vitals_by_id, VitalsHistory
tailtop/tailtop/commands.py              # +`fleet` one-shot command
tailtop/tailtop/widgets/device_card.py   # +vitals badge line + temp sparkline
tailtop/tailtop/widgets/detail_pane.py   # +#panel-vitals, +#panel-hardware
tailtop/tailtop/widgets/disk_table.py    # real disk data from vitals
tailtop/tailtop/widgets/alert_strip.py   # +summarise_health folded into summarise_alerts
tailtop/tests/fixtures/vitals_rpi.json   # new
tailtop/tests/fixtures/vitals_orangepi.json  # new
tailtop/tests/test_vitals.py             # new
tailtop/tests/test_vitals_poller.py      # new
```

## 14. Device inventory (current Pi targets)

From the canonical `~/.openclaw/workspace/INFRASTRUCTURE.md` (updated 2026-06-06).
Discovered dynamically at runtime; this table is for reference, not hardcoding.

| Host | Tailscale IP | Class | SoC family | `vcgencmd` |
|---|---|---|---|:--:|
| `fastclock` | `100.78.29.28` | SuperClock | Broadcom | ✅ |
| `slowclock` | `100.107.135.128` | SuperClock | Broadcom | ✅ |
| `smallclock` | `100.99.148.91` | SuperClock | Broadcom | ✅ |
| `squareclock` | `100.118.12.74` | SuperClock | Broadcom | ✅ |
| `dashboard-ink-bed` | `100.90.45.73` | e-paper (Pi Zero 2 W, Debian 13) | Broadcom | ✅ |
| `dashboard3eink` | `100.92.15.33` | e-paper (Pi Zero 2 W, Debian 13) | Broadcom | ✅ |
| `plantdashboard` | `100.64.79.16` | plant/kiosk | Broadcom | ✅ |
| `nickv-orangepizero2w` | `100.79.94.56` | kiosk display | **Allwinner** | ❌ |

`dashboard-ink-kitchen` / `shboard-ki` not yet enrolled — appears automatically
when it joins the tailnet and matches `tag:pi`/the allowlist.

## 15. Open questions / prerequisites

1. **Tailscale SSH on the Pis** — is `tailscale up --ssh` enabled and do ACLs
   allow Mac→Pi SSH for the chosen user? If not, fall back to OpenSSH with a key
   (collector becomes machine-specific). *Mechanism is config; default
   `tailscale ssh`, fallback `ssh`.*
2. **SSH user** on the Pis (`pi`? `nickv`?).
3. **`tag:pi`** — does this ACL tag exist, or should we ship a hostname allowlist
   in config for v1?
4. **Mac `tailscaled` running** — tailtop (and this poller) require the local
   daemon up; verify it's started.
5. **PR target branch** — `tailtop` (active integration branch) vs `main`.
