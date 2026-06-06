"""App-level render tests using Textual's headless harness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tailtop.app import TailtopApp
from tailtop.data.models import Status
from tailtop.widgets.device_list import DeviceList

FIXTURE = Path(__file__).parent / "fixtures" / "status.json"


class FakeClient:
    """Hermetic client — no subprocess (the latency probe would otherwise ping)."""

    available = True
    _binary = "tailscale"

    def __init__(self, status: Status | None = None) -> None:
        self._status = status

    async def status(self) -> Status | None:
        return self._status

    async def ping_once(self, host: str) -> str:
        return f"pong from {host} via 192.168.1.1:41641 in 6ms"

    async def run(self, *args, **kwargs) -> str:
        return ""


@pytest.fixture
def status() -> Status:
    return Status.from_json(json.loads(FIXTURE.read_text()))


async def test_app_mounts_and_populates(status: Status) -> None:
    app = TailtopApp(client=FakeClient(status), auto_poll=False)
    async with app.run_test() as pilot:
        app._on_status(status)
        await pilot.pause()
        device_list = app.query_one(DeviceList)
        # self is pinned at the top, so the list is peers + 1
        assert len(device_list) == status.total_count + 1 == 11
        assert app.error == ""


async def test_tab_cycles_modes(status: Status) -> None:
    app = TailtopApp(client=FakeClient(status), auto_poll=False)
    async with app.run_test() as pilot:
        app._on_status(status)
        await pilot.pause()
        assert app.active_mode == "comfort"
        await pilot.press("tab")
        assert app.active_mode == "cockpit"
        await pilot.press("tab")
        assert app.active_mode == "observatory"
        await pilot.press("tab")
        assert app.active_mode == "the_base"
        await pilot.press("tab")
        assert app.active_mode == "comfort"


async def test_disconnected_empty_state_does_not_crash() -> None:
    empty = Status(
        version="1.0",
        backend_state="Stopped",
        tailscale_ips=[],
        magic_dns_suffix="",
        user_display="",
        self_peer=Status.from_json({"Self": {}}).self_peer,
        peers=[],
    )
    app = TailtopApp(client=FakeClient(empty), auto_poll=False)
    async with app.run_test() as pilot:
        app._on_status(empty)
        await pilot.pause()
        assert app.query_one(DeviceList).__len__() == 0
        assert app.selected_peer() is None


async def test_navigation_updates_selection(status: Status) -> None:
    app = TailtopApp(client=FakeClient(status), auto_poll=False)
    async with app.run_test() as pilot:
        app._on_status(status)
        await pilot.pause()
        comfort = app.query_one("#comfort")
        first = comfort._selected_id
        await pilot.press("j")
        await pilot.pause()
        assert comfort._selected_id != first  # moved to next peer
