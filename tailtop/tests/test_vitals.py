"""Vitals parsing + health thresholds (pure, no Textual)."""
from __future__ import annotations

import json
from pathlib import Path

from tailtop.data.vitals import Vitals, summarise_health

FIX = Path(__file__).parent / "fixtures"


def _load(name: str) -> Vitals:
    return Vitals.from_collect_json(json.loads((FIX / name).read_text()))


def test_parses_broadcom_fixture() -> None:
    v = _load("vitals_fastclock.json")
    assert v.host == "SuperClockFast"
    assert v.vcgencmd_present is True
    assert v.soc_temp_c is not None
    assert v.cpu_cores >= 1


def test_parses_allwinner_fixture_without_vcgencmd() -> None:
    v = _load("vitals_orangepi.json")
    assert v.vcgencmd_present is False
    assert v.soc_temp_c is not None  # still read from /sys/class/thermal


def test_missing_sections_are_tolerated() -> None:
    v = Vitals.from_collect_json({"host": "x"})
    assert v.host == "x"
    assert v.soc_temp_c is None
    assert v.health_level == "ok"


def test_health_levels_at_boundaries() -> None:
    ok = Vitals(host="h", soc_temp_c=60.0, disk_used_pct=40.0)
    warn = Vitals(host="h", soc_temp_c=72.0)
    crit_temp = Vitals(host="h", soc_temp_c=81.0)
    crit_throttle = Vitals(host="h", throttled_now=True)
    crit_app = Vitals(host="h", app_name="superclock", app_running=False)
    assert ok.health_level == "ok"
    assert warn.health_level == "warn"
    assert crit_temp.health_level == "crit"
    assert crit_throttle.health_level == "crit"
    assert crit_app.health_level == "crit"


def test_summarise_health_joins_reasons() -> None:
    vbi = {
        "a": Vitals(host="fastclock", soc_temp_c=85.0),
        "b": Vitals(host="slowclock", disk_used_pct=97.0),
        "c": Vitals(host="smallclock", soc_temp_c=40.0),  # healthy → no reason
    }
    out = summarise_health(vbi)
    assert "fastclock" in out and "slowclock" in out
    assert "smallclock" not in out
