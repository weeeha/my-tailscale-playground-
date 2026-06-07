"""TheBase mode — animated belt topology dashboard. Intent: see your tailnet.

Composes:
    header  · tailnet name + online/total + aggregate ↓/↑
    alert   · offline count + expiring-key warnings + backend state
    belt    · BeltView (Hub or Bus, animated dual-lane belts)
    detail  · DeviceDetail for the selected peer

Selection is propagated to ``app.selected_peer_id`` so the existing verbs
(ping/ssh/copy IP/...) target the selected peer just like in Comfort.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from tailtop.data.models import Peer, Status
from tailtop.modes.base import ModeView
from tailtop.state import RateHistory, human_rate
from tailtop.widgets.alert_strip import AlertStrip
from tailtop.widgets.belt import BeltView
from tailtop.widgets.detail_pane import DeviceDetail


class TheBaseMode(ModeView):
    """Belt-centric dashboard mode."""

    cadence = 2.0

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._selected_id: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(id="tb-header")
            yield AlertStrip(id="tb-alert")
            with Horizontal(id="tb-body"):
                yield BeltView(id="tb-belt")
                yield DeviceDetail(id="tb-detail")

    def on_mount(self) -> None:
        self.query_one(DeviceDetail).show_empty("Loading the base…")

    def update_data(self, status: Status, rates: RateHistory) -> None:
        import time
        now = time.monotonic()

        # Belt — update first so its computed aggregate is authoritative.
        belt = self.query_one(BeltView)
        belt.update_data(status, rates, now=now)

        # Header — uses the belt's aggregate for consistency.
        header = Text()
        header.append("▌ TAILNET · THE BASE", style="bold #8bb6ff")
        header.append("   ")
        if status.connected:
            header.append(f"{status.online_count}/{status.total_count} online", style="#7be39b")
        else:
            header.append(status.backend_state, style="#f0c674")
        header.append("   ")
        header.append(f"↓{human_rate(belt._aggregate_rx)}  ↑{human_rate(belt._aggregate_tx)}", style="dim")
        self.query_one("#tb-header", Static).update(header)

        # Alert strip.
        self.query_one(AlertStrip).set_status(status, getattr(self.app, "vitals", None))

        # Seed selection from app-level state if not yet chosen locally.
        if self._selected_id is None and hasattr(self.app, "selected_peer_id") and self.app.selected_peer_id:
            self._selected_id = self.app.selected_peer_id

        # Default selection: first online peer if still none.
        if self._selected_id is None:
            for p in status.peers:
                if p.online:
                    self._select(p, status)
                    break

        # Push current selection into the belt and detail pane.
        if self._selected_id is not None:
            self.query_one(BeltView).set_selected(self._selected_id)
            peer = next((p for p in status.peers if p.id == self._selected_id), None)
            if peer is not None:
                self.query_one(DeviceDetail).update_peer(
                    peer, self.app.rates, self.app.latency,
                    getattr(self.app, "netcheck_self", None),
                    getattr(self.app, "vitals", {}).get(peer.id),
                )
            else:
                self.query_one(DeviceDetail).show_empty("Selected peer is gone")

    def _select(self, peer: Peer, status: Status) -> None:
        self._selected_id = peer.id
        self.query_one(DeviceDetail).update_peer(
            peer, self.app.rates, self.app.latency,
            getattr(self.app, "netcheck_self", None),
            getattr(self.app, "vitals", {}).get(peer.id),
        )
        self.query_one(BeltView).set_selected(peer.id)
        if hasattr(self.app, "selected_peer_id"):
            self.app.selected_peer_id = peer.id
