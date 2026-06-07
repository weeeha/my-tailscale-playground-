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
    """One direction of a belt lane. ``phase`` selects which cells show the
    chevron glyph each tick; ``cells_per_second`` drives the march speed."""

    cells_per_second: float = 0.0
    phase: float = 0.0

    SPACING: int = 2  # class constant

    def advance(self, dt: float, length: int = 0) -> None:
        """Advance the march phase by ``cells_per_second * dt``, wrapping at SPACING.

        ``length`` is accepted for backward compatibility with prior tests but
        is no longer used."""
        if self.cells_per_second <= 0:
            return
        self.phase = (self.phase + self.cells_per_second * dt) % self.SPACING


class TreadAnimator:
    """Pure math: rate → tread speed (cells/s) and intensity tier."""

    # Rate thresholds (bytes/second).
    BUSY_BPS = 100_000           # 100 KB/s — light/busy boundary
    HEAVY_BPS = 5_000_000        # 5 MB/s — busy/heavy boundary

    # Tread speed clamp (cells per second).
    MIN_CELLS_PER_S = 0.5        # ~2 s per advance at idle-ish
    MAX_CELLS_PER_S = 8.0        # ~0.125 s per advance at heavy

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


# ---- Styles ----

TIER_STYLE = {
    "heavy": "bold #ffd166",
    "busy":  "#7be39b",
    "light": "#5b9bd5",
    "idle":  "dim #6b6f78",
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


class BeltRenderer:
    """Paints belts onto a CharCanvas. Pure: no Textual, no I/O."""

    PEER_CARD_W = 14  # interior width
    PEER_CARD_H = 4   # ┌─┐ + name + rate + └─┘

    HUB_CARD_W = 16
    HUB_CARD_H = 5

    def _vchevron(self, going_up: bool) -> str:
        return "▲" if going_up else "▼"

    def _hchevron(self, going_left: bool) -> str:
        return "◀" if going_left else "▶"

    def _draw_vlane(
        self,
        canvas: CharCanvas,
        x: int,
        y_top: int,
        y_bot: int,
        going_up: bool,
        phase: float,
        tier: str,
        dim: bool,
    ) -> None:
        """Vertical lane: draws a chevron stripe in column x from y_top..y_bot inclusive.
        Idle tier draws nothing."""
        if tier == "idle":
            return
        style = TIER_STYLE.get(tier, "")
        if dim:
            style = "dim " + style if style else "dim"
        glyph = self._vchevron(going_up)
        spacing = LaneState.SPACING
        offset = int(phase)
        for i, y in enumerate(range(min(y_top, y_bot), max(y_top, y_bot) + 1)):
            if (i + offset) % spacing == 0:
                canvas.set(x, y, glyph, style)

    def _draw_hlane(
        self,
        canvas: CharCanvas,
        y: int,
        x_left: int,
        x_right: int,
        going_left: bool,
        phase: float,
        tier: str,
        dim: bool,
    ) -> None:
        """Horizontal lane: chevron stripe in row y from x_left..x_right inclusive."""
        if tier == "idle":
            return
        style = TIER_STYLE.get(tier, "")
        if dim:
            style = "dim " + style if style else "dim"
        glyph = self._hchevron(going_left)
        spacing = LaneState.SPACING
        offset = int(phase)
        for i, x in enumerate(range(min(x_left, x_right), max(x_left, x_right) + 1)):
            if (i + offset) % spacing == 0:
                canvas.set(x, y, glyph, style)

    def _draw_peer_card(
        self,
        canvas: CharCanvas,
        cx: int,  # center x of the card
        top_y: int,  # top row of the box
        peer: Peer,
        state: BeltState,
        dim: bool,
    ) -> None:
        """Draw a bordered peer card. cx is the horizontal anchor (center of card)."""
        w = self.PEER_CARD_W
        left = cx - w // 2
        right = left + w - 1
        name = peer.host_name[:w - 2]
        rate = f"↑{self._compact_rate(state.tx_bps)} ↓{self._compact_rate(state.rx_bps)}"[:w - 2]

        border_style = TIER_STYLE.get(state.in_tier, "")
        if dim:
            border_style = "dim " + border_style if border_style else "dim"

        # Top border: ┌──...──┐
        canvas.set(left, top_y, "┌", border_style)
        for x in range(left + 1, right):
            canvas.set(x, top_y, "─", border_style)
        canvas.set(right, top_y, "┐", border_style)
        # Name row: │ name │
        canvas.set(left, top_y + 1, "│", border_style)
        canvas.write(left + 2, top_y + 1, name.ljust(w - 2)[:w - 2], "" if not dim else "dim")
        canvas.set(right, top_y + 1, "│", border_style)
        # Rate row: │ rate │
        canvas.set(left, top_y + 2, "│", border_style)
        canvas.write(left + 2, top_y + 2, rate.ljust(w - 2)[:w - 2], "dim")
        canvas.set(right, top_y + 2, "│", border_style)
        # Bottom border: └──...──┘
        canvas.set(left, top_y + 3, "└", border_style)
        for x in range(left + 1, right):
            canvas.set(x, top_y + 3, "─", border_style)
        canvas.set(right, top_y + 3, "┘", border_style)

    def _draw_hub_card(
        self,
        canvas: CharCanvas,
        left: int,
        top: int,
        hub_peer: Peer,
        aggregate_rx: float,
        aggregate_tx: float,
    ) -> None:
        w = self.HUB_CARD_W
        right = left + w - 1
        name = hub_peer.host_name[:w - 2]
        agg = f"↓{self._compact_rate(aggregate_rx)} ↑{self._compact_rate(aggregate_tx)}"[:w - 2]
        style = HUB_CARD_STYLE
        # Top
        canvas.set(left, top, "┌", style)
        for x in range(left + 1, right):
            canvas.set(x, top, "─", style)
        canvas.set(right, top, "┐", style)
        # ▣ THE BASE row, centered
        title = "▣ THE BASE"
        title_x = left + (w - len(title)) // 2
        canvas.set(left, top + 1, "│", style)
        canvas.write(title_x, top + 1, title, style)
        canvas.set(right, top + 1, "│", style)
        # Aggregate row
        agg_x = left + (w - len(agg)) // 2
        canvas.set(left, top + 2, "│", style)
        canvas.write(agg_x, top + 2, agg, "dim")
        canvas.set(right, top + 2, "│", style)
        # Hostname row
        name_x = left + (w - len(name)) // 2
        canvas.set(left, top + 3, "│", style)
        canvas.write(name_x, top + 3, name, "dim")
        canvas.set(right, top + 3, "│", style)
        # Bottom
        canvas.set(left, top + 4, "└", style)
        for x in range(left + 1, right):
            canvas.set(x, top + 4, "─", style)
        canvas.set(right, top + 4, "┘", style)

    def _compact_rate(self, bps: float) -> str:
        """Compact rate string: '0', '95K', '1.2M', '25.8M'."""
        if bps < 1000:
            return f"{int(bps)}"
        if bps < 1_000_000:
            return f"{int(bps / 1000)}K"
        return f"{bps / 1_000_000:.1f}M"

    def render_bus(
        self,
        *,
        canvas: CharCanvas,
        branches: list[BusBranch],
        belt_states: dict[str, BeltState],
        hub_peer: Peer,
        peers_by_id: dict[str, Peer],
        selected_id: str | None,
        aggregate_rx: float = 0.0,
        aggregate_tx: float = 0.0,
    ) -> None:
        if canvas.width < self.HUB_CARD_W + 20 or canvas.height < self.HUB_CARD_H + self.PEER_CARD_H * 2 + 4:
            # Too small — emit a hint
            canvas.write(0, 0, "Resize terminal for The Base", "dim")
            return

        # Hub anchored at right edge, vertically centered.
        hub_top = (canvas.height - self.HUB_CARD_H) // 2
        hub_left = canvas.width - self.HUB_CARD_W - 1
        self._draw_hub_card(canvas, hub_left, hub_top, hub_peer, aggregate_rx, aggregate_tx)

        # Trunk runs horizontally in two rows just above and just below the hub's vertical center.
        trunk_top_y = hub_top + self.HUB_CARD_H // 2 - 1
        trunk_bot_y = trunk_top_y + 1
        trunk_left = 2
        trunk_right = hub_left - 1
        if trunk_left >= trunk_right:
            return

        # Trunk lanes: top = inbound toward hub (◀), bottom = outbound from hub (▶).
        # Aggregate phase: average of per-peer phases is a reasonable proxy. Sum the
        # in/out cells_per_second to find the trunk's perceived speed.
        agg_in_tier = "heavy" if aggregate_rx >= 5_000_000 else ("busy" if aggregate_rx >= 100_000 else ("light" if aggregate_rx > 0 else "idle"))
        agg_out_tier = "heavy" if aggregate_tx >= 5_000_000 else ("busy" if aggregate_tx >= 100_000 else ("light" if aggregate_tx > 0 else "idle"))
        # We don't have a separate trunk phase; reuse phase of first non-idle lane as a stand-in.
        trunk_in_phase = next((s.in_lane.phase for s in belt_states.values() if s.in_tier != "idle"), 0.0)
        trunk_out_phase = next((s.out_lane.phase for s in belt_states.values() if s.out_tier != "idle"), 0.0)

        self._draw_hlane(canvas, trunk_top_y, trunk_left, trunk_right, going_left=True, phase=trunk_in_phase, tier=agg_in_tier, dim=False)
        self._draw_hlane(canvas, trunk_bot_y, trunk_left, trunk_right, going_left=False, phase=trunk_out_phase, tier=agg_out_tier, dim=False)

        # Hub join: a couple of dashes from trunk to hub card edge.
        if hub_left - 1 > trunk_right:
            for x in range(trunk_right + 1, hub_left):
                canvas.set(x, trunk_top_y, "─", HUB_CARD_STYLE)
                canvas.set(x, trunk_bot_y, "─", HUB_CARD_STYLE)

        # Branches.
        top_card_top = trunk_top_y - 2 - self.PEER_CARD_H  # peer card ends 2 cells above trunk
        top_lane_top = top_card_top + self.PEER_CARD_H  # branch lane starts at peer card bottom
        bot_card_top = trunk_bot_y + 3  # peer card starts 3 cells below trunk
        bot_lane_bot = bot_card_top - 1  # branch lane ends 1 cell above peer card

        for b in branches:
            peer = peers_by_id.get(b.peer_id)
            state = belt_states.get(b.peer_id)
            if peer is None or state is None or peer.is_self:
                continue
            dim = selected_id is not None and selected_id != b.peer_id

            cx = b.x_offset
            if cx < trunk_left + 1 or cx > trunk_right - 1:
                continue  # branch x off-canvas

            if b.side == "top":
                # Peer card above
                if top_card_top < 0:
                    continue
                self._draw_peer_card(canvas, cx, top_card_top, peer, state, dim)
                # Two-column branch lane between peer card bottom and trunk top
                left_x = cx - 1
                right_x = cx
                if right_x > trunk_right or left_x < trunk_left:
                    continue
                self._draw_vlane(canvas, left_x, top_lane_top, trunk_top_y - 1,
                                 going_up=True, phase=state.in_lane.phase,
                                 tier=state.in_tier, dim=dim)
                self._draw_vlane(canvas, right_x, top_lane_top, trunk_top_y - 1,
                                 going_up=False, phase=state.out_lane.phase,
                                 tier=state.out_tier, dim=dim)
            else:
                # Peer card below
                if bot_card_top + self.PEER_CARD_H > canvas.height:
                    continue
                self._draw_peer_card(canvas, cx, bot_card_top, peer, state, dim)
                left_x = cx - 1
                right_x = cx
                if right_x > trunk_right or left_x < trunk_left:
                    continue
                # Going DOWN from trunk to peer
                self._draw_vlane(canvas, left_x, trunk_bot_y + 1, bot_lane_bot,
                                 going_up=False, phase=state.in_lane.phase,
                                 tier=state.in_tier, dim=dim)
                self._draw_vlane(canvas, right_x, trunk_bot_y + 1, bot_lane_bot,
                                 going_up=True, phase=state.out_lane.phase,
                                 tier=state.out_tier, dim=dim)

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
        if canvas.width < self.HUB_CARD_W + 30 or canvas.height < self.HUB_CARD_H + 12:
            canvas.write(0, 0, "Resize terminal for The Base", "dim")
            return

        # Hub centered.
        cx = canvas.width // 2
        cy = canvas.height // 2
        hub_left = cx - self.HUB_CARD_W // 2
        hub_top = cy - self.HUB_CARD_H // 2
        self._draw_hub_card(canvas, hub_left, hub_top, hub_peer, aggregate_rx, aggregate_tx)

        # Each slot: place the peer card and a two-column belt connecting it to the hub.
        for peer_id, slot in layout._slot_of.items():
            peer = peers_by_id.get(peer_id)
            state = belt_states.get(peer_id)
            if peer is None or state is None:
                continue
            dim = selected_id is not None and selected_id != peer_id

            if slot == "N":
                pcx = cx
                pcy = max(0, hub_top - 5 - self.PEER_CARD_H)
                self._draw_peer_card(canvas, pcx, pcy, peer, state, dim)
                # vertical belt from peer card bottom to hub top
                lane_top = pcy + self.PEER_CARD_H
                lane_bot = hub_top - 1
                if lane_bot >= lane_top:
                    self._draw_vlane(canvas, pcx - 1, lane_top, lane_bot,
                                     going_up=False, phase=state.in_lane.phase, tier=state.in_tier, dim=dim)
                    self._draw_vlane(canvas, pcx, lane_top, lane_bot,
                                     going_up=True, phase=state.out_lane.phase, tier=state.out_tier, dim=dim)
            elif slot == "S":
                pcx = cx
                pcy = min(canvas.height - self.PEER_CARD_H, hub_top + self.HUB_CARD_H + 5)
                self._draw_peer_card(canvas, pcx, pcy, peer, state, dim)
                lane_top = hub_top + self.HUB_CARD_H
                lane_bot = pcy - 1
                if lane_bot >= lane_top:
                    self._draw_vlane(canvas, pcx - 1, lane_top, lane_bot,
                                     going_up=True, phase=state.in_lane.phase, tier=state.in_tier, dim=dim)
                    self._draw_vlane(canvas, pcx, lane_top, lane_bot,
                                     going_up=False, phase=state.out_lane.phase, tier=state.out_tier, dim=dim)
            elif slot == "E":
                pcx = min(canvas.width - self.PEER_CARD_W // 2 - 1, hub_left + self.HUB_CARD_W + self.PEER_CARD_W // 2 + 5)
                pcy = hub_top + 1
                self._draw_peer_card(canvas, pcx, pcy, peer, state, dim)
                lane_left = hub_left + self.HUB_CARD_W
                lane_right = pcx - self.PEER_CARD_W // 2 - 1
                if lane_right >= lane_left:
                    self._draw_hlane(canvas, hub_top + self.HUB_CARD_H // 2 - 1, lane_left, lane_right,
                                     going_left=True, phase=state.in_lane.phase, tier=state.in_tier, dim=dim)
                    self._draw_hlane(canvas, hub_top + self.HUB_CARD_H // 2, lane_left, lane_right,
                                     going_left=False, phase=state.out_lane.phase, tier=state.out_tier, dim=dim)
            elif slot == "W":
                pcx = max(self.PEER_CARD_W // 2, hub_left - self.PEER_CARD_W // 2 - 5)
                pcy = hub_top + 1
                self._draw_peer_card(canvas, pcx, pcy, peer, state, dim)
                lane_left = pcx + self.PEER_CARD_W // 2 + 1
                lane_right = hub_left - 1
                if lane_right >= lane_left:
                    self._draw_hlane(canvas, hub_top + self.HUB_CARD_H // 2 - 1, lane_left, lane_right,
                                     going_left=False, phase=state.in_lane.phase, tier=state.in_tier, dim=dim)
                    self._draw_hlane(canvas, hub_top + self.HUB_CARD_H // 2, lane_left, lane_right,
                                     going_left=True, phase=state.out_lane.phase, tier=state.out_tier, dim=dim)
            # Diagonal slots (NE/NW/SE/SW) — omit for v1; only top 4 cardinals get rendered.


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
        for state in self.belt_states.values():
            state.in_lane.advance(dt=dt)
            state.out_lane.advance(dt=dt)
        self.refresh()

    def render(self):
        width = max(self.size.width, 80)
        height = max(self.size.height, 24)
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
                aggregate_rx=self._aggregate_rx,
                aggregate_tx=self._aggregate_tx,
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
