# tailtop — Animations Implementation Plan

**Status:** Implemented. All 7 steps shipped; 61 tests pass.
**Date:** 2026-06-06
**Owner:** nickv
**Companion to:** [2026-06-06-tailtop-animations.md](2026-06-06-tailtop-animations.md)

---

## 1. Goal

Ship the three placed effects (beams, print, burn) and the speedtest-net
metric widget, wired into the boot sequence, mode mounts, and error states.
Save sweep/thunderstorm/lolcat as available-but-unplaced.

## 2. Approach

Three new widgets do all the work; everything else is wiring.

```
tailtop/widgets/
  tte_runner.py        ← shared primitive (worker + queue + Static driver)
  speedtest_metric.py  ← speedtest-net metric language as a reusable widget
  effect_library.py    ← factory + theme-aware config for each TTE effect
```

`TTERunner` is the only thing that talks to TTE. Modes, the app, and the
error system all use it through a small typed API.

## 3. Steps

### Step 1 — `TTERunner` widget (the primitive)

File: `tailtop/widgets/tte_runner.py`

Single widget responsible for:
- Accepting a `terminaltexteffects.effects.*` effect instance
- Running its iterator in a `Worker(thread=True)` so TTE's internal sleeps don't block the UI loop
- Pushing each yielded frame string into an `asyncio.Queue`
- Consuming from the queue on a `set_interval(1/60, _tick)` that calls `Static.update(Text.from_ansi(frame))`
- Handling skip: any unhandled key event from the parent or a `runner.skip()` call cancels the worker, drains the queue, and jumps to the effect's final frame string
- Emitting an `Animated.Finished` message when the queue drains naturally

Public surface (rough):
```python
class TTERunner(Static):
    def __init__(self, effect: BaseEffect, *, skippable: bool = True) -> None: ...
    def skip(self) -> None: ...        # jump to final
    class Finished(Message): ...        # bubbles when animation ends
```

Acceptance: the existing `tailtop/spikes/tte_spike.py` is rewritten to use
`TTERunner` instead of the inline driver, and still hits ≥58 fps with
≤20ms p95 across the three effects.

### Step 2 — `effect_library.py` (theme-aware configs)

File: `tailtop/widgets/effect_library.py`

A small factory module that returns TTE effects pre-configured with the
active theme's tokens. Keeps theme awareness out of `TTERunner` and out of
the call sites.

```python
def beams(text: str, theme: Theme) -> Beams: ...
def print_(text: str, theme: Theme) -> Print: ...
def burn(text: str, theme: Theme) -> Burn: ...
```

Mapping (resolves open Q2 + Q3):
- `beams` & `print_` — gradient/accent stops pulled from `theme.accent` and `theme.accent_dim`
- `burn` — character set forced to the no-flame variant; gradient pulled from `theme.error` → `theme.text_dim`; total frames capped to keep wall-clock ≤300ms (per Q3)
- `lolcat` (when used) — bypasses theme; HSV cycle is the whole point

Sweep, Thunderstorm, Decrypt, Matrix etc. live here too but are unused
on-mount (open library for future).

Acceptance: factory unit-tested across the three theme files (`studio.tcss`,
`mission_control.tcss`, `brutalist.tcss`) — assert the resolved gradient
stops match each theme's accent token.

### Step 3 — Boot sequence

Files: `tailtop/app.py` (modify), `tailtop/widgets/boot_overlay.py` (new)

`BootOverlay` is a transient screen mounted as the first child of `App` on
launch. It composes two stacked `TTERunner`s:
1. Beams assembling the Comfort layout silhouette (text = the rendered Comfort skeleton with `█`-block placeholders for live data)
2. Print streaming "Connecting to tailscaled… → Connected. N peers, M online." underneath, fed by the first poller tick

Sequencing:
- App `on_mount` mounts `BootOverlay`
- BootOverlay starts the beams runner immediately
- Poller's first `Status` message kicks off the print runner with the resolved status text
- When both runners emit `Finished` (or user hits any key — handled by overlay's `on_key`), overlay calls `self.remove()` and the live Comfort mode takes over

Skip behavior (Q1): overlay's `on_key` calls `.skip()` on both active runners and dismisses.

Acceptance: snapshot test of (a) mid-boot, (b) post-boot. App is interactive
during boot (palette mountable, Tab cyclable) — verified by Pilot test that
presses keys during the overlay and asserts they reach the underlying app.

### Step 4 — Mode-mount beams hook

Files: `tailtop/modes/base.py` (modify), each `modes/*.py` minimally

Add `first_mount_done: bool = False` to `ModeBase`. When `App` switches
to a mode whose flag is False, it briefly overlays a `TTERunner` with a
beams effect spanning the mode's compose tree (re-using the same silhouette
trick as boot), then flips the flag and removes the overlay.

Acceptance: Pilot test that Tabs through all three modes twice — first
visit shows the overlay, second visit is instant. Manual: visual check
that the beam direction reads as "assembling" not "destroying."

### Step 5 — Error-state burn hook

Files: `tailtop/widgets/device_card.py`, `device_list.py`, `topology.py`
(minimal touch), plus a new `tailtop/widgets/error_burn.py`

`ErrorBurn` is a one-shot widget that wraps the affected row/card content
and replaces it with a `TTERunner(burn(...))` for ~300ms before settling
on the error state markup.

Wired at three sites:
- `device_list.py` — when a peer transitions to `offline` in the poller diff
- `device_card.py` — same, scoped to a Cockpit card
- App-level — when `TailscaleError`/`TailscaleNotFound`/`TailscaleTimeout` from the data layer fires; burn the status bar's connection chip

Per-case overrides are added inline at each site only if the default feels
wrong; the default factory in `effect_library.py` should cover all three.

Acceptance: trigger each error site in tests (mocked poller transitions);
snapshot the post-burn state.

### Step 6 — `SpeedtestMetric` widget

File: `tailtop/widgets/speedtest_metric.py`

The speedtest-net visual language as a single reusable widget.

```python
class SpeedtestMetric(Static):
    label: str           # "Ping", "Download", "Upload", "Online peers", …
    unit: str = ""       # "ms", "Mbps", "peers", ""
    state: Literal["pending", "active", "finalized"] = "pending"
    value: float | int | None = None   # None → render placeholder dashes
    spinner_when_active: bool = False  # toggle: tween-roll vs braille-spinner
```

Renders the active theme's accent for `active`, muted accent for
`finalized`, dim for `pending`. Placeholder `—+—` while pending+no-spinner.
Braille spinner cycle while `active`+spinner_when_active. Bright digit +
dim unit by composing Rich `Text` with two styles.

Numeric tween: when `value` is set while `state == "active"`, the widget
animates the displayed number from the previous value to the new value
over the next ~250ms using `set_interval` and easing — independent of any
TTE machinery. (TTE doesn't do value-tween; this is hand-rolled.)

Used by:
- Cockpit cards (one `SpeedtestMetric` per live metric — rx, tx, ping, etc.)
- The result modal of `p` ping / `n` netcheck
- Status bar's "Online: N/M" chip

Acceptance: snapshot tests across all four states for each theme. Visual
check via `textual-dev`'s live console.

### Step 7 — Documentation & references

- Move `tailtop/spikes/tte_spike.py` into the test suite as a perf regression check
- Add a short `tailtop/docs/animations.md` (one page) that points to this plan + the spec, plus example usage of `TTERunner` and `SpeedtestMetric`
- Update `tailtop/README.md` Modes table to add an "Animations" column noting which effects fire where

## 4. Out of scope (this plan)

- Sweep, Thunderstorm, Decrypt placements — library entries only via `effect_library.py`; no wiring
- Lolcat — utility module, not used by default
- Theme transitions / animated theme swaps
- Animated chart transitions in plotext (separate problem)

## 5. Rollout order

1. Step 1 (TTERunner) — unblocks everything
2. Step 2 (effect_library) — unblocks 3, 4, 5
3. Step 6 (SpeedtestMetric) — independent of TTE; can run in parallel with 1/2 if useful
4. Step 3 (boot) — first visible payoff
5. Step 4 (mode-mount)
6. Step 5 (error burn)
7. Step 7 (docs)

Each step ships with its own tests and a `textual-dev` visual check before
moving on. No step depends on a later step's existence.

## 6. What shipped

| Step | Files | Tests |
|---|---|---|
| 1 — TTERunner | [`tailtop/widgets/tte_runner.py`](../../../tailtop/tailtop/widgets/tte_runner.py) | [`test_tte_runner.py`](../../../tailtop/tests/test_tte_runner.py) (3) |
| 2 — Theme + effect_library | [`tailtop/themes/__init__.py`](../../../tailtop/tailtop/themes/__init__.py), [`tailtop/widgets/effect_library.py`](../../../tailtop/tailtop/widgets/effect_library.py) | [`test_effect_library.py`](../../../tailtop/tests/test_effect_library.py) (15) |
| 3 — BootOverlay | [`tailtop/widgets/boot_overlay.py`](../../../tailtop/tailtop/widgets/boot_overlay.py), `app.py` edits | [`test_boot_overlay.py`](../../../tailtop/tests/test_boot_overlay.py) (2) |
| 4 — Mode-mount hook | [`tailtop/modes/base.py`](../../../tailtop/tailtop/modes/base.py), `app.py` edits | [`test_mode_mount_beams.py`](../../../tailtop/tests/test_mode_mount_beams.py) (2) |
| 5 — ErrorBurn | [`tailtop/widgets/error_burn.py`](../../../tailtop/tailtop/widgets/error_burn.py), `device_card.py` edits | [`test_error_burn.py`](../../../tailtop/tests/test_error_burn.py) (3) |
| 6 — SpeedtestMetric | [`tailtop/widgets/speedtest_metric.py`](../../../tailtop/tailtop/widgets/speedtest_metric.py) | [`test_speedtest_metric.py`](../../../tailtop/tests/test_speedtest_metric.py) (5) |
| 7 — Docs + deps | `pyproject.toml`, `README.md`, this plan | — |

Deviations from plan: Step 5 wired ErrorBurn into DeviceCard only (Cockpit). DeviceList and the StatusBar are deferred — DeviceList rebuilds rows on each poll so transition detection there needs a different design; StatusBar already renders errors in red text, and adding burn would require refactoring it from Static to a TTERunner host. Both worth a follow-up if the burn moment proves it adds value.

## 7. Risks

- **TTE frame counts may be too high for our budget.** Mitigation: per-effect
  config tuning in `effect_library.py` — most TTE effects expose `total_frames`
  or `gradient_steps` knobs.
- **Theme TCSS doesn't expose tokens to Python today.** Mitigation: add a
  thin `Theme` dataclass in `tailtop/themes/__init__.py` that mirrors the
  key tokens (accent, accent_dim, error, text_dim) and is updated when the
  theme switches. Cheap.
- **Worker thread interaction with Textual's reactivity.** Mitigation: the
  worker only pushes into a queue — never touches widgets directly. All
  widget updates happen on the UI thread inside `_tick`.
- **Skippable animations interrupting in-progress data work.** Mitigation:
  TTE workers are entirely independent of `Poller` workers; cancelling one
  doesn't touch the other.
