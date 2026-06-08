"""Smart-plug collector (Tasmota / Shelly over local HTTP).

A plug on the kettle / stove / TV gives appliance-level ground truth that pure
WiFi sensing can't match. Uses stdlib ``urllib`` — no extra dependency.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable

from .base import Collector


def http_get(url: str, timeout: float = 2.0) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (local LAN)
        return resp.read().decode()


def parse_tasmota(body: str) -> bool:
    # GET http://plug/cm?cmnd=Power  ->  {"POWER":"ON"}
    return str(json.loads(body).get("POWER", "")).upper() == "ON"


def parse_shelly(body: str) -> bool:
    # GET http://plug/relay/0  ->  {"ison": true}   (Gen1)
    #     http://plug/rpc/Switch.GetStatus?id=0  ->  {"output": true}  (Gen2)
    data = json.loads(body)
    return bool(data.get("ison", data.get("output", False)))


class HttpPlugCollector(Collector):
    """``key`` reflects a plug's on/off state."""

    def __init__(
        self,
        key: str,
        url: str,
        *,
        parser: Callable[[str], bool] = parse_tasmota,
        fetch: Callable[[str], str] | None = None,
        interval_s: float = 30.0,
    ) -> None:
        super().__init__(key, interval_s)
        self.url = url
        self._parser = parser
        self._fetch = fetch or http_get

    def read(self) -> bool:
        return self._parser(self._fetch(self.url))
