"""Async scrape of tailprobe agents into the store."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx

from .fleet import Device
from .store import Store
from .vitals_norm import build_snapshot, vitals_to_metrics

ScrapeFn = Callable[[Device], Awaitable[dict | None]]


async def scrape_one(client: httpx.AsyncClient, dev: Device, port: int,
                     timeout: float, token: str | None = None) -> dict | None:
    """GET /vitals from a probe. Returns the parsed dict, or None on any failure."""
    if not dev.addr:
        return None
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = await client.get(f"http://{dev.addr}:{port}/vitals", timeout=timeout, headers=headers)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


async def scrape_cycle(store: Store, devices: list[Device], scrape: ScrapeFn,
                       now: float, prev_online: dict[str, bool]) -> dict[str, bool]:
    """Scrape all probe devices concurrently, write results, record transitions.
    Returns the new {host: online} map."""
    probes = [d for d in devices if d.has_probe]
    results = await asyncio.gather(*(scrape(d) for d in probes), return_exceptions=True)

    new_state: dict[str, bool] = {}

    def record(host: str, online: bool, reason: str) -> None:
        was = prev_online.get(host)
        if was is True and not online:
            store.add_event(host, now, "went_offline", {"reason": reason})
        elif was is False and online:
            store.add_event(host, now, "came_online", {})
        new_state[host] = online

    for dev, res in zip(probes, results):
        vitals = res if isinstance(res, dict) else None
        if vitals is None:
            store.add_device(dev.host, now, online=False, has_probe=True, snapshot={"host": dev.host})
            record(dev.host, False, "scrape_failed")
        else:
            store.add_device(dev.host, now, online=True, has_probe=True,
                             snapshot=build_snapshot(vitals))
            store.add_metrics(dev.host, now, vitals_to_metrics(vitals))
            record(dev.host, True, "")

    # agentless devices: online/offline only, from tailscale status
    for dev in devices:
        if dev.has_probe:
            continue
        store.add_device(dev.host, now, online=dev.online, has_probe=False,
                         snapshot={"host": dev.host})
        record(dev.host, dev.online, "tailscale_offline")

    store.commit()
    return new_state
