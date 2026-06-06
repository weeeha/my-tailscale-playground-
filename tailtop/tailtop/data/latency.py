"""Active latency probe — pings the selected peer and keeps an RTT series.

The official apps show a live "Ping" graph (direct/DERP + current ms); this is
the same idea. One probe task pings whichever peer is currently selected at
~1 Hz and keeps a bounded RTT ring buffer per peer, so the chart animates
between status polls.
"""

from __future__ import annotations

import asyncio
import re
from collections import deque

from tailtop.data.models import Peer

_RTT = re.compile(r"in ([\d.]+)\s*ms")
_DERP = re.compile(r"via DERP\(([a-z0-9]+)\)", re.IGNORECASE)
_DIRECT = re.compile(r"via (\d{1,3}(?:\.\d{1,3}){3}:\d+)")


def parse_ping(output: str) -> tuple[float | None, str]:
    """Extract (rtt_ms, via) from `tailscale ping` output.

    Returns (None, "timeout") when there's no pong line.
    `via` is "direct" or "DERP·<region>".
    """
    rtt: float | None = None
    if m := _RTT.search(output):
        rtt = float(m.group(1))
    via = ""
    if m := _DERP.search(output):
        via = f"DERP·{m.group(1)}"
    elif _DIRECT.search(output):
        via = "direct"
    if rtt is None:
        return None, "timeout"
    return rtt, via or "?"


class LatencyProbe:
    """Pings the current target peer on an interval; holds per-peer RTT buffers."""

    def __init__(self, client, interval: float = 1.0, width: int = 60) -> None:
        self._client = client
        self._interval = interval
        self._width = width
        self._target: Peer | None = None
        self._series: dict[str, deque[float]] = {}
        self._via: dict[str, str] = {}
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()

    def retarget(self, peer: Peer | None) -> None:
        """Point the probe at a new peer (or None to idle)."""
        self._target = peer
        self._wake.set()
        if peer is not None and (self._task is None or self._task.done()):
            self._task = asyncio.create_task(self._loop())

    def series(self, peer_id: str) -> list[float]:
        return list(self._series.get(peer_id, ()))

    def last(self, peer_id: str) -> float | None:
        s = self._series.get(peer_id)
        return s[-1] if s else None

    def via(self, peer_id: str) -> str:
        return self._via.get(peer_id, "")

    def record(self, peer_id: str, rtt: float, via: str) -> None:
        """Append a sample (used by the loop; exposed for tests)."""
        self._series.setdefault(peer_id, deque(maxlen=self._width)).append(rtt)
        self._via[peer_id] = via

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
            target = self._target
            if target is None:
                self._wake.clear()
                await self._wake.wait()
                continue
            try:
                out = await self._client.ping_once(target.ipv4)
                rtt, via = parse_ping(out)
                if rtt is not None:
                    self.record(target.id, rtt, via)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — a failed ping shouldn't kill the probe
                pass
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass
