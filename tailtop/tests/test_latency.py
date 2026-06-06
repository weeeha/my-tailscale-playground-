"""Latency + netcheck parsing, and the probe's ring buffer."""

from __future__ import annotations

from tailtop.data.latency import LatencyProbe, parse_ping
from tailtop.data.netcheck import parse_netcheck


def test_parse_ping_direct() -> None:
    rtt, via = parse_ping("pong from art (100.114.149.53) via 192.168.4.43:41641 in 6ms")
    assert rtt == 6.0
    assert via == "direct"


def test_parse_ping_derp() -> None:
    rtt, via = parse_ping("pong from box (100.78.29.28) via DERP(nyc) in 29ms")
    assert rtt == 29.0
    assert via == "DERP·nyc"


def test_parse_ping_timeout() -> None:
    rtt, via = parse_ping("no reply")
    assert rtt is None
    assert via == "timeout"


def test_probe_ring_buffer() -> None:
    probe = LatencyProbe(client=None, width=3)
    for v in (10, 11, 12, 13):
        probe.record("p1", float(v), "direct")
    assert probe.series("p1") == [11.0, 12.0, 13.0]  # bounded to width=3
    assert probe.last("p1") == 13.0
    assert probe.via("p1") == "direct"


NETCHECK_TEXT = """Report:
\t* UDP: true
\t* IPv4: yes, 70.83.57.153:53449
\t* IPv6: no, but OS has support
\t* MappingVariesByDestIP: false
\t* PortMapping: UPnP
\t* Nearest DERP: Toronto
\t* DERP latency:
\t\t- tor: 31.8ms  (Toronto)
\t\t- nyc: 32.5ms  (New York City)
\t\t- iad: 37.8ms  (Ashburn)
"""


def test_parse_netcheck() -> None:
    nc = parse_netcheck(NETCHECK_TEXT)
    assert nc.udp is True
    assert nc.ipv6 is False
    assert nc.varies is False
    assert nc.portmapping == "UPnP"
    assert nc.nearest == "Toronto"
    assert nc.relays[0] == ("tor", 31.8, "Toronto")
    assert [r[2] for r in nc.relays] == ["Toronto", "New York City", "Ashburn"]
