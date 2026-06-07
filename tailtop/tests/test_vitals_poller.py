"""VitalsPoller: collects only Pi hosts, survives per-host failures."""
from __future__ import annotations

import asyncio

from tailtop.data.vitals import Vitals
from tailtop.data.vitals_poller import VitalsPoller, PI_HOSTS


class FakeClient:
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls: list[str] = []

    async def collect_vitals(self, host, user_map):  # noqa: ANN001
        self.calls.append(host)
        b = self.behaviour.get(host)
        if isinstance(b, Exception):
            raise b
        return b


async def test_collects_each_pi_once() -> None:
    hosts = ["fastclock", "slowclock"]
    client = FakeClient({h: Vitals(host=h, soc_temp_c=40.0) for h in hosts})
    poller = VitalsPoller(client, pi_hosts=hosts, user_map={})
    result = await poller.collect_round()
    assert set(result) == {"fastclock", "slowclock"}
    assert sorted(client.calls) == ["fastclock", "slowclock"]


async def test_one_host_failure_does_not_sink_the_round() -> None:
    client = FakeClient({
        "fastclock": Vitals(host="fastclock", soc_temp_c=42.0),
        "slowclock": asyncio.TimeoutError(),
    })
    poller = VitalsPoller(client, pi_hosts=["fastclock", "slowclock"], user_map={})
    result = await poller.collect_round()
    assert "fastclock" in result
    assert "slowclock" not in result


def test_pi_hosts_default_list_is_the_known_fleet() -> None:
    assert "fastclock" in PI_HOSTS
    assert "nickv-orangepizero2w" in PI_HOSTS
