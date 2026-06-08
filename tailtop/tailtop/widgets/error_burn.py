"""ErrorBurn — a one-shot TTE burn over a message in the theme's error color.

Mount it anywhere you want a "bad-news" pulse. When the burn finishes (or
``skip()`` is called), it posts ``TTERunner.Finished`` and the parent
removes it.
"""

from __future__ import annotations

from rich.text import Text

from tailtop.themes import Theme, theme_for_mode
from tailtop.widgets.effect_library import burn
from tailtop.widgets.tte_runner import TTERunner


class ErrorBurn(TTERunner):
    """A TTERunner pre-configured for the burn-on-error pattern."""

    def __init__(
        self,
        message: str,
        *,
        theme: Theme | None = None,
        **kwargs,
    ) -> None:
        theme = theme or theme_for_mode("comfort")
        super().__init__(
            burn(message, theme),
            final_text=Text(message, style=theme.error),
            **kwargs,
        )
