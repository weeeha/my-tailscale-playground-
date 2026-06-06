"""Plain-text timeline report — the runnable payoff with no Textual needed."""

from __future__ import annotations

import time

from . import config as C
from .store import Store

_RIBBON_SLOTS = 96       # 24h at 15-minute resolution
_SLOT_S = 86400 / _RIBBON_SLOTS


def _hm(ts: float) -> str:
    return time.strftime("%H:%M", time.localtime(ts))


def _dur(seconds: float) -> str:
    m = int(round(seconds / 60))
    return f"{m // 60:>2}h{m % 60:02d}m"


def render_day(store: Store, date: str | None = None) -> str:
    if date is None:
        date = time.strftime("%Y-%m-%d")
    segments = store.segments_for_day(date)
    totals = store.activity_totals(date)

    lines = [f"Lifelog — {date}", "=" * 52, ""]

    # 24-hour ribbon
    day_start = time.mktime(time.strptime(date, "%Y-%m-%d"))
    slots = [C.GLYPH[C.AWAY]] * _RIBBON_SLOTS
    for seg in segments:
        lo = int((seg.start_ts - day_start) // _SLOT_S)
        hi = int((seg.end_ts - day_start) // _SLOT_S)
        for i in range(max(0, lo), min(_RIBBON_SLOTS, hi + 1)):
            slots[i] = C.GLYPH.get(seg.activity, "?")
    lines += ["  00      04      08      12      16      20      24",
              "  " + "".join(slots), ""]

    # timeline
    lines.append("Timeline")
    lines.append("-" * 52)
    for seg in segments:
        room = f"@{seg.room}" if seg.room else ""
        lines.append(
            f"  {_hm(seg.start_ts)}–{_hm(seg.end_ts)}  {_dur(seg.duration_s)}  "
            f"{seg.activity:<9} {room}"
        )

    # totals
    lines += ["", "Where the time went", "-" * 52]
    total = sum(totals.values()) or 1.0
    for activity, secs in totals.items():
        bar = "█" * int(round(40 * secs / total))
        lines.append(f"  {activity:<9} {_dur(secs)}  {bar}")

    legend = "  ".join(f"{g}={a}" for a, g in C.GLYPH.items() if a != C.AWAY)
    lines += ["", f"legend: {legend}"]
    return "\n".join(lines)
