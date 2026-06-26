"""The scrape loop and the process entrypoint."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import httpx

from .fleet import Device, discover_fleet, tailscale_status_json
from .scrape import scrape_cycle, scrape_one
from .settings import Settings
from .store import Store

StatusProvider = Callable[[], dict]
ScrapeFn = Callable[[Device], Awaitable[dict | None]]


async def run_cycle(store: Store, settings: Settings, now: float, prev_online: dict[str, bool],
                    status_provider: StatusProvider, scrape: ScrapeFn) -> dict[str, bool]:
    """One discover → scrape → write pass. Returns the new {host: online} map."""
    status = await asyncio.to_thread(status_provider)
    devices = discover_fleet(status, probe_hosts=set(settings.probe_hosts))
    return await scrape_cycle(store, devices, scrape, now=now, prev_online=prev_online)


async def run_scheduler(store: Store, settings: Settings, stop: asyncio.Event,
                        status_provider: StatusProvider | None = None,
                        scrape: ScrapeFn | None = None) -> None:
    """Loop run_cycle on the interval until stop is set. One bad cycle never kills the loop."""
    status_provider = status_provider or tailscale_status_json
    state: dict[str, bool] = {}
    last_rollup_hour = -1

    async with httpx.AsyncClient() as client:
        real_scrape: ScrapeFn = scrape or (
            lambda dev: scrape_one(client, dev, settings.probe_port,
                                   settings.request_timeout_s, settings.bearer_token)
        )
        while not stop.is_set():
            t0 = time.monotonic()
            now = time.time()
            try:
                state = await run_cycle(store, settings, now, state, status_provider, real_scrape)
                hour = int(now // 3600) * 3600
                if hour != last_rollup_hour:
                    store.rollup_hour(hour - 3600)          # finalize the just-completed hour
                    store.prune(now - settings.retention_days * 86400)
                    last_rollup_hour = hour
            except Exception as e:  # never let the loop die
                store.add_event("tailhub", time.time(), "cycle_error", {"error": str(e)})
                store.commit()
            elapsed = time.monotonic() - t0
            try:
                await asyncio.wait_for(stop.wait(), timeout=max(0.0, settings.scrape_interval_s - elapsed))
            except asyncio.TimeoutError:
                pass


def main() -> None:
    import uvicorn

    from .app import create_app

    settings = Settings()
    store = Store(settings.db_path)
    app = create_app(store, settings)
    stop = asyncio.Event()

    @app.on_event("startup")
    async def _start() -> None:
        app.state.scheduler = asyncio.create_task(run_scheduler(store, settings, stop))

    @app.on_event("shutdown")
    async def _stop() -> None:
        stop.set()
        await app.state.scheduler

    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
