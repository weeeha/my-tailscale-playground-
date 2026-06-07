"""Device detail — a three-section inspector for the selected peer.

Left of this lives the device list; this widget is the right side: info panels
(Status / Network / Exit·Tags) plus live charts (Latency / Throughput) and a
self-only connectivity panel. Sections without data for the selected peer are
omitted, never shown empty.
"""

from __future__ import annotations

from datetime import datetime, timezone

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from tailtop.data.latency import LatencyProbe
from tailtop.data.models import ConnType, Peer
from tailtop.data.netcheck import NetCheck
from tailtop.data.vitals import Vitals
from tailtop.state import RateHistory, human_rate, sparkline
from tailtop.widgets.charts import LatencyChart

_CONN_COLOR = {
    ConnType.DIRECT: "#7be39b",
    ConnType.DERP: "#f0c674",
    ConnType.SELF: "#8bb6ff",
    ConnType.IDLE: "#f0c674",
    ConnType.OFFLINE: "#6b6f78",
}


def _ago(when: datetime | None) -> str:
    if when is None:
        return "—"
    secs = int((datetime.now(timezone.utc) - when.astimezone(timezone.utc)).total_seconds())
    if secs < 0:
        return "—"
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _expiry(when: datetime | None) -> str:
    if when is None:
        return "never"
    days = int((when.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds() // 86400)
    if days < 0:
        return "expired"
    if days < 60:
        return f"in {days} days"
    return f"in {days // 30} months"


def _kv(rows: list[tuple[str, object]]) -> Table:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="#6b6f78", justify="left")
    grid.add_column()
    for k, v in rows:
        grid.add_row(k, v)
    return grid


class DeviceDetail(Vertical):
    """Composite detail view; updated in place each refresh."""

    def compose(self) -> ComposeResult:
        yield Static(id="detail-title")
        with Horizontal(id="detail-cols"):
            with Vertical(id="detail-info"):
                yield Static(id="panel-status", classes="dpanel")
                yield Static(id="panel-network", classes="dpanel")
                yield Static(id="panel-exit", classes="dpanel")
                yield Static(id="panel-vitals", classes="dpanel")
                yield Static(id="panel-hardware", classes="dpanel")
            with Vertical(id="detail-charts"):
                yield LatencyChart(id="latency-chart")
                yield Static(id="panel-throughput", classes="dpanel")
                yield Static(id="panel-quality", classes="dpanel")
                yield Static("send file · f   ssh · s", id="detail-actions")

    def show_empty(self, message: str = "Select a device") -> None:
        self.query_one("#detail-title", Static).update(Text(message, style="dim"))
        for pid in ("#panel-status", "#panel-network", "#panel-exit",
                    "#panel-vitals", "#panel-hardware",
                    "#panel-throughput", "#panel-quality"):
            self.query_one(pid, Static).update("")
            self.query_one(pid, Static).display = False
        self.query_one("#latency-chart", LatencyChart).display = False
        self.query_one("#detail-actions", Static).display = False

    def update_peer(
        self,
        peer: Peer,
        rates: RateHistory,
        probe: LatencyProbe,
        netcheck: NetCheck | None = None,
        vitals: Vitals | None = None,
    ) -> None:
        color = _CONN_COLOR.get(peer.conn_type, "white")

        # title
        title = Text()
        title.append(peer.name, style="bold")
        if peer.host_label.lower() in ("", "localhost") and peer.name != peer.host_label:
            title.append(f"  ({peer.host_label or 'localhost'})", style="dim")
        title.append("\n")
        title.append("● " if peer.online else "○ ", style=color)
        title.append("Connected" if peer.online else "Offline", style=color)
        title.append(f"  ·  {peer.relay_label}", style=color)
        self.query_one("#detail-title", Static).update(title)

        # Status panel
        self._panel(
            "#panel-status", "Status", "#8bb6ff",
            _kv([
                ("MagicDNS", peer.magic_dns or "—"),
                ("IPv4", peer.ipv4 or "—"),
                ("IPv6", peer.ipv6 or "—"),
                ("OS", peer.os or "—"),
                ("ID", peer.id or "—"),
            ]),
        )

        # Network panel (+ endpoints/attributes when self)
        net_rows: list[tuple[str, object]] = [
            ("Routes", "\n".join(peer.allowed_ips) or "—"),
            ("PeerAPI", peer.peerapi[0] if peer.peerapi else "—"),
            ("Created", _ago(peer.created)),
            ("Last write", _ago(peer.last_handshake)),
        ]
        if peer.is_self and peer.addrs:
            net_rows.append(("Endpoints", "\n".join(peer.addrs[:4])))
        self._panel("#panel-network", "Network", "#7be39b", _kv(net_rows))

        # Exit · Tags · Key
        exit_rows: list[tuple[str, object]] = []
        if peer.exit_node_option:
            exit_rows.append(("Exit node", "in use" if peer.exit_node else "available"))
        else:
            exit_rows.append(("Exit node", Text("not offered", style="#6b6f78")))
        exit_rows.append(("Tags", ", ".join(peer.tags) if peer.tags else Text("none", style="#6b6f78")))
        exit_rows.append(("Key expiry", _expiry(peer.key_expiry)))
        if peer.is_self and peer.attributes:
            for name, val in peer.attributes[:4]:
                exit_rows.append((name, val))
        self._panel("#panel-exit", "Exit · Tags · Key", "#c792ea", _kv(exit_rows))

        # Latency chart
        chart = self.query_one("#latency-chart", LatencyChart)
        chart.display = True
        chart.border_title = self._latency_title(peer, probe)
        chart.set_series(probe.series(peer.id))

        # Throughput panel
        rx = Text()
        rx.append("rx ", style="#6b6f78")
        rx.append(sparkline(rates.rx_series(peer.id), width=16), style="#f0c674")
        rx.append(f"  {human_rate(rates.current_rx(peer.id))}", style="white")
        tx = Text()
        tx.append("tx ", style="#6b6f78")
        tx.append(sparkline(rates.tx_series(peer.id), width=16), style="#7be39b")
        tx.append(f"  {human_rate(rates.current_tx(peer.id))}", style="white")
        self._panel("#panel-throughput", "Throughput", "#f0c674", Group(rx, tx))

        # Connection quality (+ netcheck when self)
        self._quality_panel(peer, netcheck)

        # Vitals + hardware panels (only when vitals are present)
        self._vitals_panels(vitals)

        self.query_one("#detail-actions", Static).display = True

    # ---- helpers -----------------------------------------------------------

    def _panel(self, pid: str, title: str, color: str, body) -> None:
        panel = self.query_one(pid, Static)
        panel.display = True
        panel.border_title = title
        panel.styles.border_title_color = color
        panel.update(body)

    def _latency_title(self, peer: Peer, probe: LatencyProbe) -> str:
        last = probe.last(peer.id)
        via = probe.via(peer.id)
        if last is None:
            return "Latency · ping RTT"
        return f"Latency · {last:.0f} ms · {via or peer.relay_label}"

    def _vitals_panels(self, vitals: Vitals | None) -> None:
        vp = self.query_one("#panel-vitals", Static)
        hp = self.query_one("#panel-hardware", Static)
        if vitals is None:
            vp.display = False
            hp.display = False
            return
        color = {"ok": "#7be39b", "warn": "#f0c674", "crit": "#ff7878"}[vitals.health_level]
        temp = f"{vitals.soc_temp_c:.0f}°C" if vitals.soc_temp_c is not None else "—"
        flags = []
        if vitals.throttled_now:
            flags.append("throttled")
        if vitals.under_voltage_now:
            flags.append("under-voltage")
        self._panel("#panel-vitals", "Vitals", color, _kv([
            ("Temp", Text(temp, style=color)),
            ("Flags", ", ".join(flags) if flags else Text("none", style="#6b6f78")),
            ("Load", f"{vitals.load1:.2f}"),
            ("CPU", f"{vitals.cpu_pct:.0f}%"),
            ("Memory", f"{vitals.mem_pct:.0f}%"),
            ("Disk", Text(f"{vitals.disk_used_pct:.0f}% used · {vitals.disk_free_gb:.1f} GB free", style=color)),
            ("Uptime", f"{vitals.uptime_s // 86400}d {vitals.uptime_s % 86400 // 3600}h"),
        ]))
        displays = "\n".join(f"{d.connector} {d.mode}".strip() for d in vitals.displays) or "—"
        battery = (
            f"{vitals.battery_pct:.0f}%"
            if vitals.battery_present and vitals.battery_pct is not None
            else ("present" if vitals.battery_present else "—")
        )
        if vitals.app_running is True:
            app_state = "running"
        elif vitals.app_running is False:
            app_state = "DOWN"
        else:
            app_state = "unknown"
        app = f"{vitals.app_name}: {app_state}" if vitals.app_name else "—"
        self._panel("#panel-hardware", "Hardware", "#8bb6ff", _kv([
            ("Model", vitals.model or "—"),
            ("Displays", displays),
            ("USB", str(vitals.usb_count)),
            ("Battery", battery),
            ("App", Text(app, style="#ff7878" if vitals.app_running is False else "white")),
        ]))

    def _quality_panel(self, peer: Peer, netcheck: NetCheck | None) -> None:
        rows: list[tuple[str, object]] = [("Path", Text(peer.relay_label))]
        rows.append(("State", "active" if peer.active else "idle"))
        if peer.is_self and netcheck is not None:
            yn = lambda b: Text("yes", style="#7be39b") if b else Text("no", style="#6b6f78")  # noqa: E731
            rows.append(("UDP", yn(netcheck.udp)))
            rows.append(("IPv6", yn(netcheck.ipv6)))
            rows.append(("PortMap", netcheck.portmapping or Text("none", style="#6b6f78")))
            for code, ms, name in netcheck.relays[:3]:
                mark = " ✓" if name == netcheck.nearest else ""
                rows.append((name, Text(f"{ms:.0f} ms{mark}", style="#7be39b" if mark else "white")))
        self._panel("#panel-quality", "Connection quality", "#8bb6ff", _kv(rows))
