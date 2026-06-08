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
