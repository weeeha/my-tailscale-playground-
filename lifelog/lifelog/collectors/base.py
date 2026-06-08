"""Collector base: a scheduled yes/no probe that emits context events."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..model import KIND_CONTEXT, SensorEvent


class Collector(ABC):
    """Polls one boolean about the world on a fixed interval.

    ``read`` returns:
        True / False — a definite state (published as a context event)
        None         — couldn't determine right now (skip; emit nothing)
    Exceptions from ``read`` are swallowed by ``poll`` and treated as None, so a
    flaky network never takes the daemon down.
    """

    def __init__(self, key: str, interval_s: float = 30.0) -> None:
        self.key = key
        self.interval_s = interval_s
        self._next_due = 0.0

    @abstractmethod
    def read(self) -> bool | None: ...

    def due(self, now: float) -> bool:
        return now >= self._next_due

    def poll(self, now: float) -> list[SensorEvent]:
        self._next_due = now + self.interval_s
        try:
            value = self.read()
        except Exception:
            value = None
        if value is None:
            return []
        return [SensorEvent(now, "ctx", KIND_CONTEXT, {"key": self.key, "value": bool(value)})]
