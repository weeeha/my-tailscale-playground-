"""Discover the tailnet fleet from `tailscale status --json`."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Device:
    host: str
    addr: str       # first IPv4 (100.x) or "" if none
    online: bool
    has_probe: bool


def tailscale_status_json() -> dict:
    out = subprocess.run(
        ["tailscale", "status", "--json"],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


def _first_ipv4(ips: list[str]) -> str:
    for ip in ips or []:
        if ":" not in ip:      # crude but sufficient: skip IPv6
            return ip
    return ""


def _node_to_device(node: dict, probe_hosts: set[str]) -> Device:
    host = node.get("HostName", "")
    return Device(
        host=host,
        addr=_first_ipv4(node.get("TailscaleIPs", [])),
        online=bool(node.get("Online", False)),
        has_probe=host.lower() in {h.lower() for h in probe_hosts},
    )


def discover_fleet(status: dict, probe_hosts: set[str]) -> list[Device]:
    """All tailnet nodes (Self + Peers) as Device records."""
    devices: list[Device] = []
    if status.get("Self"):
        devices.append(_node_to_device(status["Self"], probe_hosts))
    for node in (status.get("Peer") or {}).values():
        devices.append(_node_to_device(node, probe_hosts))
    return devices
