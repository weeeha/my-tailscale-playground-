# tailtop — Animations

**Status:** Brainstorm in progress — direction approved per effect, open
questions pending. No pixels yet.
**Date:** 2026-06-06
**Owner:** nickv
**Source libraries:**
[terminaltexteffects](https://github.com/ChrisBuilds/terminaltexteffects)
(TTE), [lolcat](https://github.com/busyloop/lolcat),
[speedtest-net](https://www.npmjs.com/package/speedtest-net) (visual
reference, not a dependency).

Sister doc to [2026-06-05-tailtop-tui-design.md](2026-06-05-tailtop-tui-design.md).

---

## 1. Summary

Three TTE effects are placed against specific moments in the app. Three
more effects + the lolcat rainbow style are saved as an unplaced library
for future use. A separate visual reference (the `speedtest-net` CLI tool)
gives us a coherent display language for live metrics in Cockpit.

## 2. Placed effects

| Effect | Where | When it fires |
|---|---|---|
| **Beams** | Layout assemble on first-mount per mode | Once per session per mode — at launch (Comfort first-mount) and the first time you `Tab` into Cockpit and Observatory. After that, instant. |
| **Print** | Boot status line | Once per launch only. Streams "Connecting to tailscaled…" → "Connected. N peers, M online." under the assembled layout. |
| **Burn** | Error / disconnect states | Per-event. Fires when tailscaled drops, a peer goes offline, or a mutating action fails. Visual treatment decided case-by-case during implementation (see §5). |

**Boot sequence:** beams assemble Comfort's layout → print streams the
status line under it → app is ready.

## 3. Library (unplaced)

Shipped as available effects with documented APIs but no placement.
Wire in later when a moment is identified.

| Effect | Notes |
|---|---|
| **Sweep** | Horizontal wipe. Candidate future homes: mode transitions (`Tab` after the curtain-rise), `r` refresh, list re-sort, sparkline updates. |
| **Thunderstorm** | High-drama lightning/flash. Candidate future homes: catastrophic events (daemon down, all peers offline), exit-node toggle, funnel toggle. |
| **Lolcat gradient** | Rainbow HSV cycle applied to any string. **Not an animation** — a styling utility. Apply per-call; no theme integration. Candidate uses: easter eggs, success toasts, special command output. |
| **speedtest-net metric language** | See §4. A coherent display pattern for live measured numbers (Cockpit cards, `p`/`n` outputs). Not a single effect — a small set of conventions. |

## 4. Visual reference — speedtest-net

Two GIFs in [`refs/`](refs/) show the same `speedtest-net` CLI in two
visual modes:

- [`refs/speedtest-net-panel.gif`](refs/speedtest-net-panel.gif) — 3-col
  bordered panel, teal theme
- [`refs/speedtest-net-stacked.gif`](refs/speedtest-net-stacked.gif) —
  stacked vertical, dark-grey theme, braille spinner

### 4.1 Patterns to import

| Pattern | Description | Where it likely applies |
|---|---|---|
| **Numeric tween while measuring** | Value rolls up rapidly between samples (e.g. `75.6 → 170.7 → 172.3 Mbps`), then settles. Real-time, not pre-rendered. | Cockpit live throughput, `p` ping run, `n` netcheck |
| **Tri-state metric color** | Pending = dim + placeholder; active = accent (amber in panel mode); finalized = cool/muted. Reads at a glance which metric is "in flight." | Any live metric panel |
| **Bright digit, dim unit** | The value is the active color; the unit (`ms`, `Mbps`, `peers`) is muted and slightly smaller-feeling. | Every numeric display in Cockpit |
| **Braille spinner** | 4-state braille-dots character (`⠂ ⠁ ⠃ ⠄`) cycles next to a metric being measured. Alternative to tween when there's no intermediate signal. | Atomic actions (file send, exit-node toggle, lock check) |
| **Placeholder dashes** | `—+—` shown for empty/pending metric slots before measurement begins. Signals "this slot will have a value" without committing to one. | Empty Cockpit cards on first mount |

### 4.2 What we are *not* importing

- The bordered "panel" container itself — tailtop already has its own
  panel chrome from the design spec. We borrow the metric language, not
  the box.
- The literal speedtest workflow (3 sequential measurements). Our metrics
  fire on different cadences.
- The exact teal/amber palette. Color comes from the active theme
  (Studio / Mission Control / Brutalist).

## 5. Open questions

Proposed defaults — confirm or push back before pixels.

| # | Question | Proposed default | Status |
|---|---|---|---|
| 1 | Skippable? | Yes. Any keypress / pointer event cuts beams + print at boot and snaps to final state. | **resolved (accepted)** |
| 2 | Theme awareness | Beams + print pick up the active theme's accent. Burn picks up the theme's error color. Lolcat ignores the theme by design. speedtest-net patterns use theme-mapped accent (active) and muted (finalized) tokens. | **resolved (accepted)** |
| 3 | Burn default treatment | Theme-aware error color, scoped to the affected row/card, ~300ms ease-out, no flame glyphs (default-off). Override per error type only when there's a reason. | **resolved (accepted)** |
| 4 | Frame-capture path | Spike before pixels. | **resolved — see §6** |

## 6. Spike result — frame-capture path validated

Script at [`tailtop/spikes/tte_spike.py`](../../../tailtop/spikes/tte_spike.py),
results at [`tailtop/spikes/spike_results.txt`](../../../tailtop/spikes/spike_results.txt).

**Pipeline:** `TTE.Effect → str (ANSI) → rich.text.Text.from_ansi → Static.update`.
Headless Textual app driven by `set_interval(1/60, tick)`.

| Effect | Frames | Playback | Effective fps | Avg interval | p95 interval |
|---|---|---|---|---|---|
| Decrypt("TAILTOP") | 570 | 9.52s | 59.9 | 16.67 ms | 18.73 ms |
| Beams("Connected. 47 peers, 3 online.") | 165 | 2.77s | 59.6 | 16.67 ms | 17.06 ms |
| Print("Connecting to tailscaled…") | 30 | 0.52s | 58.0 | 16.67 ms | 17.19 ms |

### 6.1 Verdict

- ✅ **Textual is not the bottleneck.** 60fps sustained, p95 ≤19ms — comfortably under the 16.67ms frame budget at the average, well within human-perception smoothness at the worst case.
- ✅ **Color survives the bridge.** TTE emits 24-bit truecolor (`\x1b[38;2;R;G;Bm`); `Text.from_ansi` parses every char as its own span with full RGB preserved; round-trip render keeps the codes intact.
- ✅ **All three placed effects work.** Beams, Print, and Decrypt (a stand-in for Burn) all stream through the pipeline without error.
- ⚠️ **TTE paces itself.** The iterator sleeps between frames to hit its target fps. "Drain time" ≈ "playback time" (Beams = 3.3s, Print = 0.6s). Boot can't synchronously block on this.

### 6.2 Implications for boot sequence

Naive boot = `beams (3.3s) + print (0.6s)` ≈ 4s of blocked UI. Too slow.

**Fix:** run TTE iteration in a Textual `Worker` (thread=True), push frames into an `asyncio.Queue`, consume from the queue in a `set_interval` tick on the UI side. The UI stays responsive (input handled, palette mountable) while frames stream in. Skippable (open question #1) becomes trivial: cancel the worker + drain the queue + jump to final state.

For burn (error events), TTE drain happens on demand — the small frame count (Burn typically <100 frames) means <2s total, acceptable for a one-shot event.

### 6.3 Open follow-ups

- Tune per-effect config to reduce frame counts where useful (Beams default is generous; we can cut ~half without losing identity).
- Theme integration: TTE accepts `Color` objects in configs; we'll map active-theme accent / error tokens into each effect's `EffectConfig` at construction time.

## 7. Next step

Light implementation plan covering: (1) `TTERunner` widget — the worker
+ queue + Static driver — as the shared primitive, (2) boot sequence
wiring, (3) mode-mount beams hook, (4) error-state burn hook, (5)
speedtest-net metric pattern as a reusable Textual widget.
