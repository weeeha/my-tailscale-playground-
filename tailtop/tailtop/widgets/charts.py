"""Chart rendering — a plotext latency line chart sized to its widget."""

from __future__ import annotations

import plotext as plt
from rich.text import Text
from textual.widget import Widget


def render_latency(series: list[float], width: int, height: int, color: str = "blue") -> Text:
    """Build a braille line chart (with y-axis ticks) as a Rich Text."""
    plt.clf()
    plt.plot(series, marker="braille", color=color)
    plt.plotsize(max(8, width), max(3, height))
    plt.theme("clear")
    plt.xfrequency(0)  # no x ticks; it's a rolling window
    return Text.from_ansi(plt.build())


class LatencyChart(Widget):
    """Renders the RTT ring buffer as a live line chart at its own size."""

    DEFAULT_CSS = "LatencyChart { height: 1fr; min-height: 5; }"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._series: list[float] = []

    def set_series(self, series: list[float]) -> None:
        self._series = series
        self.refresh()

    def render(self) -> Text:
        width, height = self.size
        if not self._series or width < 8 or height < 3:
            return Text("\n  pinging…", style="dim")
        return render_latency(self._series, width, height)
