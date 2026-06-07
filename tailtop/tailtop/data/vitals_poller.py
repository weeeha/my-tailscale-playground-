"""Slow background poll of Pi hardware vitals over tailscale ssh.

Runs alongside the network Poller on a slower cadence so SSH latency never
drags the live UI. Each round collects all Pi hosts concurrently (capped);
one host failing never sinks the round.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from tailtop.data.vitals import Vitals

# No ACL tags in use → explicit allowlist of the Pi fleet (see spec §14).
PI_HOSTS = [
    "fastclock", "slowclock", "smallclock", "squareclock",
    "dashboard-ink-bed", "dashboard3eink", "plantdashboard",
    "nickv-orangepizero2w",
]

# SSH login users (spec §15). Unknown hosts fall back to the default.
USER_MAP = {
    "fastclock": "nickv2026", "slowclock": "nickv2026",
    "smallclock": "nickv2026", "squareclock": "nickv2026",
    "nickv-orangepizero2w": "nickv",
}

VitalsCallback = Callable[[dict[str, Vitals]], Awaitable[None] | None]
ErrorCallback = Callable[[Exception], Awaitable[None] | None]


class VitalsPoller:
    def __init__(
        self,
        client,
        on_vitals: VitalsCallback | None = None,
        on_error: ErrorCallback | None = None,
        pi_hosts: list[str] | None = None,
        user_map: dict[str, str] | None = None,
        interval: float = 30.0,
        concurrency: int = 5,
    ) -> None:
        self._client = client
        self._on_vitals = on_vitals
        self._on_error = on_error
        self._hosts = pi_hosts if pi_hosts is not None else PI_HOSTS
        self._user_map = user_map if user_map is not None else USER_MAP
        self._interval = interval
        self._sem = asyncio.Semaphore(concurrency)
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self.addr_map: dict[str, str] = {}  # hostname → Tailscale IP, refreshed by the app

    async def _collect_one(self, host: str) -> tuple[str, Vitals | None]:
        async with self._sem:
            try:
                return host, await self._client.collect_vitals(host, self._user_map, self.addr_map)
            except Exception:  # noqa: BLE001 — one host's failure is not fatal
                return host, None

    async def collect_round(self) -> dict[str, Vitals]:
        pairs = await asyncio.gather(*(self._collect_one(h) for h in self._hosts))
        return {h: v for h, v in pairs if v is not None}

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    def refresh_now(self) -> None:
        self._wake.set()

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                vitals = await self.collect_round()
                result = self._on_vitals(vitals) if self._on_vitals else None
                if asyncio.iscoroutine(result):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                if self._on_error:
                    r = self._on_error(exc)
                    if asyncio.iscoroutine(r):
                        await r
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass
