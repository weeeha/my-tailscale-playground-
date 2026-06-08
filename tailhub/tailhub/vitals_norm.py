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
