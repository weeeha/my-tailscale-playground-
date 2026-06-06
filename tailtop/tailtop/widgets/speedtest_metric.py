"""SpeedtestMetric — the speedtest-net visual language as a reusable widget.

Renders one metric in tri-state color (pending / active / finalized) with a
bright-digit, dim-unit treatment. Active metrics either tween toward their
target value (default) or show a braille spinner.

Used in Cockpit cards, ping/netcheck result modals, and the status bar's
online-count chip.
"""

from __future__ import annotations

from typing import Literal

from rich.text import Text
from textual.widgets import Static

from tailtop.themes import Theme, theme_for_mode

State = Literal["pending", "active", "finalized"]

_PLACEHOLDER = "—+—"
_SPINNER_FRAMES = ("⠂", "⠁", "⠃", "⠄")
_TWEEN_DURATION_MS = 250
_TWEEN_FPS = 30


class SpeedtestMetric(Static):
    """One label / value / unit, rendered in the speedtest-net style."""

    DEFAULT_CSS = """
    SpeedtestMetric {
        height: 1;
        width: auto;
    }
    """

    def __init__(
        self,
        label: str,
        *,
        unit: str = "",
        theme: Theme | None = None,
        spinner_when_active: bool = False,
        precision: int = 1,
        **kwargs,
    ) -> None:
        self._label = label
        self._unit = unit
        self._theme = theme or theme_for_mode("comfort")
        self._spinner = spinner_when_active
        self._precision = precision

        self._state: State = "pending"
        self._value: float | int | None = None
        self._displayed: float | int | None = None

        self._spinner_idx = 0
        self._spinner_timer = None

        self._tween_timer = None
        self._tween_steps_left = 0
        self._tween_step = 0.0

        super().__init__(self._compose_text(), **kwargs)

    def _compose_text(self) -> Text:
        """Build the current renderable from state — safe to call pre-mount."""
        t = self._theme
        line = Text()
        label_color = t.text_dim if self._state == "pending" else t.text
        line.append(self._label, style=label_color)
        line.append("  ")
        line.append(self._value_text())
        return line

    # ---- public surface ----------------------------------------------------

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self._refresh_display()

    def set_state(self, state: State) -> None:
        if state == self._state:
            return
        self._state = state
        if state == "active" and self._spinner:
            self._start_spinner()
        else:
            self._stop_spinner()
        self._refresh_display()

    def set_value(self, value: float | int | None) -> None:
        self._value = value
        if value is None or self._state != "active" or self._spinner:
            self._stop_tween()
            self._displayed = value
            self._refresh_display()
        else:
            self._start_tween(value)

    def report(
        self,
        value: float | int | None,
        *,
        state: State = "active",
    ) -> None:
        """Convenience: set both state and value in one call."""
        self.set_state(state)
        self.set_value(value)

    # ---- lifecycle ---------------------------------------------------------

    def on_mount(self) -> None:
        self._refresh_display()

    def on_unmount(self) -> None:
        self._stop_spinner()
        self._stop_tween()

    # ---- spinner -----------------------------------------------------------

    def _start_spinner(self) -> None:
        if self._spinner_timer is None:
            self._spinner_timer = self.set_interval(0.12, self._spinner_tick)

    def _stop_spinner(self) -> None:
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None
        self._spinner_idx = 0

    def _spinner_tick(self) -> None:
        self._spinner_idx = (self._spinner_idx + 1) % len(_SPINNER_FRAMES)
        self._refresh_display()

    # ---- tween -------------------------------------------------------------

    def _start_tween(self, target: float | int) -> None:
        start = self._displayed if self._displayed is not None else 0
        steps = max(1, int(_TWEEN_DURATION_MS / 1000 * _TWEEN_FPS))
        self._tween_step = (target - start) / steps
        self._tween_steps_left = steps
        if self._tween_timer is None:
            self._tween_timer = self.set_interval(1 / _TWEEN_FPS, self._tween_tick)
        self._refresh_display()

    def _stop_tween(self) -> None:
        if self._tween_timer is not None:
            self._tween_timer.stop()
            self._tween_timer = None
        self._tween_steps_left = 0

    def _tween_tick(self) -> None:
        if self._tween_steps_left <= 0 or self._value is None:
            self._displayed = self._value
            self._stop_tween()
            self._refresh_display()
            return
        cur = self._displayed if self._displayed is not None else 0
        self._displayed = cur + self._tween_step
        self._tween_steps_left -= 1
        if self._tween_steps_left == 0:
            self._displayed = self._value
            self._stop_tween()
        self._refresh_display()

    # ---- render ------------------------------------------------------------

    def _refresh_display(self) -> None:
        self.update(self._compose_text())

    def _value_text(self) -> Text:
        t = self._theme

        if self._state == "active" and self._spinner:
            spin = _SPINNER_FRAMES[self._spinner_idx]
            return Text(spin, style=t.accent) + Text(f" {self._unit}".rstrip(), style=t.text_dim)

        if self._displayed is None or (self._state == "pending" and self._value is None):
            return Text(_PLACEHOLDER, style=t.text_dim)

        value = self._displayed
        digit_color = t.accent if self._state == "active" else t.accent_dim
        formatted = self._format_value(value)
        out = Text()
        out.append(formatted, style=digit_color)
        if self._unit:
            out.append(f" {self._unit}", style=t.text_dim)
        return out

    def _format_value(self, value: float | int) -> str:
        if isinstance(value, int):
            return str(value)
        if abs(value) >= 100 or self._precision == 0:
            return str(int(round(value)))
        return f"{value:.{self._precision}f}"
