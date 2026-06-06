"""Phase 3: breathing DSP + sleep analytics."""

from __future__ import annotations

import pytest

from lifelog import simulator
from lifelog.breathing import BreathingAgent, estimate_rate
from lifelog.bus import LocalBus
from lifelog.fusion import Fusion
from lifelog.model import KIND_BREATHING
from lifelog.sleep import analyze_main_sleep, render_card
from lifelog.store import Store


# -- breathing DSP -----------------------------------------------------------
@pytest.mark.parametrize("true_bpm", [10, 12, 15, 18, 24])
def test_recovers_known_breathing_rate(true_bpm):
    wave = simulator.synth_respiration(true_bpm, duration_s=60, fs=10, noise=0.25, seed=3)
    est = estimate_rate(wave, fs=10)
    assert est.ok
    assert abs(est.bpm - true_bpm) <= 1.0       # within 1 breath/min
    assert est.confidence >= 0.3


def test_empty_bed_is_not_a_rhythm():
    wave = simulator.synth_respiration(15, 60, 10, present=False, seed=4)
    assert estimate_rate(wave, fs=10).ok is False


def test_too_short_window_is_rejected():
    wave = simulator.synth_respiration(15, duration_s=5, fs=10, seed=5)
    assert estimate_rate(wave, fs=10).ok is False


def test_breathing_agent_emits_event_only_when_confident():
    agent = BreathingAgent("esp32-bedroom")
    good = agent.analyze(simulator.synth_respiration(14, 60, 10, seed=6), fs=10, now=100.0)
    assert good is not None and good.kind == KIND_BREATHING and good.features["bpm"] > 0
    empty = agent.analyze(
        simulator.synth_respiration(14, 60, 10, present=False, seed=7), fs=10, now=100.0)
    assert empty is None


# -- sleep analytics ---------------------------------------------------------
def _demo_store(tmp_path, date="2026-01-15"):
    store = Store(str(tmp_path / "s.db"))
    bus = LocalBus(store)
    for ev in simulator.generate(date=date):
        bus.publish(ev)
    Fusion(store).run_stream(bus.drain_since())
    return store, date


def test_main_sleep_session_metrics(tmp_path):
    store, date = _demo_store(tmp_path)
    s = analyze_main_sleep(store, date)
    assert s is not None
    assert 6 * 3600 <= s.asleep_s <= 9 * 3600        # a normal night
    assert 0.0 <= s.efficiency <= 1.0
    assert 10 <= s.mean_bpm <= 18                     # plausible breathing
    assert s.awakenings >= 0
    assert "asleep" in render_card(s)


def test_no_sleep_returns_none(tmp_path):
    store = Store(str(tmp_path / "empty.db"))
    assert analyze_main_sleep(store, "2026-01-15") is None
