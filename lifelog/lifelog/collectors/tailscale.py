"""Tailscale-peer collector: a named tailnet device's online state.

Reads ``tailscale status --json`` and reports whether a given peer is online — a
zero-config presence signal for anything already on your tailnet (a shield TV, a
work laptop). Returns None when the peer isn't found, so an unknown name simply
contributes nothing rather than a false "off".
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable

from .base import Collector


def tailscale_status_json() -> dict:
    out = subprocess.run(
        ["tailscale", "status", "--json"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)


class TailscaleOnlineCollector(Collector):
    def __init__(
        self,
        key: str,
        peer_host: str,
        *,
        status_provider: Callable[[], dict] | None = None,
        interval_s: float = 30.0,
    ) -> None:
        super().__init__(key, interval_s)
        self.peer_host = peer_host.lower()
        self._status = status_provider or tailscale_status_json

    def read(self) -> bool | None:
        peers = (self._status().get("Peer") or {}).values()
        for peer in peers:
            names = (peer.get("HostName", ""), peer.get("DNSName", ""))
            if any(self.peer_host in (n or "").lower() for n in names):
                return bool(peer.get("Online", False))
        return None  # peer not in tailnet → undetermined
