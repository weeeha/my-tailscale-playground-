"""DeviceDetail render tests — peer subset vs self full set."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from rich.console import Console
from textual.app import App, ComposeResult
from textual.widgets import Static

from tailtop.data.latency import LatencyProbe
from tailtop.data.models import Status
from tailtop.data.netcheck import parse_netcheck
from tailtop.state import RateHistory
from tailtop.widgets.charts import LatencyChart
from tailtop.widgets.detail_pane import DeviceDetail

FIXTURE = Path(__file__).parent / "fixtures" / "status.json"

NETCHECK = """Report:
\t* UDP: true
\t* IPv6: no
\t* MappingVariesByDestIP: false
\t* PortMapping: UPnP
\t* Nearest DERP: Toronto
\t* DERP latency:
\t\t- tor: 31.8ms  (Toronto)
"""


class DetailHarness(App):
    CSS_PATH = [
        Path(__file__).parent.parent / "tailtop" / "themes" / "base.tcss",
        Path(__file__).parent.parent / "tailtop" / "themes" / "studio.tcss",
    ]

    def compose(self) -> ComposeResult:
        yield DeviceDetail(id="detail-pane")


@pytest.fixture
def status() -> Status:
    return Status.from_json(json.loads(FIXTURE.read_text()))


async def test_detail_renders_peer(status: Status) -> None:
    app = DetailHarness()
    async with app.run_test(size=(110, 36)) as pilot:
        detail = app.query_one(DeviceDetail)
        peer = next(p for p in status.peers if not p.is_self)
        detail.update_peer(peer, RateHistory(), LatencyProbe(client=None), None)
        await pilot.pause()
        # latency chart shown; all info panels visible
        assert app.query_one(LatencyChart).display is True
        assert app.query_one("#panel-status").display is True


async def test_detail_self_shows_netcheck(status: Status) -> None:
    app = DetailHarness()
    async with app.run_test(size=(110, 36)) as pilot:
        detail = app.query_one(DeviceDetail)
        nc = parse_netcheck(NETCHECK)
        detail.update_peer(status.self_peer, RateHistory(), LatencyProbe(client=None), nc)
        await pilot.pause()
        # quality panel should carry the relay name when self + netcheck present
        quality = app.query_one("#panel-quality", Static)
        console = Console(width=60)
        with console.capture() as cap:
            console.print(quality._content)  # the renderable passed to update()
        assert "Toronto" in cap.get()


async def test_empty_state(status: Status) -> None:
    app = DetailHarness()
    async with app.run_test(size=(110, 36)) as pilot:
        detail = app.query_one(DeviceDetail)
        detail.show_empty("nothing")
        await pilot.pause()
        assert app.query_one(LatencyChart).display is False
