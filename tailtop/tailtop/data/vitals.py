"""Typed device vitals + health thresholds.

Parsed from the agent's collect JSON in the data layer; widgets consume the
typed model, never raw JSON. Thresholds live here so cards, detail, the alert
strip, and the CLI all agree.
"""
from __future__ import annotations

from dataclasses import dataclass, field

TEMP_WARN_C = 70.0
TEMP_CRIT_C = 80.0
DISK_WARN_PCT = 85.0
DISK_CRIT_PCT = 95.0
MEM_WARN_PCT = 90.0


@dataclass
class Display:
    connector: str
    status: str
    mode: str = ""


@dataclass
class Vitals:
    host: str
    collected_at: str = ""
    # config (rare-change)
    model: str = ""
    serial: str = ""
    cpu_cores: int = 0
    mem_total_mb: int = 0
    os: str = ""
    kernel: str = ""
    disk_total_gb: float = 0.0
    # thermal
    soc_temp_c: float | None = None
    vcgencmd_present: bool = False
    throttled_now: bool = False
    under_voltage_now: bool = False
    # health
    load1: float = 0.0
    cpu_pct: float = 0.0
    mem_pct: float = 0.0
    disk_used_pct: float = 0.0
    disk_free_gb: float = 0.0
    uptime_s: int = 0
    # side-things
    displays: list[Display] = field(default_factory=list)
    usb_count: int = 0
    battery_present: bool = False
    battery_pct: float | None = None
    # app
    app_name: str = ""
    app_running: bool | None = None
    app_last_render: str = ""

    @classmethod
    def from_collect_json(cls, d: dict) -> "Vitals":
        cfg = d.get("config") or {}
        th = d.get("thermal") or {}
        he = d.get("health") or {}
        st = d.get("side_things") or {}
        ap = d.get("app") or {}
        bat = st.get("battery") or {}

        def f(x, default=0.0):
            try:
                return float(x)
            except (TypeError, ValueError):
                return default

        temp = th.get("soc_temp_c")

        # usb_count: prefer explicit field if present, otherwise count array elements
        usb_raw = st.get("usb_count")
        if usb_raw is not None:
            usb_count = int(f(usb_raw))
        else:
            usb_count = len(st.get("usb") or [])

        return cls(
            host=d.get("host", ""),
            collected_at=d.get("collected_at", ""),
            model=cfg.get("model", "") or "",
            serial=cfg.get("serial", "") or "",
            cpu_cores=int(f(cfg.get("cpu_cores"))),
            mem_total_mb=int(f(cfg.get("mem_total_mb"))),
            os=cfg.get("os", "") or "",
            kernel=cfg.get("kernel", "") or "",
            disk_total_gb=f(cfg.get("disk_total_gb")),
            soc_temp_c=(f(temp) if temp is not None else None),
            vcgencmd_present=bool(th.get("vcgencmd_present", False)),
            throttled_now=bool(th.get("throttled_now", False)),
            under_voltage_now=bool(th.get("under_voltage_now", False)),
            load1=f(he.get("load1")),
            cpu_pct=f(he.get("cpu_pct")),
            mem_pct=f(he.get("mem_pct")),
            disk_used_pct=f(he.get("disk_used_pct")),
            disk_free_gb=f(he.get("disk_free_gb")),
            uptime_s=int(f(he.get("uptime_s"))),
            displays=[
                Display(x.get("connector", ""), x.get("status", ""), x.get("mode", ""))
                for x in (st.get("displays") or [])
            ],
            usb_count=usb_count,
            battery_present=bool(bat.get("present", False)),
            battery_pct=(f(bat["pct"]) if bat.get("pct") is not None else None),
            app_name=ap.get("name") or "",
            app_running=ap.get("running"),
            app_last_render=ap.get("last_render") or "",
        )

    @property
    def reasons(self) -> list[str]:
        r: list[str] = []
        t = self.soc_temp_c
        if t is not None and t >= TEMP_CRIT_C:
            r.append(f"{self.host} {t:.0f}°C")
        elif t is not None and t >= TEMP_WARN_C:
            r.append(f"{self.host} warm {t:.0f}°C")
        if self.throttled_now:
            r.append(f"{self.host} throttled")
        if self.under_voltage_now:
            r.append(f"{self.host} under-voltage")
        if self.disk_used_pct >= DISK_WARN_PCT:
            r.append(f"{self.host} disk {self.disk_used_pct:.0f}%")
        if self.mem_pct >= MEM_WARN_PCT:
            r.append(f"{self.host} mem {self.mem_pct:.0f}%")
        if self.app_running is False:
            r.append(f"{self.host} {self.app_name or 'app'} down")
        return r

    @property
    def health_level(self) -> str:
        t = self.soc_temp_c
        if (
            (t is not None and t >= TEMP_CRIT_C)
            or self.throttled_now
            or self.under_voltage_now
            or self.disk_used_pct >= DISK_CRIT_PCT
            or self.app_running is False
        ):
            return "crit"
        if (
            (t is not None and t >= TEMP_WARN_C)
            or self.disk_used_pct >= DISK_WARN_PCT
            or self.mem_pct >= MEM_WARN_PCT
        ):
            return "warn"
        return "ok"


def summarise_health(vitals_by_id: dict[str, "Vitals"]) -> str:
    """One-line health summary across the fleet; empty when all clear."""
    reasons: list[str] = []
    for v in vitals_by_id.values():
        reasons.extend(v.reasons)
    return " · ".join(reasons)
