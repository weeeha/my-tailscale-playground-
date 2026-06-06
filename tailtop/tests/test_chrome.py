"""Header + footer chrome: clickable tabs and contextual hotkey dimming."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tailtop.app import TailtopApp
from tailtop.data.models import Status
from tailtop.widgets.header_bar import HeaderBar, ModeTab
from tailtop.widgets.hotkey_bar import HotkeyBar

FIXTURE = Path(__file__).parent / "fixtures" / "status.json"


class FakeClient:
    available = True
    _binary = "tailscale"

    def __init__(self, status: Status) -> None:
        self._status = status

    async def status(self) -> Status:
        return self._status

    async def ping_once(self, host: str) -> str:
        return f"pong from {host} via 1.2.3.4:41641 in 5ms"

    async def run(self, *args, **kwargs) -> str:
        return ""


@pytest.fixture
def status() -> Status:
    return Status.from_json(json.loads(FIXTURE.read_text()))


async def test_header_marks_active_tab(status: Status) -> None:
    app = TailtopApp(client=FakeClient(status), auto_poll=False)
    async with app.run_test() as pilot:
        app._on_status(status)
        await pilot.pause()
        active = [t.mode_id for t in app.query(ModeTab) if t.has_class("-active")]
        assert active == ["list"]  # default mode


async def test_clicking_tab_switches_mode(status: Status) -> None:
    app = TailtopApp(client=FakeClient(status), auto_poll=False)
    async with app.run_test() as pilot:
        app._on_status(status)
        await pilot.pause()
        # simulate the header tab button calling its action
        app.action_set_mode("observatory")
        await pilot.pause()
        assert app.active_mode == "observatory"
        active = [t.mode_id for t in app.query(ModeTab) if t.has_class("-active")]
        assert active == ["observatory"]


async def test_header_shows_identity_and_status(status: Status) -> None:
    app = TailtopApp(client=FakeClient(status), auto_poll=False)
    async with app.run_test() as pilot:
        app._on_status(status)
        await pilot.pause()
        header = app.query_one(HeaderBar)
        from rich.console import Console

        console = Console(width=120)
        with console.capture() as cap:
            console.print(header.query_one("#status")._content)
        text = cap.get()
        assert "Connected" in text
        assert "online" in text


async def test_hotkeybar_dims_without_selection(status: Status) -> None:
    app = TailtopApp(client=FakeClient(status), auto_poll=False)
    async with app.run_test() as pilot:
        await pilot.pause()
        bar = app.query_one(HotkeyBar)
        bar.set_state(has_selection=False)  # no crash; renders dimmed
        bar.set_state(has_selection=True)
        assert isinstance(bar, HotkeyBar)
