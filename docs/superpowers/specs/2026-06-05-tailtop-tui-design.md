# tailtop — Design Spec

**Status:** Approved direction (brainstorm complete)
**Date:** 2026-06-05
**Owner:** nickv

---

## 1. Summary

`tailtop` is a terminal UI for Tailscale — a second front-end to the
`tailscaled` daemon already running on the machine (the same daemon the
official GUI uses). It mirrors the macOS app's information at first, then
improves on it with terminal-native strengths: keyboard-first control, a
command palette, live network visibility, and a strong visual identity.

It ships with **three modes**, each tuned to a single intent. `Tab` cycles
between them; **Comfort** is the default.

| Mode | Intent | View | Theme | Verbs |
|------|--------|------|-------|-------|
| **Comfort** | manage | List (Mac-app parity) | Studio | read + safe writes |
| **Cockpit** | operate | Cards (live tiles) | Mission Control | all verbs + ⌘P palette |
| **Observatory** | observe | Topology graph | Brutalist | read-only |

The name evokes `htop` for your tailnet.

## 2. Goals

- A genuinely usable daily driver for inspecting and controlling a tailnet
  from the terminal.
- Visual quality on par with polished TUIs (Bagels as the north star for
  look and feel).
- Surface information the official GUI hides: direct vs DERP-relayed paths,
  per-peer latency, RX/TX rates, relay regions.
- Keyboard-first; mouse optional.
- Zero new privileges — reuse the running daemon, install nothing on the
  Tailscale side.

## 3. Non-Goals

- **Not** a replacement for `tailscaled`. We do not run our own daemon, TUN,
  or system extension. No root.
- **Not** a pixel-perfect clone of the macOS app's chrome. We take its
  information architecture as a starting point, not its exact visuals.
- **Not** shipping the LocalAPI socket integration in v1 (see §10, Future).
- **No** Windows-native concerns in v1; target macOS/Linux terminals first.

## 4. Constraints & Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | Python 3.13 | Textual + Plotext ecosystem; fast to iterate. |
| TUI framework | Textual | Real layout engine, widgets, keybinds, built-in command palette, `.tcss` theming, snapshot testing. |
| Charts | Plotext | Terminal sparklines / line charts for ping + traffic. |
| Visual reference | Bagels (inspiration only) | Bagels is **GPL-3**. We write our own code and borrow the aesthetic only — no source copied. |
| Data source | Shell out to the `tailscale` CLI | Simple, official, robust, already installed. Wrapped behind a thin data layer so it can be swapped later. |
| v1 action scope | **All verbs** | ping, copy IP, netcheck, whois, set/clear exit node, send file, ssh, funnel, serve, lock. |
| Packaging | `uv` + `pyproject.toml` | Self-contained Python project. |
| Location | `tailtop/` at repo root | Playground sibling to the Go code; not wired into the Go build. |

## 5. Architecture

Three layers. The **data layer is the only code that knows the CLI exists**;
everything above it consumes typed models. That boundary is what allows a
later swap to the LocalAPI socket without touching the UI.

```
┌─ UI layer ───────────────────────────────────────────────┐
│ tailtop/app.py  ·  modes/  ·  widgets/                    │
│ Mode manager (Tab cycles) · reacts to AppState · no CLI   │
└──────────────────────────▲───────────────────────────────┘
                           │  reactive AppState
                           │  (peers, rates, ping buffers)
┌─ Data layer ─────────────┴───────────────────────────────┐
│ tailtop/data/  — the only CLI-aware code                  │
│ TailscaleClient · models.py · poller.py · actions.py      │
│ Returns typed dataclasses, never raw JSON                 │
└──────────────────────────▲───────────────────────────────┘
                           │  subprocess + JSON
┌─ tailscale CLI ──────────┴───────────────────────────────┐
│ status --json · ping · netcheck · whois · set · file ·   │
│ ssh · funnel · serve · lock   →  talks to tailscaled      │
└──────────────────────────────────────────────────────────┘
```

### Data layer (`tailtop/data/`)
- `client.py` — `TailscaleClient`: runs subprocesses, parses output, applies
  timeouts, normalizes errors.
- `models.py` — typed dataclasses: `Peer`, `Status`, `NetCheck`, `PingResult`,
  etc.
- `poller.py` — async refresh loop; cadence follows the active mode.
- `actions.py` — maps each verb to its CLI command; the only place mutations
  are constructed.

### UI layer (`tailtop/`)
- `app.py` — Textual `App`, mode manager, global keybinds, command palette.
- `state.py` — reactive `AppState` plus per-peer ring buffers for rate history.
- `modes/comfort.py | cockpit.py | observatory.py` — each a Screen composing
  shared widgets + its theme.
- `widgets/` — `DeviceList`, `DeviceCard`, `DetailPane`, `Sparkline`,
  `Topology`, `PingGraph`, `CommandPalette`, `StatusBar`.

### Theming (`tailtop/themes/`)
- `studio.tcss`, `mission_control.tcss`, `brutalist.tcss` — one Textual-CSS
  file per theme. Bound to mode in v1; structured so themes can detach into a
  free-choice setting later.

## 6. Data Flow

1. Poller runs `tailscale status --json` on a cadence set by the active mode:
   **2 s** (Comfort), **1 s** (Cockpit), **250 ms** (Observatory, for
   animation; status itself may poll slower with interpolation).
2. Output is parsed into `Status` + `Peer` models and written to the reactive
   `AppState`. Widgets observe `AppState` and re-render.
3. **Rates / sparklines:** `status --json` carries cumulative `RxBytes` /
   `TxBytes` per peer. The data layer diffs consecutive polls → bytes/sec →
   per-peer ring buffer → `Sparkline`.
4. **Ping graph:** `tailscale ping <ip>` repeated; parse latency and
   direct-vs-DERP; feed Plotext.
5. **Actions:** a keybind or palette entry calls the data layer, which shells
   out, then triggers a refresh.

## 7. Modes (detail)

### Comfort — *manage*
- **View:** List, mirroring the Mac app (sidebar tabs Devices / Exit Nodes /
  Stats, device rows with online dot + name + IP, detail pane below).
- **Theme:** Studio — soft, clean, Bagels-inspired default.
- **Verbs:** ping · send file · set/clear exit node · copy IP.
- **Refresh:** 2 s. **Density:** spacious.
- **Why:** "Just opened my laptop, want to glance at my tailnet." Landing mode.

### Cockpit — *operate*
- **View:** Cards — one live tile per peer with RX/TX sparkline + connection
  type (direct / DERP·region) + latency.
- **Theme:** Mission Control — accent borders, ambers, ANSI greens.
- **Verbs:** all of Comfort + ssh · funnel · serve · lock · continuous ping ·
  netcheck · whois.
- **Refresh:** 1 s, sparklines live. **Density:** compact.
- **Palette:** ⌘P / Ctrl-P opens the command palette, always.
- **Why:** "Something feels off, or I'm setting up a new device." Power-user
  identity; where the new verbs live.

### Observatory — *observe*
- **View:** Topology graph — nodes for peers, edges colored green (direct) vs
  amber (DERP-relayed), animated; a global RX/TX traffic strip beneath.
- **Theme:** Brutalist — heavy borders, big numbers, restrained palette.
- **Verbs:** read-only; navigation only.
- **Refresh:** continuous animation, 250 ms ticks. **Density:** cinematic.
- **Why:** "What's actually happening on my tailnet right now?" The cool
  screen; looks great on a side monitor.

## 8. Verbs → CLI mapping (all in v1)

| Verb | Command |
|------|---------|
| ping | `tailscale ping <ip>` |
| copy IP | clipboard via OSC52 (works over SSH) |
| netcheck | `tailscale netcheck` |
| whois | `tailscale whois <ip>` |
| set / clear exit node | `tailscale set --exit-node=<ip>` / `--exit-node=` |
| send file | `tailscale file cp <path> <peer>:` |
| ssh | `tailscale ssh <user>@<host>` — suspend TUI, hand over terminal, resume on exit |
| funnel | `tailscale funnel <port>` (+ status) |
| serve | `tailscale serve …` |
| lock | `tailscale lock status` + signing actions |

## 9. Interaction & Error Handling

### Keyboard
`Tab` cycle modes · `j/k` + arrows navigate · `/` filter · `Enter`
detail/primary action · `?` help overlay · `⌘P` / `Ctrl-P` command palette ·
single-letter verbs in Cockpit (`s` ssh, `f` send, `e` exit-node, `p` ping,
`F` funnel, …).

### Error & empty states
- `tailscale` binary missing → friendly guidance with install hint.
- Daemon not running / socket unreachable → "daemon not running" state.
- Logged out / not connected → reflect the disconnected state honestly.
- Every CLI call wrapped with a timeout; failures surface as a toast with
  stderr — never a crash.
- Mutating verbs confirm before firing.

## 10. Testing

- **Data layer:** capture real `tailscale status --json` (and friends) as
  fixtures; assert parsing into models; subprocess mocked.
- **Widgets:** Textual snapshot testing — each mode rendered against a fixture
  `AppState`.
- **Actions:** assert the correct command string is constructed; mutating
  commands never actually run in tests.

## 11. Module Layout

```
tailtop/
  pyproject.toml
  tailtop/
    __init__.py
    app.py            # Textual App, mode manager, global keybinds
    state.py          # reactive AppState, per-peer ring buffers
    data/
      client.py       # TailscaleClient (CLI wrapper)
      models.py       # Peer, Status, NetCheck, PingResult
      poller.py       # async refresh loop
      actions.py      # verb → command construction
    modes/
      comfort.py
      cockpit.py
      observatory.py
    widgets/
      device_list.py  device_card.py  detail_pane.py
      sparkline.py    topology.py     ping_graph.py
      palette.py      status_bar.py
    themes/
      studio.tcss  mission_control.tcss  brutalist.tcss
  tests/
    fixtures/         # captured tailscale JSON
    test_models.py
    test_widgets.py
```

## 12. Future (post-v1)

- LocalAPI socket integration for richer, streaming data (the data-layer
  boundary makes this a drop-in).
- Detach themes from modes — free choice of any view × any theme.
- Additional themes (CRT, Cozy).
- Multi-account / tailnet switching.
- Config file for default mode, cadences, keybindings.

## 13. Open Questions

None blocking. The data-layer abstraction defers the only significant
architectural fork (CLI vs LocalAPI) to a later, non-breaking change.
