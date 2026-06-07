"""tailtop fleet: render a table + exit code from vitals."""
from __future__ import annotations

from tailtop.data.vitals import Vitals
from tailtop.fleet_report import render_fleet


def test_render_lists_each_host_and_exits_zero_when_healthy() -> None:
    vbi = {
        "a": Vitals(host="fastclock", soc_temp_c=55.0, disk_used_pct=40.0),
        "b": Vitals(host="slowclock", soc_temp_c=49.0, disk_used_pct=33.0),
    }
    text, code = render_fleet(vbi)
    assert "fastclock" in text and "slowclock" in text
    assert code == 0


def test_exit_nonzero_when_any_host_critical() -> None:
    vbi = {"a": Vitals(host="fastclock", soc_temp_c=85.0)}
    text, code = render_fleet(vbi)
    assert code == 1
