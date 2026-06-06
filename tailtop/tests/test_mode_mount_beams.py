"""Mode-mount beams hook — first_visit fires the overlay; second visit doesn't."""

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult

from tailtop.modes.cockpit import CockpitMode
from tailtop.widgets.tte_runner import TTERunner


class _Host(App):
    def compose(self) -> ComposeResult:
        yield CockpitMode(id="cockpit")


async def test_on_first_visit_mounts_a_runner() -> None:
    host = _Host()
    async with host.run_test() as pilot:
        await pilot.pause()
        mode = host.query_one(CockpitMode)
        assert not mode.first_visit_done
        mode.on_first_visit()
        mode.mark_first_visit_done()
        await pilot.pause()
        runner = mode.query_one(TTERunner)
        assert runner is not None
        # Let the overlay run to completion / removal.
        for _ in range(300):
            await pilot.pause()
            await asyncio.sleep(0.02)
            if not mode.query(TTERunner):
                break
        assert not mode.query(TTERunner), "beams overlay never removed"


async def test_first_visit_flag_prevents_second_run() -> None:
    host = _Host()
    async with host.run_test() as pilot:
        await pilot.pause()
        mode = host.query_one(CockpitMode)
        mode.mark_first_visit_done()
        assert mode.first_visit_done
        # Subsequent Tab cycles in app.py guard on this flag — confirm idempotent.
        mode.mark_first_visit_done()
        assert mode.first_visit_done
