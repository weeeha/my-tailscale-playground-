"""BeltRenderer Hub mode tests — assert character grid contents."""

from __future__ import annotations

from tailtop.data.models import ConnType, Peer
from tailtop.widgets.belt import (
    BeltRenderer,
    BeltState,
    CharCanvas,
    HUB_SLOTS,
    HubLayout,
    LaneState,
)


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


def test_canvas_default_is_spaces() -> None:
    c = CharCanvas(width=10, height=3)
    rendered = c.to_plain()
    assert rendered.splitlines() == [" " * 10] * 3


def test_canvas_set_and_to_plain() -> None:
    c = CharCanvas(width=5, height=2)
    c.set(0, 0, "H", "")
    c.set(4, 1, "X", "")
    lines = c.to_plain().splitlines()
    assert lines[0] == "H    "
    assert lines[1] == "    X"


def test_render_hub_draws_center_card_with_self_name() -> None:
    canvas = CharCanvas(width=60, height=20)
    layout = HubLayout()
    hub_peer = _peer("the-base")
    BeltRenderer().render_hub(
        canvas=canvas,
        layout=layout,
        belt_states={},
        hub_peer=hub_peer,
        peers_by_id={"the-base": hub_peer},
        selected_id=None,
    )
    plain = canvas.to_plain()
    assert "the-base" in plain


def test_render_hub_draws_peer_in_north_slot() -> None:
    canvas = CharCanvas(width=60, height=20)
    layout = HubLayout()
    hub_peer = _peer("hub")
    north = _peer("north-peer")
    layout.assign(peers=[north], rates={"north-peer": (0.0, 0.0)}, now=0.0)
    belt_states = {
        "north-peer": BeltState(
            peer_id="north-peer",
            conn_type=ConnType.DIRECT,
            in_lane=LaneState(),
            out_lane=LaneState(),
            in_tier="idle",
            out_tier="idle",
        ),
    }
    BeltRenderer().render_hub(
        canvas=canvas,
        layout=layout,
        belt_states=belt_states,
        hub_peer=hub_peer,
        peers_by_id={"hub": hub_peer, "north-peer": north},
        selected_id=None,
    )
    plain = canvas.to_plain()
    top_half = "\n".join(plain.splitlines()[:10])
    assert "north-peer" in top_half


def test_render_hub_uses_dashed_glyph_for_derp_peers() -> None:
    canvas = CharCanvas(width=60, height=20)
    layout = HubLayout()
    hub_peer = _peer("hub")
    derp = _peer("derp-peer")
    layout.assign(peers=[derp], rates={"derp-peer": (0.0, 0.0)}, now=0.0)
    belt_states = {
        "derp-peer": BeltState(
            peer_id="derp-peer",
            conn_type=ConnType.DERP,
            in_lane=LaneState(),
            out_lane=LaneState(),
            in_tier="idle",
            out_tier="idle",
        ),
    }
    BeltRenderer().render_hub(
        canvas=canvas,
        layout=layout,
        belt_states=belt_states,
        hub_peer=hub_peer,
        peers_by_id={"hub": hub_peer, "derp-peer": derp},
        selected_id=None,
    )
    assert "╎" in canvas.to_plain()
