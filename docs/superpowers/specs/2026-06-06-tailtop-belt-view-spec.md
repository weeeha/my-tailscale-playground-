# tailtop — Belt View Design Spec

**Status:** Approved direction (brainstorm complete)
**Date:** 2026-06-06
**Owner:** nickv
**Related:** [2026-06-05-tailtop-tui-design.md](2026-06-05-tailtop-tui-design.md) · web reference: `networkio-preview.vercel.app/belt-views-v2.html`, `/the-base.html`

---

## 1. Summary

Add a **belt-style topology visualization** to tailtop — a hub-and-spoke
diagram where each peer is connected to the local node by an animated
dual-lane conveyor "belt." Lane width, tread speed, and tread direction
make traffic *physically visible*: busy peers have fast-marching treads,
idle peers freeze, offline peers don't draw a belt at all.

Shipped in **two phases**:

1. **`BeltView` widget** — reusable widget that renders the belts. Two
   layouts: **Hub** (radial) and **Main Bus** (horizontal trunk).
2. **`TheBase` mode** — a fourth top-level mode (alongside Comfort,
   Cockpit, Observatory) that wraps the belt widget in dashboard chrome:
   tailnet header, alert strip, primary device panel.

The belt is the centerpiece. Surrounding mode chrome supports it.

## 2. Goals

- Make tailnet traffic *legible at a glance* — heavy peers should be
  obvious without reading numbers.
- Give tailtop a distinctive, recognizable visualization that other
  network TUIs don't have.
- Reuse existing data infrastructure (`Status`, `RateHistory`,
  `app.selected_peer_id`) — no new data plumbing.
- Land Phase 1 as a self-contained widget so it can be embedded in
  Cockpit or Observatory later if useful.

## 3. Non-Goals

- **Not** Grid layout in v1. Web reference shows Hub / Bus / Grid; we
  ship Hub + Bus and revisit Grid only if asked.
- **Not** a network *graph* — no peer-to-peer edges. All belts radiate
  from the local node. (Tailscale is point-to-point, so this matches
  reality.)
- **Not** historical playback — belts show *now*, not the last hour.
  Sparklines belong elsewhere (Cockpit tiles).
- **Not** mouse interaction in v1 — keyboard only (selection, layout
  toggle, mode entry).
- **Not** replacing the existing topology dataclass
  ([tailtop/widgets/topology.py](../../../tailtop/tailtop/widgets/topology.py)) —
  the belt widget consumes the same `Status`, but renders independently.

## 4. Constraints & Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Visual aesthetic | **Industrial dual-lane** (Option B) | Faithful to the web reference; only option that survives "is this a belt?". Studio (Option A) reduced it to a wire; Particle (Option C) abandoned the belt metaphor. |
| Layouts in v1 | Hub + Main Bus, toggleable | Hub is iconic for ≤8 peers; Bus scales horizontally for unlimited peers. Grid deferred. |
| Animation | Speed-modulated tread, separate ~10 Hz tick | Tread visibly marches; speed scales with bandwidth. Cheap to render (~80×24 redraw budget); cadence is independent of the 2 s data poll so visual smoothness ≠ poll cost. |
| Hub centerpiece | `status.self_peer` | The local node is always the hub. Multi-tailnet is not supported by `tailscale status` anyway. |
| Peer selection | All online peers (DIRECT + DERP + IDLE). Offline counted in a badge. | Offline peers as ghosted belts would clutter the viz; a `+N offline` badge preserves the count without noise. |
| Hub slot count | Fixed 8-slot ring (N, NE, E, SE, S, SW, W, NW) | Predictable geometry, fits in 60×20. Overflow goes to `+N more` chip. |
| Slot assignment | Bandwidth-priority, sticky | Highest-rate peers take cardinal slots first (N→E→W→S then diagonals). Sticky for several seconds to prevent flicker on rate jitter. |
| Bus orientation | Horizontal trunk, peers branch alternating top/bottom | Densest packing for wide terminals; trunk auto-scrolls if peers > viewport. |
| Lane → data | In-lane = RX (peer → hub), Out-lane = TX (hub → peer) | Matches the hub's frame of reference. Arrow direction reinforces "into me" / "out of me". |
| Intensity tiers | Light < 100 KB/s · Busy 100 KB/s–5 MB/s · Heavy > 5 MB/s | Round thresholds; user can tune in a follow-up. Tier sets tread brightness and color token. |
| Conn-type styling | DIRECT solid · DERP dashed + `DERP·xxx` tag · IDLE ghosted | Reuses `Peer.conn_type` and `Peer.relay_label`. |
| Selection model | Reads/writes `app.selected_peer_id` | Already established by `ComfortMode`; selection is shared across modes. |
| Theme tokens | New `belt-*` tokens added to all three themes | Lane base color, tread heavy/busy/light, offline, ghost, divider. Defined in `base.tcss` with overrides per theme. |
| Narrow terminal fallback | Auto-degrade Hub → Bus below 60 cols or 20 rows | Hub needs minimum size for the 8-slot ring; Bus tolerates anything ≥40 cols. |
| Mode keybinding | `Tab` cycles through 4 modes now (Comfort → Cockpit → Observatory → TheBase) | Same Tab loop as the existing 3 modes. Letter shortcut TBD with user. |

## 5. Architecture

```
tailtop/tailtop/widgets/
  belt.py              # BeltView widget (Phase 1)
    ├── BeltView          # Textual widget; takes Status + RateHistory
    ├── HubLayout         # 8-slot radial geometry
    ├── BusLayout         # horizontal trunk geometry
    ├── BeltRenderer      # converts geometry → character buffer
    └── TreadAnimator     # 10 Hz tick, advances tread positions

tailtop/tailtop/modes/
  the_base.py          # TheBase mode (Phase 2)
    └── TheBaseMode       # composes BeltView + header + alerts + detail
```

`BeltView` is dumb-ish: it receives a `Status`, a `RateHistory`, a layout
mode (`"hub" | "bus"`), and a selected peer id. It owns the animation
timer. It does **not** know about modes, alerts, or detail panels.

`TheBaseMode` is composition: it lays out `BeltView` in the center, with
a header row, an optional alert strip, and a detail pane that mirrors
the comfort-mode pattern. It does not draw belts itself.

## 6. Data flow

```
poller (2 s)
   └─► Status snapshot ─► RateHistory ─► TheBaseMode.update_data(...)
                                              │
                                              ├─► header (counts, aggregate ↓/↑)
                                              ├─► alert strip (offline, expiring keys)
                                              ├─► BeltView (peers, rates, conn types)
                                              │     └─► HubLayout / BusLayout
                                              │           └─► BeltRenderer (per-frame)
                                              │                  ▲
                                              │       TreadAnimator (10 Hz) ──┘
                                              └─► DetailPane (selected peer)
```

Two independent clocks: **2 s data poll** and **~10 Hz animation tick**.
The animation tick only re-renders belt cells (no data fetch). Rates
between polls are frozen — tread speeds change in steps every 2 s.

## 7. Rendering contract

### 7.1 Hub layout

- Center: 3-line hub card (hostname, aggregate ↓/↑, online/total).
- 8 slots around the hub (N, NE, E, SE, S, SW, W, NW), 3 lines tall
  each.
- Each slot draws: a peer card (hostname truncated to 14 chars,
  rate, conn label) + a belt segment connecting it to the hub.
- Belt segment: dual-lane (in + out) with center divider, arc corners
  via `╭╮╰╯` and `╱╲`, tread arrows `▲ ▼ ◀ ▶`.
- Overflow: `+N more` chip below the hub.
- Minimum size: 60 × 20. Smaller → degrade to Bus.

### 7.2 Bus layout

- Hub anchored to the left edge as a 3-line card.
- Horizontal trunk extends right; peers branch off alternating top/bottom.
- Branch lanes are vertical mini-belts (same dual-lane treatment).
- Trunk auto-scrolls horizontally; hub stays pinned on the left.
- Minimum size: 40 × 12.

### 7.3 Tread animation

Per lane, per tick:

```
cells_per_second = clamp(rate_bps / threshold_busy_bps, 0.67, 16.7)
                   # 1.5 s/cell at lowest, 0.06 s/cell at heavy
position += cells_per_second * dt
```

Tread glyph is redrawn at the integer cell of `position`. Lane base
stays put. Idle (rate ≈ 0) freezes tread, dims to ghost tier. Offline
draws no lane.

### 7.4 Selection

- Selected belt: full tier color.
- Other belts: dimmed to ~40% (via theme token).
- Hub card carries a small focus indicator.

## 8. Themes & tokens

New tokens added to [tailtop/themes/base.tcss](../../../tailtop/tailtop/themes/base.tcss):

| Token | Purpose |
|-------|---------|
| `--belt-lane` | Belt lane base color (DIRECT) |
| `--belt-lane-derp` | Belt lane base color (DERP) — dashed |
| `--belt-lane-idle` | Lane color when no traffic |
| `--belt-lane-offline` | (Unused — offline draws nothing — reserved) |
| `--belt-tread-heavy` | Tread color, > 5 MB/s |
| `--belt-tread-busy` | Tread color, 100 KB/s–5 MB/s |
| `--belt-tread-light` | Tread color, < 100 KB/s |
| `--belt-divider` | Center divider between in/out lanes |
| `--belt-dim` | Multiplier (text-tint) applied to non-selected belts |

Each of `studio.tcss`, `mission_control.tcss`, `brutalist.tcss`
provides its own values. Studio is muted (designer-quiet); Mission
Control is high-saturation (operator-now); Brutalist is hard contrast.

## 9. Interaction

- `Tab` — cycle modes (now 4-way).
- `h` / `b` (inside TheBase) — Hub / Bus layout toggle.
- `↑ / ↓` — move selection to next/previous peer in current layout
  order (Hub: clockwise from N; Bus: left-to-right).
- `Enter` — open detail pane focus (no-op if already focused).
- Verbs (ping, copy IP, etc.) operate on `app.selected_peer_id` just
  like in Comfort.

## 10. Edge cases & error states

| Condition | Behavior |
|-----------|----------|
| Not connected (`backend_state ≠ "Running"`) | Belt area shows centered "tailscaled not running" placeholder; header shows current state. |
| 0 peers | Hub card alone, with a "your tailnet is empty" hint. |
| 1 peer | Drawn in the N slot; rest of ring empty. |
| > 8 peers (Hub) | Top 8 by rate take slots; `+N more` chip below. |
| Terminal < 60 × 20 | Auto-switch to Bus; show toast "Hub needs ≥60 cols". |
| Terminal < 40 × 12 | Show "Resize to use The Base" placeholder. |
| Peer goes offline mid-session | Lane fades out over 1 s; peer moves to offline badge count. |
| Peer joins mid-session | New belt fades in over 1 s; slot assigned by current bandwidth ranking. |
| Rate spikes briefly | Tread speed jumps; sticky-slot logic prevents the peer from immediately leaping to a better slot for ≥3 s. |

## 11. Testing

- **Unit tests** for `HubLayout.assign_slots(...)` — bandwidth priority,
  sticky behavior, cardinal-first ordering.
- **Unit tests** for `TreadAnimator.tick(dt, rate)` — speed clamping,
  position wrap-around, idle freeze.
- **Snapshot tests** for `BeltView` against fixtures in
  [tests/fixtures/status.json](../../../tailtop/tests/fixtures/status.json):
  - 0 peers, 1 peer, 8 peers, 12 peers (overflow).
  - Mix of DIRECT, DERP, IDLE, OFFLINE.
  - Both layouts.
- **Live smoke** in CI: render against a synthetic `Status` for 5
  animation ticks; assert no exceptions, glyph budget within bounds.

## 12. Module layout

```
tailtop/tailtop/
  widgets/
    belt.py                 # NEW — BeltView + layouts + renderer + animator
  modes/
    the_base.py             # NEW — TheBaseMode
    __init__.py             # UPDATED — register TheBaseMode
  themes/
    base.tcss               # UPDATED — add belt-* tokens
    studio.tcss             # UPDATED — token values
    mission_control.tcss    # UPDATED — token values
    brutalist.tcss          # UPDATED — token values
  app.py                    # UPDATED — Tab cycle includes TheBase

tests/
  test_belt_layout.py       # NEW — slot assignment, sticky logic
  test_belt_animator.py     # NEW — tread tick math
  test_the_base.py          # NEW — mode composition + selection wiring
```

## 13. Future (post-v1)

- **Grid layout** — third layout option from the web reference.
- **Drill-in** — Enter on a belt opens a per-peer detail overlay with
  RTT sparkline (Plotext) and recent path changes.
- **Recording / playback** — record 60 s of rates, scrub backwards.
- **Multi-tailnet** — once `tailscale switch` is a verb, the hub
  identifies the current tailnet visually.
- **User-tunable thresholds** — light/busy/heavy boundaries in settings.
- **Sound** (very optional) — a soft tick on heavy traffic spikes.

## 14. Open questions

- **Letter shortcut for TheBase** — Comfort/Cockpit/Observatory don't
  currently have letter shortcuts in the spec I read; if added,
  `b` for TheBase (or `4`) — TBD with user.
- **Threshold values** — 100 KB/s and 5 MB/s are guesses. May need
  tuning against a real busy tailnet.
- **Sticky slot duration** — 3 s feels right; subject to feel-test in
  the live widget.
- **Aggregate ↓/↑ in hub card** — sum of all peer rates, or just
  direct peers? (Spec assumes "all online" — confirm.)
- **Should the hub card itself participate in selection?** I.e. can you
  select "self" and see local-side detail? Currently no.

---

## Changelog

- 2026-06-06 — initial draft from brainstorm.
