"""Pure renderer for the `tailtop fleet` one-shot table."""
from __future__ import annotations

from tailtop.data.vitals import Vitals

_MARK = {"ok": "·", "warn": "!", "crit": "✗"}


def render_fleet(vitals_by_id: dict[str, Vitals]) -> tuple[str, int]:
    """Return (table_text, exit_code). exit_code is 1 if any host is critical."""
    rows = ["  HOST                 TEMP   CPU   MEM   DISK   APP        HEALTH"]
    worst_crit = False
    for v in sorted(vitals_by_id.values(), key=lambda x: x.host):
        worst_crit = worst_crit or v.health_level == "crit"
        temp = f"{v.soc_temp_c:.0f}C" if v.soc_temp_c is not None else "—"
        app = (v.app_name or "—")[:9]
        if v.app_running is False:
            app += "↓"
        rows.append(
            f"{_MARK[v.health_level]} {v.host:<20} {temp:>4} {v.cpu_pct:>4.0f}% "
            f"{v.mem_pct:>4.0f}% {v.disk_used_pct:>4.0f}%  {app:<10} {v.health_level}"
        )
    if not vitals_by_id:
        rows.append("  (no Pi vitals collected)")
    return "\n".join(rows), (1 if worst_crit else 0)
