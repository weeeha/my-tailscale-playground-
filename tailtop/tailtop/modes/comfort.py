"""Comfort mode — List view + rich device detail. Intent: manage."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from tailtop.data.models import Peer, Status
from tailtop.modes.base import ModeView
from tailtop.state import RateHistory
from tailtop.widgets.detail_pane import DeviceDetail
from tailtop.widgets.device_list import DeviceList


class ComfortMode(ModeView):
    cadence = 2.0

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._selected_id: str | None = None
        self._selected_peer: Peer | None = None
        self._status: Status | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Devices", id="comfort-header")
            with Horizontal(id="comfort-body"):
                yield DeviceList(id="device-list")
                yield DeviceDetail(id="detail-pane")

    def on_mount(self) -> None:
        self.query_one(DeviceDetail).show_empty("Loading devices…")
        # animate the latency/throughput charts between status polls
        self.set_interval(1.0, self._tick)

    def update_data(self, status: Status, rates: RateHistory) -> None:
        self._status = status
        peers = status.all_nodes()  # self pinned at top, then peers
        header = self.query_one("#comfort-header", Static)
        if not status.connected:
            header.update(f"Devices · {status.backend_state}")
        else:
            header.update(f"Devices · {status.online_count}/{status.total_count} online")
        self.query_one(DeviceList).populate(peers, keep_id=self._selected_id)
        if not peers:
            self.query_one(DeviceDetail).show_empty("No devices on this tailnet")
            return
        if self._selected_id is None:
            self._select(peers[0])
        else:
            # refresh the currently-selected peer's data
            current = next((p for p in peers if p.id == self._selected_id), None)
            if current:
                self._selected_peer = current
                self._render_detail()

    def on_device_list_peer_highlighted(self, event: DeviceList.PeerHighlighted) -> None:
        if event.peer:
            self._select(event.peer)

    def _select(self, peer: Peer) -> None:
        self._selected_id = peer.id
        self._selected_peer = peer
        app = self.app
        if hasattr(app, "selected_peer_id"):
            app.selected_peer_id = peer.id
        if hasattr(app, "latency"):
            app.latency.retarget(peer)
        if peer.is_self and hasattr(app, "ensure_netcheck"):
            app.ensure_netcheck()
        self._render_detail()

    def _tick(self) -> None:
        # cheap: re-render from current buffers so the chart animates at ~1 Hz
        if self._selected_peer is not None and getattr(self.app, "active_mode", "") == "comfort":
            self._render_detail()

    def _render_detail(self) -> None:
        if self._selected_peer is None:
            return
        app = self.app
        self.query_one(DeviceDetail).update_peer(
            self._selected_peer,
            app.rates,
            app.latency,
            getattr(app, "netcheck_self", None),
        )
