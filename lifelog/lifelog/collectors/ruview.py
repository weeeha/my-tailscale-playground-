"""RuView bridge — adopt RuView's WiFi-CSI sensing as our edge layer.

RuView (github.com/ruvnet/RuView) is a mature ESP32-CSI platform that already
solves the hard bottom layer we stubbed: it captures CSI and publishes
breathing / presence / motion over MQTT (Home Assistant auto-discovery style).
This bridge subscribes to those topics and translates each reading into our
``SensorEvent`` stream, so RuView's senses feed lifelog's localization, activity
labeling, and time-tracking — the layers RuView does *not* have.

Observed RuView contract (verify against RuView ADR-115 / source; the exact
payload schema isn't fully published, so ``translate`` parses defensively and
accepts both per-entity scalar topics and JSON blobs):

    topic:   ruview/<node_id>/bfld/<entity>/state      e.g. .../presence/state
             ruview/<node_id>/bfld/availability         online | offline (LWT)
    fields:  presence, motion, motion_energy, presence_score,
             breathing_rate_bpm, breathing_confidence, heartrate_bpm,
             n_persons, fall_detected, timestamp_ms

The RuView node_id → lifelog node (room) mapping is configurable; keys must
resolve through ``config.NODES`` for fusion to place them in a room.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping

from .. import config as C
from ..model import KIND_BREATHING, KIND_MOTION, SensorEvent

# presence with no explicit motion magnitude ⇒ "occupied" just over threshold
_PRESENCE_MOTION = C.MOTION_OCCUPIED + 0.05


def _truthy(v: object) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    return str(v).strip().lower() in {"on", "true", "1", "online", "yes", "occupied"}


def _num(v: object) -> float | None:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _first(d: Mapping, *keys: str):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _maybe_json(payload: str) -> dict | None:
    try:
        obj = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def _from_blob(node: str, d: Mapping, now: float) -> list[SensorEvent]:
    evs: list[SensorEvent] = []
    motion = _num(_first(d, "motion_energy", "motion", "presence_score"))
    if motion is None and "presence" in d:
        motion = _PRESENCE_MOTION if _truthy(d["presence"]) else 0.0
    if motion is not None:
        evs.append(SensorEvent(now, node, KIND_MOTION, {"motion": motion}))

    bpm = _num(_first(d, "breathing_rate_bpm", "breathing_bpm", "breathing_rate"))
    if bpm:
        conf = _num(_first(d, "breathing_confidence")) or 0.8
        evs.append(SensorEvent(now, node, KIND_BREATHING, {"bpm": bpm, "confidence": conf}))
    return evs


def _from_scalar(node: str, entity: str, payload: str, now: float) -> list[SensorEvent]:
    e = entity.lower()
    if e in {"presence", "occupancy", "room_active"}:
        motion = _PRESENCE_MOTION if _truthy(payload) else 0.0
        return [SensorEvent(now, node, KIND_MOTION, {"motion": motion})]
    if e in {"motion", "motion_energy", "presence_score"}:
        v = _num(payload)
        return [SensorEvent(now, node, KIND_MOTION, {"motion": v})] if v is not None else []
    if e in {"breathing", "breathing_rate", "respiration", "breathing_rate_bpm"}:
        v = _num(payload)
        return [SensorEvent(now, node, KIND_BREATHING, {"bpm": v, "confidence": 0.8})] if v else []
    return []


def translate(
    topic: str,
    payload: str,
    node_map: Mapping[str, str] | None = None,
    now: float | None = None,
) -> list[SensorEvent]:
    """RuView MQTT message → lifelog SensorEvents (pure; no network)."""
    now = time.time() if now is None else now
    parts = topic.split("/")
    if len(parts) < 2 or parts[0] != "ruview":
        return []
    rid = parts[1]
    node = (node_map or {}).get(rid, rid)
    # ruview/<node>/bfld/<entity>/state  →  entity = parts[3]
    # ruview/<node>/bfld/availability    →  entity = "availability" (unrecognized)
    entity = parts[3] if len(parts) >= 4 else ""

    blob = _maybe_json(payload)
    if blob is not None:
        return _from_blob(node, blob, now)
    return _from_scalar(node, entity, payload, now)


class RuViewBridge:
    """Subscribe to RuView MQTT and republish as lifelog events into ``sink``."""

    def __init__(
        self,
        sink,
        node_map: Mapping[str, str] | None = None,
        host: str = "127.0.0.1",
        port: int = 1883,
        topic: str = "ruview/#",
    ) -> None:
        self.sink = sink
        self.node_map = dict(node_map or {})
        self.host = host
        self.port = port
        self.topic = topic

    def handle(self, topic: str, payload: str, now: float | None = None) -> list[SensorEvent]:
        events = translate(topic, payload, self.node_map, now)
        for ev in events:
            self.sink.publish(ev)
        return events

    def run(self) -> None:  # pragma: no cover - needs a broker + paho
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:
            raise ImportError("RuViewBridge.run needs paho-mqtt: pip install 'lifelog[mqtt]'") from exc

        client = mqtt.Client()
        client.on_message = lambda c, u, m: self.handle(m.topic, m.payload.decode())
        client.connect(self.host, self.port)
        client.subscribe(self.topic)
        client.loop_forever()
