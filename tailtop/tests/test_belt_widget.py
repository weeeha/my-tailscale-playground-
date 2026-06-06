"""BeltView widget smoke tests — instantiation, update, layout pick."""

from __future__ import annotations

import pytest

from tailtop.data.models import Status
from tailtop.state import RateHistory
from tailtop.widgets.belt import BeltView


@pytest.fixture
def empty_status() -> Status:
    return Status(
        version="dev",
        backend_state="Running",
        tailscale_ips=["100.64.0.1"],
        magic_dns_suffix="example.ts.net",
        user_display="me",
        self_peer=_make_self(),
        peers=[],
    )


def _make_self():
    from tailtop.data.models import Peer
    return Peer(
        id="self",
        host_name="the-base",
        dns_name="the-base.example.",
        os="linux",
        ips=["100.64.0.1"],
        online=True,
        active=True,
        exit_node=False,
        exit_node_option=False,
        relay="",
        cur_addr="",
        rx_bytes=0,
        tx_bytes=0,
        last_handshake=None,
        key_expiry=None,
        is_self=True,
    )


async def test_belt_view_instantiates() -> None:
    view = BeltView()
    assert view is not None
    assert view.layout_mode == "hub"


async def test_update_data_records_belt_states(empty_status: Status) -> None:
    from tailtop.data.models import Peer
    peer = Peer(
        id="p1",
        host_name="peer-1",
        dns_name="peer-1.example.",
        os="linux",
        ips=["100.64.0.2"],
        online=True,
        active=True,
        exit_node=False,
        exit_node_option=False,
        relay="",
        cur_addr="100.64.0.2:41641",
        rx_bytes=200_000,
        tx_bytes=50_000,
        last_handshake=None,
        key_expiry=None,
    )
    status = Status(**{**empty_status.__dict__, "peers": [peer]})
    rates = RateHistory()
    rates.update("p1", 200_000, 50_000, now=0.0)
    rates.update("p1", 400_000, 100_000, now=1.0)  # 200 KB/s rx, 50 KB/s tx

    view = BeltView()
    view.update_data(status, rates, now=1.0)
    assert "p1" in view.belt_states
    state = view.belt_states["p1"]
    assert state.in_tier == "busy"
    assert state.out_tier == "light"


async def test_layout_auto_degrades_to_bus_in_narrow_terminal() -> None:
    view = BeltView()
    view._on_resize_dims(width=50, height=15)   # below Hub minimum (60×20)
    assert view.layout_mode == "bus"
    view._on_resize_dims(width=80, height=24)
    assert view.layout_mode == "hub"


async def test_render_shows_overflow_chip_when_more_than_eight_peers() -> None:
    view = BeltView()
    view.hub_peer = _make_self()
    view.peers_by_id = {"self": _make_self()}
    view.overflow_count = 4
    view.layout_mode = "hub"
    rendered = view.render()
    plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
    assert "+4 more" in plain
