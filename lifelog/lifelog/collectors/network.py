"""Network-reachability collector.

Most consoles/PCs drop off the network when powered down or asleep, so
reachability is a solid proxy for "is it in use". TCP-connect is preferred (no
root, fast); ICMP ping is the fallback when no service port is known.
"""

from __future__ import annotations

import socket
import subprocess
from collections.abc import Callable

from .base import Collector


def tcp_reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def ping_reachable(host: str, timeout: float = 1.0) -> bool:
    proc = subprocess.run(
        ["ping", "-c", "1", "-W", str(max(1, int(timeout))), host],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return proc.returncode == 0


class NetworkDeviceCollector(Collector):
    """``key`` is True when ``host`` is reachable.

    Pass ``port`` for a TCP probe (e.g. PlayStation 9295, SSH 22); omit it to
    fall back to ping. ``probe`` overrides both (used in tests).
    """

    def __init__(
        self,
        key: str,
        host: str,
        port: int | None = None,
        *,
        probe: Callable[[], bool] | None = None,
        interval_s: float = 30.0,
        timeout: float = 1.0,
    ) -> None:
        super().__init__(key, interval_s)
        self.host = host
        self.port = port
        self.timeout = timeout
        self._probe = probe

    def read(self) -> bool:
        if self._probe is not None:
            return bool(self._probe())
        if self.port is not None:
            return tcp_reachable(self.host, self.port, self.timeout)
        return ping_reachable(self.host, self.timeout)
