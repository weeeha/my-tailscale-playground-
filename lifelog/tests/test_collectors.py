"""Phase 2: context-collector tests (real logic, injected fakes — no devices)."""

from __future__ import annotations

from lifelog import config as C
from lifelog.bus import LocalBus
from lifelog.collectors.network import NetworkDeviceCollector
from lifelog.collectors.plug import HttpPlugCollector, parse_shelly, parse_tasmota
from lifelog.collectors.runner import CollectorRunner
from lifelog.collectors.tailscale import TailscaleOnlineCollector
from lifelog.fusion import Fusion
from lifelog.model import KIND_CONTEXT, KIND_MOTION, SensorEvent
from lifelog.store import Store


# -- network -----------------------------------------------------------------
def test_network_collector_emits_reachable_state():
    up = NetworkDeviceCollector(C.CTX_PLAYSTATION, "h", port=1, probe=lambda: True)
    evs = up.poll(100.0)
    assert len(evs) == 1
    assert evs[0].kind == KIND_CONTEXT
    assert evs[0].features == {"key": C.CTX_PLAYSTATION, "value": True}


def test_collector_swallows_probe_errors():
    def boom() -> bool:
        raise OSError("network down")

    c = NetworkDeviceCollector("x", "h", probe=boom)
    assert c.poll(1.0) == []   # degrades to no event, no crash


def test_collector_respects_interval():
    c = NetworkDeviceCollector("x", "h", probe=lambda: True, interval_s=30.0)
    assert c.due(0.0)
    c.poll(0.0)
    assert not c.due(10.0)
    assert c.due(30.0)


# -- plug parsers ------------------------------------------------------------
def test_parse_tasmota_and_shelly():
    assert parse_tasmota('{"POWER":"ON"}') is True
    assert parse_tasmota('{"POWER":"OFF"}') is False
    assert parse_shelly('{"ison": true}') is True
    assert parse_shelly('{"output": false}') is False


def test_plug_collector_uses_injected_fetch():
    c = HttpPlugCollector(C.CTX_KETTLE_ON, "http://x", fetch=lambda url: '{"POWER":"ON"}')
    assert c.read() is True


# -- tailscale ---------------------------------------------------------------
def _status(host: str, online: bool) -> dict:
    return {"Peer": {"k": {"HostName": host, "DNSName": f"{host}.ts.net", "Online": online}}}


def test_tailscale_online_and_missing_peer():
    on = TailscaleOnlineCollector(C.CTX_TV, "shield", status_provider=lambda: _status("shield", True))
    assert on.read() is True
    off = TailscaleOnlineCollector(C.CTX_TV, "shield", status_provider=lambda: _status("shield", False))
    assert off.read() is False
    missing = TailscaleOnlineCollector(C.CTX_TV, "nope", status_provider=lambda: _status("shield", True))
    assert missing.read() is None   # not in tailnet → undetermined


# -- runner + pipeline integration ------------------------------------------
def test_runner_snapshot():
    runner = CollectorRunner([
        NetworkDeviceCollector(C.CTX_PLAYSTATION, "h", probe=lambda: True),
        NetworkDeviceCollector(C.CTX_PC_ACTIVE, "h", probe=lambda: False),
    ])
    assert runner.snapshot(0.0) == {C.CTX_PLAYSTATION: True, C.CTX_PC_ACTIVE: False}


def test_collector_context_drives_gaming_through_fusion(tmp_path):
    """A real collector reporting PlayStation-up should make fusion label GAMING."""
    import time

    store = Store(str(tmp_path / "c.db"))
    bus = LocalBus(store)
    runner = CollectorRunner(
        [NetworkDeviceCollector(C.CTX_PLAYSTATION, "h", probe=lambda: True, interval_s=30.0)],
        sink=bus,
    )
    # Interleave living-room motion with collector polls over ~10 min of "today".
    base = time.time()
    for off in range(0, 600, 30):
        t = base + off
        bus.publish(SensorEvent(t, "pi-living", KIND_MOTION, {"motion": 0.22}))
        runner.poll(t, force=True)

    Fusion(store).run_stream(bus.drain_since())
    totals = store.activity_totals(time.strftime("%Y-%m-%d", time.localtime(base)))
    assert C.GAMING in totals, totals
