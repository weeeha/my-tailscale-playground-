"""Theme tokens mirrored from the .tcss files for Python-side use.

The .tcss files are the source of truth for the rendered UI. This module
mirrors the few tokens animations need (accents, error, dim) so effects
can be configured without parsing CSS.

Keep in sync with base/studio/mission_control/brutalist.tcss.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    name: str
    accent: str       # primary brand color for this mode
    accent_dim: str   # muted accent (post-animation settled state, etc.)
    text: str         # body text
    text_dim: str     # muted body text
    error: str        # destructive / disconnect color
    background: str

    # convenience: bare hex without leading '#' (what TTE's Color accepts)
    def accent_hex(self) -> str:
        return self.accent.lstrip("#")

    def accent_dim_hex(self) -> str:
        return self.accent_dim.lstrip("#")

    def error_hex(self) -> str:
        return self.error.lstrip("#")

    def text_dim_hex(self) -> str:
        return self.text_dim.lstrip("#")

    def rgb_accent(self) -> tuple[int, int, int]:
        return _hex_to_rgb(self.accent)

    def rgb_accent_dim(self) -> tuple[int, int, int]:
        return _hex_to_rgb(self.accent_dim)

    def rgb_error(self) -> tuple[int, int, int]:
        return _hex_to_rgb(self.error)

    def rgb_text_dim(self) -> tuple[int, int, int]:
        return _hex_to_rgb(self.text_dim)


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    s = hex_str.lstrip("#")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


STUDIO = Theme(
    name="studio",
    accent="#8bb6ff",
    accent_dim="#5a6f99",
    text="#cfd3da",
    text_dim="#8a8f99",
    error="#ff7e88",
    background="#0d0d12",
)

MISSION_CONTROL = Theme(
    name="mission_control",
    accent="#f0c674",
    accent_dim="#7a6536",
    text="#cfd3da",
    text_dim="#6b6f78",
    error="#ff7e88",
    background="#0d0d12",
)

BRUTALIST = Theme(
    name="brutalist",
    accent="#c792ea",
    accent_dim="#5a4a6e",
    text="#cfd3da",
    text_dim="#6b6f78",
    error="#ff7e88",
    background="#0d0d12",
)

_BY_MODE = {
    "comfort": STUDIO,
    "cockpit": MISSION_CONTROL,
    "observatory": BRUTALIST,
}


def theme_for_mode(mode: str) -> Theme:
    """Return the Theme for an app mode. Falls back to Studio."""
    return _BY_MODE.get(mode, STUDIO)
