# "The Base" Mode (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `TheBaseMode` — a fourth top-level tailtop mode that wraps the Phase 1 `BeltView` widget in dashboard chrome (tailnet header, alert strip, primary device detail) and registers alongside Comfort/Cockpit/Observatory in the `Tab` cycle. Also lands three Phase-1 polish items called out in the Phase 1 review.

**Architecture:** One new mode file `tailtop/tailtop/modes/the_base.py`, one new widget `tailtop/tailtop/widgets/alert_strip.py`, small extensions to `BeltView` (aggregate hub card text, per-peer rate labels), and surgical edits to `app.py` (MODE_ORDER + compose). Theme tokens for the new mode chrome.

**Tech Stack:** Same as Phase 1 — Python 3.13 · Textual 1.x · pytest with asyncio_mode=auto · `uv`.

**Spec:** [2026-06-06-tailtop-belt-view-spec.md](../specs/2026-06-06-tailtop-belt-view-spec.md)
**Prior plan:** [2026-06-06-belt-widget-phase-1.md](2026-06-06-belt-widget-phase-1.md)

---

## Pre-flight

From worktree root: `/Users/nickv/ClaudeCode Projects/Tailscale/.claude/worktrees/blissful-cray-af234d`. All commands use absolute paths or run from this root. Tests via:

```bash
uv --project tailtop run pytest --rootdir tailtop -q tailtop/tests
```

Confirm 68 passing before any change (Phase 1's final count).

---

## Task 1: Belt widget polish (aggregate ↓/↑ + per-peer rate labels + overflow test)

Three deferred Phase 1 items, all in `belt.py`. Single commit.

**Files:**
- Modify: `tailtop/tailtop/widgets/belt.py`
- Modify: `tailtop/tests/test_belt_renderer.py`
- Modify: `tailtop/tests/test_belt_widget.py`

- [ ] **Step 1: Add failing tests**

Append to `tailtop/tests/test_belt_renderer.py`:

```python
from tailtop.widgets.belt import BeltView  # noqa: E402


def test_render_hub_includes_aggregate_traffic_under_hub_name() -> None:
    canvas = CharCanvas(width=60, height=20)
    layout = HubLayout()
    hub_peer = _peer("base")
    # Inject pre-known aggregate via a BeltView-rendered scenario.
    view = BeltView()
    view.hub_peer = hub_peer
    view.peers_by_id = {"base": hub_peer}
    view.layout_mode = "hub"
    view._aggregate_rx = 25_800_000.0  # 25.8 MB/s
    view._aggregate_tx = 14_100_000.0  # 14.1 MB/s
    rendered = view.render()
    plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
    assert "25.8" in plain
    assert "14.1" in plain


def test_render_hub_peer_card_includes_rate_label() -> None:
    canvas = CharCanvas(width=60, height=20)
    layout = HubLayout()
    hub_peer = _peer("hub")
    peer = _peer("busy-peer")
    layout.assign(peers=[peer], rates={"busy-peer": (200_000.0, 50_000.0)}, now=0.0)
    in_lane = LaneState(cells_per_second=2.0)
    out_lane = LaneState(cells_per_second=0.5)
    belt_states = {
        "busy-peer": BeltState(
            peer_id="busy-peer",
            conn_type=ConnType.DIRECT,
            in_lane=in_lane,
            out_lane=out_lane,
            in_tier="busy",
            out_tier="light",
            rx_bps=200_000.0,
            tx_bps=50_000.0,
        ),
    }
    BeltRenderer().render_hub(
        canvas=canvas,
        layout=layout,
        belt_states=belt_states,
        hub_peer=hub_peer,
        peers_by_id={"hub": hub_peer, "busy-peer": peer},
        selected_id=None,
    )
    plain = canvas.to_plain()
    # Compact rate label is "↓200K ↑50K" or similar; assert the units appear near the peer.
    assert "200" in plain or "195" in plain  # 200_000 B/s rounded
```

Append to `tailtop/tests/test_belt_widget.py`:

```python
async def test_render_shows_overflow_chip_when_more_than_eight_peers() -> None:
    from tailtop.data.models import Peer

    view = BeltView()
    # Fake the post-update_data state directly.
    view.hub_peer = _make_self()
    view.peers_by_id = {"self": _make_self()}
    view.overflow_count = 4
    view.layout_mode = "hub"
    rendered = view.render()
    plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
    assert "+4 more" in plain
```

- [ ] **Step 2: Run — confirm failures**

```bash
uv --project tailtop run pytest --rootdir tailtop -q tailtop/tests/test_belt_renderer.py tailtop/tests/test_belt_widget.py
```

Expected: the 2 new renderer tests + 1 new widget test fail because `rx_bps`/`tx_bps` fields don't exist on `BeltState`, the hub card has no aggregate text, the peer card has no rate label.

- [ ] **Step 3: Extend `BeltState` and rendering in `tailtop/tailtop/widgets/belt.py`**

Find the `BeltState` dataclass and add two fields:

```python
@dataclass
class BeltState:
    """Per-peer animation + tier state — driven by data poll + animation tick."""

    peer_id: str
    conn_type: ConnType
    in_lane: LaneState
    out_lane: LaneState
    in_tier: str
    out_tier: str
    rx_bps: float = 0.0
    tx_bps: float = 0.0
```

In `BeltView.__init__`, add aggregate attributes alongside `overflow_count`:

```python
        self._aggregate_rx: float = 0.0
        self._aggregate_tx: float = 0.0
```

In `BeltView.update_data`, populate them and the new BeltState fields. Find the loop body:

```python
            state.in_tier = TreadAnimator.tier_for(rx)
            state.out_tier = TreadAnimator.tier_for(tx)
```

and append two lines below:

```python
            state.rx_bps = rx
            state.tx_bps = tx
```

After the `# Drop departed peers.` block but before `self.hub_layout.assign(...)`, compute aggregates:

```python
        self._aggregate_rx = sum(s.rx_bps for s in self.belt_states.values())
        self._aggregate_tx = sum(s.tx_bps for s in self.belt_states.values())
```

In `BeltRenderer.render_hub`, replace the existing aggregate line. Find:

```python
        canvas.write(cx - 4, cy + 1, "▣ base", DIM)
```

and replace with a call to a new helper. First, add this helper to `BeltRenderer` (after `_draw_peer_card`):

```python
    def _compact_rate(self, bps: float) -> str:
        """Compact rate string: '0', '95K', '1.2M', '25.8M'."""
        if bps < 1000:
            return f"{int(bps)}"
        if bps < 1_000_000:
            return f"{int(bps / 1000)}K"
        return f"{bps / 1_000_000:.1f}M"
```

Update `render_hub` to take the aggregates. Change its signature from `render_hub(self, *, canvas, layout, belt_states, hub_peer, peers_by_id, selected_id)` to:

```python
    def render_hub(
        self,
        *,
        canvas: CharCanvas,
        layout: HubLayout,
        belt_states: dict[str, BeltState],
        hub_peer: Peer,
        peers_by_id: dict[str, Peer],
        selected_id: str | None,
        aggregate_rx: float = 0.0,
        aggregate_tx: float = 0.0,
    ) -> None:
```

and replace the `▣ base` line:

```python
        agg = f"▣ ↓{self._compact_rate(aggregate_rx)} ↑{self._compact_rate(aggregate_tx)}"
        canvas.write(cx - len(agg) // 2, cy + 1, agg, DIM)
```

Similarly update `_draw_peer_card`. Replace the body of `_draw_peer_card` with:

```python
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
        # Compact rate label one row below the name.
        rate = f"↓{self._compact_rate(state.rx_bps)} ↑{self._compact_rate(state.tx_bps)}"
        rate_style = "dim " + DIM if dim else DIM
        canvas.write(x - len(rate) // 2, y + 1, rate, rate_style)
```

`render_bus` uses `_draw_peer_card` too — no signature change needed there; rate label appears automatically.

In `BeltView.render`, pass the aggregates through to `render_hub`. Find the hub render call and add:

```python
        if self.layout_mode == "hub":
            self._renderer.render_hub(
                canvas=canvas,
                layout=self.hub_layout,
                belt_states=self.belt_states,
                hub_peer=self.hub_peer,
                peers_by_id=self.peers_by_id,
                selected_id=self.selected_id,
                aggregate_rx=self._aggregate_rx,
                aggregate_tx=self._aggregate_tx,
            )
```

- [ ] **Step 4: Run — confirm pass**

```bash
uv --project tailtop run pytest --rootdir tailtop -q tailtop/tests
```

Expected: 71 passing (68 prior + 3 new).

- [ ] **Step 5: Lint**

```bash
uv --project tailtop run --with ruff ruff check tailtop/tailtop/widgets/belt.py
```

Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add tailtop/tailtop/widgets/belt.py tailtop/tests/test_belt_renderer.py tailtop/tests/test_belt_widget.py
git commit -m "feat(tailtop): belt aggregate hub card + per-peer rate labels + overflow test"
```

---

## Task 2: AlertStrip widget

A one-line status strip that summarizes anomalies: N offline, M with keys expiring soon, P backend-state warnings. Reusable; lands in `tailtop/widgets/`.

**Files:**
- Create: `tailtop/tailtop/widgets/alert_strip.py`
- Create: `tailtop/tests/test_alert_strip.py`

- [ ] **Step 1: Write failing tests**

Create `tailtop/tests/test_alert_strip.py`:

```python
"""AlertStrip tests — collates offline/expiring-key counts into a one-line summary."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tailtop.data.models import Peer, Status
from tailtop.widgets.alert_strip import AlertStrip, summarise_alerts


def _peer(pid: str, online: bool = True, expiry_days: int | None = None) -> Peer:
    expiry = None
    if expiry_days is not None:
        expiry = datetime.now(timezone.utc) + timedelta(days=expiry_days)
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
        rx_bytes=0,
        tx_bytes=0,
        last_handshake=None,
        key_expiry=expiry,
    )


def _status(peers: list[Peer], state: str = "Running") -> Status:
    return Status(
        version="dev",
        backend_state=state,
        tailscale_ips=["100.64.0.1"],
        magic_dns_suffix="example.ts.net",
        user_display="me",
        self_peer=_peer("self"),
        peers=peers,
    )


def test_summary_empty_when_no_issues() -> None:
    status = _status([_peer("p1"), _peer("p2")])
    assert summarise_alerts(status) == ""


def test_summary_counts_offline() -> None:
    status = _status([_peer("on"), _peer("off1", online=False), _peer("off2", online=False)])
    out = summarise_alerts(status)
    assert "2 offline" in out


def test_summary_counts_expiring_keys_within_seven_days() -> None:
    status = _status([_peer("hot", expiry_days=3), _peer("safe", expiry_days=60)])
    assert "1 key expiring" in summarise_alerts(status)


def test_summary_flags_backend_not_running() -> None:
    status = _status([], state="NeedsLogin")
    assert "NeedsLogin" in summarise_alerts(status)


def test_alert_strip_widget_instantiates_and_updates() -> None:
    strip = AlertStrip()
    strip.set_status(_status([_peer("a", online=False)]))
    # Widget's renderable should contain the offline count.
    rendered = strip.render()
    plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
    assert "1 offline" in plain
```

- [ ] **Step 2: Run — confirm failure**

```bash
uv --project tailtop run pytest --rootdir tailtop -q tailtop/tests/test_alert_strip.py
```

Expected: `ModuleNotFoundError: No module named 'tailtop.widgets.alert_strip'`.

- [ ] **Step 3: Implement `tailtop/tailtop/widgets/alert_strip.py`**

```python
"""AlertStrip — a one-line summary of tailnet anomalies for TheBaseMode.

Computes offline peer count, peers with keys expiring within 7 days, and any
non-Running backend state. Pure ``summarise_alerts(status)`` is unit-tested
without Textual; the widget is a thin Static wrapper.
"""

from __future__ import annotations

from datetime import datetime, timezone

from rich.text import Text
from textual.widgets import Static

from tailtop.data.models import Status

_EXPIRY_WARNING_DAYS = 7


def summarise_alerts(status: Status) -> str:
    """Return a single-line summary; empty string when nothing's wrong."""
    parts: list[str] = []

    if status.backend_state and status.backend_state != "Running":
        parts.append(status.backend_state)

    offline = sum(1 for p in status.peers if not p.online)
    if offline:
        parts.append(f"{offline} offline")

    now = datetime.now(timezone.utc)
    expiring = 0
    for p in status.peers:
        if p.key_expiry is None:
            continue
        delta = p.key_expiry.astimezone(timezone.utc) - now
        if 0 <= delta.total_seconds() <= _EXPIRY_WARNING_DAYS * 86400:
            expiring += 1
    if expiring:
        parts.append(f"{expiring} key expiring soon")

    return " · ".join(parts)


class AlertStrip(Static):
    """Thin Textual wrapper around summarise_alerts."""

    def set_status(self, status: Status) -> None:
        text = summarise_alerts(status)
        if not text:
            self.update(Text("", style="dim"))
        else:
            self.update(Text(f"⚠ {text}", style="#f0c674"))
```

- [ ] **Step 4: Run — confirm pass**

```bash
uv --project tailtop run pytest --rootdir tailtop -q tailtop/tests/test_alert_strip.py
```

Expected: 5 new tests pass. Full suite: 76 passing.

- [ ] **Step 5: Commit**

```bash
git add tailtop/tailtop/widgets/alert_strip.py tailtop/tests/test_alert_strip.py
git commit -m "feat(tailtop): add AlertStrip widget for backend / offline / expiring-key warnings"
```

---

## Task 3: TheBaseMode skeleton

The new mode composes the layout: header (tailnet name + counts), alert strip, belt centerpiece, detail pane on the side. Wires `update_data`.

**Files:**
- Create: `tailtop/tailtop/modes/the_base.py`
- Create: `tailtop/tests/test_the_base.py`

- [ ] **Step 1: Write failing tests**

Create `tailtop/tests/test_the_base.py`:

```python
"""TheBaseMode composition tests — header, alert, belt, detail pane."""

from __future__ import annotations

import pytest

from tailtop.data.models import Peer, Status
from tailtop.modes.the_base import TheBaseMode
from tailtop.state import RateHistory
from tailtop.widgets.alert_strip import AlertStrip
from tailtop.widgets.belt import BeltView
from tailtop.widgets.detail_pane import DetailPane


def _self() -> Peer:
    return Peer(
        id="self", host_name="the-base", dns_name="the-base.example.", os="linux",
        ips=["100.64.0.1"], online=True, active=True, exit_node=False,
        exit_node_option=False, relay="", cur_addr="", rx_bytes=0, tx_bytes=0,
        last_handshake=None, key_expiry=None, is_self=True,
    )


def _peer(pid: str, online: bool = True) -> Peer:
    return Peer(
        id=pid, host_name=pid, dns_name=f"{pid}.example.", os="linux",
        ips=["100.64.0.2"], online=online, active=True, exit_node=False,
        exit_node_option=False, relay="", cur_addr="100.64.0.2:41641",
        rx_bytes=0, tx_bytes=0, last_handshake=None, key_expiry=None,
    )


@pytest.fixture
def status_with_peers() -> Status:
    return Status(
        version="dev", backend_state="Running", tailscale_ips=["100.64.0.1"],
        magic_dns_suffix="example.ts.net", user_display="me",
        self_peer=_self(),
        peers=[_peer("p1"), _peer("p2", online=False)],
    )


def test_mode_class_has_expected_cadence() -> None:
    assert TheBaseMode.cadence == 2.0


def test_mode_instantiates_with_expected_child_widgets() -> None:
    mode = TheBaseMode()
    # Children get created in compose(), which only runs after mount.
    # Confirm classes are wired by attribute presence.
    assert hasattr(mode, "_selected_id")
    assert mode._selected_id is None


async def test_update_data_populates_belt_and_alert_strip(status_with_peers: Status) -> None:
    from textual.app import App

    class _Harness(App):
        def compose(self):
            yield TheBaseMode(id="tb")

    rates = RateHistory()
    async with _Harness().run_test() as pilot:
        mode = pilot.app.query_one(TheBaseMode)
        mode.update_data(status_with_peers, rates)
        # Belt got the status.
        belt = pilot.app.query_one(BeltView)
        assert belt.hub_peer is not None
        assert belt.hub_peer.host_name == "the-base"
        # Alert strip reflects the offline peer.
        strip = pilot.app.query_one(AlertStrip)
        plain = strip.renderable.plain if hasattr(strip.renderable, "plain") else str(strip.renderable)
        assert "1 offline" in plain


async def test_default_selection_is_first_online_peer(status_with_peers: Status) -> None:
    from textual.app import App

    class _Harness(App):
        def compose(self):
            yield TheBaseMode(id="tb")

    rates = RateHistory()
    async with _Harness().run_test() as pilot:
        mode = pilot.app.query_one(TheBaseMode)
        mode.update_data(status_with_peers, rates)
        assert mode._selected_id == "p1"
        # Detail pane was updated for the selected peer (we trust the wiring; the
        # DetailPane's own tests cover its rendering).
```

- [ ] **Step 2: Run — confirm failure**

```bash
uv --project tailtop run pytest --rootdir tailtop -q tailtop/tests/test_the_base.py
```

Expected: `ModuleNotFoundError: No module named 'tailtop.modes.the_base'`.

- [ ] **Step 3: Implement `tailtop/tailtop/modes/the_base.py`**

```python
"""TheBase mode — animated belt topology dashboard. Intent: see your tailnet.

Composes:
    header  · tailnet name + online/total + aggregate ↓/↑
    alert   · offline count + expiring-key warnings + backend state
    belt    · BeltView (Hub or Bus, animated dual-lane belts)
    detail  · DetailPane for the selected peer

Selection is propagated to ``app.selected_peer_id`` so the existing verbs
(ping/ssh/copy IP/...) target the selected peer just like in Comfort.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from tailtop.data.models import Peer, Status
from tailtop.modes.base import ModeView
from tailtop.state import RateHistory, human_rate
from tailtop.widgets.alert_strip import AlertStrip
from tailtop.widgets.belt import BeltView
from tailtop.widgets.detail_pane import DetailPane


class TheBaseMode(ModeView):
    """Belt-centric dashboard mode."""

    cadence = 2.0

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._selected_id: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(id="tb-header")
            yield AlertStrip(id="tb-alert")
            with Horizontal(id="tb-body"):
                yield BeltView(id="tb-belt")
                yield DetailPane(id="tb-detail")

    def on_mount(self) -> None:
        self.query_one(DetailPane).show_empty("Loading the base…")

    def update_data(self, status: Status, rates: RateHistory) -> None:
        import time
        now = time.monotonic()

        # Header.
        agg_rx = sum(rates.current_rx(p.id) for p in status.peers)
        agg_tx = sum(rates.current_tx(p.id) for p in status.peers)
        header = Text()
        header.append("▌ TAILNET · THE BASE", style="bold #8bb6ff")
        header.append("   ")
        if status.connected:
            header.append(f"{status.online_count}/{status.total_count} online", style="#7be39b")
        else:
            header.append(status.backend_state, style="#f0c674")
        header.append("   ")
        header.append(f"↓{human_rate(agg_rx)}  ↑{human_rate(agg_tx)}", style="dim")
        self.query_one("#tb-header", Static).update(header)

        # Alert strip.
        self.query_one(AlertStrip).set_status(status)

        # Belt.
        self.query_one(BeltView).update_data(status, rates, now=now)

        # Default selection: first online peer if none chosen.
        if self._selected_id is None:
            for p in status.peers:
                if p.online:
                    self._select(p, status)
                    break

        # Push current selection into the belt and detail pane.
        if self._selected_id is not None:
            self.query_one(BeltView).set_selected(self._selected_id)
            peer = next((p for p in status.peers if p.id == self._selected_id), None)
            if peer is not None:
                self.query_one(DetailPane).update_peer(peer)
            else:
                self.query_one(DetailPane).show_empty("Selected peer is gone")

    def _select(self, peer: Peer, status: Status) -> None:
        self._selected_id = peer.id
        self.query_one(DetailPane).update_peer(peer)
        self.query_one(BeltView).set_selected(peer.id)
        # propagate to app-level selection so existing verbs target it
        if hasattr(self.app, "selected_peer_id"):
            self.app.selected_peer_id = peer.id
```

- [ ] **Step 4: Add tcss for TheBaseMode chrome**

Append to `tailtop/tailtop/themes/base.tcss`:

```css
/* ---- TheBase layout ---- */

#tb-header {
    height: 1;
    padding: 0 1;
    color: #cfd3da;
    border-bottom: solid #23232c;
}

#tb-alert {
    height: 1;
    padding: 0 1;
    border-bottom: solid #23232c;
}

#tb-body {
    height: 1fr;
}

#tb-belt {
    width: 1fr;
}

#tb-detail {
    width: 36;
    padding: 1 2;
    border-left: solid #23232c;
}
```

- [ ] **Step 5: Run — confirm pass**

```bash
uv --project tailtop run pytest --rootdir tailtop -q tailtop/tests
```

Expected: 80 passing (76 prior + 4 new).

- [ ] **Step 6: Commit**

```bash
git add tailtop/tailtop/modes/the_base.py tailtop/tests/test_the_base.py tailtop/tailtop/themes/base.tcss
git commit -m "feat(tailtop): add TheBaseMode composing header + alert + belt + detail"
```

---

## Task 4: Wire TheBaseMode into the app

Add to `MODE_ORDER`, mount in `compose`, register the import.

**Files:**
- Modify: `tailtop/tailtop/app.py`

- [ ] **Step 1: Add an integration test**

Append to `tailtop/tests/test_the_base.py`:

```python
async def test_tab_cycles_into_the_base() -> None:
    from tailtop.app import TailtopApp
    app = TailtopApp(auto_poll=False)
    async with app.run_test() as pilot:
        # Cycle until we reach TheBaseMode.
        seen = []
        for _ in range(5):
            seen.append(app.active_mode)
            if app.active_mode == "the_base":
                break
            await pilot.press("tab")
        assert "the_base" in seen
```

- [ ] **Step 2: Run — confirm failure**

```bash
uv --project tailtop run pytest --rootdir tailtop -q tailtop/tests/test_the_base.py::test_tab_cycles_into_the_base
```

Expected: assertion failure (the_base not in seen).

- [ ] **Step 3: Edit `tailtop/tailtop/app.py`**

Find the imports block and add:

```python
from tailtop.modes.the_base import TheBaseMode
```

Find `MODE_ORDER = ["comfort", "cockpit", "observatory"]` and change to:

```python
    MODE_ORDER = ["comfort", "cockpit", "observatory", "the_base"]
```

Find the `compose` method and add a fourth mode mount before the `StatusBar`:

```python
    def compose(self) -> ComposeResult:
        with ContentSwitcher(initial="comfort", id="modes"):
            yield ComfortMode(id="comfort")
            yield CockpitMode(id="cockpit")
            yield ObservatoryMode(id="observatory")
            yield TheBaseMode(id="the_base")
        yield StatusBar(id="statusbar")
```

- [ ] **Step 4: Run — confirm pass**

```bash
uv --project tailtop run pytest --rootdir tailtop -q tailtop/tests
```

Expected: 81 passing (80 prior + 1 new). All existing app tests still green — the cycle just gains one more stop.

- [ ] **Step 5: Commit**

```bash
git add tailtop/tailtop/app.py
git commit -m "feat(tailtop): register TheBaseMode in the Tab cycle"
```

---

## Task 5: Disconnected + empty-state polish

Two edge cases from spec §10 that should not crash and should communicate clearly.

**Files:**
- Modify: `tailtop/tailtop/modes/the_base.py`
- Modify: `tailtop/tests/test_the_base.py`

- [ ] **Step 1: Add failing tests**

Append to `tailtop/tests/test_the_base.py`:

```python
async def test_disconnected_state_shows_helpful_header() -> None:
    from tailtop.app import TailtopApp
    from tailtop.data.models import Status

    status = Status(
        version="dev", backend_state="NeedsLogin", tailscale_ips=[],
        magic_dns_suffix="", user_display="",
        self_peer=_self(), peers=[],
    )
    app = TailtopApp(auto_poll=False)
    async with app.run_test() as pilot:
        for _ in range(4):
            if app.active_mode == "the_base":
                break
            await pilot.press("tab")
        rates = RateHistory()
        mode = pilot.app.query_one(TheBaseMode)
        mode.update_data(status, rates)
        from tailtop.widgets.alert_strip import AlertStrip
        strip = pilot.app.query_one(AlertStrip)
        plain = strip.renderable.plain if hasattr(strip.renderable, "plain") else str(strip.renderable)
        assert "NeedsLogin" in plain


async def test_empty_tailnet_does_not_crash_or_select() -> None:
    from tailtop.app import TailtopApp
    from tailtop.data.models import Status

    status = Status(
        version="dev", backend_state="Running", tailscale_ips=["100.64.0.1"],
        magic_dns_suffix="example.ts.net", user_display="me",
        self_peer=_self(), peers=[],
    )
    app = TailtopApp(auto_poll=False)
    async with app.run_test() as pilot:
        for _ in range(4):
            if app.active_mode == "the_base":
                break
            await pilot.press("tab")
        rates = RateHistory()
        mode = pilot.app.query_one(TheBaseMode)
        mode.update_data(status, rates)
        assert mode._selected_id is None
```

- [ ] **Step 2: Run — confirm pass without changes**

The disconnected test should pass already (AlertStrip handles non-Running state); empty-tailnet test passes if `update_data` already guards against empty peers — which it does (`for p in status.peers: if p.online` won't enter the loop).

```bash
uv --project tailtop run pytest --rootdir tailtop -q tailtop/tests/test_the_base.py
```

Expected: 7 passing in this file (4 from Task 3 + 1 from Task 4 + 2 new). If anything fails, the harness flagged a real bug — investigate and patch.

> Note: this task may end up being purely test-additive ("characterization tests") if the prior code handled edges. That's a valid TDD outcome — we lock in the behavior with tests we didn't have before.

- [ ] **Step 3: Commit**

```bash
git add tailtop/tests/test_the_base.py
git commit -m "test(tailtop): cover disconnected + empty-tailnet edges for TheBaseMode"
```

---

## Task 6: Wrap-up — full suite, lint, demo verification

- [ ] **Step 1: Full test suite verbose**

```bash
uv --project tailtop run pytest --rootdir tailtop -v tailtop/tests
```

Expected: 83 passing.

- [ ] **Step 2: Lint check across new + modified files**

```bash
uv --project tailtop run --with ruff ruff check \
  tailtop/tailtop/widgets/belt.py \
  tailtop/tailtop/widgets/alert_strip.py \
  tailtop/tailtop/modes/the_base.py \
  tailtop/tailtop/app.py
```

Expected: clean. If issues, fix and re-run; commit as `style(tailtop): ruff cleanup for the-base mode`.

- [ ] **Step 3: Manual verification (controller, not subagent)**

The controller runs the full app — NOT the subagent. The subagent reports DONE and lets the controller do this step:

```bash
uv --project tailtop run python -m tailtop.app
```

Expected:
- App launches.
- Press `Tab` three times to reach TheBaseMode — header reads "TAILNET · THE BASE", belt visible, treads animating, detail pane on the right.
- Press `Tab` again to cycle back to Comfort.
- Note: keyboard selection navigation inside TheBaseMode is deferred (see "Out of scope" below). Selection still flows in from ComfortMode's `app.selected_peer_id` if you select a peer there first, then `Tab` over.

- [ ] **Step 4: Revisit spec §14 open questions**

Closed by Phase 2:
- ✅ Hub aggregate ↓/↑ — now shown.
- ✅ Selection wiring — `app.selected_peer_id` propagation when peer chosen elsewhere.

Still open (deferred to a future polish iteration):
- Letter shortcut for TheBaseMode (Tab works; a dedicated letter is post-MVP).
- Threshold tuning + sticky-slot duration tuning — feel-test against a real busy tailnet.
- Hub self-selection — not yet supported.

- [ ] **Step 5: Final commit (if any cleanup occurred), then report**

Phase 2 complete. Report:
- Total commits: ~6
- Total tests now passing: 83
- New widgets: AlertStrip
- New modes: TheBaseMode
- BeltView extensions: aggregate hub card, per-peer rate label, overflow chip test

---

## Out of scope for Phase 2

Deferred to a future polish iteration:
- **Keyboard selection navigation inside TheBaseMode** (`↑/↓`, `j/k`). Requires focus-discipline work across the ContentSwitcher; selection inflows via `app.selected_peer_id` for now.
- Letter shortcut for TheBaseMode in the global `Tab`/`?` help.
- Grid layout (spec §13 future).
- Tunable thresholds (Phase 1 `BUSY_BPS`/`HEAVY_BPS` exposed via settings).
- Sound on heavy spikes (spec §13 future).
- Recording / playback.
- Multi-tailnet visual treatment.
- Snapshot-image tests (Textual snapshot fixtures) — current tests assert on character / Rich text contents.
