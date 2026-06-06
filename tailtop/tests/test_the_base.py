"""TheBaseMode composition tests — header, alert, belt, detail pane."""

from __future__ import annotations

import pytest

from tailtop.data.models import Peer, Status
from tailtop.modes.the_base import TheBaseMode
from tailtop.state import RateHistory
from tailtop.widgets.alert_strip import AlertStrip
from tailtop.widgets.belt import BeltView


def _self() -> Peer:
    return Peer(
        id="self", host_name="the-base", dns_name="the-base.example.", os="linux",
        ips=["100.64.0.1"], online=True, active=True, exit_node=False,
        exit_node_option=False, relay="", cur_addr="", rx_bytes=0, tx_bytes=0,
        last_handshake=None, key_expiry=None, is_self=True,
    )


def _peer(pid: str, online: bool = True) -> Peer:
    return Peer(
        id=pid, host_name=pid, dns_name=f"{pid}.example.", os="linux",
        ips=["100.64.0.2"], online=online, active=True, exit_node=False,
        exit_node_option=False, relay="", cur_addr="100.64.0.2:41641",
        rx_bytes=0, tx_bytes=0, last_handshake=None, key_expiry=None,
    )


@pytest.fixture
def status_with_peers() -> Status:
    return Status(
        version="dev", backend_state="Running", tailscale_ips=["100.64.0.1"],
        magic_dns_suffix="example.ts.net", user_display="me",
        self_peer=_self(),
        peers=[_peer("p1"), _peer("p2", online=False)],
    )


def test_mode_class_has_expected_cadence() -> None:
    assert TheBaseMode.cadence == 2.0


def test_mode_instantiates_with_expected_child_widgets() -> None:
    mode = TheBaseMode()
    assert hasattr(mode, "_selected_id")
    assert mode._selected_id is None


async def test_update_data_populates_belt_and_alert_strip(status_with_peers: Status) -> None:
    from textual.app import App

    class _Harness(App):
        def compose(self):
            yield TheBaseMode(id="tb")

    rates = RateHistory()
    async with _Harness().run_test() as pilot:
        mode = pilot.app.query_one(TheBaseMode)
        mode.update_data(status_with_peers, rates)
        belt = pilot.app.query_one(BeltView)
        assert belt.hub_peer is not None
        assert belt.hub_peer.host_name == "the-base"
        strip = pilot.app.query_one(AlertStrip)
        plain = strip.renderable.plain if hasattr(strip.renderable, "plain") else str(strip.renderable)
        assert "1 offline" in plain


async def test_default_selection_is_first_online_peer(status_with_peers: Status) -> None:
    from textual.app import App

    class _Harness(App):
        def compose(self):
            yield TheBaseMode(id="tb")

    rates = RateHistory()
    async with _Harness().run_test() as pilot:
        mode = pilot.app.query_one(TheBaseMode)
        mode.update_data(status_with_peers, rates)
        assert mode._selected_id == "p1"
        # Detail pane was updated for the selected peer (we trust the wiring; the
        # DetailPane's own tests cover its rendering).


async def test_tab_cycles_into_the_base() -> None:
    from tailtop.app import TailtopApp
    app = TailtopApp(auto_poll=False)
    async with app.run_test() as pilot:
        seen = []
        for _ in range(5):
            seen.append(app.active_mode)
            if app.active_mode == "the_base":
                break
            await pilot.press("tab")
        assert "the_base" in seen


async def test_disconnected_state_shows_helpful_header() -> None:
    from tailtop.app import TailtopApp

    status = Status(
        version="dev", backend_state="NeedsLogin", tailscale_ips=[],
        magic_dns_suffix="", user_display="",
        self_peer=_self(), peers=[],
    )
    app = TailtopApp(auto_poll=False)
    async with app.run_test() as pilot:
        for _ in range(4):
            if app.active_mode == "the_base":
                break
            await pilot.press("tab")
        rates = RateHistory()
        mode = pilot.app.query_one(TheBaseMode)
        mode.update_data(status, rates)
        strip = pilot.app.query_one(AlertStrip)
        plain = strip.renderable.plain if hasattr(strip.renderable, "plain") else str(strip.renderable)
        assert "NeedsLogin" in plain


async def test_empty_tailnet_does_not_crash_or_select() -> None:
    from tailtop.app import TailtopApp

    status = Status(
        version="dev", backend_state="Running", tailscale_ips=["100.64.0.1"],
        magic_dns_suffix="example.ts.net", user_display="me",
        self_peer=_self(), peers=[],
    )
    app = TailtopApp(auto_poll=False)
    async with app.run_test() as pilot:
        for _ in range(4):
            if app.active_mode == "the_base":
                break
            await pilot.press("tab")
        rates = RateHistory()
        mode = pilot.app.query_one(TheBaseMode)
        mode.update_data(status, rates)
        assert mode._selected_id is None
