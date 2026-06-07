"""Parse `tailscale netcheck` (text) into a structured report.

netcheck describes *this* machine's network conditions — connectivity flags
and DERP-region latencies (with names). The JSON form keys latency by numeric
region id; the text form carries human names, so we parse text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_RELAY = re.compile(r"-\s*(\w+):\s*([\d.]+)ms\s*\(([^)]+)\)")


@dataclass
class NetCheck:
    udp: bool | None = None
    ipv6: bool | None = None
    varies: bool | None = None
    portmapping: str = ""
    nearest: str = ""
    relays: list[tuple[str, float, str]] = field(default_factory=list)  # (code, ms, name)


def parse_netcheck(text: str) -> NetCheck:
    nc = NetCheck()
    in_derp = False
    for line in text.splitlines():
        s = line.strip()
        low = s.lower()
        if low.startswith("* udp:"):
            nc.udp = "true" in low
        elif low.startswith("* ipv6:"):
            nc.ipv6 = low.split(":", 1)[1].strip().startswith("yes")
        elif low.startswith("* mappingvariesbydestip:"):
            nc.varies = "true" in low
        elif low.startswith("* portmapping:"):
            nc.portmapping = s.split(":", 1)[1].strip()
        elif low.startswith("* nearest derp:"):
            nc.nearest = s.split(":", 1)[1].strip()
        elif low.startswith("* derp latency"):
            in_derp = True
        elif in_derp and s.startswith("-"):
            if m := _RELAY.match(s):
                nc.relays.append((m.group(1), float(m.group(2)), m.group(3)))
        elif in_derp and s.startswith("*"):
            in_derp = False
    nc.relays.sort(key=lambda r: r[1])
    return nc
