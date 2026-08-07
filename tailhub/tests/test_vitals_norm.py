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
