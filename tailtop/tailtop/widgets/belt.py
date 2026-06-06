"""Belt-style topology widget.

Renders the local node as a hub and online peers as belted nodes with
animated dual-lane conveyor belts. Tread speed scales with bandwidth.

See docs/superpowers/specs/2026-06-06-tailtop-belt-view-spec.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from rich.text import Text

from tailtop.data.models import ConnType, Peer


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
        canvas.write(0, trunk_y, name, HUB_CARD_STYLE)
        canvas.write(len(name), trunk_y, "═", HUB_CARD_STYLE)

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
