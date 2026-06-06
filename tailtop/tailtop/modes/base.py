"""Base class for mode views.

A mode is a full-screen view (Comfort / Cockpit / Observatory). The app owns
the data and pushes it down via ``update_data`` whenever a fresh poll lands or
the user switches into the mode.

The first time a mode is shown in a session, ``on_first_visit`` fires. The
default plays a brief beams animation over the mode's content (curtain rise).
ComfortMode overrides to skip — the BootOverlay handles its first visit.
"""

from __future__ import annotations

from rich.text import Text
from textual.containers import Container

from tailtop.data.models import Status
from tailtop.state import RateHistory
from tailtop.themes import theme_for_mode
from tailtop.widgets.effect_library import beams
from tailtop.widgets.tte_runner import TTERunner


class ModeView(Container):
    """Common interface every mode implements."""

    #: cadence (seconds) the poller should use while this mode is active
    cadence: float = 2.0

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._first_visit_done = False
        self._mount_overlay: TTERunner | None = None

    @property
    def first_visit_done(self) -> bool:
        return self._first_visit_done

    def on_first_visit(self) -> None:
        """Called by the app the first time this mode becomes the current view.

        Default: mount a beams overlay using the mode's id as the title.
        Override to opt out (e.g. when something else covers first-visit).
        """
        title = self.id.title() if self.id else "Mode"
        theme = theme_for_mode(self.id or "comfort")
        overlay = TTERunner(
            beams(title, theme),
            final_text=Text(title, style=theme.accent),
            id="mode-mount-beams",
        )
        # Stretch over the whole mode briefly
        overlay.styles.dock = "top"
        overlay.styles.layer = "overlay"
        overlay.styles.width = "100%"
        overlay.styles.height = "1"
        overlay.styles.content_align = ("center", "middle")
        overlay.styles.background = theme.background
        self.mount(overlay)
        self._mount_overlay = overlay

    def _dismiss_mount_overlay(self) -> None:
        if self._mount_overlay is not None:
            try:
                self._mount_overlay.remove()
            except Exception:  # noqa: BLE001
                pass
            self._mount_overlay = None

    def on_tterunner_finished(self, msg: TTERunner.Finished) -> None:
        if self._mount_overlay is not None and msg.runner is self._mount_overlay:
            self._dismiss_mount_overlay()

    def mark_first_visit_done(self) -> None:
        """Called by the app to flip the flag without firing the hook."""
        self._first_visit_done = True

    def update_data(self, status: Status, rates: RateHistory) -> None:  # noqa: B027
        """Receive a fresh snapshot. Override in subclasses."""
