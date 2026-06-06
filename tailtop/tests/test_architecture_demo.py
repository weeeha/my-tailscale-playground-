"""ArchitectureDemo widget smoke tests."""

from __future__ import annotations

import pytest

from tailtop.widgets.architecture_demo import ArchitectureDemo


def test_widget_instantiates() -> None:
    demo = ArchitectureDemo()
    assert demo is not None


def test_render_includes_all_major_labels() -> None:
    demo = ArchitectureDemo()
    rendered = demo.render()
    plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
    assert "Main Office" in plain
    assert "Remote User" in plain
    assert "Branch Office" in plain
    # Device cards show hostnames, not the generic "Tailscale Client" label
    assert "prod-server" in plain
    assert "alice-mbp" in plain
    assert "Active Directory" in plain
    assert "Coordination Server" in plain
    assert "Auth Server" in plain
    assert "Office 365" in plain


def test_render_draws_site_box_borders() -> None:
    demo = ArchitectureDemo()
    plain = demo.render().plain
    # Should contain rounded-corner glyphs for site boxes.
    assert "╭" in plain
    assert "╮" in plain
    assert "╰" in plain
    assert "╯" in plain


def test_render_draws_inner_box_borders() -> None:
    demo = ArchitectureDemo()
    plain = demo.render().plain
    # Should contain square-corner glyphs for inner entry boxes.
    assert "┌" in plain
    assert "└" in plain


def test_render_includes_arrows() -> None:
    demo = ArchitectureDemo()
    plain = demo.render().plain
    # Chevron stripes use ▶; auth→AD arrow uses ◀.
    assert "▶" in plain
    assert "◀" in plain


@pytest.mark.asyncio
async def test_widget_advances_on_animation_tick() -> None:
    from textual.app import App

    class _Harness(App):
        def compose(self):
            yield ArchitectureDemo(id="demo")

    async with _Harness().run_test() as pilot:
        demo = pilot.app.query_one(ArchitectureDemo)
        # Pick a non-idle peer's lane.
        non_idle = next(
            s for s in demo._belt_states.values() if s.in_lane.cells_per_second > 0
        )
        before = non_idle.in_lane.phase
        # Advance several ticks worth of time manually.
        demo._on_tick()  # first tick records baseline
        for _ in range(5):
            demo._on_tick()
        after = non_idle.in_lane.phase
        assert after != before or non_idle.in_lane.cells_per_second == 0


def test_demo_peer_data_is_present_and_realistic() -> None:
    from tailtop.widgets.architecture_demo import DEMO_PEERS
    # Need realistic spread across tiers so the demo has visual variety.
    tiers = {p.host_name: (p.rx_bps, p.tx_bps) for p in DEMO_PEERS}
    assert any(rx >= 5_000_000 or tx >= 5_000_000 for rx, tx in tiers.values()), "need heavy peer"
    assert any(rx == 0 and tx == 0 for rx, tx in tiers.values()), "need idle peer"
    assert any(0 < rx < 5_000_000 for rx, _ in tiers.values()), "need light/busy peer"
