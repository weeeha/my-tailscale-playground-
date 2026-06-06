"""Localization + the rule-based activity state machine (design doc §5).

Rule-first on purpose: explainable today, and it generates the labeled ground
truth you later train an ML classifier on. Each ``classify`` call returns
(room, activity, confidence) from the current fused world state.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import config as C


@dataclass
class WorldState:
    """Latest known value per signal, with timestamps so stale data decays out."""

    now: float = 0.0
    _motion: dict[str, tuple[float, float]] = field(default_factory=dict)   # room -> (val, ts)
    _breath: dict[str, tuple[float, float]] = field(default_factory=dict)   # room -> (bpm, ts)
    _ctx: dict[str, tuple[bool, float]] = field(default_factory=dict)       # key  -> (val, ts)

    # -- ingest ----
    def set_motion(self, room: str, val: float, ts: float) -> None:
        self._motion[room] = (val, ts)

    def set_breathing(self, room: str, bpm: float, ts: float) -> None:
        self._breath[room] = (bpm, ts)

    def set_context(self, key: str, val: bool, ts: float) -> None:
        self._ctx[key] = (val, ts)

    # -- fresh accessors ----
    def motion(self, room: str) -> float:
        val, ts = self._motion.get(room, (0.0, 0.0))
        return val if (self.now - ts) <= C.STALE_S else 0.0

    def breathing(self, room: str) -> float:
        bpm, ts = self._breath.get(room, (0.0, 0.0))
        return bpm if (self.now - ts) <= C.STALE_S else 0.0

    def ctx(self, key: str) -> bool:
        val, ts = self._ctx.get(key, (False, 0.0))
        return bool(val) if (self.now - ts) <= C.STALE_S else False


def is_night(ts: float) -> bool:
    h = time.localtime(ts).tm_hour
    return h >= C.NIGHT_START_H or h < C.NIGHT_END_H


def current_room(ws: WorldState) -> str | None:
    """L1 localization: the room with the strongest fresh evidence of a person."""
    best, best_motion = None, 0.0
    for room in C.ROOMS:
        m = ws.motion(room)
        if m > best_motion:
            best, best_motion = room, m
    if best is not None and best_motion >= C.MOTION_OCCUPIED:
        return best
    # nobody's moving much — a still person shows up only as breathing
    for room in C.ROOMS:
        if ws.breathing(room) > 0:
            return room
    return None


def classify(ws: WorldState) -> tuple[str, str, float]:
    """Return (room, activity, confidence). Rules are checked most-specific first."""
    room = current_room(ws)
    if room is None:
        return ("", C.AWAY, 0.9)

    motion = ws.motion(room)

    # bedroom + still + breathing rhythm at night ⇒ asleep
    if room == "bedroom" and motion < C.MOTION_OCCUPIED and ws.breathing("bedroom") > 0:
        return (room, C.SLEEPING, 0.9 if is_night(ws.now) else 0.6)

    # L3 device context dominates wherever it exists
    if room == "living" and ws.ctx(C.CTX_PLAYSTATION):
        return (room, C.GAMING, 0.95)
    if room == "living" and ws.ctx(C.CTX_TV):
        return (room, C.WATCHING, 0.9)
    if room == "office" and ws.ctx(C.CTX_PC_ACTIVE):
        return (room, C.WORKING, 0.9)
    if room == "kitchen" and (
        ws.ctx(C.CTX_FRIDGE_OPEN) or ws.ctx(C.CTX_KETTLE_ON) or motion >= C.MOTION_ACTIVE
    ):
        return (room, C.COOKING, 0.8)
    if room == "bathroom":
        return (room, C.BATHROOM, 0.85)

    # present in the room but nothing specific to say
    return (room, C.IDLE, 0.5)
