"""Bottom hotkey bar — the core verb shortcuts.

`p palette` is always live. `s ssh`, `f send`, `e exit-node` dim when no peer
is selected, since they all target the current selection.
"""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

_KEY = "#f0c674"
_LABEL = "#8a8f99"
_DIM_KEY = "#3a3a44"
_DIM_LABEL = "#3a3a44"


class HotkeyBar(Static):
    """Single row of core hotkeys, contextual to whether a peer is selected."""

    def set_state(self, has_selection: bool) -> None:
        line = Text()
        line.append("  ")
        line.append("p", style=f"bold {_KEY}")
        line.append(" palette", style=_LABEL)
        line.append("     ")

        key_style = f"bold {_KEY}" if has_selection else f"bold {_DIM_KEY}"
        label_style = _LABEL if has_selection else _DIM_LABEL

        line.append("s", style=key_style)
        line.append(" ssh", style=label_style)
        line.append("     ")
        line.append("f", style=key_style)
        line.append(" send", style=label_style)
        line.append("     ")
        line.append("e", style=key_style)
        line.append(" exit-node", style=label_style)

        self.update(line)
