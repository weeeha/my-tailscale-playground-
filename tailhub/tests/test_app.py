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


def test_dashboard_served(tmp_path):
    c = TestClient(create_app(_seed(tmp_path), Settings()))
    r = c.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    body = r.text
    assert "<!DOCTYPE html>" in body
    assert "tailfleet" in body
    assert "/fleet" in body          # the page polls the live API
