"""Spike: TTE frames → Rich → Textual Static. Validates the integration path."""
from __future__ import annotations

import asyncio
import time
from collections import deque
from pathlib import Path

from rich.text import Text
from terminaltexteffects.effects.effect_beams import Beams
from terminaltexteffects.effects.effect_decrypt import Decrypt
from terminaltexteffects.effects.effect_print import Print
from textual.app import App, ComposeResult
from textual.widgets import Static

EFFECTS = {
    "decrypt": lambda: Decrypt("TAILTOP"),
    "beams": lambda: Beams("Connected. 47 peers, 3 online."),
    "print": lambda: Print("Connecting to tailscaled…"),
}


class TTESpikeApp(App[dict]):
    """Drains a pre-collected frame list through Static.update via set_interval."""

    CSS = "Static { content-align: center middle; height: 1fr; padding: 2; }"

    def __init__(self, frames: list[str], target_fps: int = 60) -> None:
        super().__init__()
        self._frames = deque(frames)
        self._target_fps = target_fps
        self._update_timestamps: list[float] = []
        self._start: float = 0.0

    def compose(self) -> ComposeResult:
        yield Static("", id="stage")

    def on_mount(self) -> None:
        self._start = time.perf_counter()
        self.set_interval(1 / self._target_fps, self._tick)

    def _tick(self) -> None:
        if not self._frames:
            elapsed = time.perf_counter() - self._start
            self.exit({
                "frames_played": len(self._update_timestamps),
                "elapsed": elapsed,
                "fps_effective": len(self._update_timestamps) / elapsed if elapsed else 0,
                "intervals_ms": [
                    (b - a) * 1000
                    for a, b in zip(self._update_timestamps, self._update_timestamps[1:])
                ],
            })
            return
        frame = self._frames.popleft()
        self.query_one(Static).update(Text.from_ansi(frame))
        self._update_timestamps.append(time.perf_counter())


async def run_one(name: str, factory) -> dict:
    print(f"\n[{name}] draining frames from TTE…")
    t0 = time.perf_counter()
    frames = list(factory())
    drain = time.perf_counter() - t0
    print(f"[{name}] {len(frames)} frames in {drain:.2f}s (tte-paced)")

    app = TTESpikeApp(frames)
    result = await app.run_async(headless=True, size=(80, 24))

    intervals = result["intervals_ms"]
    avg = sum(intervals) / len(intervals) if intervals else 0
    p95 = sorted(intervals)[int(len(intervals) * 0.95)] if intervals else 0
    return {
        "effect": name,
        "frames": result["frames_played"],
        "playback_s": round(result["elapsed"], 2),
        "fps_effective": round(result["fps_effective"], 1),
        "avg_interval_ms": round(avg, 2),
        "p95_interval_ms": round(p95, 2),
        "tte_drain_s": round(drain, 2),
    }


async def main() -> None:
    results = []
    for name, factory in EFFECTS.items():
        results.append(await run_one(name, factory))

    out = Path(__file__).parent / "spike_results.txt"
    lines = ["TTE → Textual spike results", "=" * 60, ""]
    for r in results:
        lines.append(f"effect: {r['effect']}")
        lines.append(f"  frames: {r['frames']}")
        lines.append(f"  playback wall-clock: {r['playback_s']}s")
        lines.append(f"  effective fps: {r['fps_effective']}")
        lines.append(f"  avg interval: {r['avg_interval_ms']}ms")
        lines.append(f"  p95 interval: {r['p95_interval_ms']}ms")
        lines.append(f"  (tte drain time: {r['tte_drain_s']}s)")
        lines.append("")
    out.write_text("\n".join(lines))
    print("\n".join(lines))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
