# Belt Widget (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `BeltView` Textual widget — a dual-lane, animated belt-style topology visualization with Hub and Main Bus layouts — alongside theme tokens, unit tests, and a runnable demo entry point. The widget gets composed into `TheBaseMode` in Phase 2; Phase 1 ends with a standalone widget you can feel-test via `python -m tailtop.widgets.belt`.

**Architecture:** Single file `tailtop/widgets/belt.py` containing pure data classes (`LaneState`, `BeltState`, `HubSlotMap`, `BusBranchMap`), pure math (`TreadAnimator`), pure layout (`HubLayout`, `BusLayout`), a `CharCanvas` helper, a `BeltRenderer`, and the Textual `BeltView` widget. Pure pieces are TDD-tested in isolation; the widget gets a smoke test plus the demo.

**Tech Stack:** Python 3.13 · Textual 1.x · Rich (via Textual) · pytest with `asyncio_mode=auto` · `uv` for env management.

**Spec:** [2026-06-06-tailtop-belt-view-spec.md](../specs/2026-06-06-tailtop-belt-view-spec.md)

---

## Pre-flight

Run from `tailtop/` (the inner project directory, not the repo root):

```bash
cd tailtop && uv sync --extra dev
```

Verify tests pass before any changes:

```bash
uv run pytest -q
```

Expected: all existing tests green.

---

## Task 1: Theme tokens for belts

Add `--belt-*` color tokens to base + 3 themes. No tests (it's CSS); we verify by loading the app in Task 8 and confirming nothing regresses.

**Files:**
- Modify: `tailtop/tailtop/themes/base.tcss` (append new section)
- Modify: `tailtop/tailtop/themes/studio.tcss` (append theme values)
- Modify: `tailtop/tailtop/themes/mission_control.tcss` (append theme values)
- Modify: `tailtop/tailtop/themes/brutalist.tcss` (append theme values)

- [ ] **Step 1: Append the BeltView block to `base.tcss`**

Append at the end of `tailtop/tailtop/themes/base.tcss`:

```css
/* ---- BeltView (defaults; overridden per theme) ---- */

BeltView {
    width: 1fr;
    height: 1fr;
    background: #0d0d12;
    color: #cfd3da;
    padding: 0;
    /* Inline character output; Rich Text supplies the per-char styling. */
}
```

- [ ] **Step 2: Append BeltView overrides to `studio.tcss`**

Append at the end of `tailtop/tailtop/themes/studio.tcss`:

```css
/* studio belt — muted, calm */

ComfortMode BeltView,
TheBaseMode BeltView {
    background: #101017;
}
```

- [ ] **Step 3: Append to `mission_control.tcss`**

Append at the end of `tailtop/tailtop/themes/mission_control.tcss`:

```css
/* mission control belt — high-saturation, operator-now */

CockpitMode BeltView,
TheBaseMode.mission BeltView {
    background: #0a0e1a;
}
```

- [ ] **Step 4: Append to `brutalist.tcss`**

Append at the end of `tailtop/tailtop/themes/brutalist.tcss`:

```css
/* brutalist belt — hard contrast */

ObservatoryMode BeltView,
TheBaseMode.brutalist BeltView {
    background: #000000;
}
```

> Per-tier tread colors (heavy/busy/light/idle), divider, and DERP styling are applied inline as Rich styles in the renderer (Task 6) — not via tcss — because they're data-driven per character cell. The tcss above just covers the widget's box-level background.

- [ ] **Step 5: Commit**

```bash
cd tailtop && git add tailtop/themes/
git commit -m "feat(tailtop): add BeltView theme blocks across themes"
```

---

## Task 2: Constants and tread math (TDD)

Pure functions: `speed_for(rate_bps)` → cells/second, `tier_for(rate_bps)` → one of `"heavy"`, `"busy"`, `"light"`, `"idle"`.

**Files:**
- Create: `tailtop/tailtop/widgets/belt.py`
- Create: `tailtop/tests/test_belt_math.py`

- [ ] **Step 1: Write the failing tests**

Create `tailtop/tests/test_belt_math.py`:

```python
"""Tread speed/tier math — pure, no Textual."""

from __future__ import annotations

import pytest

from tailtop.widgets.belt import TreadAnimator as TA


@pytest.mark.parametrize(
    "rate,expected_tier",
    [
        (0, "idle"),
        (50_000, "light"),          # 50 KB/s
        (100_000, "busy"),          # exactly at busy threshold
        (1_000_000, "busy"),        # 1 MB/s
        (4_999_999, "busy"),
        (5_000_000, "heavy"),       # exactly at heavy threshold
        (50_000_000, "heavy"),      # 50 MB/s
    ],
)
def test_tier_for(rate: int, expected_tier: str) -> None:
    assert TA.tier_for(rate) == expected_tier


def test_speed_for_zero_is_zero() -> None:
    assert TA.speed_for(0) == 0.0


def test_speed_for_clamps_at_min() -> None:
    # Anything > 0 but tiny still produces at least MIN_CELLS_PER_S.
    assert TA.speed_for(1) == pytest.approx(TA.MIN_CELLS_PER_S)


def test_speed_for_clamps_at_max() -> None:
    # Massive rate gets clamped to MAX_CELLS_PER_S, not infinity.
    assert TA.speed_for(10_000_000_000) == pytest.approx(TA.MAX_CELLS_PER_S)


def test_speed_for_scales_linearly_in_band() -> None:
    # At BUSY_BPS the formula yields exactly 1.0 norm → clamped to MIN.
    # At 100 * BUSY_BPS the norm is 100 → above MAX, clamped.
    # Pick a mid-band value.
    mid = TA.BUSY_BPS * 10  # 10× busy threshold = 1 MB/s
    expected = max(TA.MIN_CELLS_PER_S, min(TA.MAX_CELLS_PER_S, 10.0))
    assert TA.speed_for(mid) == pytest.approx(expected)
```

- [ ] **Step 2: Run tests — confirm they fail with import error**

Run from `tailtop/`:

```bash
uv run pytest tests/test_belt_math.py -v
```

Expected: collection error — `ModuleNotFoundError: No module named 'tailtop.widgets.belt'`.

- [ ] **Step 3: Create `belt.py` with `TreadAnimator`**

Create `tailtop/tailtop/widgets/belt.py`:

```python
"""Belt-style topology widget.

Renders the local node as a hub and online peers as belted nodes with
animated dual-lane conveyor belts. Tread speed scales with bandwidth.

See docs/superpowers/specs/2026-06-06-tailtop-belt-view-spec.md.
"""

from __future__ import annotations


class TreadAnimator:
    """Pure math: rate → tread speed (cells/s) and intensity tier."""

    # Rate thresholds (bytes/second).
    BUSY_BPS = 100_000           # 100 KB/s — light/busy boundary
    HEAVY_BPS = 5_000_000        # 5 MB/s — busy/heavy boundary

    # Tread speed clamp (cells per second).
    MIN_CELLS_PER_S = 0.67       # ~1.5 s per cell when traffic is barely above idle
    MAX_CELLS_PER_S = 16.7       # ~0.06 s per cell when fully heavy

    @classmethod
    def tier_for(cls, rate_bps: float) -> str:
        if rate_bps >= cls.HEAVY_BPS:
            return "heavy"
        if rate_bps >= cls.BUSY_BPS:
            return "busy"
        if rate_bps > 0:
            return "light"
        return "idle"

    @classmethod
    def speed_for(cls, rate_bps: float) -> float:
        if rate_bps <= 0:
            return 0.0
        # Normalize so BUSY_BPS == 1.0 cell/s baseline; clamp into band.
        norm = rate_bps / cls.BUSY_BPS
        return max(cls.MIN_CELLS_PER_S, min(cls.MAX_CELLS_PER_S, norm))
```

- [ ] **Step 4: Run tests — confirm pass**

```bash
uv run pytest tests/test_belt_math.py -v
```

Expected: all 5 (parametrized expands to more) tests pass.

- [ ] **Step 5: Commit**

```bash
cd tailtop && git add tailtop/widgets/belt.py tests/test_belt_math.py
git commit -m "feat(tailtop): add tread speed/tier math for belt widget"
```

---

## Task 3: LaneState position advancement (TDD)

Each belt has two `LaneState` values (in + out) with a `position` (float) and `cells_per_second`. Each animation tick advances `position += cps * dt`, wrapping at the lane length.

**Files:**
- Modify: `tailtop/tailtop/widgets/belt.py` (add `LaneState`)
- Modify: `tailtop/tests/test_belt_math.py` (extend)

- [ ] **Step 1: Add failing tests at the bottom of `test_belt_math.py`**

Append to `tailtop/tests/test_belt_math.py`:

```python
from tailtop.widgets.belt import LaneState  # noqa: E402


def test_lane_state_defaults() -> None:
    s = LaneState()
    assert s.position == 0.0
    assert s.cells_per_second == 0.0


def test_lane_state_advances_by_speed_times_dt() -> None:
    s = LaneState(cells_per_second=4.0, position=0.0)
    s.advance(dt=0.5, length=20)
    assert s.position == pytest.approx(2.0)


def test_lane_state_wraps_at_length() -> None:
    s = LaneState(cells_per_second=10.0, position=9.0)
    s.advance(dt=0.5, length=10)  # 9 + 5 = 14 → wrap to 4
    assert s.position == pytest.approx(4.0)


def test_lane_state_idle_does_not_move() -> None:
    s = LaneState(cells_per_second=0.0, position=3.0)
    s.advance(dt=10.0, length=20)
    assert s.position == 3.0
```

- [ ] **Step 2: Run — confirm failure**

```bash
uv run pytest tests/test_belt_math.py::test_lane_state_defaults -v
```

Expected: `ImportError: cannot import name 'LaneState'`.

- [ ] **Step 3: Add `LaneState` to `belt.py`**

Insert near the top of `tailtop/tailtop/widgets/belt.py`, **above** the `TreadAnimator` class:

```python
from dataclasses import dataclass


@dataclass
class LaneState:
    """One direction of a belt: tread speed and current head position."""

    cells_per_second: float = 0.0
    position: float = 0.0

    def advance(self, dt: float, length: int) -> None:
        """Move the tread head forward by ``cells_per_second * dt``, wrapping at length."""
        if self.cells_per_second <= 0 or length <= 0:
            return
        self.position = (self.position + self.cells_per_second * dt) % length
```

- [ ] **Step 4: Run — confirm pass**

```bash
uv run pytest tests/test_belt_math.py -v
```

Expected: all tests pass (original 7+ plus 4 new).

- [ ] **Step 5: Commit**

```bash
cd tailtop && git add tailtop/widgets/belt.py tests/test_belt_math.py
git commit -m "feat(tailtop): add LaneState with wrapping position advancement"
```

---

## Task 4: HubLayout slot assignment (TDD)

Assigns up to 8 peers to slots in priority order N→E→W→S→NE→NW→SE→SW, ranked by current bandwidth, with sticky retention so a peer keeps its slot for `sticky_seconds` even if its rate drops out of the top 8.

**Files:**
- Modify: `tailtop/tailtop/widgets/belt.py` (add `HubLayout`)
- Create: `tailtop/tests/test_belt_layout.py`

- [ ] **Step 1: Write failing tests**

Create `tailtop/tests/test_belt_layout.py`:

```python
"""Hub + Bus layout assignment tests — pure, no Textual."""

from __future__ import annotations

from dataclasses import replace

from tailtop.data.models import ConnType, Peer
from tailtop.widgets.belt import HUB_SLOTS, HubLayout


def _peer(pid: str, rx: int = 0, tx: int = 0, online: bool = True) -> Peer:
    return Peer(
        id=pid,
        host_name=pid,
        dns_name=f"{pid}.example.",
        os="linux",
        ips=["100.64.0.1"],
        online=online,
        active=True,
        exit_node=False,
        exit_node_option=False,
        relay="",
        cur_addr="100.64.0.1:41641",
        rx_bytes=rx,
        tx_bytes=tx,
        last_handshake=None,
        key_expiry=None,
    )


def test_priority_order_is_cardinals_first() -> None:
    assert HUB_SLOTS[:4] == ("N", "E", "W", "S")
    assert set(HUB_SLOTS) == {"N", "E", "W", "S", "NE", "NW", "SE", "SW"}


def test_one_peer_goes_to_north() -> None:
    layout = HubLayout()
    layout.assign(peers=[_peer("a")], rates={"a": (0, 0)}, now=0.0)
    assert layout.slot_of("a") == "N"
    assert layout.overflow_count == 0


def test_higher_bandwidth_takes_better_slots() -> None:
    layout = HubLayout()
    peers = [_peer("low"), _peer("hi"), _peer("mid")]
    rates = {
        "low": (1_000, 1_000),
        "hi": (10_000_000, 10_000_000),  # 10 MB/s combined
        "mid": (100_000, 100_000),
    }
    layout.assign(peers=peers, rates=rates, now=0.0)
    assert layout.slot_of("hi") == "N"
    assert layout.slot_of("mid") == "E"
    assert layout.slot_of("low") == "W"


def test_more_than_eight_peers_overflows() -> None:
    layout = HubLayout()
    peers = [_peer(f"p{i}", rx=i * 1_000_000) for i in range(12)]
    rates = {p.id: (p.rx_bytes, 0) for p in peers}
    layout.assign(peers=peers, rates=rates, now=0.0)
    assigned = [pid for pid in (layout.slot_of(p.id) for p in peers) if pid]
    assert len(assigned) == 8
    assert layout.overflow_count == 4
    # Top 8 by rate are p11..p4.
    for pid in [f"p{i}" for i in range(4, 12)]:
        assert layout.slot_of(pid) is not None
    for pid in ["p0", "p1", "p2", "p3"]:
        assert layout.slot_of(pid) is None


def test_sticky_keeps_peer_in_slot_when_rate_drops() -> None:
    layout = HubLayout(sticky_seconds=3.0)
    peers = [_peer("hi", rx=10_000_000), _peer("low", rx=10), _peer("rising", rx=0)]
    rates = {"hi": (10_000_000, 0), "low": (10, 0), "rising": (0, 0)}
    layout.assign(peers=peers, rates=rates, now=0.0)
    assert layout.slot_of("hi") == "N"

    # 1 s later: "hi" idles, "rising" spikes — but sticky window holds.
    rates2 = {"hi": (0, 0), "low": (10, 0), "rising": (10_000_000, 0)}
    layout.assign(peers=peers, rates=rates2, now=1.0)
    assert layout.slot_of("hi") == "N", "still within sticky window"

    # 4 s after first assign: sticky has expired — rising takes over.
    layout.assign(peers=peers, rates=rates2, now=4.0)
    assert layout.slot_of("rising") == "N"


def test_offline_peers_not_assigned() -> None:
    layout = HubLayout()
    peers = [_peer("on", rx=1_000), _peer("off", rx=999_999, online=False)]
    rates = {"on": (1_000, 0), "off": (999_999, 0)}
    layout.assign(peers=peers, rates=rates, now=0.0)
    assert layout.slot_of("on") == "N"
    assert layout.slot_of("off") is None
```

- [ ] **Step 2: Run — confirm failure**

```bash
uv run pytest tests/test_belt_layout.py -v
```

Expected: `ImportError: cannot import name 'HUB_SLOTS'`.

- [ ] **Step 3: Add `HUB_SLOTS` and `HubLayout` to `belt.py`**

Append to `tailtop/tailtop/widgets/belt.py`:

```python
from dataclasses import field

from tailtop.data.models import Peer

# Priority order: cardinals first (eye-line), then diagonals.
HUB_SLOTS: tuple[str, ...] = ("N", "E", "W", "S", "NE", "NW", "SE", "SW")


@dataclass
class HubLayout:
    """8-slot radial assignment with bandwidth priority + sticky retention.

    ``assign`` is idempotent within a sticky window: a peer that won a slot
    keeps it until ``sticky_seconds`` have passed since its last assignment.
    """

    sticky_seconds: float = 3.0
    _slot_of: dict[str, str] = field(default_factory=dict)        # peer_id → slot
    _assigned_at: dict[str, float] = field(default_factory=dict)  # peer_id → ts
    overflow_count: int = 0

    def slot_of(self, peer_id: str) -> str | None:
        return self._slot_of.get(peer_id)

    def assign(
        self,
        peers: list[Peer],
        rates: dict[str, tuple[float, float]],
        now: float,
    ) -> None:
        """Re-run the slot auction. Rates dict maps peer_id → (rx_bps, tx_bps)."""
        # 1. Only online peers compete.
        online = [p for p in peers if p.online]

        # 2. Drop departed peers from the maps.
        live_ids = {p.id for p in online}
        for gone in list(self._slot_of.keys()):
            if gone not in live_ids:
                self._slot_of.pop(gone, None)
                self._assigned_at.pop(gone, None)

        # 3. Sticky holds: peers within the window keep their slot.
        sticky_held: dict[str, str] = {
            pid: slot
            for pid, slot in self._slot_of.items()
            if now - self._assigned_at.get(pid, 0.0) < self.sticky_seconds
        }
        held_slots = set(sticky_held.values())

        # 4. Rank remaining peers by combined bandwidth (rx + tx), highest first.
        contenders = sorted(
            (p for p in online if p.id not in sticky_held),
            key=lambda p: -(rates.get(p.id, (0.0, 0.0))[0] + rates.get(p.id, (0.0, 0.0))[1]),
        )

        # 5. Fill open slots in priority order.
        open_slots = [s for s in HUB_SLOTS if s not in held_slots]
        new_assignments: dict[str, str] = dict(sticky_held)
        for slot, peer in zip(open_slots, contenders):
            new_assignments[peer.id] = slot
            self._assigned_at[peer.id] = now

        # 6. Anyone not assigned counts as overflow.
        self.overflow_count = max(0, len(online) - len(new_assignments))

        self._slot_of = new_assignments
```

- [ ] **Step 4: Run — confirm pass**

```bash
uv run pytest tests/test_belt_layout.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
cd tailtop && git add tailtop/widgets/belt.py tests/test_belt_layout.py
git commit -m "feat(tailtop): add HubLayout slot assignment with sticky priority"
```

---

## Task 5: BusLayout arrangement (TDD)

Peers strung along a horizontal trunk, alternating top/bottom for density, ordered by bandwidth. No slot cap — overflow handled by trunk auto-scroll (rendering concern, not layout).

**Files:**
- Modify: `tailtop/tailtop/widgets/belt.py` (add `BusLayout`)
- Modify: `tailtop/tests/test_belt_layout.py` (extend)

- [ ] **Step 1: Add failing tests**

Append to `tailtop/tests/test_belt_layout.py`:

```python
from tailtop.widgets.belt import BusBranch, BusLayout  # noqa: E402


def test_bus_alternates_top_and_bottom() -> None:
    layout = BusLayout()
    peers = [_peer(f"p{i}", rx=(10 - i) * 1_000_000) for i in range(4)]
    rates = {p.id: (p.rx_bytes, 0) for p in peers}
    branches = layout.arrange(peers=peers, rates=rates)
    sides = [b.side for b in branches]
    assert sides == ["top", "bottom", "top", "bottom"]


def test_bus_orders_by_combined_bandwidth() -> None:
    layout = BusLayout()
    peers = [_peer("low", rx=1_000), _peer("hi", rx=10_000_000), _peer("mid", rx=100_000)]
    rates = {p.id: (p.rx_bytes, 0) for p in peers}
    branches = layout.arrange(peers=peers, rates=rates)
    assert [b.peer_id for b in branches] == ["hi", "mid", "low"]


def test_bus_offsets_increment_along_trunk() -> None:
    layout = BusLayout(branch_spacing=12)
    peers = [_peer(f"p{i}") for i in range(3)]
    rates = {p.id: (0.0, 0.0) for p in peers}
    branches = layout.arrange(peers=peers, rates=rates)
    assert [b.x_offset for b in branches] == [12, 24, 36]


def test_bus_excludes_offline() -> None:
    layout = BusLayout()
    peers = [_peer("on"), _peer("off", online=False)]
    rates = {"on": (0.0, 0.0), "off": (1_000_000.0, 0.0)}
    branches = layout.arrange(peers=peers, rates=rates)
    assert [b.peer_id for b in branches] == ["on"]


def test_bus_branch_is_pure_dataclass() -> None:
    b = BusBranch(peer_id="x", side="top", x_offset=12)
    assert b.peer_id == "x"
    assert b.side == "top"
    assert b.x_offset == 12
```

- [ ] **Step 2: Run — confirm failure**

```bash
uv run pytest tests/test_belt_layout.py -v -k bus
```

Expected: `ImportError: cannot import name 'BusBranch'`.

- [ ] **Step 3: Add `BusBranch` + `BusLayout` to `belt.py`**

Append to `tailtop/tailtop/widgets/belt.py`:

```python
from typing import Literal


@dataclass
class BusBranch:
    """A single peer's branch off the horizontal trunk."""

    peer_id: str
    side: Literal["top", "bottom"]
    x_offset: int


@dataclass
class BusLayout:
    """Horizontal trunk; peers branch alternating top/bottom, bandwidth-ordered."""

    branch_spacing: int = 12  # columns between branch x_offsets

    def arrange(
        self,
        peers: list[Peer],
        rates: dict[str, tuple[float, float]],
    ) -> list[BusBranch]:
        online = [p for p in peers if p.online]
        ranked = sorted(
            online,
            key=lambda p: -(rates.get(p.id, (0.0, 0.0))[0] + rates.get(p.id, (0.0, 0.0))[1]),
        )
        branches: list[BusBranch] = []
        for i, p in enumerate(ranked):
            branches.append(
                BusBranch(
                    peer_id=p.id,
                    side="top" if i % 2 == 0 else "bottom",
                    x_offset=self.branch_spacing * (i + 1),
                )
            )
        return branches
```

- [ ] **Step 4: Run — confirm pass**

```bash
uv run pytest tests/test_belt_layout.py -v
```

Expected: all 11 tests pass.

- [ ] **Step 5: Commit**

```bash
cd tailtop && git add tailtop/widgets/belt.py tests/test_belt_layout.py
git commit -m "feat(tailtop): add BusLayout horizontal-trunk arrangement"
```

---

## Task 6: CharCanvas + BeltRenderer for Hub mode (TDD)

A `CharCanvas` is a 2D grid of `(char, style)` cells that flushes to a Rich `Text`. `BeltRenderer.render_hub(canvas, layout, belt_states, hub_peer, peers_by_id, selected_id)` paints:

1. The center hub card (3 lines).
2. For each assigned slot, a peer card + a belt segment with two lanes + tread heads at their current positions.
3. Lane glyphs by `ConnType` (DIRECT solid `│`, DERP dashed `╎`, IDLE ghosted `┊`).
4. Tread glyphs colored by `tier` (heavy/busy/light/idle).
5. Non-selected belts dimmed.

**Files:**
- Modify: `tailtop/tailtop/widgets/belt.py` (add `CharCanvas`, `BeltState`, `BeltRenderer.render_hub`)
- Create: `tailtop/tests/test_belt_renderer.py`

- [ ] **Step 1: Write failing tests**

Create `tailtop/tests/test_belt_renderer.py`:

```python
"""BeltRenderer Hub mode tests — assert character grid contents."""

from __future__ import annotations

from tailtop.data.models import ConnType
from tailtop.data.models import Peer
from tailtop.widgets.belt import (
    BeltRenderer,
    BeltState,
    CharCanvas,
    HUB_SLOTS,
    HubLayout,
    LaneState,
)


def _peer(pid: str, rx: int = 0, tx: int = 0, online: bool = True) -> Peer:
    return Peer(
        id=pid,
        host_name=pid,
        dns_name=f"{pid}.example.",
        os="linux",
        ips=["100.64.0.1"],
        online=online,
        active=True,
        exit_node=False,
        exit_node_option=False,
        relay="",
        cur_addr="100.64.0.1:41641",
        rx_bytes=rx,
        tx_bytes=tx,
        last_handshake=None,
        key_expiry=None,
    )


def test_canvas_default_is_spaces() -> None:
    c = CharCanvas(width=10, height=3)
    rendered = c.to_plain()
    assert rendered.splitlines() == [" " * 10] * 3


def test_canvas_set_and_to_plain() -> None:
    c = CharCanvas(width=5, height=2)
    c.set(0, 0, "H", "")
    c.set(4, 1, "X", "")
    lines = c.to_plain().splitlines()
    assert lines[0] == "H    "
    assert lines[1] == "    X"


def test_render_hub_draws_center_card_with_self_name() -> None:
    canvas = CharCanvas(width=60, height=20)
    layout = HubLayout()
    hub_peer = _peer("the-base")
    BeltRenderer().render_hub(
        canvas=canvas,
        layout=layout,
        belt_states={},
        hub_peer=hub_peer,
        peers_by_id={"the-base": hub_peer},
        selected_id=None,
    )
    plain = canvas.to_plain()
    assert "the-base" in plain


def test_render_hub_draws_peer_in_north_slot() -> None:
    canvas = CharCanvas(width=60, height=20)
    layout = HubLayout()
    hub_peer = _peer("hub")
    north = _peer("north-peer")
    layout.assign(peers=[north], rates={"north-peer": (0.0, 0.0)}, now=0.0)
    belt_states = {
        "north-peer": BeltState(
            peer_id="north-peer",
            conn_type=ConnType.DIRECT,
            in_lane=LaneState(),
            out_lane=LaneState(),
            in_tier="idle",
            out_tier="idle",
        ),
    }
    BeltRenderer().render_hub(
        canvas=canvas,
        layout=layout,
        belt_states=belt_states,
        hub_peer=hub_peer,
        peers_by_id={"hub": hub_peer, "north-peer": north},
        selected_id=None,
    )
    plain = canvas.to_plain()
    # The north peer card should be in the top half of the grid.
    top_half = "\n".join(plain.splitlines()[:10])
    assert "north-peer" in top_half


def test_render_hub_uses_dashed_glyph_for_derp_peers() -> None:
    canvas = CharCanvas(width=60, height=20)
    layout = HubLayout()
    hub_peer = _peer("hub")
    derp = _peer("derp-peer")
    layout.assign(peers=[derp], rates={"derp-peer": (0.0, 0.0)}, now=0.0)
    belt_states = {
        "derp-peer": BeltState(
            peer_id="derp-peer",
            conn_type=ConnType.DERP,
            in_lane=LaneState(),
            out_lane=LaneState(),
            in_tier="idle",
            out_tier="idle",
        ),
    }
    BeltRenderer().render_hub(
        canvas=canvas,
        layout=layout,
        belt_states=belt_states,
        hub_peer=hub_peer,
        peers_by_id={"hub": hub_peer, "derp-peer": derp},
        selected_id=None,
    )
    # Dashed lane glyph (vertical) should appear somewhere in the canvas.
    assert "╎" in canvas.to_plain()
```

- [ ] **Step 2: Run — confirm failures**

```bash
uv run pytest tests/test_belt_renderer.py -v
```

Expected: `ImportError: cannot import name 'CharCanvas'`.

- [ ] **Step 3: Add canvas + belt state + renderer to `belt.py`**

Append to `tailtop/tailtop/widgets/belt.py`:

```python
from rich.text import Text

from tailtop.data.models import ConnType

# ---- Glyphs ----

LANE_VERTICAL = {
    ConnType.DIRECT: "│",
    ConnType.DERP: "╎",
    ConnType.IDLE: "┊",
}
LANE_HORIZONTAL = {
    ConnType.DIRECT: "─",
    ConnType.DERP: "╌",
    ConnType.IDLE: "┄",
}
TREAD_GLYPH = {
    "up": "▲",
    "down": "▼",
    "left": "◀",
    "right": "▶",
}
TIER_STYLE = {
    "heavy": "bold #ffd166",
    "busy":  "#7be39b",
    "light": "#5b9bd5",
    "idle":  "dim #6b6f78",
}
LANE_STYLE = {
    ConnType.DIRECT: "#3a6dbb",
    ConnType.DERP:   "#7a5fa3",
    ConnType.IDLE:   "dim #6b6f78",
}
DIM = "dim"
HUB_CARD_STYLE = "bold #8bb6ff"


@dataclass
class BeltState:
    """Per-peer animation + tier state — driven by data poll + animation tick."""

    peer_id: str
    conn_type: ConnType
    in_lane: LaneState
    out_lane: LaneState
    in_tier: str
    out_tier: str


class CharCanvas:
    """2D grid of (char, style) cells, flushed to a Rich Text."""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self._chars: list[list[str]] = [[" "] * width for _ in range(height)]
        self._styles: list[list[str]] = [[""] * width for _ in range(height)]

    def set(self, x: int, y: int, char: str, style: str = "") -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            self._chars[y][x] = char
            self._styles[y][x] = style

    def write(self, x: int, y: int, text: str, style: str = "") -> None:
        for i, ch in enumerate(text):
            self.set(x + i, y, ch, style)

    def to_plain(self) -> str:
        return "\n".join("".join(row) for row in self._chars)

    def to_text(self) -> Text:
        out = Text()
        for y in range(self.height):
            for x in range(self.width):
                out.append(self._chars[y][x], style=self._styles[y][x])
            if y < self.height - 1:
                out.append("\n")
        return out


# ---- Hub geometry ----
# Each slot anchors a 3-row peer card and a belt segment between it and the
# center hub. The hub itself is fixed at the canvas center.

_SLOT_DIRECTION: dict[str, tuple[int, int]] = {
    "N":  (0, -1),
    "S":  (0,  1),
    "E":  (1,  0),
    "W":  (-1, 0),
    "NE": (1, -1),
    "NW": (-1, -1),
    "SE": (1,  1),
    "SW": (-1, 1),
}


class BeltRenderer:
    """Paints belts onto a CharCanvas. Pure: no Textual, no I/O."""

    def render_hub(
        self,
        *,
        canvas: CharCanvas,
        layout: HubLayout,
        belt_states: dict[str, BeltState],
        hub_peer: Peer,
        peers_by_id: dict[str, Peer],
        selected_id: str | None,
    ) -> None:
        cx, cy = canvas.width // 2, canvas.height // 2

        # Hub card at center (3 lines: name / aggregate / count).
        name = hub_peer.host_name[:18] or "self"
        canvas.write(cx - len(name) // 2, cy, name, HUB_CARD_STYLE)
        canvas.write(cx - 4, cy + 1, "▣ base", DIM)

        # For each assigned slot, draw the peer card + belt segment.
        for peer_id, slot in layout._slot_of.items():
            dx, dy = _SLOT_DIRECTION[slot]
            peer = peers_by_id.get(peer_id)
            state = belt_states.get(peer_id)
            if peer is None or state is None:
                continue

            # Peer card position: ~6 cells out from hub along (dx, dy).
            arm = max(canvas.width, canvas.height) // 6
            px, py = cx + dx * arm, cy + dy * arm

            dim = selected_id is not None and selected_id != peer_id

            self._draw_peer_card(canvas, px, py, peer, state, dim)
            self._draw_belt(canvas, cx, cy, px, py, state, dim)

    def _draw_peer_card(
        self,
        canvas: CharCanvas,
        x: int,
        y: int,
        peer: Peer,
        state: BeltState,
        dim: bool,
    ) -> None:
        name = peer.host_name[:14]
        style = TIER_STYLE.get(state.in_tier, "")
        if dim:
            style = "dim " + style if style else DIM
        canvas.write(x - len(name) // 2, y, name, style)

    def _draw_belt(
        self,
        canvas: CharCanvas,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        state: BeltState,
        dim: bool,
    ) -> None:
        lane_style = LANE_STYLE.get(state.conn_type, "")
        if dim:
            lane_style = "dim " + lane_style if lane_style else DIM

        # Walk from hub to peer along the dominant axis; vertical or horizontal lane glyph.
        if abs(x1 - x0) >= abs(y1 - y0):
            glyph = LANE_HORIZONTAL.get(state.conn_type, "─")
            step = 1 if x1 > x0 else -1
            for x in range(x0 + step, x1, step):
                canvas.set(x, y0, glyph, lane_style)
            # Tread heads — out arrow at out_lane position, in arrow at in_lane position.
            self._draw_tread_h(canvas, x0, x1, y0, state, dim)
        else:
            glyph = LANE_VERTICAL.get(state.conn_type, "│")
            step = 1 if y1 > y0 else -1
            for y in range(y0 + step, y1, step):
                canvas.set(x0, y, glyph, lane_style)
            self._draw_tread_v(canvas, y0, y1, x0, state, dim)

    def _draw_tread_v(
        self,
        canvas: CharCanvas,
        y0: int,
        y1: int,
        x: int,
        state: BeltState,
        dim: bool,
    ) -> None:
        length = abs(y1 - y0) - 1
        if length <= 0:
            return
        going_up = y1 < y0
        # in_lane = peer→hub; out_lane = hub→peer.
        in_arrow = "down" if going_up else "up"   # peer is above → tread comes down
        out_arrow = "up" if going_up else "down"
        in_style = TIER_STYLE.get(state.in_tier, "")
        out_style = TIER_STYLE.get(state.out_tier, "")
        if dim:
            in_style = "dim " + in_style if in_style else DIM
            out_style = "dim " + out_style if out_style else DIM
        # Lane cells live at min(y0,y1)+1 .. min(y0,y1)+length; tread head sits inside.
        base_y = min(y0, y1) + 1
        in_y = base_y + int(state.in_lane.position) % length
        out_y = base_y + int(state.out_lane.position) % length
        canvas.set(x, in_y, TREAD_GLYPH[in_arrow], in_style)
        canvas.set(x, out_y, TREAD_GLYPH[out_arrow], out_style)

    def _draw_tread_h(
        self,
        canvas: CharCanvas,
        x0: int,
        x1: int,
        y: int,
        state: BeltState,
        dim: bool,
    ) -> None:
        length = abs(x1 - x0) - 1
        if length <= 0:
            return
        going_right = x1 > x0
        in_arrow = "left" if going_right else "right"
        out_arrow = "right" if going_right else "left"
        in_style = TIER_STYLE.get(state.in_tier, "")
        out_style = TIER_STYLE.get(state.out_tier, "")
        if dim:
            in_style = "dim " + in_style if in_style else DIM
            out_style = "dim " + out_style if out_style else DIM
        base_x = min(x0, x1) + 1
        in_x = base_x + int(state.in_lane.position) % length
        out_x = base_x + int(state.out_lane.position) % length
        canvas.set(in_x, y, TREAD_GLYPH[in_arrow], in_style)
        canvas.set(out_x, y, TREAD_GLYPH[out_arrow], out_style)
```

- [ ] **Step 4: Run — confirm pass**

```bash
uv run pytest tests/test_belt_renderer.py -v
```

Expected: all 5 tests pass. If a test fails because the peer name doesn't fit in 60 cols, widen the canvas in the failing test.

- [ ] **Step 5: Commit**

```bash
cd tailtop && git add tailtop/widgets/belt.py tests/test_belt_renderer.py
git commit -m "feat(tailtop): add CharCanvas + BeltRenderer Hub paint pass"
```

---

## Task 7: BeltRenderer for Bus mode (TDD)

Trunk runs horizontally one row below the hub card. Branches are short vertical belts up (top) or down (bottom). Same lane/tread treatment.

**Files:**
- Modify: `tailtop/tailtop/widgets/belt.py` (add `render_bus`)
- Modify: `tailtop/tests/test_belt_renderer.py` (extend)

- [ ] **Step 1: Add failing tests**

Append to `tailtop/tests/test_belt_renderer.py`:

```python
from tailtop.widgets.belt import BusBranch, BusLayout  # noqa: E402


def test_render_bus_draws_hub_at_left_edge() -> None:
    canvas = CharCanvas(width=60, height=12)
    hub = _peer("hub")
    BeltRenderer().render_bus(
        canvas=canvas,
        branches=[],
        belt_states={},
        hub_peer=hub,
        peers_by_id={"hub": hub},
        selected_id=None,
    )
    first_line = canvas.to_plain().splitlines()[canvas.height // 2]
    assert "hub" in first_line[:10]


def test_render_bus_paints_trunk_across_canvas() -> None:
    canvas = CharCanvas(width=40, height=12)
    hub = _peer("hub")
    branches = [BusBranch(peer_id="x", side="top", x_offset=10)]
    states = {
        "x": BeltState(
            peer_id="x",
            conn_type=ConnType.DIRECT,
            in_lane=LaneState(),
            out_lane=LaneState(),
            in_tier="idle",
            out_tier="idle",
        )
    }
    peers = {"hub": hub, "x": _peer("x")}
    BeltRenderer().render_bus(
        canvas=canvas,
        branches=branches,
        belt_states=states,
        hub_peer=hub,
        peers_by_id=peers,
        selected_id=None,
    )
    mid_line = canvas.to_plain().splitlines()[canvas.height // 2]
    assert "─" in mid_line  # trunk segment present


def test_render_bus_places_top_branch_above_trunk() -> None:
    canvas = CharCanvas(width=40, height=12)
    hub = _peer("hub")
    branches = [BusBranch(peer_id="up", side="top", x_offset=15)]
    states = {
        "up": BeltState(
            peer_id="up",
            conn_type=ConnType.DIRECT,
            in_lane=LaneState(),
            out_lane=LaneState(),
            in_tier="idle",
            out_tier="idle",
        )
    }
    peers = {"hub": hub, "up": _peer("up")}
    BeltRenderer().render_bus(
        canvas=canvas,
        branches=branches,
        belt_states=states,
        hub_peer=hub,
        peers_by_id=peers,
        selected_id=None,
    )
    plain = canvas.to_plain().splitlines()
    trunk_y = canvas.height // 2
    above = "\n".join(plain[:trunk_y])
    assert "up" in above
```

- [ ] **Step 2: Run — confirm failure**

```bash
uv run pytest tests/test_belt_renderer.py -v -k bus
```

Expected: `AttributeError: 'BeltRenderer' object has no attribute 'render_bus'`.

- [ ] **Step 3: Add `render_bus` to `BeltRenderer` in `belt.py`**

Insert as a method on `BeltRenderer` (after `render_hub`):

```python
    def render_bus(
        self,
        *,
        canvas: CharCanvas,
        branches: list[BusBranch],
        belt_states: dict[str, BeltState],
        hub_peer: Peer,
        peers_by_id: dict[str, Peer],
        selected_id: str | None,
    ) -> None:
        trunk_y = canvas.height // 2

        # Hub label at left edge.
        name = hub_peer.host_name[:18] or "self"
        canvas.write(0, trunk_y - 1, name, HUB_CARD_STYLE)
        canvas.write(0, trunk_y, "▣═", HUB_CARD_STYLE)

        if not branches:
            return

        # Trunk extent: from hub to the furthest branch.
        max_x = max(b.x_offset for b in branches)
        for x in range(2, min(canvas.width - 1, max_x + 1)):
            canvas.set(x, trunk_y, "─", "")

        # Branches.
        for b in branches:
            peer = peers_by_id.get(b.peer_id)
            state = belt_states.get(b.peer_id)
            if peer is None or state is None:
                continue
            dim = selected_id is not None and selected_id != b.peer_id

            if b.side == "top":
                # Branch goes up — peer card sits above trunk.
                py = max(0, trunk_y - 3)
                self._draw_belt(canvas, b.x_offset, trunk_y, b.x_offset, py, state, dim)
                self._draw_peer_card(canvas, b.x_offset, py - 1, peer, state, dim)
            else:
                py = min(canvas.height - 1, trunk_y + 3)
                self._draw_belt(canvas, b.x_offset, trunk_y, b.x_offset, py, state, dim)
                self._draw_peer_card(canvas, b.x_offset, py + 1, peer, state, dim)
```

- [ ] **Step 4: Run — confirm pass**

```bash
uv run pytest tests/test_belt_renderer.py -v
```

Expected: all renderer tests pass (5 hub + 3 bus).

- [ ] **Step 5: Commit**

```bash
cd tailtop && git add tailtop/widgets/belt.py tests/test_belt_renderer.py
git commit -m "feat(tailtop): add BeltRenderer Bus paint pass"
```

---

## Task 8: BeltView Textual widget (smoke test + impl)

The widget wires it all together: receives `Status` + `RateHistory` via `update_data`, owns the animation timer (~10 Hz), maintains per-peer `BeltState`, picks the current layout based on terminal size, and re-renders on each tick.

**Files:**
- Modify: `tailtop/tailtop/widgets/belt.py` (add `BeltView`)
- Create: `tailtop/tests/test_belt_widget.py`

- [ ] **Step 1: Write a smoke test**

Create `tailtop/tests/test_belt_widget.py`:

```python
"""BeltView widget smoke tests — instantiation, update, layout pick."""

from __future__ import annotations

import pytest

from tailtop.data.models import Status
from tailtop.state import RateHistory
from tailtop.widgets.belt import BeltView


@pytest.fixture
def empty_status() -> Status:
    return Status(
        version="dev",
        backend_state="Running",
        tailscale_ips=["100.64.0.1"],
        magic_dns_suffix="example.ts.net",
        user_display="me",
        self_peer=_make_self(),
        peers=[],
    )


def _make_self():
    from tailtop.data.models import Peer
    return Peer(
        id="self",
        host_name="the-base",
        dns_name="the-base.example.",
        os="linux",
        ips=["100.64.0.1"],
        online=True,
        active=True,
        exit_node=False,
        exit_node_option=False,
        relay="",
        cur_addr="",
        rx_bytes=0,
        tx_bytes=0,
        last_handshake=None,
        key_expiry=None,
        is_self=True,
    )


async def test_belt_view_instantiates() -> None:
    view = BeltView()
    assert view is not None
    assert view.layout_mode == "hub"


async def test_update_data_records_belt_states(empty_status: Status) -> None:
    from tailtop.data.models import Peer
    peer = Peer(
        id="p1",
        host_name="peer-1",
        dns_name="peer-1.example.",
        os="linux",
        ips=["100.64.0.2"],
        online=True,
        active=True,
        exit_node=False,
        exit_node_option=False,
        relay="",
        cur_addr="100.64.0.2:41641",
        rx_bytes=200_000,
        tx_bytes=50_000,
        last_handshake=None,
        key_expiry=None,
    )
    status = Status(**{**empty_status.__dict__, "peers": [peer]})
    rates = RateHistory()
    rates.update("p1", 200_000, 50_000, now=0.0)
    rates.update("p1", 400_000, 100_000, now=1.0)  # 200 KB/s rx, 50 KB/s tx

    view = BeltView()
    view.update_data(status, rates, now=1.0)
    assert "p1" in view.belt_states
    state = view.belt_states["p1"]
    # 200 KB/s rx is "busy" tier; 50 KB/s tx is "light" tier.
    assert state.in_tier == "busy"
    assert state.out_tier == "light"


async def test_layout_auto_degrades_to_bus_in_narrow_terminal() -> None:
    view = BeltView()
    view._on_resize_dims(width=50, height=15)   # below Hub minimum (60×20)
    assert view.layout_mode == "bus"
    view._on_resize_dims(width=80, height=24)
    assert view.layout_mode == "hub"
```

- [ ] **Step 2: Run — confirm failure**

```bash
uv run pytest tests/test_belt_widget.py -v
```

Expected: `ImportError: cannot import name 'BeltView'`.

- [ ] **Step 3: Add `BeltView` to `belt.py`**

Append to `tailtop/tailtop/widgets/belt.py`:

```python
from textual.widget import Widget

from tailtop.state import RateHistory

# Animation tick at ~10 Hz.
_ANIMATION_INTERVAL = 1 / 10
_HUB_MIN_W, _HUB_MIN_H = 60, 20


class BeltView(Widget):
    """Animated belt-style topology widget.

    External contract:
      ``update_data(status, rates, now)`` — call on each poll (~2s).
      The widget owns the animation timer internally.
    """

    DEFAULT_CSS = """
    BeltView {
        background: transparent;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.layout_mode: str = "hub"
        self.hub_layout = HubLayout()
        self.bus_layout = BusLayout()
        self.belt_states: dict[str, BeltState] = {}
        self.hub_peer: Peer | None = None
        self.peers_by_id: dict[str, Peer] = {}
        self.overflow_count: int = 0
        self.selected_id: str | None = None
        self._renderer = BeltRenderer()
        self._last_tick: float | None = None
        self._anim_timer = None

    def on_mount(self) -> None:
        self._anim_timer = self.set_interval(_ANIMATION_INTERVAL, self._on_animation_tick)
        self._on_resize_dims(self.size.width, self.size.height)

    def on_resize(self, event) -> None:
        self._on_resize_dims(event.size.width, event.size.height)

    def _on_resize_dims(self, width: int, height: int) -> None:
        if width >= _HUB_MIN_W and height >= _HUB_MIN_H:
            self.layout_mode = "hub"
        else:
            self.layout_mode = "bus"
        self.refresh()

    def update_data(self, status: Status, rates: RateHistory, now: float) -> None:
        """Refresh per-peer belt state from a new Status snapshot."""
        self.hub_peer = status.self_peer
        self.peers_by_id = {p.id: p for p in status.peers}
        self.peers_by_id[status.self_peer.id] = status.self_peer

        rate_map: dict[str, tuple[float, float]] = {}
        for peer in status.peers:
            rx = rates.current_rx(peer.id)
            tx = rates.current_tx(peer.id)
            rate_map[peer.id] = (rx, tx)

            state = self.belt_states.get(peer.id)
            if state is None:
                state = BeltState(
                    peer_id=peer.id,
                    conn_type=peer.conn_type,
                    in_lane=LaneState(),
                    out_lane=LaneState(),
                    in_tier="idle",
                    out_tier="idle",
                )
                self.belt_states[peer.id] = state
            state.conn_type = peer.conn_type
            state.in_lane.cells_per_second = TreadAnimator.speed_for(rx)
            state.out_lane.cells_per_second = TreadAnimator.speed_for(tx)
            state.in_tier = TreadAnimator.tier_for(rx)
            state.out_tier = TreadAnimator.tier_for(tx)

        # Drop departed peers.
        for gone in list(self.belt_states.keys()):
            if gone not in self.peers_by_id:
                self.belt_states.pop(gone, None)

        self.hub_layout.assign(peers=status.peers, rates=rate_map, now=now)
        self.overflow_count = self.hub_layout.overflow_count
        self.refresh()

    def set_selected(self, peer_id: str | None) -> None:
        self.selected_id = peer_id
        self.refresh()

    def _on_animation_tick(self) -> None:
        import time
        now = time.monotonic()
        dt = (now - self._last_tick) if self._last_tick is not None else _ANIMATION_INTERVAL
        self._last_tick = now
        # Lane length is the dominant axis of the canvas; treat 16 as a safe
        # default that wraps quickly enough to look alive.
        for state in self.belt_states.values():
            state.in_lane.advance(dt=dt, length=16)
            state.out_lane.advance(dt=dt, length=16)
        self.refresh()

    def render(self):
        width = max(self.size.width, 40)
        height = max(self.size.height, 12)
        canvas = CharCanvas(width=width, height=height)

        if self.hub_peer is None:
            canvas.write(width // 2 - 7, height // 2, "loading belts…", DIM)
            return canvas.to_text()

        if self.layout_mode == "hub":
            self._renderer.render_hub(
                canvas=canvas,
                layout=self.hub_layout,
                belt_states=self.belt_states,
                hub_peer=self.hub_peer,
                peers_by_id=self.peers_by_id,
                selected_id=self.selected_id,
            )
            if self.overflow_count > 0:
                msg = f"+{self.overflow_count} more"
                canvas.write(width // 2 - len(msg) // 2, height - 2, msg, DIM)
        else:
            branches = self.bus_layout.arrange(
                peers=list(self.peers_by_id.values()),
                rates={
                    pid: (s.in_lane.cells_per_second, s.out_lane.cells_per_second)
                    for pid, s in self.belt_states.items()
                },
            )
            self._renderer.render_bus(
                canvas=canvas,
                branches=branches,
                belt_states=self.belt_states,
                hub_peer=self.hub_peer,
                peers_by_id=self.peers_by_id,
                selected_id=self.selected_id,
            )

        return canvas.to_text()
```

- [ ] **Step 4: Run — confirm pass**

```bash
uv run pytest tests/test_belt_widget.py -v
```

Expected: all 3 tests pass. If `test_update_data_records_belt_states` fails because the rate is computed differently, inspect `RateHistory.update` semantics — the test sets rx=200_000 at t=0 then rx=400_000 at t=1.0 so rate should be 200_000 bps → "busy".

- [ ] **Step 5: Run the full test suite to confirm no regressions**

```bash
uv run pytest -q
```

Expected: all previously-passing tests still pass.

- [ ] **Step 6: Commit**

```bash
cd tailtop && git add tailtop/widgets/belt.py tests/test_belt_widget.py
git commit -m "feat(tailtop): add BeltView Textual widget with animation timer"
```

---

## Task 9: Demo entry point — `python -m tailtop.widgets.belt`

Run the widget against the existing `tests/fixtures/status.json` so a developer can see it without Phase 2.

**Files:**
- Modify: `tailtop/tailtop/widgets/belt.py` (add `__main__`)
- Modify: `tailtop/tailtop/widgets/__init__.py` (export `BeltView`)

- [ ] **Step 1: Append `__main__` block to `belt.py`**

Append at the very end of `tailtop/tailtop/widgets/belt.py`:

```python
if __name__ == "__main__":
    import json
    import time
    from pathlib import Path

    from textual.app import App, ComposeResult

    from tailtop.data.models import Status
    from tailtop.state import RateHistory


    class _BeltDemo(App):
        CSS = "BeltView { width: 1fr; height: 1fr; background: #0d0d12; }"
        BINDINGS = [("q", "quit", "Quit"), ("space", "step", "Bump rates")]

        def __init__(self) -> None:
            super().__init__()
            self.belt = BeltView()
            self.rates = RateHistory()
            fixture = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "status.json"
            self.status = Status.from_json(json.loads(fixture.read_text()))
            self._t = 0.0

        def compose(self) -> ComposeResult:
            yield self.belt

        def on_mount(self) -> None:
            self._push()
            self.set_interval(2.0, self._push)

        def _push(self) -> None:
            now = time.monotonic()
            for peer in self.status.peers:
                # Synthesise a slowly-rising counter so RateHistory sees motion.
                self.rates.update(
                    peer.id,
                    peer.rx_bytes + int(self._t * 500_000),
                    peer.tx_bytes + int(self._t * 200_000),
                    now=now,
                )
            self._t += 1
            self.belt.update_data(self.status, self.rates, now=now)

        def action_step(self) -> None:
            self._push()


    _BeltDemo().run()
```

- [ ] **Step 2: Export `BeltView` from the widgets package**

Read `tailtop/tailtop/widgets/__init__.py`. If it has explicit re-exports, add:

```python
from tailtop.widgets.belt import BeltView

__all__ = [*__all__, "BeltView"]  # adjust to match the existing pattern
```

If it's empty, write:

```python
"""Widget barrel — re-exports for convenience."""

from tailtop.widgets.belt import BeltView

__all__ = ["BeltView"]
```

- [ ] **Step 3: Manually verify the demo runs**

```bash
cd tailtop && uv run python -m tailtop.widgets.belt
```

Expected:
- Terminal switches to full-screen Textual app.
- A belt visualization appears centered, with peers from the fixture.
- Treads visibly advance (every animation tick).
- Press `space` to bump rates; press `q` to quit.

Note: this is a manual step. If the demo crashes, inspect the traceback and fix in a follow-up step before committing.

- [ ] **Step 4: Run the full test suite one more time**

```bash
uv run pytest -q
```

Expected: all tests green.

- [ ] **Step 5: Commit**

```bash
cd tailtop && git add tailtop/widgets/belt.py tailtop/widgets/__init__.py
git commit -m "feat(tailtop): add belt widget demo entry point"
```

---

## Task 10: Wrap-up — verify and report

- [ ] **Step 1: Run the whole suite**

```bash
cd tailtop && uv run pytest -v
```

Expected: all tests green, no warnings about deprecated APIs we introduced.

- [ ] **Step 2: Lint check (optional but recommended)**

```bash
cd tailtop && uv run ruff check tailtop/widgets/belt.py
```

Fix any issues. Common one: long lines — wrap to fit `line-length = 100`.

- [ ] **Step 3: Confirm the spec's open questions are still open / resolved as expected**

Open spec questions to revisit:
- Letter shortcut for TheBase — still open, deferred to Phase 2.
- Threshold values (100 KB/s / 5 MB/s) — locked in as `BUSY_BPS` / `HEAVY_BPS` constants; surface for user feedback after first feel-test.
- Sticky slot duration — locked at 3.0s; feel-test it via the demo.
- Aggregate ↓/↑ in hub card — Phase 1 hub card just shows `▣ base`; aggregate rendering deferred to Phase 2 (it belongs in the surrounding mode chrome).
- Hub self-selection — Phase 1 selects peers only; self-selection deferred to Phase 2.

- [ ] **Step 4: Mark Phase 1 task complete and hand off**

Tell the user:
> Phase 1 complete. Belt widget + tests + demo landed across N commits. Run `uv run python -m tailtop.widgets.belt` to see it. Phase 2 ("the base" mode) is unblocked.

---

## Out of scope for Phase 1

The following are deferred to Phase 2 or later — do NOT add them in this plan:
- "The base" mode (alerts strip, primary device panel, tailnet header).
- Keybinding integration into the app-level `Tab` cycle.
- Selection wiring against `app.selected_peer_id`. (`BeltView.set_selected()` exists; calling it lives in Phase 2.)
- Snapshot tests against `tests/fixtures/status.json` — current renderer tests use synthetic peers; full fixture rendering is a Phase 2 polish step.
- Per-peer rate label in the peer card (`↓25.8 ↑14.1` text). Currently the peer card is just the hostname. Add when Phase 2 needs it.
- Grid layout.
