"""BootOverlay — the launch sequence.

Two TTE animations play concurrently:
- ``beams`` assembles the title in the active theme's accent
- ``print`` streams the status line under it

When both finish (or the user presses any key), the overlay dismisses
and the underlying ComfortMode takes over.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Key
from textual.screen import Screen
from textual.widgets import Static

from tailtop.themes import Theme, theme_for_mode
from tailtop.widgets.effect_library import beams, print_
from tailtop.widgets.tte_runner import TTERunner

_TITLE = "TAILTOP — htop for your tailnet"
_CONNECTING = "Connecting to tailscaled…"


class BootOverlay(Screen):
    DEFAULT_CSS = """
    BootOverlay {
        align: center middle;
        background: #0d0d12;
    }
    BootOverlay #boot-stack {
        height: auto;
        width: auto;
    }
    BootOverlay TTERunner {
        height: 1;
        width: auto;
        content-align: center middle;
    }
    BootOverlay #spacer {
        height: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "skip", "Skip"),
    ]

    def __init__(
        self,
        *,
        theme: Theme | None = None,
        title: str = _TITLE,
        status: str = _CONNECTING,
    ) -> None:
        super().__init__()
        self._theme = theme or theme_for_mode("comfort")
        self._title = title
        self._status = status
        self._finished_count = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="boot-stack"):
            yield TTERunner(
                beams(self._title, self._theme),
                final_text=Text(self._title, style=self._theme.accent),
                id="boot-beams",
            )
            yield Static("", id="spacer")
            yield TTERunner(
                print_(self._status, self._theme),
                final_text=Text(self._status, style=self._theme.text),
                id="boot-print",
            )

    def on_tterunner_finished(self, _msg: TTERunner.Finished) -> None:
        self._finished_count += 1
        if self._finished_count >= 2:
            self.dismiss()

    def on_key(self, event: Key) -> None:
        # Any key skips both
        event.stop()
        for runner in self.query(TTERunner):
            runner.skip()

    def action_skip(self) -> None:
        for runner in self.query(TTERunner):
            runner.skip()
