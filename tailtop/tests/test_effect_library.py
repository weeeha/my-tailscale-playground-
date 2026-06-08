"""effect_library tests — theme tokens correctly threaded into TTE configs."""

from __future__ import annotations

import pytest

from tailtop.themes import BRUTALIST, MISSION_CONTROL, STUDIO, Theme, theme_for_mode
from tailtop.widgets.effect_library import beams, burn, lolcat, print_


@pytest.mark.parametrize(
    "mode,expected",
    [("comfort", STUDIO), ("cockpit", MISSION_CONTROL), ("observatory", BRUTALIST)],
)
def test_theme_lookup_by_mode(mode: str, expected: Theme) -> None:
    assert theme_for_mode(mode) is expected


def test_theme_rgb_conversion() -> None:
    assert STUDIO.rgb_accent() == (0x8B, 0xB6, 0xFF)
    assert MISSION_CONTROL.rgb_accent() == (0xF0, 0xC6, 0x74)
    assert BRUTALIST.rgb_error() == (0xFF, 0x7E, 0x88)


@pytest.mark.parametrize("theme", [STUDIO, MISSION_CONTROL, BRUTALIST])
def test_beams_uses_theme_accent(theme: Theme) -> None:
    effect = beams("Hello", theme)
    cfg = effect.effect_config
    stops = cfg.final_gradient_stops
    assert len(stops) >= 1
    # Color stores RGB - confirm the accent is in the final gradient
    assert any(c.rgb_ints == theme.rgb_accent() for c in stops)


@pytest.mark.parametrize("theme", [STUDIO, MISSION_CONTROL, BRUTALIST])
def test_print_uses_theme_accent(theme: Theme) -> None:
    effect = print_("Connected.", theme)
    stops = effect.effect_config.final_gradient_stops
    assert any(c.rgb_ints == theme.rgb_accent() for c in stops)


@pytest.mark.parametrize("theme", [STUDIO, MISSION_CONTROL, BRUTALIST])
def test_burn_uses_error_and_no_smoke(theme: Theme) -> None:
    effect = burn("Offline", theme)
    cfg = effect.effect_config
    assert cfg.starting_color.rgb_ints == theme.rgb_error()
    assert cfg.smoke_chance == 0.0


def test_lolcat_per_char_color() -> None:
    text = lolcat("ABC")
    assert text.plain == "ABC"
    # Each char gets its own span - 3 chars = 3 spans
    assert len(text.spans) == 3
    # Colors should be distinct (rainbow)
    colors = {str(s.style) for s in text.spans}
    assert len(colors) == 3


def test_effects_are_iterable_after_configuration() -> None:
    """After theme-config, the effect still iterates and yields strings."""
    effect = beams("Hi", STUDIO)
    frames = list(effect)
    assert len(frames) > 0
    assert all(isinstance(f, str) for f in frames)
