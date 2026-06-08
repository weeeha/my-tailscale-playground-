"""Example collector wiring — edit to match your devices.

These point at placeholder hostnames so the package runs anywhere; unreachable
devices simply report "off" (or, for the tailnet peer, "undetermined"). Swap in
your real hosts / plug URLs / peer names to make Phase 2 live.
"""

from __future__ import annotations

from .. import config as C
from .base import Collector
from .network import NetworkDeviceCollector
from .plug import HttpPlugCollector, parse_tasmota
from .tailscale import TailscaleOnlineCollector


def example_collectors() -> list[Collector]:
    return [
        # Console: reachable on its remote-play port ⇒ powered on.
        NetworkDeviceCollector(C.CTX_PLAYSTATION, host="playstation.local", port=9295),
        # Work machine: SSH open ⇒ awake. (Better: an agent that also reports the
        # foreground app, so WORKING can require an IDE/docs window.)
        NetworkDeviceCollector(C.CTX_PC_ACTIVE, host="workstation.local", port=22),
        # Kitchen appliance on a Tasmota plug.
        HttpPlugCollector(C.CTX_KETTLE_ON, "http://kitchen-plug.local/cm?cmnd=Power",
                          parser=parse_tasmota),
        # TV as a tailnet peer's online state.
        TailscaleOnlineCollector(C.CTX_TV, "shield-tv"),
    ]
