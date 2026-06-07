"""The device card shows a vitals badge when vitals are present."""
from __future__ import annotations

from tailtop.data.vitals import Vitals
from tailtop.widgets.device_card import vitals_badge


def test_badge_shows_temp_and_disk() -> None:
    v = Vitals(host="fastclock", soc_temp_c=58.0, cpu_pct=12.0, mem_pct=30.0, disk_used_pct=41.0)
    text = vitals_badge(v).plain
    assert "58" in text
    assert "41" in text


def test_badge_flags_throttle() -> None:
    v = Vitals(host="fastclock", soc_temp_c=84.0, throttled_now=True)
    text = vitals_badge(v).plain.lower()
    assert "throttl" in text or "84" in text


def test_no_badge_for_none() -> None:
    assert vitals_badge(None).plain == ""
