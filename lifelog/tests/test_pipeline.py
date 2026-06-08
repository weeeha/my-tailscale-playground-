"""End-to-end and unit tests for the Phase 1 lifelog scaffold."""

from __future__ import annotations

import collections

from lifelog import config as C
from lifelog import rules, simulator
from lifelog.bus import LocalBus
from lifelog.fusion import Fusion
from lifelog.model import KIND_BREATHING, KIND_CONTEXT, KIND_MOTION, SensorEvent
from lifelog.store import Store


def _run_day(tmp_path, date="2026-01-15"):
    store = Store(str(tmp_path / "t.db"))
    bus = LocalBus(store)
    for ev in simulator.generate(date=date):
        bus.publish(ev)
    Fusion(store).run_stream(bus.drain_since())
    return store, date


# -- store roundtrip ---------------------------------------------------------
def test_store_sensor_event_roundtrip(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    store.add_sensor_event(SensorEvent(100.0, "pi-office", KIND_MOTION, {"motion": 0.3}))
    store.commit()
    got = list(store.sensor_events_since(0))
    assert len(got) == 1 and got[0].features["motion"] == 0.3


# -- rules -------------------------------------------------------------------
def test_rule_sleeping_needs_breathing_and_stillness():
    ws = rules.WorldState(now=1000.0)
    ws.set_motion("bedroom", 0.02, 1000.0)
    ws.set_breathing("bedroom", 14.0, 1000.0)
    room, activity, conf = rules.classify(ws)
    assert (room, activity) == ("bedroom", C.SLEEPING)
    assert conf > 0.5


def test_rule_gaming_from_device_context():
    ws = rules.WorldState(now=1000.0)
    ws.set_motion("living", 0.22, 1000.0)
    ws.set_context(C.CTX_PLAYSTATION, True, 1000.0)
    assert rules.classify(ws)[1] == C.GAMING


def test_rule_away_when_no_signal():
    ws = rules.WorldState(now=1000.0)
    assert rules.classify(ws)[1] == C.AWAY


def test_stale_motion_decays_to_away():
    ws = rules.WorldState(now=1000.0)
    ws.set_motion("office", 0.5, 1000.0)
    ws.now = 1000.0 + C.STALE_S + 10
    assert rules.classify(ws)[1] == C.AWAY


# -- fusion / segments -------------------------------------------------------
def test_segments_are_coalesced(tmp_path):
    store, date = _run_day(tmp_path)
    segs = store.segments_for_day(date)
    # consecutive segments must differ in (room, activity) — no redundant splits
    assert segs
    for a, b in zip(segs, segs[1:]):
        assert (a.room, a.activity) != (b.room, b.activity)


def test_day_covers_expected_activities(tmp_path):
    store, date = _run_day(tmp_path)
    totals = store.activity_totals(date)
    for expected in (C.SLEEPING, C.WORKING, C.GAMING, C.COOKING, C.BATHROOM):
        assert expected in totals, f"missing {expected}: {totals}"
    # sleeping is one of the biggest chunks of a normal day
    top2 = sorted(totals, key=totals.get, reverse=True)[:2]
    assert C.SLEEPING in top2, f"sleeping not in top 2: {totals}"


def test_fusion_matches_ground_truth_majority(tmp_path):
    """For each scene, the fused activity over its span should match its truth."""
    store, date = _run_day(tmp_path)
    samples = list(store.db.execute(
        "SELECT ts, activity FROM state_sample ORDER BY ts"))
    t0 = simulator._midnight(date)

    correct = total = 0
    for scene in simulator.SCENES:
        lo, hi = t0 + scene.start_min * 60, t0 + scene.end_min * 60
        votes = collections.Counter(
            a for ts, a in samples if lo <= ts < hi)
        if not votes:
            continue
        total += 1
        if votes.most_common(1)[0][0] == scene.truth:
            correct += 1
    assert total and correct / total >= 0.85, f"{correct}/{total} scenes matched"
