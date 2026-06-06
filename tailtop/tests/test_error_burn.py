"""ErrorBurn widget + DeviceCard transition wiring."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from textual.app import App, ComposeResult

from tailtop.data.models import ConnType, Peer
from tailtop.state import RateHistory
from tailtop.themes import MISSION_CONTROL
from tailtop.widgets.device_card import DeviceCard
from tailtop.widgets.error_burn import ErrorBurn


@dataclass
class _FakePeer:
    id: str = "peer-1"
    name: str = "alpha"
    os: str = "linux"
    online: bool = True
    is_self: bool = False
    ipv4: str = "100.0.0.1"
    magic_dns: str = ""
    conn_type: ConnType = ConnType.DIRECT
    relay_label: str = "direct"
    rx_bytes: int = 0
    tx_bytes: int = 0
    exit_node: bool = False
    exit_node_option: bool = False


class _Host(App):
    def __init__(self, card: DeviceCard) -> None:
        super().__init__()
        self._card = card

    def compose(self) -> ComposeResult:
        yield self._card


async def test_error_burn_runs_and_finishes() -> None:
    burn = ErrorBurn("Daemon down", theme=MISSION_CONTROL)
    host = _Host(burn)
    async with host.run_test() as pilot:
        for _ in range(300):
            await pilot.pause()
            if burn.done:
                break
            await asyncio.sleep(0.02)
        assert burn.done


async def test_card_no_burn_on_first_update() -> None:
    """A peer that is offline on first sight should NOT trigger burn."""
    card = DeviceCard("peer-1")
    host = _Host(card)
    rates = RateHistory()
    async with host.run_test() as pilot:
        await pilot.pause()
        offline_peer = _FakePeer(online=False, conn_type=ConnType.OFFLINE)
        card.update_card(offline_peer, rates)  # type: ignore[arg-type]
        await pilot.pause()
        assert card._burn is None, "first-sight offline peer should not burn"


async def test_card_burns_on_online_to_offline_transition() -> None:
    card = DeviceCard("peer-1")
    host = _Host(card)
    rates = RateHistory()
    async with host.run_test() as pilot:
        await pilot.pause()
        # First update: online (sets _was_online=True)
        card.update_card(_FakePeer(online=True), rates)  # type: ignore[arg-type]
        await pilot.pause()
        assert card._burn is None
        # Second update: offline (triggers burn)
        card.update_card(_FakePeer(online=False, conn_type=ConnType.OFFLINE), rates)  # type: ignore[arg-type]
        await pilot.pause()
        assert card._burn is not None, "online → offline transition should mount ErrorBurn"
        # Eventually the burn completes and dismisses
        for _ in range(400):
            await pilot.pause()
            await asyncio.sleep(0.02)
            if card._burn is None:
                break
        assert card._burn is None, "ErrorBurn should remove itself after finishing"
