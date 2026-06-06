"""Belt-style topology widget.

Renders the local node as a hub and online peers as belted nodes with
animated dual-lane conveyor belts. Tread speed scales with bandwidth.

See docs/superpowers/specs/2026-06-06-tailtop-belt-view-spec.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from rich.text import Text
from textual.widget import Widget

from tailtop.data.models import ConnType, Peer, Status
from tailtop.state import RateHistory


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
    rx_bps: float = 0.0
    tx_bps: float = 0.0


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
        aggregate_rx: float = 0.0,
        aggregate_tx: float = 0.0,
    ) -> None:
        cx, cy = canvas.width // 2, canvas.height // 2

        # Hub card at center (3 lines: name / aggregate / count).
        name = hub_peer.host_name[:18] or "self"
        canvas.write(cx - len(name) // 2, cy, name, HUB_CARD_STYLE)
        agg = f"▣ ↓{self._compact_rate(aggregate_rx)} ↑{self._compact_rate(aggregate_tx)}"
        canvas.write(cx - len(agg) // 2, cy + 1, agg, DIM)

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
                py = max(0, trunk_y - 3)
                self._draw_belt(canvas, b.x_offset, trunk_y, b.x_offset, py, state, dim)
                self._draw_peer_card(canvas, b.x_offset, py - 1, peer, state, dim)
            else:
                py = min(canvas.height - 1, trunk_y + 3)
                self._draw_belt(canvas, b.x_offset, trunk_y, b.x_offset, py, state, dim)
                self._draw_peer_card(canvas, b.x_offset, py + 1, peer, state, dim)

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
        rate = f"↓{self._compact_rate(state.rx_bps)} ↑{self._compact_rate(state.tx_bps)}"
        rate_style = "dim " + DIM if dim else DIM
        canvas.write(x - len(rate) // 2, y + 1, rate, rate_style)

    def _compact_rate(self, bps: float) -> str:
        """Compact rate string: '0', '95K', '1.2M', '25.8M'."""
        if bps < 1000:
            return f"{int(bps)}"
        if bps < 1_000_000:
            return f"{int(bps / 1000)}K"
        return f"{bps / 1_000_000:.1f}M"

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

        if abs(x1 - x0) >= abs(y1 - y0):
            glyph = LANE_HORIZONTAL.get(state.conn_type, "─")
            step = 1 if x1 > x0 else -1
            for x in range(x0 + step, x1, step):
                canvas.set(x, y0, glyph, lane_style)
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
        in_arrow = "down" if going_up else "up"
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
        self._latest_rates: dict[str, tuple[float, float]] = {}
        self._aggregate_rx: float = 0.0
        self._aggregate_tx: float = 0.0

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
            state.rx_bps = rx
            state.tx_bps = tx

        self._latest_rates = rate_map

        # Drop departed peers.
        for gone in list(self.belt_states.keys()):
            if gone not in self.peers_by_id:
                self.belt_states.pop(gone, None)

        self._aggregate_rx = sum(s.rx_bps for s in self.belt_states.values())
        self._aggregate_tx = sum(s.tx_bps for s in self.belt_states.values())

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
        # Logical lane length: matches the arm length used in render_hub
        # (cells from hub center to peer card minus the two endpoint cells).
        arm = max(self.size.width, self.size.height) // 6
        length = max(2, arm - 1)
        for state in self.belt_states.values():
            state.in_lane.advance(dt=dt, length=length)
            state.out_lane.advance(dt=dt, length=length)
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
                aggregate_rx=self._aggregate_rx,
                aggregate_tx=self._aggregate_tx,
            )
            if self.overflow_count > 0:
                msg = f"+{self.overflow_count} more"
                canvas.write(width // 2 - len(msg) // 2, height - 2, msg, DIM)
        else:
            branches = self.bus_layout.arrange(
                peers=[p for p in self.peers_by_id.values() if not p.is_self],
                rates=self._latest_rates,
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
