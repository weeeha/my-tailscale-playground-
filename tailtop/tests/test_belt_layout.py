"""Hub + Bus layout assignment tests — pure, no Textual."""

from __future__ import annotations

from dataclasses import replace

from tailtop.data.models import ConnType, Peer
from tailtop.widgets.belt import HUB_SLOTS, HubLayout


def _peer(pid: str, rx: int = 0, tx: int = 0, online: bool = True) -> Peer:
    return Peer(
        id=pid,
        host_name=pid,
        dns_name=f"{pid}.example.",
        os="linux",
        ips=["100.64.0.1"],
        online=online,
        active=True,
        exit_node=False,
        exit_node_option=False,
        relay="",
        cur_addr="100.64.0.1:41641",
        rx_bytes=rx,
        tx_bytes=tx,
        last_handshake=None,
        key_expiry=None,
    )


def test_priority_order_is_cardinals_first() -> None:
    assert HUB_SLOTS[:4] == ("N", "E", "W", "S")
    assert set(HUB_SLOTS) == {"N", "E", "W", "S", "NE", "NW", "SE", "SW"}


def test_one_peer_goes_to_north() -> None:
    layout = HubLayout()
    layout.assign(peers=[_peer("a")], rates={"a": (0, 0)}, now=0.0)
    assert layout.slot_of("a") == "N"
    assert layout.overflow_count == 0


def test_higher_bandwidth_takes_better_slots() -> None:
    layout = HubLayout()
    peers = [_peer("low"), _peer("hi"), _peer("mid")]
    rates = {
        "low": (1_000, 1_000),
        "hi": (10_000_000, 10_000_000),  # 10 MB/s combined
        "mid": (100_000, 100_000),
    }
    layout.assign(peers=peers, rates=rates, now=0.0)
    assert layout.slot_of("hi") == "N"
    assert layout.slot_of("mid") == "E"
    assert layout.slot_of("low") == "W"


def test_more_than_eight_peers_overflows() -> None:
    layout = HubLayout()
    peers = [_peer(f"p{i}", rx=i * 1_000_000) for i in range(12)]
    rates = {p.id: (p.rx_bytes, 0) for p in peers}
    layout.assign(peers=peers, rates=rates, now=0.0)
    assigned = [pid for pid in (layout.slot_of(p.id) for p in peers) if pid]
    assert len(assigned) == 8
    assert layout.overflow_count == 4
    # Top 8 by rate are p11..p4.
    for pid in [f"p{i}" for i in range(4, 12)]:
        assert layout.slot_of(pid) is not None
    for pid in ["p0", "p1", "p2", "p3"]:
        assert layout.slot_of(pid) is None


def test_sticky_keeps_peer_in_slot_when_rate_drops() -> None:
    layout = HubLayout(sticky_seconds=3.0)
    peers = [_peer("hi", rx=10_000_000), _peer("low", rx=10), _peer("rising", rx=0)]
    rates = {"hi": (10_000_000, 0), "low": (10, 0), "rising": (0, 0)}
    layout.assign(peers=peers, rates=rates, now=0.0)
    assert layout.slot_of("hi") == "N"

    # 1 s later: "hi" idles, "rising" spikes — but sticky window holds.
    rates2 = {"hi": (0, 0), "low": (10, 0), "rising": (10_000_000, 0)}
    layout.assign(peers=peers, rates=rates2, now=1.0)
    assert layout.slot_of("hi") == "N", "still within sticky window"

    # 4 s after first assign: sticky has expired — rising takes over.
    layout.assign(peers=peers, rates=rates2, now=4.0)
    assert layout.slot_of("rising") == "N"


def test_offline_peers_not_assigned() -> None:
    layout = HubLayout()
    peers = [_peer("on", rx=1_000), _peer("off", rx=999_999, online=False)]
    rates = {"on": (1_000, 0), "off": (999_999, 0)}
    layout.assign(peers=peers, rates=rates, now=0.0)
    assert layout.slot_of("on") == "N"
    assert layout.slot_of("off") is None


from tailtop.widgets.belt import BusBranch, BusLayout  # noqa: E402


def test_bus_alternates_top_and_bottom() -> None:
    layout = BusLayout()
    peers = [_peer(f"p{i}", rx=(10 - i) * 1_000_000) for i in range(4)]
    rates = {p.id: (p.rx_bytes, 0) for p in peers}
    branches = layout.arrange(peers=peers, rates=rates)
    sides = [b.side for b in branches]
    assert sides == ["top", "bottom", "top", "bottom"]


def test_bus_orders_by_combined_bandwidth() -> None:
    layout = BusLayout()
    peers = [_peer("low", rx=1_000), _peer("hi", rx=10_000_000), _peer("mid", rx=100_000)]
    rates = {p.id: (p.rx_bytes, 0) for p in peers}
    branches = layout.arrange(peers=peers, rates=rates)
    assert [b.peer_id for b in branches] == ["hi", "mid", "low"]


def test_bus_offsets_increment_along_trunk() -> None:
    layout = BusLayout(branch_spacing=12)
    peers = [_peer(f"p{i}") for i in range(3)]
    rates = {p.id: (0.0, 0.0) for p in peers}
    branches = layout.arrange(peers=peers, rates=rates)
    assert [b.x_offset for b in branches] == [12, 24, 36]


def test_bus_excludes_offline() -> None:
    layout = BusLayout()
    peers = [_peer("on"), _peer("off", online=False)]
    rates = {"on": (0.0, 0.0), "off": (1_000_000.0, 0.0)}
    branches = layout.arrange(peers=peers, rates=rates)
    assert [b.peer_id for b in branches] == ["on"]


def test_bus_branch_is_pure_dataclass() -> None:
    b = BusBranch(peer_id="x", side="top", x_offset=12)
    assert b.peer_id == "x"
    assert b.side == "top"
    assert b.x_offset == 12
