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
