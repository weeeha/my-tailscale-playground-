"""SpeedtestMetric widget tests."""

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult

from tailtop.themes import MISSION_CONTROL, STUDIO
from tailtop.widgets.speedtest_metric import SpeedtestMetric


class _Host(App):
    def __init__(self, metric: SpeedtestMetric) -> None:
        super().__init__()
        self._metric = metric

    def compose(self) -> ComposeResult:
        yield self._metric


def _rendered(m: SpeedtestMetric) -> str:
    return m.renderable.plain if hasattr(m.renderable, "plain") else str(m.renderable)


async def test_pending_state_shows_placeholder() -> None:
    metric = SpeedtestMetric("Ping", unit="ms", theme=STUDIO)
    async with _Host(metric).run_test():
        # pending + no value → placeholder dashes
        assert "—+—" in _rendered(metric)
        assert "Ping" in _rendered(metric)


async def test_active_value_renders_with_unit() -> None:
    metric = SpeedtestMetric("Download", unit="Mbps", theme=MISSION_CONTROL)
    async with _Host(metric).run_test() as pilot:
        metric.report(42.4)
        await pilot.pause()
        # let tween settle
        for _ in range(60):
            await pilot.pause()
            await asyncio.sleep(0.01)
            if _rendered(metric).strip().endswith("Mbps") and "42.4" in _rendered(metric):
                break
        assert "42.4" in _rendered(metric)
        assert "Mbps" in _rendered(metric)


async def test_finalized_state_renders_value() -> None:
    metric = SpeedtestMetric("Upload", unit="Mbps", theme=MISSION_CONTROL)
    async with _Host(metric).run_test() as pilot:
        metric.report(11.2)
        await pilot.pause()
        await asyncio.sleep(0.3)  # let tween finish
        metric.set_state("finalized")
        await pilot.pause()
        assert "11.2" in _rendered(metric)


async def test_spinner_mode_cycles_braille() -> None:
    metric = SpeedtestMetric("Online", unit="peers", spinner_when_active=True)
    async with _Host(metric).run_test() as pilot:
        metric.set_state("active")
        await pilot.pause()
        seen: set[str] = set()
        for _ in range(20):
            r = _rendered(metric)
            for ch in r:
                if ch in "⠂⠁⠃⠄":
                    seen.add(ch)
            await pilot.pause()
            await asyncio.sleep(0.05)
        # we should see at least 2 distinct spinner glyphs
        assert len(seen) >= 2, f"expected braille rotation, saw {seen!r}"


async def test_tween_animates_toward_target() -> None:
    metric = SpeedtestMetric("Bandwidth", unit="Mbps", precision=1)
    async with _Host(metric).run_test() as pilot:
        # First active value snaps from None (displayed=None → starts at 0)
        metric.report(0)
        await pilot.pause()
        # Now set a target while active — should tween
        metric.set_value(100.0)
        await pilot.pause()
        # Check displayed value is between 0 and 100 during the tween
        snapshots: list[str] = []
        for _ in range(8):
            snapshots.append(_rendered(metric))
            await pilot.pause()
            await asyncio.sleep(0.02)
        # at least one snapshot should show a mid-tween value (not the endpoints)
        digits = [int(round(float(s.replace("Bandwidth", "").replace("Mbps", "").strip().split()[0])))
                  for s in snapshots if "—+—" not in s]
        assert any(0 < d < 100 for d in digits), f"no intermediate tween value seen: {digits}"
