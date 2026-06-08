"""Sleep analytics — the Phase 3 "wow" output.

Builds on the SLEEPING segments fusion already produces (bedroom + still +
breathing rhythm) and turns them into a night's summary: when you slept, how
long, how many times you stirred, how restless, and your average breathing rate.
A brief bathroom trip or a roll-over splits the SLEEPING run; sessions stitch
those back together across short gaps so the night reads as one sleep.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from statistics import mean

from . import config as C
from .model import Segment
from .store import Store

MERGE_GAP_S = 45 * 60       # gaps shorter than this stay within one night's sleep
RESTLESS_REF = C.MOTION_OCCUPIED   # motion scale for the 0..1 restlessness index


@dataclass(slots=True)
class SleepSummary:
    date: str
    in_bed_start: float
    wake_end: float
    asleep_s: float          # time actually classified SLEEPING
    in_bed_s: float          # session span (onset → final wake)
    awakenings: int          # interruptions stitched within the session
    restless_index: float    # 0..1, mean motion during the session
    mean_bpm: float          # average breathing rate while asleep
    efficiency: float        # asleep_s / in_bed_s


def _sessions(sleeps: list[Segment]) -> list[list[Segment]]:
    out: list[list[Segment]] = []
    cur = [sleeps[0]]
    for prev, seg in zip(sleeps, sleeps[1:]):
        if seg.start_ts - prev.end_ts <= MERGE_GAP_S:
            cur.append(seg)
        else:
            out.append(cur)
            cur = [seg]
    out.append(cur)
    return out


def analyze_main_sleep(store: Store, date: str | None = None) -> SleepSummary | None:
    """Return the night's main (longest) sleep session, or None if no sleep."""
    if date is None:
        date = time.strftime("%Y-%m-%d")
    sleeps = [s for s in store.segments_for_day(date) if s.activity == C.SLEEPING]
    if not sleeps:
        return None

    main = max(_sessions(sleeps), key=lambda ss: ss[-1].end_ts - ss[0].start_ts)
    lo, hi = main[0].start_ts, main[-1].end_ts
    asleep_s = sum(s.duration_s for s in main)
    in_bed_s = max(1.0, hi - lo)

    bpms = [b for b in store.breathing_between(lo, hi) if b > 0]
    motions = store.motion_samples_between(lo, hi)
    restless = min(1.0, (mean(motions) / RESTLESS_REF) if motions else 0.0)

    return SleepSummary(
        date=date,
        in_bed_start=lo,
        wake_end=hi,
        asleep_s=asleep_s,
        in_bed_s=in_bed_s,
        awakenings=len(main) - 1,
        restless_index=round(restless, 2),
        mean_bpm=round(mean(bpms), 1) if bpms else 0.0,
        efficiency=round(asleep_s / in_bed_s, 2),
    )


def render_card(s: SleepSummary) -> str:
    def hm(ts: float) -> str:
        return time.strftime("%H:%M", time.localtime(ts))

    def dur(sec: float) -> str:
        m = int(round(sec / 60))
        return f"{m // 60}h{m % 60:02d}m"

    quality = "good" if s.efficiency >= 0.9 and s.restless_index < 0.3 else \
              "ok" if s.efficiency >= 0.8 else "rough"
    bars = "▁▂▃▄▅▆▇█"
    restless_bar = bars[min(len(bars) - 1, int(s.restless_index * (len(bars) - 1)))]
    return "\n".join([
        "Sleep",
        "-" * 52,
        f"  asleep      {hm(s.in_bed_start)} → {hm(s.wake_end)}   ({dur(s.asleep_s)})",
        f"  efficiency  {int(s.efficiency * 100)}%   ({quality})",
        f"  awakenings  {s.awakenings}",
        f"  restless    {restless_bar} {s.restless_index:.2f}",
        f"  breathing   {s.mean_bpm:.1f}/min avg",
    ])
