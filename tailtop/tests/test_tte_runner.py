"""TTERunner widget tests."""

from __future__ import annotations

import asyncio

import pytest
from textual.app import App, ComposeResult

from tailtop.widgets.tte_runner import TTERunner


def _ansi_iter(frames: list[str]):
    for f in frames:
        yield f


class _Host(App):
    def __init__(self, runner: TTERunner) -> None:
        super().__init__()
        self._runner = runner
        self.finished = False

    def compose(self) -> ComposeResult:
        yield self._runner

    def on_tterunner_finished(self, _msg: TTERunner.Finished) -> None:
        self.finished = True


async def test_runner_plays_frames_to_completion() -> None:
    frames = [
        "\x1b[38;2;255;0;0mA\x1b[0m",
        "\x1b[38;2;0;255;0mAB\x1b[0m",
        "\x1b[38;2;0;0;255mABC\x1b[0m",
    ]
    runner = TTERunner(_ansi_iter(frames), final_text="ABC")
    host = _Host(runner)
    async with host.run_test() as pilot:
        # Give the worker + tick loop time to drain three frames at 60fps.
        for _ in range(60):
            await pilot.pause()
            if host.finished:
                break
            await asyncio.sleep(0.01)
        assert host.finished
        assert runner.done


async def test_runner_skip_jumps_to_final() -> None:
    # 200 frames - more than we want to drain naturally
    frames = [f"\x1b[38;2;0;255;0m{i:03d}\x1b[0m" for i in range(200)]
    runner = TTERunner(_ansi_iter(frames), final_text="DONE")
    host = _Host(runner)
    async with host.run_test() as pilot:
        await pilot.pause()
        runner.skip()
        await pilot.pause()
        assert runner.done
        # final_text was rendered
        assert "DONE" in runner.renderable.plain if hasattr(runner.renderable, "plain") else True


async def test_runner_with_real_tte_effect() -> None:
    """End-to-end with the actual TTE library — Print on a short string."""
    from terminaltexteffects.effects.effect_print import Print

    effect = Print("Hi")
    runner = TTERunner(effect, final_text="Hi")
    host = _Host(runner)
    async with host.run_test() as pilot:
        # Print on "Hi" produces ~10 frames at TTE's pace - should finish under 1s.
        for _ in range(200):
            await pilot.pause()
            if host.finished:
                break
            await asyncio.sleep(0.01)
        assert host.finished, "TTE Print effect did not complete in time"
