"""Tailnet data model — a thin view over ``tailscale status --json``."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Peer:
    name: str
    os: str
    ip: str
    online: bool
    relay: str = ""           # "" = direct path, else a DERP region code (e.g. "fra")
    is_exit_node: bool = False  # currently the active exit node
    exit_option: bool = False   # advertises itself as an exit node
    rx_bytes: int = 0
    tx_bytes: int = 0
    active: bool = False

    @property
    def conn(self) -> str:
        return "direct" if not self.relay else f"DERP·{self.relay}"

    @property
    def traffic(self) -> int:
        return self.rx_bytes + self.tx_bytes


@dataclass(slots=True)
class Tailnet:
    self_name: str
    magic_dns: str = ""
    peers: list[Peer] = field(default_factory=list)

    @property
    def online(self) -> list[Peer]:
        return [p for p in self.peers if p.online]

    @property
    def offline(self) -> list[Peer]:
        return [p for p in self.peers if not p.online]

    @property
    def exit_node(self) -> str | None:
        for p in self.peers:
            if p.is_exit_node:
                return p.name
        return None
