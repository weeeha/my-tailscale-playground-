"""SQLite timeline store for the fleet hub.

Sibling of lifelog's store (same idioms: constructor runs the schema, Row
factory, ts REAL epoch seconds, JSON-blob columns, decoupled commit()), with
WAL enabled for concurrent scheduler-writes + API-reads.
"""

from __future__ import annotations

import json
import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS device (
    host          TEXT NOT NULL,
    ts            REAL NOT NULL,
    online        INTEGER NOT NULL,
    has_probe     INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL,
    PRIMARY KEY (host, ts)
);

CREATE TABLE IF NOT EXISTS metric (
    host  TEXT NOT NULL,
    ts    REAL NOT NULL,
    key   TEXT NOT NULL,
    value REAL NOT NULL,
    UNIQUE (host, ts, key)
);
CREATE INDEX IF NOT EXISTS ix_metric_host_key_ts ON metric(host, key, ts);

CREATE TABLE IF NOT EXISTS event (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    host        TEXT NOT NULL,
    ts          REAL NOT NULL,
    kind        TEXT NOT NULL,
    detail_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_event_host_ts ON event(host, ts);

CREATE TABLE IF NOT EXISTS metric_hourly (
    host  TEXT NOT NULL,
    hour  INTEGER NOT NULL,
    key   TEXT NOT NULL,
    min   REAL NOT NULL,
    max   REAL NOT NULL,
    avg   REAL NOT NULL,
    n     INTEGER NOT NULL,
    PRIMARY KEY (host, hour, key)
);
"""


class Store:
    def __init__(self, path: str = "tailhub.db") -> None:
        self.path = path
        # check_same_thread=False: FastAPI serves sync handlers from a threadpool, so
        # the connection is read off the creating thread. WAL + a single writer keeps this safe.
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        # WAL: safe concurrent reads (API) during writes (scheduler).
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(_SCHEMA)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def commit(self) -> None:
        self.db.commit()

    # -- writes --------------------------------------------------------------
    def add_device(self, host: str, ts: float, *, online: bool, has_probe: bool,
                   snapshot: dict) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO device(host, ts, online, has_probe, snapshot_json) "
            "VALUES (?,?,?,?,?)",
            (host, ts, int(online), int(has_probe), json.dumps(snapshot)),
        )

    def add_metrics(self, host: str, ts: float, metrics: dict[str, float]) -> None:
        self.db.executemany(
            "INSERT OR IGNORE INTO metric(host, ts, key, value) VALUES (?,?,?,?)",
            [(host, ts, k, float(v)) for k, v in metrics.items()],
        )

    def add_event(self, host: str, ts: float, kind: str, detail: dict) -> None:
        self.db.execute(
            "INSERT INTO event(host, ts, kind, detail_json) VALUES (?,?,?,?)",
            (host, ts, kind, json.dumps(detail)),
        )

    # -- reads ---------------------------------------------------------------
    def _row_to_device(self, r: sqlite3.Row) -> dict:
        return {
            "host": r["host"],
            "last_seen": r["ts"],
            "online": bool(r["online"]),
            "has_probe": bool(r["has_probe"]),
            "snapshot": json.loads(r["snapshot_json"]),
        }

    def latest_devices(self) -> list[dict]:
        cur = self.db.execute(
            "SELECT d.host, d.ts, d.online, d.has_probe, d.snapshot_json FROM device d "
            "JOIN (SELECT host, MAX(ts) AS mts FROM device GROUP BY host) m "
            "  ON d.host = m.host AND d.ts = m.mts "
            "ORDER BY d.host ASC"
        )
        return [self._row_to_device(r) for r in cur]

    def latest_device(self, host: str) -> dict | None:
        r = self.db.execute(
            "SELECT host, ts, online, has_probe, snapshot_json FROM device "
            "WHERE host = ? ORDER BY ts DESC LIMIT 1",
            (host,),
        ).fetchone()
        return self._row_to_device(r) if r else None

    def metric_history(self, host: str, key: str, since: float,
                       until: float | None = None) -> list[list]:
        """Return [[ts, value], ...] for ts in (since, until] — since-exclusive, until-inclusive."""
        until = until if until is not None else since + 86400.0
        cur = self.db.execute(
            "SELECT ts, value FROM metric WHERE host=? AND key=? AND ts > ? AND ts <= ? "
            "ORDER BY ts ASC",
            (host, key, since, until),
        )
        return [[r["ts"], r["value"]] for r in cur]

    def recent_events(self, host: str, since: float | None = None,
                      limit: int = 50) -> list[dict]:
        if since is None:
            cur = self.db.execute(
                "SELECT ts, kind, detail_json FROM event WHERE host=? ORDER BY ts DESC LIMIT ?",
                (host, limit),
            )
        else:
            cur = self.db.execute(
                "SELECT ts, kind, detail_json FROM event WHERE host=? AND ts > ? "
                "ORDER BY ts DESC LIMIT ?",
                (host, since, limit),
            )
        return [{"ts": r["ts"], "kind": r["kind"], "detail": json.loads(r["detail_json"])}
                for r in cur]

    def rollup_hour(self, hour_start: int) -> int:
        """Aggregate raw metrics in [hour_start, hour_start+3600) into metric_hourly.
        Returns the number of (host, key) buckets written."""
        lo, hi = float(hour_start), float(hour_start) + 3600.0
        rows = self.db.execute(
            "SELECT host, key, MIN(value) AS mn, MAX(value) AS mx, AVG(value) AS av, COUNT(*) AS n "
            "FROM metric WHERE ts >= ? AND ts < ? GROUP BY host, key",
            (lo, hi),
        ).fetchall()
        for r in rows:
            self.db.execute(
                "INSERT OR REPLACE INTO metric_hourly(host, hour, key, min, max, avg, n) "
                "VALUES (?,?,?,?,?,?,?)",
                (r["host"], hour_start, r["key"], r["mn"], r["mx"], r["av"], r["n"]),
            )
        self.db.commit()
        return len(rows)

    def prune(self, before_ts: float) -> None:
        """Delete raw device/metric rows older than before_ts (rollups are kept)."""
        self.db.execute("DELETE FROM metric WHERE ts < ?", (before_ts,))
        self.db.execute("DELETE FROM device WHERE ts < ?", (before_ts,))
        self.db.commit()
