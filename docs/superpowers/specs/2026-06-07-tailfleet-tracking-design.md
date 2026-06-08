# tailprobe + tailhub — Fleet-Tracking Stack Design Spec

**Status:** Approved direction (brainstorm complete)
**Date:** 2026-06-07
**Owner:** nickv

---

## 1. Summary

A two-part system that turns the tailnet into a continuously-tracked device
fleet:

- **`tailprobe`** — a tiny static Go binary installed as a service on each
  device. It exposes that device's telemetry on a Tailscale-only HTTP endpoint.
- **`tailhub`** — a Python/FastAPI service on the always-on Mac Studio. It
  scrapes every probe on a schedule, stores history in SQLite, runs alerting,
  and serves a JSON API that `tailtop`, future dashboards, the lifelog pipeline,
  and OpenClaw agents all read.

This replaces today's **agentless, on-demand** vitals collection (in which
`tailtop` streams `tailtop/agent/fleet_collect.sh` over `tailscale ssh` only
while the TUI is open and stores nothing) with an **always-on, installed,
historical** system — while reusing the existing `fleet_collect.sh` logic, the
`lifelog` SQLite timeline + collectors, and the `tailtop` UI.

The design is **hybrid**: the probe speaks Prometheus exposition format on day
one, so the bespoke hub collects it now and a Prometheus/Grafana stack can scrape
the *same* endpoints later with zero agent changes. Own the agent; stay
interoperable; never get locked in.

## 2. Goals

- **One agent, four collectors.** Each device tracks **vitals**, **network**,
  **usage**, and **presence/activity** through one pluggable agent — not four
  separate tools.
- **Always-on with history.** Telemetry is recorded continuously, even when no
  one is watching, into a real time-series store with trends and rollups.
- **Four outcomes, all served:** alerting (→ Telegram), a live dashboard
  (`tailtop`), history & trends (SQLite + rollups), and an API the lifelog
  pipeline and OpenClaw agents can query.
- **100% local / owned / Tailscale-only.** No cloud, no third-party SaaS. This
  is the explicit differentiator carried over from the lifelog concept.
- **Reuse what's built.** `fleet_collect.sh` (vitals), `lifelog/` (store +
  collectors), `tailtop` (UI) are foundations, not throwaways.
- **Prometheus-ready.** Keep the door open to Grafana/PromQL without committing
  to running that stack.
- **Minimal device footprint.** A single dependency-free binary suitable for a
  Pi Zero 2 W.

## 3. Non-Goals

- **No remote control / command execution on devices.** The agent is read-only
  and structurally cannot be told to *do* things — the hub only pulls data. No
  C2 surface. (Mutating actions like exit-node toggling stay in `tailtop`, which
  drives the local `tailscaled`, not the probe.)
- **Not running Prometheus/Grafana on day one.** Compatibility now; adoption
  only if SQLite analytics prove insufficient (Phase 5, optional).
- **No agent on iOS.** iPhone/iPads cannot run an arbitrary binary; they are
  tracked online/offline only, via `tailscale status` on the hub.
- **Not a replacement for `tailtop`'s interactive control.** `tailtop` remains
  the operator UI; this stack becomes its data source.
- **No sub-room WiFi-CSI localization here.** That lives in the lifelog project;
  this stack ingests presence *signals*, it does not do CSI DSP.

## 4. Decisions locked in brainstorming

| Decision | Choice | Rationale |
|---|---|---|
| What to track | vitals + network + usage + presence (pluggable collectors) | User wants the full picture; one pipeline, four collectors |
| What it's for | alerting + live dashboard + history & trends + agent/lifelog API | All four; drives store + API + alerting + UI |
| Build vs adopt | **Hybrid** — bespoke agent/hub, Prometheus-format compatible | Reuse existing code + own/local values, without locking out Grafana later |
| Agent runtime | **Static Go binary** | Single dep-free file, cross-compiles to every Pi arch, native to this repo; ideal for Pi Zero 2 W |
| Hub runtime/location | **Python/FastAPI on Mac Studio** (`100.75.213.56`) | Always-on; runs OpenClaw gateway; reuses lifelog/tailtop Python |
| Transport | **Pull/scrape** over Tailscale (hub → probe `/metrics` + `/vitals`) | Prometheus-native; intermittent devices simply scrape "offline"; one endpoint serves both collectors |

## 5. Architecture

```
PER DEVICE (Linux Pis → later Mac/Win)        HUB (Mac Studio, always-on)         CLIENTS
┌──────────────────────────────┐
│ tailprobe  (static Go binary) │              ┌───────────────────────────┐
│ systemd / launchd service     │  Tailscale   │ tailhub (Python / FastAPI)│      tailtop (TUI)
│ HTTP bound to tailscale0 ONLY │── 100.x ────►│  scheduler: scrape every  │◄──── reads hub API
│   GET /metrics  (Prom text)   │   scrape     │    probe ~30s              │
│   GET /vitals   (rich JSON)   │◄── ~30s ─────│  tailscale-status collector│      web dashboard
│   GET /healthz                │              │    (agentless iOS/iPad)    │◄──── (optional)
│ collectors:                   │              │  SQLite timeline + rollups │
│   vitals·network·usage·presence│             │  rules engine → alerts     │      OpenClaw agents
└──────────────────────────────┘              │  REST/JSON API             │◄──── query fleet
   iPhone / iPads (no agent) ────────────────► │  /metrics passthrough      │      Telegram (alerts)
        online/offline only                    └───────────────────────────┘
                                                          │ (optional, later)
                                               Prometheus + Grafana scrape the SAME probe /metrics
```

**Data flow:** hub scheduler → discover fleet from `tailscale status --json` →
for each device with a probe, `GET /vitals` (+ `/metrics`) over its `100.x`
address → normalize → write to SQLite (`device`/`metric`/`event`) → evaluate
alert rules → dispatch alerts → expose via API. Devices without a probe are
recorded online/offline from the tailscale status itself.

## 6. Components

### 6.1 `tailprobe` — the agent (Go, static binary, per device)

- **Packaging:** one static binary, no runtime/pip deps. Installed as a systemd
  unit (Linux), launchd plist (macOS), or service (Windows). Runs unprivileged
  where the readings allow; vitals need only read access to `/proc`, `/sys`, and
  `vcgencmd` (Broadcom only).
- **Binding/security:** HTTP listener binds the device's **Tailscale address
  only** (never `0.0.0.0`). The probe discovers its own `100.x` from the running
  `tailscaled` via `tailscale.com/client/local` (`Client.Status().TailscaleIPs`)
  — not `tsnet` (too heavy: a second node), not interface-name guessing — and
  retries with backoff at boot until an IP exists. Tailscale ACLs restrict
  `/metrics` + `/vitals` to the hub's IP/tag; an optional shared bearer token (and
  an optional `WhoIs` caller check) add defense-in-depth.
- **Endpoints:**
  - `GET /metrics` — Prometheus exposition format (numeric series only). The
    Prometheus-compatible surface.
  - `GET /vitals` — rich JSON: the full `fleet_collect.sh`-shaped object plus
    network/usage/presence detail, including non-numeric fields (model, app
    name/running, display connectors).
  - `GET /healthz` — liveness.
- **Collectors** (each a Go module behind one `Collector` interface):
  - **vitals** — port of `tailtop/agent/fleet_collect.sh`: model, serial, cpu
    cores + %, mem total/%, disk total/used/free, SoC temp, throttle +
    under-voltage flags (Broadcom `vcgencmd`), load, uptime, display connectors
    (DRM), USB count, battery (UPS HAT), and app-health by hostname class
    (`*clock*` → superclock, `*eink*` → epaper, `*dashboard*`/`*plant*` →
    dashboard). App-down emits `null` (unknown), never false-critical — matches
    the existing script's contract.
  - **network** — interface byte/packet/error counters, active TCP connection
    count, default route, optional local `tailscaled` self-status.
  - **usage** — load trend, swap, top process by cpu/mem (name only — no args,
    privacy-aware).
  - **presence/activity** — derived signals: kiosk app up + last-render time *is*
    presence on a dashboard Pi. Richer sensor presence (PIR / smart-plug /
    RuView) is collected by the existing `lifelog` collectors and ingested at the
    hub, not re-implemented in Go.
- **Behavior:** read-only, side-effect-free, low overhead; samples on scrape or
  serves a recently-cached sample. CPU% uses the existing two-sample `/proc/stat`
  delta technique.

### 6.2 `tailhub` — the hub (Python/FastAPI, Mac Studio)

- **Scheduler:** every ~30s, discover the fleet from `tailscale status --json`,
  then scrape each probe (`/vitals` + `/metrics`). Reuse
  `lifelog/collectors/tailscale.py::TailscaleOnlineCollector` for agentless
  devices (iPhone/iPads, or any Pi before install) → online/offline only.
- **Store:** SQLite timeline extending `lifelog/store.py`. Raw samples retained N
  days; hourly/daily rollups for trends. SQLite is ample at fleet scale
  (≤ ~20 devices × 30 s).
- **Rules engine:** declarative, operator-configurable thresholds —
  `soc_temp_c >` limit, `disk_free_gb <` floor, app down, `online == false` for
  longer than a grace window, throttle / under-voltage — emit alert events with
  de-dupe + hysteresis (fire once, clear once). Concrete limits live in config,
  not the design. Dispatch to Telegram via the existing OpenClaw path (or a
  direct bot token).
- **API (REST/JSON):** `/fleet` (current state of all devices), `/device/{host}`
  (current + history), `/history?metric=&since=`, `/alerts`, `/presence`. This is
  the single surface `tailtop`, a web dashboard, the lifelog pipeline, and
  OpenClaw agents consume.
- **Prometheus hook:** the probes' `/metrics` is the standard surface; a future
  Prometheus scrapes probes directly (or the hub federates an aggregated
  `/metrics`). No agent change required.

### 6.3 Views & integrations

- **`tailtop`:** repoint `tailtop/tailtop/data/vitals_poller.py` from
  "SSH-stream `fleet_collect.sh`" to "GET `tailhub`/fleet". `tailtop fleet`
  (one-shot table) reads the hub. The TUI gains *real* historical sparklines and
  a hub-fed alert strip. Mostly a data-source swap — the UI already exists.
- **Web dashboard (optional, later):** a small hub-served page for at-a-glance +
  historical charts, or attach Grafana via the Prometheus hook and skip building
  charts.
- **OpenClaw agents / lifelog:** agents hit the hub API ("is `plantdashboard`
  overheating?", "which devices are offline?"); lifelog ingests presence from
  `/presence`.
- **Alerts:** hub → Telegram.

## 7. Data model (extends lifelog's SQLite)

- `device(host, ts, config_json, online)` — identity + latest config snapshot +
  reachability.
- `metric(host, ts, key, value)` — narrow/long numeric series for trends
  (`cpu_pct`, `soc_temp_c`, `mem_pct`, `disk_free_gb`, `net_rx_bytes`, …).
- `event(host, ts, kind, detail_json)` — discrete events: `app_down`,
  `throttled`, `came_online`/`offline`, `alert_fired`/`cleared`, presence
  transitions.
- `metric_hourly(host, hour, key, min, max, avg)` — rollups for trend queries.

Reuse `lifelog/store.py` patterns (it already does a SQLite timeline with schema
+ writes + day queries).

## 8. Security & privacy

This is whole-fleet and health-adjacent (presence), so privacy is a requirement,
not a phase.

- **Tailscale-only bind + ACLs.** Probe HTTP never binds `0.0.0.0`; ACLs restrict
  `/metrics` + `/vitals` to the hub's IP. Optional bearer token for
  defense-in-depth.
- **Read-only agent, no control plane.** The probe never executes hub-supplied
  commands; the hub pulls data and cannot push actions. No C2 surface.
- **Data stays on the Mac Studio** (SQLite). Presence is the sensitive layer:
  opt-in per device, modest retention, and **at-rest DB encryption** when
  presence is stored (the lifelog concept doc flags this as a requirement).
- **Privacy-aware collectors.** Process info is coarse (top-1 name, no cmdline /
  args) by default.

## 9. Phasing / roadmap

Each phase ships independently and is individually useful. This document is the
umbrella; each phase gets its own spec → plan → implementation cycle. The first
implementation spec is **Phase 0**.

| Phase | Deliverable | Outcome |
|---|---|---|
| **0 Skeleton** | `tailprobe` (vitals collector only) + `/metrics` + `/vitals`; `tailhub` scheduler → SQLite → `/fleet`; one-command installer that pushes the binary + service unit over **key-based OpenSSH** (tailtop's proven transport — see §12) to the 8 arm64 Linux SBCs; repoint `tailtop fleet` to read the hub | Always-on vitals **with history**, replacing the on-demand pull |
| **1 Alerting** | rules engine + de-dupe/hysteresis + Telegram | overheating / app-down / offline pages you |
| **2 Network + usage** | two more collectors + `tailtop` history sparklines from stored data | richer fleet telemetry |
| **3 Presence** | presence collector + hub `/presence` + lifelog ingestion + agent-API endpoints | feeds the life-tracker & automations |
| **4 Mac / Win / iOS** | launchd + Windows agents; agentless iOS via `tailscale status` | whole fleet covered |
| **5 (optional) Prometheus** | Grafana/Prometheus attached to the same probe `/metrics` | only if SQLite analytics aren't enough |

## 10. Relationship to existing code

- **`tailtop/agent/fleet_collect.sh`** — its logic is the Phase-0 vitals
  collector, ported to Go. The shell script can remain as a fallback / reference.
- **`tailtop`** — becomes a *client of the hub*. `vitals_poller.py` swaps its data
  source; the rest of the UI (cards, vitals/hardware panels, alert strip) is
  reused as-is and gains real history.
- **`lifelog`** — `store.py` is the basis for the hub's timeline; `collectors/`
  (network, plug, tailscale, ruview) feed the presence layer (Phase 3); the
  `TailscaleOnlineCollector` covers agentless devices from Phase 0.
- **`tailsnap`** — unaffected; remains the print-and-exit snapshot tool.

## 11. Open questions & risks

- **Probe self-update.** *Resolved:* upgrades are an **operator-run idempotent
  installer** — install to a versioned path (`/usr/local/bin/tailprobe-<ver>`),
  atomically swap a `tailprobe` symlink, `systemctl restart` (instant rollback by
  re-pointing). A hub-driven "push new binary" step is **rejected**: it would
  reintroduce a control plane and violate the §3 no-C2 invariant. The hub only
  pulls.
- **Clock skew.** Devices timestamp their own samples; the hub also stamps
  receipt. Decide which is authoritative for the timeline (lean hub-receipt for
  ordering, keep device `collected_at` for accuracy).
- **macOS/Windows vitals parity.** The vitals collector is Linux-shaped
  (`/proc`, `/sys`, `vcgencmd`). Phase 4 needs platform-specific reads; the
  `Collector` interface must not assume Linux.
- **SQLite write volume.** ~20 devices × 30 s × many metrics is fine, but confirm
  rollup/retention keeps the DB bounded over months.
- **ArtPC on Tailscale.** *Resolved:* ArtPC is **not** on the tailnet (canonical
  infra doc lists only the direct-ethernet `192.168.100.2`, no `100.x`). It is a
  Phase 4 Windows target, scraped by the hub over the direct link
  (`192.168.100.1` ↔ `192.168.100.2`), not Tailscale.
- **Names.** `tailprobe` / `tailhub` are provisional.

## 12. Phase 0 — validated specifics (from parallel spikes, 2026-06-07)

Four read-only investigation agents validated this design against the codebase
and the live fleet. Concretions and corrections that feed the Phase 0 plan:

**Fleet — Phase 0 install set is 8 arm64 Linux SBCs** (one build covers all):

| Host | `100.x` | Board |
|---|---|---|
| `fastclock` | 100.78.29.28 | Raspberry Pi (arm64) |
| `slowclock` | 100.107.135.128 | Raspberry Pi |
| `smallclock` | 100.99.148.91 | Raspberry Pi |
| `squareclock` | 100.118.12.74 | Raspberry Pi |
| `dashboard-ink-bed` | 100.90.45.73 | Pi Zero 2 W |
| `dashboard3eink` | 100.92.15.33 | Pi Zero 2 W |
| `plantdashboard` | 100.64.79.16 | Pi Zero 2 W |
| `nickv-orangepizero2w` | 100.79.94.56 | Orange Pi Zero 2 W (Allwinner H616 — no `vcgencmd`) |

Hub = Mac Studio `100.75.213.56`. Agentless (online/offline only): iPhone
`100.70.107.55` + 2 iPads. All targets are arm64 → a **single** build:
`CGO_ENABLED=0 GOOS=linux GOARCH=arm64 ./tool/go build -trimpath -ldflags='-s -w'
./cmd/tailprobe` (build via the repo's pinned `./tool/go`; no system Go on PATH).

**Probe (`cmd/tailprobe/`):** the vitals port is almost entirely pure-Go reads of
`/proc` + `/sys` + `x/sys/unix` (`Statfs`, `Uname`); only `vcgencmd get_throttled`
shells out (Broadcom only — Allwinner keeps the flags `false`, matching the
script). Reuse `hostinfo/` (model/kernel/OS), `util/lineiter` (`/proc` reader),
and `metrics`/`tsweb/varz` (Prometheus exposition writer). Bind via `client/local`
(see §6.1). Preserve the `app.running = null` (unknown, never false-critical)
contract. Acceptance shape = the existing `fleet_collect.sh` JSON (`schema:1`) and
fixtures `tailtop/tests/fixtures/vitals_*.json`.

**Hub (new `tailhub/` package):** reuse `lifelog/store.py` *idioms* (a sibling
store with 4 tables, not an in-place extension), `tailscale_status_json()`, and
`TailscaleOnlineCollector` (fleet discovery + agentless devices). Build it
**async** (httpx + `asyncio.gather`) so a dead probe times out in parallel instead
of stalling the cycle; wrap the `tailscale status` subprocess in `to_thread`.
**Enable SQLite WAL** (`journal_mode=WAL`, `synchronous=NORMAL`) — lifelog's
single non-WAL connection is unsafe for concurrent scheduler-writes + API-reads.
Main new code = the `/vitals` → narrow-metric-rows + events normalizers; the
retention/prune job is load-bearing and entirely new. New deps: `fastapi`,
`uvicorn`, `httpx`, `pydantic-settings`.

**tailtop repoint:** the swap is at the **collection layer only** —
`Vitals.from_collect_json` and every UI consumer stay intact because the probe
reproduces the exact `fleet_collect.sh` JSON. Add
`TailscaleClient.fetch_fleet(hub_url)` + one hub GET in
`vitals_poller.collect_round()`; keep the OpenSSH path as a fallback (§10). Hub
URL via `TAILTOP_HUB_URL` env + a `--hub-url` flag (no config system exists
today). **`/fleet` must emit each device's OS hostname as `host`** — the UI
remaps vitals→peer by `host_name` (`pid_for`). Tests to update:
`tailtop/tests/test_vitals_poller.py`, `test_vitals_app.py`.

**Deploy + ACL — transport correction (important):** tailtop does **not** use
`tailscale ssh` for collection; it uses key-based **OpenSSH**
(`ssh -i ~/.ssh/id_ed25519 -o BatchMode=yes`) to the **LAN hostname**,
deliberately avoiding `100.x` (Tailscale SSH intercepts port 22 and demands
browser auth, so OpenSSH-to-`100.x` hangs). The Phase 0 installer mirrors this:
stream the binary over OpenSSH stdin (`cat > … && sudo install -m0755 …`), drop a
**system** systemd unit (`DynamicUser=yes`, `SupplementaryGroups=video`,
`After=tailscaled.service`, retry-bind), `systemctl enable --now`, then verify by
curling the probe's `100.x` from the hub. ACL: tag-based — allow only
`tag:tailhub` → `tag:tailprobe:9100`. An optional `ssh` ACL stanza would unlock
`tailscale ssh`-over-`100.x` and remove the LAN dependency. The port (9100) must
agree across probe `--port`, ACL `dst`, hub scraper, and verify-curl.

**Phase 0 risks to plan around:** (1) **passwordless sudo** on each Pi is required
at install time (root for `/usr/local/bin` + systemd + `enable`); verify it.
(2) The three dashboard Pis' SSH user is `nickv2026`; the existing tailtop
`USER_MAP` omits them (falls back to `""`) — the installer needs an explicit
per-host user map. (3) **Bind-before-`tailscaled` race** — the probe must
retry-bind, not exit, or systemd flaps it. (4) Self-update stays operator-run
(versioned symlink), never a hub push (§3).

---

*Companion context: `tailtop/README.md` (existing fleet vitals),
`notes/concept-and-findings.md` (lifelog concept + privacy posture),
`lifelog/README.md` (collectors + SQLite timeline).*
