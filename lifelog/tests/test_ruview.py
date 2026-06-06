"""RuView bridge: translate RuView MQTT messages into lifelog SensorEvents."""

from __future__ import annotations

from lifelog import config as C
from lifelog.bus import LocalBus
from lifelog.collectors.ruview import RuViewBridge, translate
from lifelog.fusion import Fusion
from lifelog.model import KIND_BREATHING, KIND_MOTION
from lifelog.store import Store

NODE_MAP = {"node-bedroom": "esp32-bedroom", "node-living": "pi-living"}


# -- scalar per-entity topics ------------------------------------------------
def test_presence_scalar_becomes_motion():
    evs = translate("ruview/node-living/bfld/presence/state", "ON", NODE_MAP, now=10.0)
    assert len(evs) == 1
    assert evs[0].node_id == "pi-living"
    assert evs[0].kind == KIND_MOTION and evs[0].features["motion"] > C.MOTION_OCCUPIED


def test_presence_off_is_zero_motion():
    evs = translate("ruview/node-living/bfld/presence/state", "OFF", NODE_MAP, now=10.0)
    assert evs[0].features["motion"] == 0.0


def test_motion_energy_scalar():
    evs = translate("ruview/node-living/bfld/motion_energy/state", "0.63", NODE_MAP, now=1.0)
    assert evs[0].kind == KIND_MOTION and abs(evs[0].features["motion"] - 0.63) < 1e-9


def test_breathing_scalar():
    evs = translate("ruview/node-bedroom/bfld/breathing_rate/state", "14.2", NODE_MAP, now=1.0)
    assert evs[0].kind == KIND_BREATHING and evs[0].features["bpm"] == 14.2


# -- JSON edge_vitals blob ---------------------------------------------------
def test_json_blob_emits_motion_and_breathing():
    payload = ('{"presence": true, "motion_energy": 0.04, '
               '"breathing_rate_bpm": 13.5, "breathing_confidence": 0.77}')
    evs = translate("ruview/node-bedroom/bfld/edge_vitals/state", payload, NODE_MAP, now=5.0)
    kinds = {e.kind for e in evs}
    assert KIND_MOTION in kinds and KIND_BREATHING in kinds
    breath = next(e for e in evs if e.kind == KIND_BREATHING)
    assert breath.features == {"bpm": 13.5, "confidence": 0.77}


def test_unknown_topic_ignored():
    assert translate("homeassistant/sensor/x/config", "{}", NODE_MAP) == []
    assert translate("ruview/node/bfld/availability", "online", NODE_MAP) == []


# -- bridge + pipeline integration ------------------------------------------
def test_bridge_feeds_fusion_to_sleeping(tmp_path):
    """RuView bedroom vitals (still + breathing) at night → fusion SLEEPING."""
    import time

    store = Store(str(tmp_path / "r.db"))
    bridge = RuViewBridge(LocalBus(store), node_map=NODE_MAP)

    # 22:00 local, bedroom: low motion + a breathing rhythm, every 30s for 10 min
    base = time.mktime(time.strptime(time.strftime("%Y-%m-%d") + " 22:00", "%Y-%m-%d %H:%M"))
    for off in range(0, 600, 30):
        payload = '{"presence": true, "motion_energy": 0.03, "breathing_rate_bpm": 14.0}'
        bridge.handle("ruview/node-bedroom/bfld/edge_vitals/state", payload, now=base + off)

    Fusion(store).run_stream(store.sensor_events_since(-1))
    totals = store.activity_totals(time.strftime("%Y-%m-%d", time.localtime(base)))
    assert C.SLEEPING in totals, totals
