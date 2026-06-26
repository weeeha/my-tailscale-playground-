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


def test_rollup_excludes_next_hour(tmp_path):
    db = Store(str(tmp_path / "b.db"))
    db.add_metrics("fastclock", 3600.0, {"cpu_pct": 10.0})
    db.add_metrics("fastclock", 7200.0, {"cpu_pct": 99.0})   # start of the NEXT hour
    db.commit()
    db.rollup_hour(3600)
    row = db.db.execute(
        "SELECT n, max FROM metric_hourly WHERE host='fastclock' AND hour=3600 AND key='cpu_pct'"
    ).fetchone()
    assert row["n"] == 1 and row["max"] == 10.0     # 7200 excluded from the 3600 bucket


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
