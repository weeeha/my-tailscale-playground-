"""Scripted-day simulator: stands in for real CSI/RSSI/context sensors.

Emits the same ``SensorEvent`` stream the real edge agents will, so the whole
pipeline runs end-to-end with no hardware. Each scene also carries its ground
truth, which the tests use to score fusion accuracy.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import config as C
from .model import KIND_BREATHING, KIND_CONTEXT, KIND_MOTION, SensorEvent

# room -> the node that watches it (inverse of C.NODES)
_NODE_FOR = {room: node for node, room in C.NODES.items()}

# typical motion level for an activity (0..1)
_MOTION = {
    C.SLEEPING: 0.03,
    C.WORKING: 0.18,
    C.GAMING: 0.22,
    C.WATCHING: 0.12,
    C.COOKING: 0.70,
    C.BATHROOM: 0.40,
    C.IDLE: 0.20,
}


@dataclass(frozen=True)
class Scene:
    start_min: int      # minutes from local midnight
    end_min: int
    room: str
    truth: str          # ground-truth activity for scoring


# A plausible one-person weekday.
SCENES: list[Scene] = [
    Scene(0, 450, "bedroom", C.SLEEPING),       # 00:00–07:30 asleep
    Scene(450, 475, "bathroom", C.BATHROOM),     # 07:30–07:55
    Scene(475, 510, "kitchen", C.COOKING),       # 07:55–08:30 breakfast
    Scene(510, 750, "office", C.WORKING),        # 08:30–12:30
    Scene(750, 780, "kitchen", C.COOKING),       # 12:30–13:00 lunch
    Scene(780, 1080, "office", C.WORKING),       # 13:00–18:00
    Scene(1080, 1140, "kitchen", C.COOKING),     # 18:00–19:00 dinner
    Scene(1140, 1380, "living", C.GAMING),       # 19:00–23:00 PlayStation
    Scene(1410, 1440, "bedroom", C.SLEEPING),    # 23:30–24:00 back to bed
]


def _midnight(date: str | None) -> float:
    base = datetime.now() if date is None else datetime.strptime(date, "%Y-%m-%d")
    return base.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def generate(date: str | None = None, step_s: int = 30, seed: int = 7) -> Iterator[SensorEvent]:
    """Yield the day's sensor events in time order."""
    rng = random.Random(seed)
    t0 = _midnight(date)

    for scene in SCENES:
        node = _NODE_FOR[scene.room]
        base_motion = _MOTION.get(scene.truth, 0.2)
        t = t0 + scene.start_min * 60
        end = t0 + scene.end_min * 60

        while t < end:
            jitter = rng.uniform(-0.03, 0.05)
            motion = max(0.0, base_motion + jitter)
            yield SensorEvent(t, node, KIND_MOTION, {"motion": round(motion, 3)})

            # device-state pollers re-assert latched context every cycle
            for key, on in _scene_context(scene):
                yield SensorEvent(t, "ctx", KIND_CONTEXT, {"key": key, "value": on})

            if scene.truth == C.SLEEPING:
                bpm = round(rng.uniform(13.0, 16.0), 1)
                yield SensorEvent(t, node, KIND_BREATHING, {"bpm": bpm, "confidence": 0.8})

            # fridge pulses a few times during cooking
            if scene.truth == C.COOKING and rng.random() < 0.15:
                yield SensorEvent(t, "ctx", KIND_CONTEXT,
                                  {"key": C.CTX_FRIDGE_OPEN, "value": True})
                yield SensorEvent(t + 5, "ctx", KIND_CONTEXT,
                                  {"key": C.CTX_FRIDGE_OPEN, "value": False})
            t += step_s

        for key, _ in _scene_context(scene):
            yield SensorEvent(end, "ctx", KIND_CONTEXT, {"key": key, "value": False})


def _scene_context(scene: Scene) -> list[tuple[str, bool]]:
    if scene.truth == C.GAMING:
        return [(C.CTX_PLAYSTATION, True)]
    if scene.truth == C.WATCHING:
        return [(C.CTX_TV, True)]
    if scene.truth == C.WORKING:
        return [(C.CTX_PC_ACTIVE, True)]
    if scene.truth == C.COOKING:
        return [(C.CTX_KETTLE_ON, True)]
    return []
