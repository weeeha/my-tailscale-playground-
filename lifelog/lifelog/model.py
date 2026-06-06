"""Core records that flow through the pipeline.

``SensorEvent``  — raw-ish edge output (a node's extracted feature, not raw CSI).
``StateSample``  — one fused (room, activity) reading, ~1 Hz / on-change.
``Segment``      — a contiguous block of one activity; what "where did my time
                   go" actually queries.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# SensorEvent.kind values
KIND_MOTION = "motion"        # features: {"motion": float 0..1}
KIND_BREATHING = "breathing"  # features: {"bpm": float, "confidence": float}
KIND_CONTEXT = "context"      # features: {"key": str, "value": bool}


@dataclass(slots=True)
class SensorEvent:
    ts: float
    node_id: str
    kind: str
    features: dict


@dataclass(slots=True)
class StateSample:
    ts: float
    room: str
    activity: str
    motion: float
    confidence: float


@dataclass(slots=True)
class Segment:
    start_ts: float
    end_ts: float
    room: str
    activity: str
    duration_s: float = 0.0
    attrs: dict = field(default_factory=dict)

    def finalize(self) -> "Segment":
        self.duration_s = max(0.0, self.end_ts - self.start_ts)
        return self
