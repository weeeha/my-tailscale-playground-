"""Fusion service: sensor events → fused state → timeline segments.

Maintains the live ``WorldState``, samples a fused (room, activity) on a tick,
and coalesces consecutive identical states into ``Segment`` rows. This is the
"brain" node from the design doc; here it runs in-process over the local bus.
"""

from __future__ import annotations

from collections.abc import Iterable

from . import config as C
from . import rules
from .model import KIND_BREATHING, KIND_CONTEXT, KIND_MOTION, Segment, SensorEvent, StateSample
from .store import Store


class Fusion:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.ws = rules.WorldState()
        self._open: Segment | None = None

    # -- ingest one edge event ----------------------------------------------
    def ingest(self, ev: SensorEvent) -> None:
        self.ws.now = max(self.ws.now, ev.ts)
        room = C.NODES.get(ev.node_id, "")
        if ev.kind == KIND_MOTION and room:
            self.ws.set_motion(room, float(ev.features.get("motion", 0.0)), ev.ts)
        elif ev.kind == KIND_BREATHING and room:
            self.ws.set_breathing(room, float(ev.features.get("bpm", 0.0)), ev.ts)
        elif ev.kind == KIND_CONTEXT:
            self.ws.set_context(str(ev.features["key"]), bool(ev.features["value"]), ev.ts)

    # -- sample the fused state and extend/close segments --------------------
    def tick(self, now: float) -> StateSample:
        self.ws.now = now
        room, activity, conf = rules.classify(self.ws)
        sample = StateSample(now, room, activity, self.ws.motion(room) if room else 0.0, conf)
        self.store.add_state_sample(sample)
        self._advance_segment(room, activity, now)
        return sample

    def _advance_segment(self, room: str, activity: str, now: float) -> None:
        cur = self._open
        if cur is not None and cur.room == room and cur.activity == activity:
            cur.end_ts = now  # extend
            return
        if cur is not None:
            cur.end_ts = now
            self.store.add_segment(cur)
        self._open = Segment(start_ts=now, end_ts=now, room=room, activity=activity)

    def flush(self, now: float | None = None) -> None:
        """Close the open segment and commit. Call at end of a run."""
        if self._open is not None:
            if now is not None:
                self._open.end_ts = max(self._open.end_ts, now)
            self.store.add_segment(self._open)
            self._open = None
        self.store.commit()

    # -- convenience: drive a whole event stream at a fixed sample cadence ---
    def run_stream(self, events: Iterable[SensorEvent], tick_s: float = 60.0) -> None:
        next_tick: float | None = None
        last_ts = 0.0
        for ev in events:
            self.ingest(ev)
            last_ts = ev.ts
            if next_tick is None:
                next_tick = ev.ts
            while ev.ts >= next_tick:
                self.tick(next_tick)
                next_tick += tick_s
        if last_ts:
            self.tick(last_ts)
        self.flush(last_ts)
