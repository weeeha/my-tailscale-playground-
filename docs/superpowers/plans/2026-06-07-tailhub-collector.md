# tailhub Collector Implementation Plan (Phase 0, Plan 2 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `tailhub`, a Python/FastAPI service that discovers the Tailscale fleet, scrapes each `tailprobe` agent's `/vitals` on a schedule, stores history in SQLite, and serves a `/fleet` / `/device/{host}` / `/history` JSON API.

**Architecture:** A new sibling Python package `tailhub/` (like `tailtop/`, `tailsnap/`, `lifelog/`). It reuses `lifelog`'s store *idioms* (a sibling SQLite store: `sqlite3` + `Row` factory + `executescript` schema + decoupled `commit()`, `ts REAL` epoch, JSON-blob columns) but is self-contained (no cross-package import). The device row holds the full normalized snapshot JSON (so `/fleet` is a trivial read), while a narrow `metric(host, ts, key, value)` table feeds `/history` + hourly rollups. An async scheduler (`httpx` + `asyncio.gather`) scrapes all probes each cycle so one dead probe times out in parallel instead of stalling. The read API (`create_app`) is built independently of the scheduler so it's testable against a seeded store.

**Tech Stack:** Python ≥3.11, FastAPI, uvicorn, httpx (async), pydantic-settings, SQLite (stdlib, WAL). Tests: pytest + pytest-asyncio + FastAPI `TestClient`. Run with `uv` (as the sibling `tailtop` does).

**Contract (frozen):** consumes the probe's `schema:1` `/vitals` JSON (see `tailtop/agent/fleet_collect.sh` / `tailtop/tests/fixtures/vitals_orangepi.json`) and `cmd/tailprobe/` (Plan 1). Produces the `/fleet` API that `tailtop` will consume in Plan 4. Hub host: Mac Studio `100.75.213.56`. Probe port: 9100. Fleet (8 probe hosts) per design §12.

**Build/test commands:** from the repo root, all `tailhub` work uses `uv` against `tailhub/pyproject.toml`: `cd tailhub && uv run pytest tests/ -q`. (`uv run` auto-creates the venv and installs deps from pyproject — the same workflow `tailtop/README.md` documents. If `uv` is unavailable, fall back to `python3 -m venv .venv && .venv/bin/pip install -e '.[dev]' && .venv/bin/python -m pytest`.)

---

## File Structure

All under `tailhub/` (mirrors `tailtop/`):

| File | Responsibility |
|------|----------------|
| `tailhub/pyproject.toml` | package metadata + deps (fastapi, uvicorn, httpx, pydantic-settings; dev: pytest, pytest-asyncio) |
| `tailhub/tailhub/__init__.py` | package marker |
| `tailhub/tailhub/settings.py` | `Settings` (pydantic-settings): db path, interval, probe port/hosts, timeout, retention, bearer token, API bind |
| `tailhub/tailhub/store.py` | `Store` — SQLite (WAL) schema, writers, latest/history reads, rollup, prune |
| `tailhub/tailhub/vitals_norm.py` | pure `build_snapshot` + `vitals_to_metrics` (probe `/vitals` → snapshot dict + narrow metrics) |
| `tailhub/tailhub/fleet.py` | `tailscale_status_json` + `discover_fleet` (status → `Device` list; agentless included) |
| `tailhub/tailhub/scrape.py` | async `scrape_one` + `scrape_cycle` (gather, write, online-transition events) |
| `tailhub/tailhub/app.py` | `create_app(store, settings)` — FastAPI read API (`/fleet`, `/device/{host}`, `/history`, `/healthz`, `/alerts`+`/presence` stubs) |
| `tailhub/tailhub/scheduler.py` | async `run_cycle` / `run_scheduler` loop + `main()` (uvicorn + scheduler) |
| `tailhub/tailhub/__main__.py` | `python -m tailhub` → `main()` |
| `tailhub/tests/test_*.py` | one test module per source file |

---

## Task 1: Scaffold the `tailhub` package + settings

**Files:**
- Create: `tailhub/pyproject.toml`, `tailhub/tailhub/__init__.py`, `tailhub/tailhub/settings.py`, `tailhub/.gitignore`
- Test: `tailhub/tests/test_settings.py`

- [ ] **Step 1: Create package metadata and `.gitignore`**

`tailhub/pyproject.toml`:
```toml
[project]
name = "tailhub"
version = "0.1.0"
description = "Central collector for the Tailscale fleet: scrapes tailprobe agents into a SQLite timeline and serves a JSON API."
readme = "README.md"
requires-python = ">=3.11"
license = { text = "BSD-3-Clause" }
dependencies = [
    "fastapi>=0.110",
    "uvicorn>=0.29",
    "httpx>=0.27",
    "pydantic-settings>=2.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0,<9.0", "pytest-asyncio>=0.23"]

[project.scripts]
tailhub = "tailhub.__main__:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["tailhub"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.ruff]
line-length = 100
target-version = "py311"
```

`tailhub/.gitignore`:
```
.venv/
__pycache__/
*.pyc
*.db
*.db-wal
*.db-shm
.pytest_cache/
```

`tailhub/tailhub/__init__.py`:
```python
"""tailhub — central collector + API for a Tailscale tailprobe fleet."""
```

Create `tailhub/README.md` with a one-paragraph description (so `readme` resolves):
```markdown
# tailhub

Central collector for a Tailscale fleet. Discovers devices via `tailscale status`,
scrapes each `tailprobe` agent's `/vitals` on a schedule into a SQLite timeline,
and serves `/fleet`, `/device/{host}`, and `/history` over HTTP. Part of the
fleet-tracking stack (`docs/superpowers/specs/2026-06-07-tailfleet-tracking-design.md`).

    cd tailhub && uv run pytest tests/ -q     # tests
    cd tailhub && uv run tailhub               # run the collector + API
```

- [ ] **Step 2: Write the failing test**

`tailhub/tests/test_settings.py`:
```python
from tailhub.settings import Settings


def test_defaults():
    s = Settings()
    assert s.probe_port == 9100
    assert s.scrape_interval_s == 30.0
    assert s.retention_days >= 1
    assert "plantdashboard" in s.probe_hosts
    assert s.api_host and isinstance(s.api_port, int)


def test_env_override(monkeypatch):
    monkeypatch.setenv("TAILHUB_SCRAPE_INTERVAL_S", "5")
    monkeypatch.setenv("TAILHUB_DB_PATH", "/tmp/x.db")
    s = Settings()
    assert s.scrape_interval_s == 5.0
    assert s.db_path == "/tmp/x.db"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd tailhub && uv run pytest tests/test_settings.py -q`
Expected: FAIL — `ModuleNotFoundError: tailhub.settings`.

- [ ] **Step 4: Write minimal implementation**

`tailhub/tailhub/settings.py`:
```python
"""Runtime configuration, overridable via TAILHUB_* env vars."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

# The 8 Phase-0 Linux SBCs that run a tailprobe agent (design §12).
DEFAULT_PROBE_HOSTS = [
    "fastclock", "slowclock", "smallclock", "squareclock",
    "dashboard-ink-bed", "dashboard3eink", "plantdashboard",
    "nickv-orangepizero2w",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TAILHUB_", env_file=None)

    db_path: str = "tailhub.db"
    scrape_interval_s: float = 30.0
    probe_port: int = 9100
    request_timeout_s: float = 5.0
    retention_days: int = 14
    probe_hosts: list[str] = DEFAULT_PROBE_HOSTS
    bearer_token: str | None = None
    api_host: str = "127.0.0.1"
    api_port: int = 8099
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd tailhub && uv run pytest tests/test_settings.py -q`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add tailhub/pyproject.toml tailhub/.gitignore tailhub/README.md tailhub/tailhub/__init__.py tailhub/tailhub/settings.py tailhub/tests/test_settings.py
git commit -m "feat(tailhub): scaffold package + settings"
```

---

## Task 2: SQLite store — schema, writers, latest reads

**Files:**
- Create: `tailhub/tailhub/store.py`
- Test: `tailhub/tests/test_store.py`

Reuses lifelog `store.py` idioms (constructor runs `executescript`; `Row` factory; `ts REAL`; JSON-blob columns; decoupled `commit()`), adding WAL and the hub's 4 tables. The `device.snapshot_json` holds the full `/fleet`-shaped per-device object; `metric` is the narrow numeric series.

- [ ] **Step 1: Write the failing test**

`tailhub/tests/test_store.py`:
```python
from tailhub.store import Store


def test_write_and_latest(tmp_path):
    db = Store(str(tmp_path / "t.db"))
    db.add_device("fastclock", 100.0, online=True, has_probe=True,
                  snapshot={"host": "fastclock", "metrics": {"cpu_pct": 10.0}})
    db.add_metrics("fastclock", 100.0, {"cpu_pct": 10.0, "soc_temp_c": 50.0})
    # a later snapshot for the same host
    db.add_device("fastclock", 200.0, online=True, has_probe=True,
                  snapshot={"host": "fastclock", "metrics": {"cpu_pct": 22.0}})
    db.add_metrics("fastclock", 200.0, {"cpu_pct": 22.0, "soc_temp_c": 51.0})
    db.add_device("nick-iphone", 150.0, online=False, has_probe=False, snapshot={"host": "nick-iphone"})
    db.commit()

    latest = {d["host"]: d for d in db.latest_devices()}
    assert set(latest) == {"fastclock", "nick-iphone"}
    assert latest["fastclock"]["last_seen"] == 200.0          # newest row wins
    assert latest["fastclock"]["snapshot"]["metrics"]["cpu_pct"] == 22.0
    assert latest["fastclock"]["online"] is True and latest["fastclock"]["has_probe"] is True
    assert latest["nick-iphone"]["online"] is False and latest["nick-iphone"]["has_probe"] is False

    one = db.latest_device("fastclock")
    assert one["last_seen"] == 200.0
    assert db.latest_device("nope") is None


def test_wal_enabled(tmp_path):
    db = Store(str(tmp_path / "w.db"))
    mode = db.db.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tailhub && uv run pytest tests/test_store.py -q`
Expected: FAIL — `ModuleNotFoundError: tailhub.store`.

- [ ] **Step 3: Write minimal implementation**

`tailhub/tailhub/store.py`:
```python
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
CREATE INDEX IF NOT EXISTS ix_device_host_ts ON device(host, ts);

CREATE TABLE IF NOT EXISTS metric (
    host  TEXT NOT NULL,
    ts    REAL NOT NULL,
    key   TEXT NOT NULL,
    value REAL NOT NULL
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
        self.db = sqlite3.connect(path)
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
            "INSERT INTO metric(host, ts, key, value) VALUES (?,?,?,?)",
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tailhub && uv run pytest tests/test_store.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add tailhub/tailhub/store.py tailhub/tests/test_store.py
git commit -m "feat(tailhub): SQLite store (WAL) + device writers/latest reads"
```

---

## Task 3: Store — history, rollup, prune

**Files:**
- Modify: `tailhub/tailhub/store.py`
- Test: `tailhub/tests/test_store_history.py`

- [ ] **Step 1: Write the failing test**

`tailhub/tests/test_store_history.py`:
```python
from tailhub.store import Store


def test_metric_history_and_events(tmp_path):
    db = Store(str(tmp_path / "h.db"))
    for ts, v in [(100.0, 50.0), (130.0, 51.0), (160.0, 52.0)]:
        db.add_metrics("fastclock", ts, {"soc_temp_c": v})
    db.add_event("fastclock", 130.0, "went_offline", {"reason": "scrape_failed"})
    db.commit()

    pts = db.metric_history("fastclock", "soc_temp_c", since=120.0, until=200.0)
    assert pts == [[130.0, 51.0], [160.0, 52.0]]            # since is exclusive of 100.0

    evs = db.recent_events("fastclock")
    assert evs[0]["kind"] == "went_offline" and evs[0]["detail"]["reason"] == "scrape_failed"


def test_rollup_and_prune(tmp_path):
    db = Store(str(tmp_path / "r.db"))
    # three samples inside the hour starting at 3600
    for ts, v in [(3600.0, 10.0), (3700.0, 20.0), (3800.0, 30.0)]:
        db.add_metrics("fastclock", ts, {"cpu_pct": v})
    db.commit()

    n = db.rollup_hour(3600)
    assert n == 1                                          # one (host,key) bucket
    row = db.db.execute(
        "SELECT min,max,avg,n FROM metric_hourly WHERE host='fastclock' AND hour=3600 AND key='cpu_pct'"
    ).fetchone()
    assert row["min"] == 10.0 and row["max"] == 30.0 and row["avg"] == 20.0 and row["n"] == 3

    db.prune(before_ts=3650.0)                             # drop the 3600 sample only
    remaining = db.db.execute("SELECT COUNT(*) AS c FROM metric WHERE host='fastclock'").fetchone()["c"]
    assert remaining == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tailhub && uv run pytest tests/test_store_history.py -q`
Expected: FAIL — `AttributeError: 'Store' object has no attribute 'metric_history'`.

- [ ] **Step 3: Add the methods to `store.py`**

Append these methods to the `Store` class in `tailhub/tailhub/store.py`:
```python
    def metric_history(self, host: str, key: str, since: float,
                       until: float | None = None) -> list[list]:
        until = until if until is not None else since + 86400.0
        cur = self.db.execute(
            "SELECT ts, value FROM metric WHERE host=? AND key=? AND ts > ? AND ts <= ? "
            "ORDER BY ts ASC",
            (host, key, since, until),
        )
        return [[r["ts"], r["value"]] for r in cur]

    def recent_events(self, host: str, since: float | None = None,
                      limit: int = 50) -> list[dict]:
        import json
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
```

(Note: the `import json` inside `recent_events` is redundant with the module-level `import json` from Task 2 — remove the local import; it's shown here only so this task is self-contained. Use the module-level `json`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tailhub && uv run pytest tests/test_store_history.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add tailhub/tailhub/store.py tailhub/tests/test_store_history.py
git commit -m "feat(tailhub): metric history, hourly rollup, retention prune"
```

---

## Task 4: Vitals normalization

**Files:**
- Create: `tailhub/tailhub/vitals_norm.py`
- Test: `tailhub/tests/test_vitals_norm.py`

Pure functions turning one probe `/vitals` object into (a) the `/fleet`-shaped snapshot stored in `device.snapshot_json`, and (b) the narrow numeric `metric` rows. Missing/`null` numeric fields are simply omitted (never coerced to 0).

- [ ] **Step 1: Write the failing test**

`tailhub/tests/test_vitals_norm.py`:
```python
from tailhub.vitals_norm import build_snapshot, vitals_to_metrics

VITALS = {
    "schema": 1, "host": "plantdashboard", "collected_at": "2026-06-07T00:00:00Z",
    "config": {"model": "Raspberry Pi Zero 2 W", "cpu_cores": 4, "kernel": "6.12"},
    "thermal": {"soc_temp_c": 51.2, "vcgencmd_present": False,
                "throttled_now": True, "under_voltage_now": False},
    "health": {"load1": 0.3, "cpu_pct": 17.4, "mem_pct": 38.0,
               "disk_used_pct": 36.0, "disk_free_gb": 18.6, "uptime_s": 90432},
    "side_things": {"displays": [], "usb": [], "usb_count": 1, "battery": {"present": False}},
    "app": {"name": "dashboard", "running": True, "last_render": ""},
}


def test_build_snapshot():
    snap = build_snapshot(VITALS)
    assert snap["host"] == "plantdashboard"
    assert snap["config"]["model"] == "Raspberry Pi Zero 2 W"
    assert snap["metrics"]["cpu_pct"] == 17.4
    assert snap["metrics"]["soc_temp_c"] == 51.2
    assert snap["flags"] == {"throttled": True, "under_voltage": False}
    assert snap["apps"] == {"dashboard": True}
    assert snap["collected_at"] == "2026-06-07T00:00:00Z"


def test_vitals_to_metrics_omits_null_temp():
    m = vitals_to_metrics(VITALS)
    assert m["cpu_pct"] == 17.4 and m["uptime_s"] == 90432 and m["soc_temp_c"] == 51.2
    # null temp must be omitted, not 0
    v2 = {**VITALS, "thermal": {**VITALS["thermal"], "soc_temp_c": None}}
    m2 = vitals_to_metrics(v2)
    assert "soc_temp_c" not in m2
    # unknown app.running (null) must not appear as a numeric metric
    assert "app_running" not in m2


def test_apps_unknown_running_is_null():
    v = {**VITALS, "app": {"name": "dashboard", "running": None, "last_render": ""}}
    snap = build_snapshot(v)
    assert snap["apps"] == {"dashboard": None}     # null preserved, never coerced to False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tailhub && uv run pytest tests/test_vitals_norm.py -q`
Expected: FAIL — `ModuleNotFoundError: tailhub.vitals_norm`.

- [ ] **Step 3: Write minimal implementation**

`tailhub/tailhub/vitals_norm.py`:
```python
"""Turn a probe's schema:1 /vitals object into a stored snapshot + narrow metrics."""

from __future__ import annotations

# Numeric health fields lifted into the metric series.
_HEALTH_KEYS = ("load1", "cpu_pct", "mem_pct", "disk_used_pct", "disk_free_gb", "uptime_s")


def build_snapshot(vitals: dict) -> dict:
    """The /fleet-shaped per-device object stored in device.snapshot_json."""
    config = vitals.get("config", {})
    thermal = vitals.get("thermal", {})
    app = vitals.get("app", {})
    snap = {
        "host": vitals.get("host", ""),
        "collected_at": vitals.get("collected_at", ""),
        "config": {
            "model": config.get("model", ""),
            "serial": config.get("serial", ""),
            "cpu_cores": config.get("cpu_cores", 0),
            "mem_total_mb": config.get("mem_total_mb", 0),
            "os": config.get("os", ""),
            "kernel": config.get("kernel", ""),
            "disk_total_gb": config.get("disk_total_gb", 0.0),
        },
        "metrics": vitals_to_metrics(vitals),
        "flags": {
            "throttled": bool(thermal.get("throttled_now", False)),
            "under_voltage": bool(thermal.get("under_voltage_now", False)),
        },
        "apps": {},
    }
    name = app.get("name") or ""
    if name:
        snap["apps"][name] = app.get("running")   # True / False / None (null preserved)
    return snap


def vitals_to_metrics(vitals: dict) -> dict[str, float]:
    """Narrow numeric series for the metric table. Null/absent values are omitted."""
    out: dict[str, float] = {}
    health = vitals.get("health", {})
    for k in _HEALTH_KEYS:
        v = health.get(k)
        if isinstance(v, (int, float)):
            out[k] = float(v)
    temp = vitals.get("thermal", {}).get("soc_temp_c")
    if isinstance(temp, (int, float)):
        out["soc_temp_c"] = float(temp)
    usb = vitals.get("side_things", {}).get("usb_count")
    if isinstance(usb, (int, float)):
        out["usb_count"] = float(usb)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tailhub && uv run pytest tests/test_vitals_norm.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add tailhub/tailhub/vitals_norm.py tailhub/tests/test_vitals_norm.py
git commit -m "feat(tailhub): normalize /vitals to snapshot + narrow metrics"
```

---

## Task 5: Fleet discovery

**Files:**
- Create: `tailhub/tailhub/fleet.py`
- Test: `tailhub/tests/test_fleet.py`

`discover_fleet` parses `tailscale status --json` into `Device` records (host, 100.x addr, online, has_probe) for `Self` + every `Peer`. `has_probe` is true when the host is in the configured probe set. `tailscale_status_json` is the only impure bit and is injected for tests.

- [ ] **Step 1: Write the failing test**

`tailhub/tests/test_fleet.py`:
```python
from tailhub.fleet import Device, discover_fleet

STATUS = {
    "Self": {"HostName": "mac-studio", "DNSName": "mac-studio.tail.ts.net.",
             "TailscaleIPs": ["100.75.213.56", "fd7a::1"], "Online": True},
    "Peer": {
        "k1": {"HostName": "plantdashboard", "DNSName": "plantdashboard.tail.ts.net.",
               "TailscaleIPs": ["100.64.79.16"], "Online": True},
        "k2": {"HostName": "nick-iphone", "DNSName": "nick-iphone.tail.ts.net.",
               "TailscaleIPs": ["100.70.107.55"], "Online": False},
    },
}


def test_discover_fleet():
    devs = {d.host: d for d in discover_fleet(STATUS, probe_hosts={"plantdashboard", "fastclock"})}
    assert set(devs) == {"mac-studio", "plantdashboard", "nick-iphone"}

    pd = devs["plantdashboard"]
    assert pd == Device(host="plantdashboard", addr="100.64.79.16", online=True, has_probe=True)

    # iPhone: present, agentless (not in probe set), offline
    ip = devs["nick-iphone"]
    assert ip.addr == "100.70.107.55" and ip.online is False and ip.has_probe is False

    # Self is included but not a probe host here
    assert devs["mac-studio"].addr == "100.75.213.56" and devs["mac-studio"].has_probe is False


def test_handles_missing_fields():
    devs = discover_fleet({"Peer": {"k": {"HostName": "x", "TailscaleIPs": [], "Online": True}}},
                          probe_hosts=set())
    assert len(devs) == 1 and devs[0].addr == ""    # no IPv4 → empty addr, still listed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tailhub && uv run pytest tests/test_fleet.py -q`
Expected: FAIL — `ModuleNotFoundError: tailhub.fleet`.

- [ ] **Step 3: Write minimal implementation**

`tailhub/tailhub/fleet.py`:
```python
"""Discover the tailnet fleet from `tailscale status --json`."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Device:
    host: str
    addr: str       # first IPv4 (100.x) or "" if none
    online: bool
    has_probe: bool


def tailscale_status_json() -> dict:
    out = subprocess.run(
        ["tailscale", "status", "--json"],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


def _first_ipv4(ips: list[str]) -> str:
    for ip in ips or []:
        if ":" not in ip:      # crude but sufficient: skip IPv6
            return ip
    return ""


def _node_to_device(node: dict, probe_hosts: set[str]) -> Device:
    host = node.get("HostName", "")
    return Device(
        host=host,
        addr=_first_ipv4(node.get("TailscaleIPs", [])),
        online=bool(node.get("Online", False)),
        has_probe=host.lower() in {h.lower() for h in probe_hosts},
    )


def discover_fleet(status: dict, probe_hosts: set[str]) -> list[Device]:
    """All tailnet nodes (Self + Peers) as Device records."""
    devices: list[Device] = []
    if status.get("Self"):
        devices.append(_node_to_device(status["Self"], probe_hosts))
    for node in (status.get("Peer") or {}).values():
        devices.append(_node_to_device(node, probe_hosts))
    return devices
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tailhub && uv run pytest tests/test_fleet.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add tailhub/tailhub/fleet.py tailhub/tests/test_fleet.py
git commit -m "feat(tailhub): fleet discovery from tailscale status --json"
```

---

## Task 6: Async scrape cycle

**Files:**
- Create: `tailhub/tailhub/scrape.py`
- Test: `tailhub/tests/test_scrape.py`

`scrape_one` does one async `GET /vitals`. `scrape_cycle` fans out over probe devices (injected `scrape` callable so tests need no network), writes snapshots + metrics for reachable probes, marks unreachable probes and agentless devices online/offline, and records on/offline **transition** events (using the passed `prev_online` map). All writes use the None/except discipline: a failed scrape ⇒ offline, never a bogus metric.

- [ ] **Step 1: Write the failing test**

`tailhub/tests/test_scrape.py`:
```python
from tailhub.fleet import Device
from tailhub.scrape import scrape_cycle
from tailhub.store import Store

VITALS = {
    "schema": 1, "host": "fastclock", "collected_at": "2026-06-07T00:00:00Z",
    "config": {"model": "Pi", "cpu_cores": 4}, "thermal": {"soc_temp_c": 50.0,
    "throttled_now": False, "under_voltage_now": False},
    "health": {"load1": 0.1, "cpu_pct": 12.0, "mem_pct": 30.0, "disk_used_pct": 20.0,
               "disk_free_gb": 25.0, "uptime_s": 1000}, "side_things": {"usb_count": 0},
    "app": {"name": "superclock", "running": True, "last_render": ""},
}


async def test_scrape_cycle_writes_and_transitions(tmp_path):
    db = Store(str(tmp_path / "s.db"))
    devices = [
        Device("fastclock", "100.78.29.28", online=True, has_probe=True),       # scrapes OK
        Device("slowclock", "100.107.135.128", online=True, has_probe=True),    # scrape fails
        Device("nick-iphone", "100.70.107.55", online=False, has_probe=False),  # agentless, offline
    ]

    async def fake_scrape(dev: Device):
        return VITALS if dev.host == "fastclock" else None

    prev = {"fastclock": True}     # slowclock was not previously known
    new_state = await scrape_cycle(db, devices, fake_scrape, now=100.0, prev_online=prev)

    latest = {d["host"]: d for d in db.latest_devices()}
    assert latest["fastclock"]["online"] is True
    assert latest["fastclock"]["snapshot"]["metrics"]["cpu_pct"] == 12.0
    assert db.metric_history("fastclock", "cpu_pct", since=0.0)[0] == [100.0, 12.0]
    assert latest["slowclock"]["online"] is False and latest["slowclock"]["has_probe"] is True
    assert latest["nick-iphone"]["online"] is False

    # slowclock newly seen offline → a went_offline event; fastclock stayed online → none
    kinds = {e["kind"] for e in db.recent_events("slowclock")}
    assert "went_offline" in kinds
    assert db.recent_events("fastclock") == []
    assert new_state["fastclock"] is True and new_state["slowclock"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tailhub && uv run pytest tests/test_scrape.py -q`
Expected: FAIL — `ModuleNotFoundError: tailhub.scrape`.

- [ ] **Step 3: Write minimal implementation**

`tailhub/tailhub/scrape.py`:
```python
"""Async scrape of tailprobe agents into the store."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx

from .fleet import Device
from .store import Store
from .vitals_norm import build_snapshot, vitals_to_metrics

ScrapeFn = Callable[[Device], Awaitable[dict | None]]


async def scrape_one(client: httpx.AsyncClient, dev: Device, port: int,
                     timeout: float, token: str | None = None) -> dict | None:
    """GET /vitals from a probe. Returns the parsed dict, or None on any failure."""
    if not dev.addr:
        return None
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = await client.get(f"http://{dev.addr}:{port}/vitals", timeout=timeout, headers=headers)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


async def scrape_cycle(store: Store, devices: list[Device], scrape: ScrapeFn,
                       now: float, prev_online: dict[str, bool]) -> dict[str, bool]:
    """Scrape all probe devices concurrently, write results, record transitions.
    Returns the new {host: online} map."""
    probes = [d for d in devices if d.has_probe]
    results = await asyncio.gather(*(scrape(d) for d in probes), return_exceptions=True)

    new_state: dict[str, bool] = {}

    def record(host: str, online: bool) -> None:
        was = prev_online.get(host)
        if was is True and not online:
            store.add_event(host, now, "went_offline", {"reason": "scrape_failed"})
        elif was is False and online:
            store.add_event(host, now, "came_online", {})
        new_state[host] = online

    for dev, res in zip(probes, results):
        vitals = res if isinstance(res, dict) else None
        if vitals is None:
            store.add_device(dev.host, now, online=False, has_probe=True, snapshot={"host": dev.host})
            record(dev.host, False)
        else:
            store.add_device(dev.host, now, online=True, has_probe=True,
                             snapshot=build_snapshot(vitals))
            store.add_metrics(dev.host, now, vitals_to_metrics(vitals))
            record(dev.host, True)

    # agentless devices: online/offline only, from tailscale status
    for dev in devices:
        if dev.has_probe:
            continue
        store.add_device(dev.host, now, online=dev.online, has_probe=False,
                         snapshot={"host": dev.host})
        record(dev.host, dev.online)

    store.commit()
    return new_state
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tailhub && uv run pytest tests/test_scrape.py -q`
Expected: PASS (1 test). (`asyncio_mode = "auto"` in pyproject runs the `async def` test directly.)

- [ ] **Step 5: Commit**

```bash
git add tailhub/tailhub/scrape.py tailhub/tests/test_scrape.py
git commit -m "feat(tailhub): async scrape_cycle with online-transition events"
```

---

## Task 7: Read API (FastAPI)

**Files:**
- Create: `tailhub/tailhub/app.py`
- Test: `tailhub/tests/test_app.py`

`create_app(store, settings)` builds the read API only (no scheduler), so it's testable against a seeded store via FastAPI's `TestClient`.

- [ ] **Step 1: Write the failing test**

`tailhub/tests/test_app.py`:
```python
from fastapi.testclient import TestClient

from tailhub.app import create_app
from tailhub.settings import Settings
from tailhub.store import Store


def _seed(tmp_path):
    db = Store(str(tmp_path / "a.db"))
    db.add_device("fastclock", 100.0, online=True, has_probe=True,
                  snapshot={"host": "fastclock", "metrics": {"cpu_pct": 12.0, "soc_temp_c": 50.0}})
    db.add_metrics("fastclock", 100.0, {"soc_temp_c": 50.0})
    db.add_metrics("fastclock", 130.0, {"soc_temp_c": 51.0})
    db.add_device("nick-iphone", 90.0, online=False, has_probe=False, snapshot={"host": "nick-iphone"})
    db.commit()
    return db


def test_fleet_and_device_and_history(tmp_path):
    app = create_app(_seed(tmp_path), Settings())
    c = TestClient(app)

    assert c.get("/healthz").json() == {"status": "ok"}

    fleet = c.get("/fleet").json()
    hosts = {d["host"] for d in fleet["devices"]}
    assert hosts == {"fastclock", "nick-iphone"}
    fast = next(d for d in fleet["devices"] if d["host"] == "fastclock")
    assert fast["online"] is True and fast["snapshot"]["metrics"]["cpu_pct"] == 12.0

    dev = c.get("/device/fastclock").json()
    assert dev["host"] == "fastclock" and dev["last_seen"] == 100.0

    assert c.get("/device/nope").status_code == 404

    hist = c.get("/history", params={"host": "fastclock", "metric": "soc_temp_c", "since": 0}).json()
    assert hist["metric"] == "soc_temp_c"
    assert hist["points"] == [[100.0, 50.0], [130.0, 51.0]]

    # stubs present
    assert c.get("/alerts").json() == {"active": [], "recent": []}
    assert c.get("/presence").json() == {"devices": []}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tailhub && uv run pytest tests/test_app.py -q`
Expected: FAIL — `ModuleNotFoundError: tailhub.app`.

- [ ] **Step 3: Write minimal implementation**

`tailhub/tailhub/app.py`:
```python
"""FastAPI read API over the hub store (no scheduler; that lives in scheduler.py)."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .settings import Settings
from .store import Store


def create_app(store: Store, settings: Settings) -> FastAPI:
    app = FastAPI(title="tailhub", version="0.1.0")

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/fleet")
    def fleet() -> dict:
        return {"devices": store.latest_devices()}

    @app.get("/device/{host}")
    def device(host: str, since: float | None = None) -> dict:
        d = store.latest_device(host)
        if d is None:
            raise HTTPException(status_code=404, detail=f"unknown host {host}")
        d = dict(d)
        d["recent_events"] = store.recent_events(host, since=since)
        return d

    @app.get("/history")
    def history(host: str, metric: str, since: float, until: float | None = None) -> dict:
        return {
            "host": host,
            "metric": metric,
            "since": since,
            "until": until,
            "points": store.metric_history(host, metric, since=since, until=until),
        }

    # Phase-1/3 stubs (documented; real wiring in later plans).
    @app.get("/alerts")
    def alerts() -> dict:
        return {"active": [], "recent": []}

    @app.get("/presence")
    def presence() -> dict:
        return {"devices": []}

    return app
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tailhub && uv run pytest tests/test_app.py -q`
Expected: PASS (1 test).

- [ ] **Step 5: Commit**

```bash
git add tailhub/tailhub/app.py tailhub/tests/test_app.py
git commit -m "feat(tailhub): FastAPI read API (/fleet, /device, /history, stubs)"
```

---

## Task 8: Scheduler + entrypoint

**Files:**
- Create: `tailhub/tailhub/scheduler.py`, `tailhub/tailhub/__main__.py`
- Test: `tailhub/tests/test_scheduler.py`

`run_cycle` does one full discover→scrape→(periodic rollup/prune) pass. `run_scheduler` loops it on the interval until a stop event (drift-corrected, whole-cycle try/except so one bad cycle never kills the loop). `main()` wires the store + a background scheduler task + uvicorn. Tests exercise one `run_cycle` with injected `status`/`scrape` (no network), and that the loop stops.

- [ ] **Step 1: Write the failing test**

`tailhub/tests/test_scheduler.py`:
```python
import asyncio

from tailhub.scheduler import run_cycle, run_scheduler
from tailhub.settings import Settings
from tailhub.store import Store

STATUS = {"Peer": {"k": {"HostName": "fastclock", "TailscaleIPs": ["100.78.29.28"], "Online": True}}}
VITALS = {
    "schema": 1, "host": "fastclock", "collected_at": "t", "config": {"cpu_cores": 4},
    "thermal": {"soc_temp_c": 50.0, "throttled_now": False, "under_voltage_now": False},
    "health": {"load1": 0.1, "cpu_pct": 9.0, "mem_pct": 1.0, "disk_used_pct": 1.0,
               "disk_free_gb": 9.0, "uptime_s": 5}, "side_things": {"usb_count": 0},
    "app": {"name": "superclock", "running": True, "last_render": ""},
}


async def test_run_cycle_writes(tmp_path):
    db = Store(str(tmp_path / "c.db"))
    s = Settings(probe_hosts=["fastclock"])
    state: dict = {}

    async def fake_scrape(dev):
        return VITALS

    await run_cycle(db, s, now=100.0, prev_online=state,
                    status_provider=lambda: STATUS, scrape=fake_scrape)

    latest = db.latest_device("fastclock")
    assert latest["online"] is True
    assert db.metric_history("fastclock", "cpu_pct", since=0.0) == [[100.0, 9.0]]


async def test_run_scheduler_stops(tmp_path):
    db = Store(str(tmp_path / "l.db"))
    s = Settings(probe_hosts=["fastclock"], scrape_interval_s=0.01)
    stop = asyncio.Event()
    cycles = 0

    async def fake_scrape(dev):
        nonlocal cycles
        cycles += 1
        if cycles >= 2:
            stop.set()
        return VITALS

    await asyncio.wait_for(
        run_scheduler(db, s, stop, status_provider=lambda: STATUS, scrape=fake_scrape),
        timeout=2.0,
    )
    assert cycles >= 2 and stop.is_set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tailhub && uv run pytest tests/test_scheduler.py -q`
Expected: FAIL — `ModuleNotFoundError: tailhub.scheduler`.

- [ ] **Step 3: Write minimal implementation**

`tailhub/tailhub/scheduler.py`:
```python
"""The scrape loop and the process entrypoint."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import httpx

from .fleet import Device, discover_fleet, tailscale_status_json
from .scrape import scrape_cycle, scrape_one
from .settings import Settings
from .store import Store

StatusProvider = Callable[[], dict]
ScrapeFn = Callable[[Device], Awaitable[dict | None]]


async def run_cycle(store: Store, settings: Settings, now: float, prev_online: dict[str, bool],
                    status_provider: StatusProvider, scrape: ScrapeFn) -> dict[str, bool]:
    """One discover → scrape → write pass. Returns the new {host: online} map."""
    status = await asyncio.to_thread(status_provider)
    devices = discover_fleet(status, probe_hosts=set(settings.probe_hosts))
    return await scrape_cycle(store, devices, scrape, now=now, prev_online=prev_online)


async def run_scheduler(store: Store, settings: Settings, stop: asyncio.Event,
                        status_provider: StatusProvider | None = None,
                        scrape: ScrapeFn | None = None) -> None:
    """Loop run_cycle on the interval until stop is set. One bad cycle never kills the loop."""
    status_provider = status_provider or tailscale_status_json
    state: dict[str, bool] = {}
    last_rollup_hour = -1

    async with httpx.AsyncClient() as client:
        real_scrape: ScrapeFn = scrape or (
            lambda dev: scrape_one(client, dev, settings.probe_port,
                                   settings.request_timeout_s, settings.bearer_token)
        )
        while not stop.is_set():
            t0 = time.monotonic()
            now = time.time()
            try:
                state = await run_cycle(store, settings, now, state, status_provider, real_scrape)
                hour = int(now // 3600) * 3600
                if hour != last_rollup_hour:
                    store.rollup_hour(hour - 3600)          # finalize the just-completed hour
                    store.prune(now - settings.retention_days * 86400)
                    last_rollup_hour = hour
            except Exception as e:  # never let the loop die
                store.add_event("tailhub", time.time(), "cycle_error", {"error": str(e)})
                store.commit()
            elapsed = time.monotonic() - t0
            try:
                await asyncio.wait_for(stop.wait(), timeout=max(0.0, settings.scrape_interval_s - elapsed))
            except asyncio.TimeoutError:
                pass


def main() -> None:
    import uvicorn

    from .app import create_app

    settings = Settings()
    store = Store(settings.db_path)
    app = create_app(store, settings)
    stop = asyncio.Event()

    @app.on_event("startup")
    async def _start() -> None:
        app.state.scheduler = asyncio.create_task(run_scheduler(store, settings, stop))

    @app.on_event("shutdown")
    async def _stop() -> None:
        stop.set()
        await app.state.scheduler

    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
```

`tailhub/tailhub/__main__.py`:
```python
from .scheduler import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tailhub && uv run pytest tests/test_scheduler.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the whole suite + a smoke import**

Run:
```bash
cd tailhub && uv run pytest tests/ -q && uv run python -c "import tailhub.scheduler, tailhub.app; print('import OK')"
```
Expected: all tests PASS (Tasks 1–8) and `import OK`.

- [ ] **Step 6: Commit**

```bash
git add tailhub/tailhub/scheduler.py tailhub/tailhub/__main__.py tailhub/tests/test_scheduler.py
git commit -m "feat(tailhub): scrape scheduler loop + uvicorn entrypoint"
```

---

## Self-Review

**Spec coverage (design §6.2 + §12 hub rows):**
- Discover fleet via `tailscale status --json` → Task 5 (`discover_fleet`); agentless devices included. ✅
- Scrape each probe `/vitals` over Tailscale, async, dead probe → offline not stall → Task 6 (`scrape_cycle` + `asyncio.gather`, `scrape_one` timeout). ✅
- SQLite store, WAL, 4 tables (device/metric/event/metric_hourly) → Tasks 2–3. ✅
- Rollups + retention prune (load-bearing, new) → Task 3 + scheduler wiring Task 8. ✅
- Normalize `/vitals` → metrics + snapshot; null/absent omitted; `app.running` null preserved → Task 4. ✅
- API `/fleet`, `/device/{host}`, `/history` + `/alerts`/`/presence` stubs → Task 7. ✅
- Reuse lifelog store idioms (sibling, not import) + `tailscale status` discovery → Tasks 2, 5. ✅
- Settings (interval, probe port/hosts, timeout, retention, bearer token) → Task 1. ✅
- *Deferred (correct):* rules engine/alerting (Phase 1 — `/alerts` is a stub; only on/offline transition events recorded now), presence ingestion (Phase 3 — `/presence` stub), Prometheus federation (Phase 5), `tailtop` repoint (Plan 4). Bearer token is plumbed into `scrape_one` but the API itself is unauthenticated (Tailscale-only bind is the boundary).

**Placeholder scan:** No TBD/TODO; every code step has complete code; every test step has real assertions + exact `uv run pytest` command + expected. The one redundant `import json` inside `recent_events` (Task 3) is explicitly called out with the instruction to use the module-level import. ✅

**Type consistency:** `Store` methods (`add_device`, `add_metrics`, `add_event`, `commit`, `latest_devices`, `latest_device`, `metric_history`, `recent_events`, `rollup_hour`, `prune`) are defined in Tasks 2–3 and used consistently in Tasks 6–8. `Device(host, addr, online, has_probe)` (Task 5) is used by `scrape_one`/`scrape_cycle` (Task 6) and `run_cycle` (Task 8). `build_snapshot`/`vitals_to_metrics` (Task 4) are used by `scrape_cycle` (Task 6). `ScrapeFn` signature `(Device) -> Awaitable[dict|None]` is consistent across Tasks 6 and 8. `create_app(store, settings)` (Task 7) is used by `main` (Task 8). ✅

---

## Phase 0 remaining plans (after this)

3. **Installer** — cross-compile `tailprobe` (Plan 1) + OpenSSH push + systemd unit + ACL to the 8 SBCs; point `tailhub` at them and watch `/fleet` populate live.
4. **tailtop repoint** — `TailscaleClient.fetch_fleet(hub_url)` + `vitals_poller` hub GET; `tailtop fleet` reads this hub's `/fleet`.
