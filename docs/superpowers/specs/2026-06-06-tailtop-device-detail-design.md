# tailtop — Device Detail Screen (Comfort mode) — Design Spec

**Status:** Approved direction (brainstorm complete)
**Date:** 2026-06-06
**Extends:** `2026-06-05-tailtop-tui-design.md`
**Owner:** nickv

---

## 1. Summary

Enrich **Comfort mode's** right-hand detail so that selecting a device opens a
lazydocker-style, three-column screen: **device list │ info panels │ live
charts**. It mirrors the official macOS app's detail (addresses, ping graph,
details) and the web admin's Machine Details (routes, endpoints, attributes,
connectivity, relay latency), within the limits of what the **local** daemon
exposes.

The device list and Comfort's overall shape are unchanged. Only the detail pane
is replaced.

## 2. Goals

- A genuinely useful, dense per-device inspector — the "open a device and see
  everything" screen.
- Two **live charts**: latency (active ping RTT) and throughput (rx/tx).
- Honest data: show what the local CLI actually provides; **hide** (never fake)
  sections that aren't available for a given peer.
- Fix peer display names so iOS/`localhost` devices show their real name.

## 3. Non-Goals

- **No control-plane admin actions** (rename, edit ACL tags, remove, share).
  Those require the Tailscale HTTP API + an API key, not the local CLI. The
  CLI-accessible actions (SSH, exit-node, send file) already exist as verbs.
- No changes to Cockpit or Observatory.
- No new third-party dependencies beyond **plotext** (already a project dep).

## 4. The self-vs-peer data reality

The web admin aggregates data server-side; the local daemon has the **full
picture for *this* machine** and a **smaller view of remote peers**. Verified
against live `status --json`:

| Section | Local source | self | peer |
|---|---|:--:|:--:|
| IPv4/IPv6, domains, path, OS | `status` | ✅ | ✅ |
| Routes (`AllowedIPs`) | `status` | ✅ | ✅ |
| Created / key expiry / last handshake | `status` | ✅ | ✅ |
| ID / node key | `status` | ✅ | ✅ |
| Exit-node / tags | `status` | ✅ | ✅ |
| Endpoints (`Addrs`) | `status` | ✅ | ❌ (null) |
| Attributes (`CapMap`) | `status` | ✅ | ❌ (null) |
| Client connectivity (UDP/UPnP/PCP/NAT-PMP) | `netcheck` | ✅ | ❌ (self only) |
| Relay latency table (per DERP region) | `netcheck` | ✅ | ❌ (self only) |

**Principle: rich for every peer, richest for self.** Sections without data for
the selected peer are omitted, not shown empty.

## 5. Layout (Option A — three columns)

```
┌ Devices ───────┬─ Detail: <name> ──────────────────────────────────────┐
│ ● api-prod-1   │ ┌ Status ─────────────┐   ┌ Latency · ping RTT ──────┐ │
│ ● fastclock ◂  │ │ name / online / path│   │   plotext line chart      │ │
│ ● mac-studio   │ │ MagicDNS IPv4 IPv6   │   │   72 ms · direct          │ │
│ ● bastion-nyc  │ │ OS / ID              │   └───────────────────────────┘ │
│ ○ legacy-win   │ └─────────────────────┘   ┌ Throughput · rx/tx ───────┐ │
│                │ ┌ Network ────────────┐   │   rx/tx bars or chart      │ │
│                │ │ routes / endpoint    │   │   18 KB/s · 13 KB/s        │ │
│                │ │ created / last write │   └───────────────────────────┘ │
│                │ │ (+endpoints,attrs:self)│  ┌ Connection quality ──────┐ │
│                │ └─────────────────────┘   │ direct/DERP·region active │ │
│                │ ┌ Exit · Tags · Key ──┐   │ (+UDP/UPnP/PCP/relay:self) │ │
│                │ │ exit-node / tags/key │   └───────────────────────────┘ │
│                │ └─────────────────────┘   send file · f                  │
└────────────────┴───────────────────────────────────────────────────────┘
```

- **Middle (info panels):** Status, Network, Exit·Tags·Key. The Network and
  Connection-quality panels gain extra rows when the selected peer is **self**
  (endpoints list, attributes, connectivity flags, relay-latency table).
- **Right (charts):** Latency (top), Throughput (below), and a **Connection
  quality** summary. A `send file · f` affordance sits where the macOS app puts
  its Taildrop drop-zone.
- Responsiveness: fixed three-column for v1 (matches the wireframe). If the
  terminal is too narrow, the charts column wraps under the info column
  (CSS-grid reflow); full responsive A↔B is a fast-follow, not v1.

## 6. Components

### `LatencyProbe` (`tailtop/data/latency.py`)
- Owns an async task that pings the **currently selected** peer (`tailscale
  ping <ip>`, parsed for RTT + direct/DERP) about once per second.
- Maintains a bounded RTT ring buffer (e.g. 60 samples) per peer id.
- `retarget(peer)` cancels and restarts for the new selection; stops when the
  detail isn't visible (Comfort inactive).
- Pure parse of ping output (`… in NNms`, `via DERP(region)`) is unit-tested.

### `netcheck` cache (extends `TailscaleClient`)
- `client.netcheck()` already exists. The detail caches the last result and
  refreshes lazily (it's slow, ~seconds) — only consulted for the **self**
  panels.

### `DeviceDetail` widget (`tailtop/widgets/detail_pane.py`, rewritten)
- Replaces the single-Static pane with a composite: info panels (each a
  bordered `Static`) + chart widgets.
- `update_peer(peer, rates, latency, netcheck_self)` renders all panels; helper
  methods build each panel and **skip** panels whose data is absent.

### Charts
- **Latency:** render the RTT ring buffer with **plotext** into a `Static`
  (axis + line, like the wireframe). Falls back to a block sparkline if plotext
  output doesn't fit the available width.
- **Throughput:** reuse `state.sparkline` rx/tx from existing rate buffers (no
  new pinging needed).

### Model change (`tailtop/data/models.py`)
- Add fields: `addrs: list[str]` (endpoints), `peerapi: list[str]`,
  `cap_map: dict` (raw attributes, self only). Parse from `status`.
- **Display name fix:** `Peer.name` prefers the MagicDNS label (first segment
  of `DNSName`) when `HostName` is empty or a generic value (`localhost`); the
  OS hostname becomes a secondary `(localhost)` annotation. This fixes the three
  `localhost` rows for iOS devices.

## 7. Data flow

1. Comfort selection → `app.selected_peer_id` (exists) → also calls
   `LatencyProbe.retarget(peer)`.
2. Each poll updates `Status` + rate buffers (exists). The detail re-renders
   from the current peer + rates + latency buffer.
3. The latency buffer updates independently (~1 Hz) from the probe, so the chart
   animates between status polls.
4. For self, `netcheck` is fetched once on first self-view and cached.

## 8. Error / empty states

- No selection → "Select a device" placeholder (exists).
- Ping failing (peer offline/unreachable) → latency chart shows "no response",
  not a crash.
- `netcheck` unavailable/slow → self panels that depend on it show "checking…"
  then fill in, or are omitted on failure.
- Offline peer → panels render from cached `status` fields; charts idle.

## 9. Testing

- **Latency parse:** canned `tailscale ping` outputs (direct + DERP + timeout)
  → RTT/relay extraction.
- **Name fix:** `HostName="localhost"`, `DNSName="ipad-air-5th-gen-wifi.…"` →
  `name == "ipad-air-5th-gen-wifi"`.
- **Model parse:** `addrs`/`peerapi`/`cap_map` populated for self, empty for
  peers (from fixture).
- **Render:** headless mount of `DeviceDetail` for a peer (subset panels) and
  for self (all panels) — no crash, expected panels present/absent.
- **Probe:** `retarget` swaps target; ring buffer accumulates.

## 10. Module deltas

```
tailtop/data/latency.py        # new: LatencyProbe + ping parse
tailtop/data/models.py         # +addrs, +peerapi, +cap_map, name fix
tailtop/widgets/detail_pane.py # rewritten: DeviceDetail composite
tailtop/widgets/charts.py      # new: latency_chart() / throughput helpers
tailtop/modes/comfort.py       # wire LatencyProbe + new layout
tailtop/themes/studio.tcss     # detail 3-column grid + panel styling
tests/test_latency.py          # new
tests/test_models.py           # +name fix, +new fields
tests/test_detail.py           # new: render self vs peer
```

## 11. Open questions

None blocking. Full A↔B responsiveness and a netcheck-driven relay-latency
*bar chart* (vs table) are noted fast-follows.
