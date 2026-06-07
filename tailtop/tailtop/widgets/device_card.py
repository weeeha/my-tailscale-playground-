"""A live device card for Cockpit mode — status, path, and RX/TX sparklines."""

from __future__ import annotations

from rich.console import Group
from rich.text import Text
from textual.widgets import Static

from tailtop.data.models import ConnType, Peer
from tailtop.data.vitals import Vitals
from tailtop.state import RateHistory, human_rate, sparkline
from tailtop.themes import theme_for_mode
from tailtop.widgets.error_burn import ErrorBurn
from tailtop.widgets.tte_runner import TTERunner

_SPARK_MAX = 32  # matches RateHistory.WIDTH; past this we're drawing empty dots

_CONN_COLOR = {
    ConnType.DIRECT: "#7be39b",
    ConnType.DERP: "#f0c674",
    ConnType.SELF: "#8bb6ff",
    ConnType.IDLE: "#f0c674",
    ConnType.OFFLINE: "#6b6f78",
}

_HEALTH_COLOR = {"ok": "#7be39b", "warn": "#f0c674", "crit": "#ff7878"}


def vitals_badge(v: Vitals | None) -> Text:
    """One-line temp/cpu/mem/disk badge, colored by health. Empty when no vitals."""
    if v is None:
        return Text("")
    color = _HEALTH_COLOR[v.health_level]
    t = Text()
    if v.soc_temp_c is not None:
        t.append(f"{v.soc_temp_c:.0f}°C", style=color)
        t.append("  ", style="dim")
    if v.throttled_now or v.under_voltage_now:
        t.append("⚡throttled  ", style="#ff7878")
    t.append(f"cpu {v.cpu_pct:.0f}%  ", style="dim")
    t.append(f"mem {v.mem_pct:.0f}%  ", style="dim")
    t.append(f"disk {v.disk_used_pct:.0f}%", style=color)
    return t


class DeviceCard(Static):
    """One peer, rendered as a bordered tile. Updated in place each poll."""

    def __init__(self, peer_id: str) -> None:
        super().__init__("", classes="devcard")
        self._peer_id = peer_id
        self._was_online: bool | None = None
        self._burn: ErrorBurn | None = None

    def update_card(self, peer: Peer, rates: RateHistory, vitals: Vitals | None = None) -> None:
        # Detect online → offline transition (first call has _was_online=None,
        # which doesn't fire the burn — only real transitions do).
        if (
            self._was_online is True
            and not peer.online
            and self._burn is None
        ):
            self._fire_burn(f"{peer.name} offline")
        self._was_online = peer.online

        color = _CONN_COLOR.get(peer.conn_type, "white")
        self.border_title = peer.name
        self.set_class(not peer.online, "offline")

        status_line = Text()
        status_line.append("◉ " if peer.online else "○ ", style=color)
        status_line.append("ONLINE" if peer.online else "OFFLINE", style=color)
        status_line.append(f"  {peer.os}", style="dim")

        path_line = Text(peer.relay_label, style=color)

        rx_label = f"  {human_rate(rates.current_rx(peer.id)):>10}"
        tx_label = f"  {human_rate(rates.current_tx(peer.id)):>10}"

        # Stretch the sparkline to fill the card. content_size is post-border,
        # post-padding; it's 0 before the first layout, so fall back to a value
        # that looks fine in a 3-column grid until the real size arrives.
        avail = self.content_size.width or 48
        spark_w = max(8, min(_SPARK_MAX, avail - len(rx_label) - 1))

        rx = Text()
        rx.append(sparkline(rates.rx_series(peer.id), width=spark_w), style="#f0c674")
        rx.append(rx_label, style="dim")

        tx = Text()
        tx.append(sparkline(rates.tx_series(peer.id), width=spark_w), style="#7be39b")
        tx.append(tx_label, style="dim")

        rows = [status_line, path_line, Text(""), rx, tx]
        if vitals is not None:
            rows.append(Text(""))
            rows.append(vitals_badge(vitals))
        self.update(Group(*rows))

    def _fire_burn(self, message: str) -> None:
        """Mount a brief ErrorBurn overlay over the card."""
        theme = theme_for_mode("cockpit")
        self._burn = ErrorBurn(message, theme=theme, id=f"burn-{self._peer_id}")
        self._burn.styles.dock = "top"
        self._burn.styles.layer = "overlay"
        self._burn.styles.width = "100%"
        self._burn.styles.height = "1"
        self._burn.styles.content_align = ("center", "middle")
        self._burn.styles.background = theme.background
        self.mount(self._burn)

    def on_tterunner_finished(self, msg: TTERunner.Finished) -> None:
        if self._burn is not None and msg.runner is self._burn:
            try:
                self._burn.remove()
            except Exception:  # noqa: BLE001
                pass
            self._burn = None
