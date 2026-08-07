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
