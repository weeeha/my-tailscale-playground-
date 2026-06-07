"""Pure terminal-rendering primitives: color, sparklines, bars, tables.

No I/O, no tailnet knowledge — just strings in, strings out, so each piece is
trivially testable. ANSI-aware width handling keeps colored cells aligned.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

_BLOCKS = "▁▂▃▄▅▆▇█"
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

# SGR codes
GREEN, RED, YELLOW, CYAN, DIM, BOLD = "32", "31", "33", "36", "2", "1"


def color(text: str, code: str, enabled: bool = True) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if enabled else text


def visible_len(s: str) -> int:
    """Length excluding ANSI escapes — for aligning colored text."""
    return len(_ANSI.sub("", s))


def sparkline(values: Sequence[float]) -> str:
    if not values:
        return ""
    lo, hi = min(values), max(values)
    if hi == lo:
        return _BLOCKS[0] * len(values)
    span = hi - lo
    return "".join(_BLOCKS[int((v - lo) / span * (len(_BLOCKS) - 1))] for v in values)


def bar(value: float, maximum: float, width: int = 22,
        fill: str = "█", empty: str = "░") -> str:
    n = 0 if maximum <= 0 else round(width * value / maximum)
    n = max(0, min(width, int(n)))
    return fill * n + empty * (width - n)


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


def table(headers: Sequence[str], rows: Sequence[Sequence[str]], gap: str = "  ") -> str:
    widths = [visible_len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], visible_len(cell))

    def fmt(cells: Sequence[str]) -> str:
        return gap.join(c + " " * (widths[i] - visible_len(c)) for i, c in enumerate(cells))

    return "\n".join([fmt(headers), *(fmt(r) for r in rows)])
