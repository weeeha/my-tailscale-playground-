"""BootOverlay tests."""

from __future__ import annotations

import asyncio

from textual.app import App

from tailtop.widgets.boot_overlay import BootOverlay


class _Host(App):
    def on_mount(self) -> None:
        self.push_screen(BootOverlay(title="Hi", status="Boot"))


async def test_overlay_dismisses_when_both_runners_finish() -> None:
    """Both TTERunners reach Finished → overlay pops."""
    host = _Host()
    async with host.run_test() as pilot:
        # Wait until the overlay is gone (its screen was popped).
        for _ in range(300):
            await pilot.pause()
            if not isinstance(host.screen, BootOverlay):
                break
            await asyncio.sleep(0.02)
        assert not isinstance(host.screen, BootOverlay), \
            "BootOverlay did not dismiss after both runners finished"


async def test_overlay_skips_on_keypress() -> None:
    """Pressing any key on the overlay skips both runners and dismisses."""
    host = _Host()
    async with host.run_test() as pilot:
        await pilot.pause()
        assert isinstance(host.screen, BootOverlay)
        # Send any key
        await pilot.press("space")
        await pilot.pause()
        await asyncio.sleep(0.05)
        await pilot.pause()
        assert not isinstance(host.screen, BootOverlay)
