"""Tailnet data source: parse ``tailscale status --json``, or a demo fixture."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable

from .models import Peer, Tailnet


def _peer_from(d: dict) -> Peer:
    ips = d.get("TailscaleIPs") or []
    name = d.get("HostName") or (d.get("DNSName", "") or "").split(".")[0] or "?"
    return Peer(
        name=name,
        os=d.get("OS", "") or "",
        ip=ips[0] if ips else "",
        online=bool(d.get("Online")),
        relay=d.get("Relay", "") or "",
        is_exit_node=bool(d.get("ExitNode")),
        exit_option=bool(d.get("ExitNodeOption")),
        rx_bytes=int(d.get("RxBytes", 0) or 0),
        tx_bytes=int(d.get("TxBytes", 0) or 0),
        active=bool(d.get("Active")),
    )


def from_json(data: dict) -> Tailnet:
    self_ = data.get("Self", {}) or {}
    peers = [_peer_from(p) for p in (data.get("Peer") or {}).values()]
    peers.sort(key=lambda p: (not p.online, p.name.lower()))
    return Tailnet(
        self_name=self_.get("HostName", "this-machine"),
        magic_dns=data.get("MagicDNSSuffix", "") or "",
        peers=peers,
    )


def _run_tailscale() -> str:
    return subprocess.run(
        ["tailscale", "status", "--json"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def load(run: Callable[[], str] | None = None) -> Tailnet:
    """Live tailnet from the local ``tailscale`` CLI (raises if it's missing)."""
    return from_json(json.loads((run or _run_tailscale)()))


def demo() -> Tailnet:
    """A believable fixture so tailsnap runs with no tailnet present."""
    mb = 1024 * 1024
    return Tailnet(
        self_name="workstation",
        magic_dns="tail1234.ts.net",
        peers=[
            Peer("nas", "linux", "100.64.0.3", True, "", is_exit_node=True,
                 exit_option=True, rx_bytes=9800 * mb, tx_bytes=1200 * mb, active=True),
            Peer("laptop", "macOS", "100.64.0.1", True, "", rx_bytes=2400 * mb,
                 tx_bytes=900 * mb, active=True),
            Peer("phone", "iOS", "100.64.0.2", True, "fra", rx_bytes=120 * mb,
                 tx_bytes=40 * mb),
            Peer("pi-garage", "linux", "100.64.0.4", True, "fra", exit_option=False,
                 rx_bytes=15 * mb, tx_bytes=8 * mb),
            Peer("old-tablet", "android", "100.64.0.7", False),
        ],
    )
