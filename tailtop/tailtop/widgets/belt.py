"""Belt-style topology widget.

Renders the local node as a hub and online peers as belted nodes with
animated dual-lane conveyor belts. Tread speed scales with bandwidth.

See docs/superpowers/specs/2026-06-06-tailtop-belt-view-spec.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from tailtop.data.models import Peer


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
