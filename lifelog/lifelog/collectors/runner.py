"""CollectorRunner — drives a set of collectors and publishes their events.

Schedule-aware: ``poll`` only fires collectors whose interval has elapsed.
``snapshot`` force-reads every collector once (for ``lifelog collect --once``).
Publishes through any object with ``.publish(SensorEvent)`` (e.g. ``LocalBus``).
"""

from __future__ import annotations

from collections.abc import Iterable

from ..bus import EventSink
from ..model import SensorEvent
from .base import Collector


class CollectorRunner:
    def __init__(self, collectors: Iterable[Collector], sink: EventSink | None = None) -> None:
        self.collectors = list(collectors)
        self.sink = sink

    def poll(self, now: float, *, force: bool = False) -> list[SensorEvent]:
        events: list[SensorEvent] = []
        for c in self.collectors:
            if force or c.due(now):
                for ev in c.poll(now):
                    if self.sink is not None:
                        self.sink.publish(ev)
                    events.append(ev)
        return events

    def snapshot(self, now: float) -> dict[str, bool | None]:
        """One read of every collector, schedule ignored. Side-effect free read."""
        out: dict[str, bool | None] = {}
        for c in self.collectors:
            try:
                out[c.key] = c.read()
            except Exception:
                out[c.key] = None
        return out
