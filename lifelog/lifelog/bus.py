"""Transport between edge agents and the fusion brain.

Phase 1 ships ``LocalBus`` (events go straight into the SQLite store, fusion
reads them back) so the pipeline runs with zero infrastructure. ``MqttBus`` is
the drop-in for the real fleet — same ``publish`` interface, lazy-imports
``paho-mqtt`` so it's an optional dependency.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from .model import SensorEvent
from .store import Store


class EventSink(Protocol):
    def publish(self, ev: SensorEvent) -> None: ...


class LocalBus:
    """In-process bus backed by the timeline store's sensor_event table."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def publish(self, ev: SensorEvent) -> None:
        self.store.add_sensor_event(ev)

    def drain_since(self, ts: float = -1.0) -> Iterator[SensorEvent]:
        self.store.commit()
        yield from self.store.sensor_events_since(ts)


class MqttBus:
    """Real-fleet transport. Each event → an MQTT message on lifelog/<node>/<kind>."""

    def __init__(self, host: str, port: int = 1883, prefix: str = "lifelog") -> None:
        try:
            import paho.mqtt.client as mqtt  # noqa: F401
        except ImportError as exc:  # pragma: no cover - optional dep
            raise ImportError(
                "MqttBus needs paho-mqtt: pip install 'lifelog[mqtt]'"
            ) from exc
        self._mqtt = mqtt
        self.prefix = prefix
        self.client = mqtt.Client()
        self.client.connect(host, port)

    def publish(self, ev: SensorEvent) -> None:  # pragma: no cover - needs a broker
        import json

        topic = f"{self.prefix}/{ev.node_id}/{ev.kind}"
        self.client.publish(topic, json.dumps({"ts": ev.ts, "features": ev.features}))
