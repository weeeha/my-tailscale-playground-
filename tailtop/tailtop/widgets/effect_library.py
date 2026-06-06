"""Factories that return theme-configured TTE effects.

Only the three *placed* effects (beams, print_, burn) are tuned for our
themes. Sweep, Thunderstorm, and a handful of other effects are exposed
as raw factories for the unplaced library — defaults preserved.

Lolcat is a styling utility (rainbow per-character), not a TTE effect;
it lives at the bottom of this module.
"""

from __future__ import annotations

import colorsys

from rich.text import Text
from terminaltexteffects import Color, Gradient
from terminaltexteffects.effects.effect_beams import Beams, BeamsConfig
from terminaltexteffects.effects.effect_burn import Burn, BurnConfig
from terminaltexteffects.effects.effect_print import Print, PrintConfig
from terminaltexteffects.effects.effect_sweep import Sweep
from terminaltexteffects.effects.effect_thunderstorm import Thunderstorm
from terminaltexteffects.engine.base_effect import BaseEffect

from tailtop.themes import Theme

# ---- placed effects --------------------------------------------------------


def beams(text: str, theme: Theme) -> BaseEffect:
    """Curtain-rise: beams sweep in and resolve to ``text`` in the theme's accent."""
    effect = Beams(text)
    cfg: BeamsConfig = effect.effect_config
    cfg.beam_gradient_stops = (
        Color(theme.text_dim_hex()),
        Color(theme.accent_hex()),
    )
    cfg.final_gradient_stops = (Color(theme.accent_hex()),)
    cfg.final_gradient_steps = 8
    return effect


def print_(text: str, theme: Theme) -> BaseEffect:
    """Typewriter status line — final color = theme accent."""
    effect = Print(text)
    cfg: PrintConfig = effect.effect_config
    cfg.final_gradient_stops = (Color(theme.accent_hex()),)
    cfg.final_gradient_steps = 6
    return effect


def burn(text: str, theme: Theme) -> BaseEffect:
    """Error-state burn — theme error → text_dim, no flame glyphs, ~300ms.

    TTE's Burn uses block glyphs ▓▒░ which read as 'degrade' more than 'fire'
    once we drop the orange palette; we keep them and just override colors.
    """
    effect = Burn(text)
    cfg: BurnConfig = effect.effect_config
    cfg.starting_color = Color(theme.error_hex())
    cfg.burn_colors = (
        Color(theme.error_hex()),
        Color(theme.text_dim_hex()),
    )
    cfg.smoke_chance = 0.0
    cfg.final_gradient_stops = (Color(theme.text_dim_hex()),)
    cfg.final_gradient_steps = 4
    cfg.final_gradient_direction = Gradient.Direction.HORIZONTAL
    return effect


# ---- unplaced library (defaults; pass through) -----------------------------


def sweep(text: str) -> BaseEffect:
    return Sweep(text)


def thunderstorm(text: str) -> BaseEffect:
    return Thunderstorm(text)


# ---- lolcat (styling utility, not an animation) ----------------------------


def lolcat(text: str, *, frequency: float = 0.2, offset: float = 0.0) -> Text:
    """Apply a rainbow HSV gradient across each character of ``text``.

    Returns a Rich ``Text`` with per-character colors. Not animated — drop
    it into a Static.update() for an instant-on rainbow string.
    """
    out = Text()
    for i, ch in enumerate(text):
        h = (offset + i * frequency) % 1.0
        r, g, b = colorsys.hsv_to_rgb(h, 1.0, 1.0)
        hex_color = f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"
        out.append(ch, style=hex_color)
    return out
