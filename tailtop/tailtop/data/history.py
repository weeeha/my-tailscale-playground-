"""SQLite-backed vitals history store.

One lightweight table keeps the last N samples per host so Cockpit sparklines
survive a restart.  Uses stdlib ``sqlite3`` only — no extra deps.

Default DB path: ``~/.local/state/tailtop/vitals.db``.  Pass ``":memory:"``
(or any other explicit path) to override, e.g. in tests.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tailtop.data.vitals import Vitals

_DEFAULT_DB_PATH = Path.home() / ".local" / "state" / "tailtop" / "vitals.db"

_DDL = """
CREATE TABLE IF NOT EXISTS samples (
    host     TEXT    NOT NULL,
    ts       REAL    NOT NULL,
    temp_c   REAL,
    cpu_pct  REAL,
    disk_pct REAL,
    health   TEXT
);
CREATE INDEX IF NOT EXISTS idx_samples_host_ts ON samples (host, ts);
"""


class VitalsStore:
    """Persist vitals samples to SQLite and retrieve recent series."""

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            db_path = _DEFAULT_DB_PATH
            db_path.parent.mkdir(parents=True, exist_ok=True)
            connect_arg = str(db_path)
        elif str(path) == ":memory:":
            connect_arg = ":memory:"
        else:
            db_path = Path(path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            connect_arg = str(db_path)

        self._conn = sqlite3.connect(connect_arg)
        self._conn.executescript(_DDL)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(self, host: str, ts: float, v: "Vitals") -> None:
        """Insert one sample row.

        Skips the row only when *both* ``soc_temp_c`` and ``cpu_pct`` are
        ``None`` (i.e. the Vitals object carries no meaningful metric at all).
        A zero ``cpu_pct`` is valid and will be stored.
        """
        temp = v.soc_temp_c
        cpu = v.cpu_pct if v.cpu_pct is not None else None
        disk = v.disk_used_pct if v.disk_used_pct is not None else None
        health = v.health_level

        # Guard: only skip when we have literally nothing useful
        if temp is None and cpu is None:
            return

        self._conn.execute(
            "INSERT INTO samples (host, ts, temp_c, cpu_pct, disk_pct, health) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (host, ts, temp, cpu, disk, health),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def recent_temps(self, host: str, limit: int = 32) -> list[float]:
        """Return up to *limit* temperature readings, oldest→newest.

        Missing (NULL) temperature rows are excluded.
        Returns ``[]`` for an unknown host.
        """
        rows = self._conn.execute(
            "SELECT temp_c FROM ("
            "  SELECT temp_c, ts FROM samples"
            "  WHERE host = ? AND temp_c IS NOT NULL"
            "  ORDER BY ts DESC LIMIT ?"
            ") ORDER BY ts ASC",
            (host, limit),
        ).fetchall()
        return [r[0] for r in rows]

    def recent_cpu(self, host: str, limit: int = 32) -> list[float]:
        """Return up to *limit* CPU% readings, oldest→newest.

        Missing (NULL) cpu rows are excluded.
        Returns ``[]`` for an unknown host.
        """
        rows = self._conn.execute(
            "SELECT cpu_pct FROM ("
            "  SELECT cpu_pct, ts FROM samples"
            "  WHERE host = ? AND cpu_pct IS NOT NULL"
            "  ORDER BY ts DESC LIMIT ?"
            ") ORDER BY ts ASC",
            (host, limit),
        ).fetchall()
        return [r[0] for r in rows]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()
