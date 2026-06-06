"""SQLite timeline store.

Local-first by design: one file you own, nothing leaves the machine. Schema
mirrors ``notes/lifelog-wifi-sensing-design.md`` §4.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from datetime import datetime

from .model import Segment, SensorEvent, StateSample

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sensor_event (
    ts REAL NOT NULL,
    node_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    features_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sensor_event_ts ON sensor_event(ts);

CREATE TABLE IF NOT EXISTS state_sample (
    ts REAL NOT NULL,
    room TEXT NOT NULL,
    activity TEXT NOT NULL,
    motion REAL NOT NULL,
    confidence REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_state_sample_ts ON state_sample(ts);

CREATE TABLE IF NOT EXISTS segment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_ts REAL NOT NULL,
    end_ts REAL NOT NULL,
    room TEXT NOT NULL,
    activity TEXT NOT NULL,
    duration_s REAL NOT NULL,
    attrs_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_segment_start ON segment(start_ts);
"""


def _day_bounds(date: str) -> tuple[float, float]:
    """[start, end) epoch seconds for a local YYYY-MM-DD date."""
    start = datetime.strptime(date, "%Y-%m-%d").timestamp()
    return start, start + 86400.0


class Store:
    def __init__(self, path: str = "lifelog.db") -> None:
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # -- writes --------------------------------------------------------------
    def add_sensor_event(self, ev: SensorEvent) -> None:
        self.db.execute(
            "INSERT INTO sensor_event(ts, node_id, kind, features_json) VALUES (?,?,?,?)",
            (ev.ts, ev.node_id, ev.kind, json.dumps(ev.features)),
        )

    def add_state_sample(self, s: StateSample) -> None:
        self.db.execute(
            "INSERT INTO state_sample(ts, room, activity, motion, confidence) VALUES (?,?,?,?,?)",
            (s.ts, s.room, s.activity, s.motion, s.confidence),
        )

    def add_segment(self, seg: Segment) -> None:
        seg.finalize()
        self.db.execute(
            "INSERT INTO segment(start_ts, end_ts, room, activity, duration_s, attrs_json) "
            "VALUES (?,?,?,?,?,?)",
            (seg.start_ts, seg.end_ts, seg.room, seg.activity, seg.duration_s,
             json.dumps(seg.attrs)),
        )

    def commit(self) -> None:
        self.db.commit()

    # -- reads ---------------------------------------------------------------
    def sensor_events_since(self, ts: float) -> Iterator[SensorEvent]:
        cur = self.db.execute(
            "SELECT ts, node_id, kind, features_json FROM sensor_event "
            "WHERE ts > ? ORDER BY ts ASC",
            (ts,),
        )
        for r in cur:
            yield SensorEvent(r["ts"], r["node_id"], r["kind"], json.loads(r["features_json"]))

    def segments_for_day(self, date: str | None = None) -> list[Segment]:
        if date is None:
            date = time.strftime("%Y-%m-%d")
        lo, hi = _day_bounds(date)
        cur = self.db.execute(
            "SELECT start_ts, end_ts, room, activity, duration_s, attrs_json FROM segment "
            "WHERE start_ts >= ? AND start_ts < ? ORDER BY start_ts ASC",
            (lo, hi),
        )
        return [
            Segment(r["start_ts"], r["end_ts"], r["room"], r["activity"],
                    r["duration_s"], json.loads(r["attrs_json"]))
            for r in cur
        ]

    def breathing_between(self, lo: float, hi: float) -> list[float]:
        """Breathing-rate readings (bpm) in [lo, hi) — for sleep analytics."""
        cur = self.db.execute(
            "SELECT features_json FROM sensor_event "
            "WHERE kind='breathing' AND ts >= ? AND ts < ? ORDER BY ts",
            (lo, hi),
        )
        return [json.loads(r["features_json"]).get("bpm", 0.0) for r in cur]

    def motion_samples_between(self, lo: float, hi: float) -> list[float]:
        """Fused motion values in [lo, hi) — for the restlessness index."""
        cur = self.db.execute(
            "SELECT motion FROM state_sample WHERE ts >= ? AND ts < ? ORDER BY ts",
            (lo, hi),
        )
        return [r["motion"] for r in cur]

    def activity_totals(self, date: str | None = None) -> dict[str, float]:
        """Activity → total seconds for a day. The 'where did my time go' query."""
        if date is None:
            date = time.strftime("%Y-%m-%d")
        lo, hi = _day_bounds(date)
        cur = self.db.execute(
            "SELECT activity, SUM(duration_s) AS total FROM segment "
            "WHERE start_ts >= ? AND start_ts < ? GROUP BY activity ORDER BY total DESC",
            (lo, hi),
        )
        return {r["activity"]: r["total"] for r in cur}
