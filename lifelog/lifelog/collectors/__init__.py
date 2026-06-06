"""Context collectors (L3) — real device/appliance state off the network.

Each collector answers one yes/no question about the world ("is the PlayStation
up?", "is the kitchen plug on?") and publishes it as a context ``SensorEvent``
into the same pipeline the simulator fed in Phase 1. This is the high-value
layer: device truth beats inferring activity from a body.

Collectors are real, but every one takes an injectable probe so the logic is
unit-testable without the device present, and a failed/unreachable probe
degrades to "no event" rather than crashing the daemon.
"""

from __future__ import annotations

from .base import Collector
from .network import NetworkDeviceCollector, ping_reachable, tcp_reachable
from .plug import HttpPlugCollector, parse_shelly, parse_tasmota
from .runner import CollectorRunner
from .ruview import RuViewBridge, translate as ruview_translate
from .tailscale import TailscaleOnlineCollector

__all__ = [
    "Collector",
    "NetworkDeviceCollector",
    "tcp_reachable",
    "ping_reachable",
    "HttpPlugCollector",
    "parse_tasmota",
    "parse_shelly",
    "TailscaleOnlineCollector",
    "CollectorRunner",
    "RuViewBridge",
    "ruview_translate",
]
