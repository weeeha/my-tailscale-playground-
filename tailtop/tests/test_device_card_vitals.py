"""The device card shows a vitals badge when vitals are present."""
from __future__ import annotations

import io

from rich.console import Console

from tailtop.data.models import Peer
from tailtop.data.vitals import Vitals
from tailtop.state import RateHistory
from tailtop.widgets.device_card import DeviceCard, vitals_badge


def _peer() -> Peer:
    return Peer(
        id="p1", host_name="fastclock", dns_name="fastclock.example.", os="linux",
        ips=["100.78.29.28"], online=True, active=True, exit_node=False,
        exit_node_option=False, relay="", cur_addr="100.78.29.28:41641",
        rx_bytes=0, tx_bytes=0, last_handshake=None, key_expiry=None,
    )


def _render(renderable) -> str:
    buf = Console(width=120, file=io.StringIO(), highlight=False)
    buf.print(renderable)
    return buf.file.getvalue()


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


def test_card_renders_temp_sparkline() -> None:
    """update_card with a non-empty temp_series should include a spark glyph."""
    peer = _peer()
    vitals = Vitals(host="fastclock", soc_temp_c=50.0, cpu_pct=10.0, mem_pct=20.0, disk_used_pct=30.0)
    card = DeviceCard(peer.id)
    card.update_card(peer, RateHistory(), vitals, temp_series=[40.0, 45.0, 50.0, 55.0])

    text = _render(card.renderable)
    spark_glyphs = "▁▂▃▄▅▆▇█"
    assert any(g in text for g in spark_glyphs), f"No spark glyph found in: {text!r}"
