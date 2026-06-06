"""Tread speed/tier math — pure, no Textual."""

from __future__ import annotations

import pytest

from tailtop.widgets.belt import TreadAnimator as TA


@pytest.mark.parametrize(
    "rate,expected_tier",
    [
        (0, "idle"),
        (50_000, "light"),          # 50 KB/s
        (100_000, "busy"),          # exactly at busy threshold
        (1_000_000, "busy"),        # 1 MB/s
        (4_999_999, "busy"),
        (5_000_000, "heavy"),       # exactly at heavy threshold
        (50_000_000, "heavy"),      # 50 MB/s
    ],
)
def test_tier_for(rate: int, expected_tier: str) -> None:
    assert TA.tier_for(rate) == expected_tier


def test_speed_for_zero_is_zero() -> None:
    assert TA.speed_for(0) == 0.0


def test_speed_for_clamps_at_min() -> None:
    # Anything > 0 but tiny still produces at least MIN_CELLS_PER_S.
    assert TA.speed_for(1) == pytest.approx(TA.MIN_CELLS_PER_S)


def test_speed_for_clamps_at_max() -> None:
    # Massive rate gets clamped to MAX_CELLS_PER_S, not infinity.
    assert TA.speed_for(10_000_000_000) == pytest.approx(TA.MAX_CELLS_PER_S)


def test_speed_for_scales_linearly_in_band() -> None:
    # At BUSY_BPS the formula yields exactly 1.0 norm → clamped to MIN.
    # At 100 * BUSY_BPS the norm is 100 → above MAX, clamped.
    # Pick a mid-band value.
    mid = TA.BUSY_BPS * 10  # 10× busy threshold = 1 MB/s
    expected = max(TA.MIN_CELLS_PER_S, min(TA.MAX_CELLS_PER_S, 10.0))
    assert TA.speed_for(mid) == pytest.approx(expected)


from tailtop.widgets.belt import LaneState  # noqa: E402


def test_lane_state_defaults() -> None:
    s = LaneState()
    assert s.phase == 0.0
    assert s.cells_per_second == 0.0


def test_lane_state_advances_by_speed_times_dt() -> None:
    s = LaneState(cells_per_second=1.0, phase=0.0)
    s.advance(dt=0.5)
    assert s.phase == pytest.approx(0.5)


def test_lane_state_phase_wraps_at_spacing() -> None:
    s = LaneState(cells_per_second=2.0, phase=0.5)
    s.advance(dt=1.0)  # +2.0, total 2.5, wraps to 0.5
    assert s.phase == pytest.approx(0.5)


def test_lane_state_idle_does_not_move() -> None:
    s = LaneState(cells_per_second=0.0, phase=0.3)
    s.advance(dt=10.0)
    assert s.phase == 0.3
