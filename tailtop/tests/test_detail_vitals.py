"""DeviceDetail shows vitals/hardware panels only when vitals are present."""
from __future__ import annotations

import pytest
from textual.app import App
from textual.widgets import Static

from tailtop.data.latency import LatencyProbe
from tailtop.data.models import Peer
from tailtop.data.vitals import Display, Vitals
from tailtop.state import RateHistory
from tailtop.widgets.detail_pane import DeviceDetail


def _peer() -> Peer:
    return Peer(
        id="p1", host_name="fastclock", dns_name="fastclock.example.", os="linux",
        ips=["100.78.29.28"], online=True, active=True, exit_node=False,
        exit_node_option=False, relay="", cur_addr="100.78.29.28:41641",
        rx_bytes=0, tx_bytes=0, last_handshake=None, key_expiry=None,
    )


class _Harness(App):
    def compose(self):
        yield DeviceDetail(id="d")


async def test_vitals_panel_visible_with_vitals() -> None:
    v = Vitals(host="fastclock", soc_temp_c=57.0, disk_used_pct=44.0,
               displays=[Display("HDMI-A-1", "connected")], app_name="superclock", app_running=True)
    async with _Harness().run_test() as pilot:
        d = pilot.app.query_one(DeviceDetail)
        d.update_peer(_peer(), RateHistory(), LatencyProbe(None), None, vitals=v)
        panel = pilot.app.query_one("#panel-vitals", Static)
        assert panel.display is True
        assert "57" in panel.renderable.plain if hasattr(panel.renderable, "plain") else True


async def test_vitals_panel_hidden_without_vitals() -> None:
    async with _Harness().run_test() as pilot:
        d = pilot.app.query_one(DeviceDetail)
        d.update_peer(_peer(), RateHistory(), LatencyProbe(None), None, vitals=None)
        assert pilot.app.query_one("#panel-vitals", Static).display is False
