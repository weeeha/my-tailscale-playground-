"""Typed models for Tailscale state.

These dataclasses are the boundary between the CLI and the rest of the app.
Nothing above the data layer should ever touch raw ``tailscale`` JSON — it
consumes these instead. Parsing lives here so the shape of the CLI output is
pinned in one place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

# Tailscale serializes a never-handshaked node with this Go zero-value time.
_ZERO_TIME = "0001-01-01T00:00:00Z"

# OS hostnames that aren't useful as a display name (iOS reports "localhost").
_GENERIC_HOSTNAMES = {"", "localhost"}


class ConnType(str, Enum):
    """How we currently reach a peer."""

    SELF = "self"
    DIRECT = "direct"
    DERP = "derp"
    OFFLINE = "offline"
    IDLE = "idle"  # online and in the netmap, but no active path yet


def _parse_time(value: str | None) -> datetime | None:
    if not value or value == _ZERO_TIME:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class Peer:
    """A single node on the tailnet (a peer, or ``self``)."""

    id: str
    host_name: str
    dns_name: str
    os: str
    ips: list[str]
    online: bool
    active: bool
    exit_node: bool  # currently selected as *our* exit node
    exit_node_option: bool  # advertises itself as an available exit node
    relay: str  # DERP region code (e.g. "nyc"); "" when none
    cur_addr: str  # direct endpoint "ip:port"; "" when relayed
    rx_bytes: int
    tx_bytes: int
    last_handshake: datetime | None
    key_expiry: datetime | None
    created: datetime | None = None
    allowed_ips: list[str] = field(default_factory=list)  # advertised routes
    addrs: list[str] = field(default_factory=list)  # candidate endpoints (self only)
    peerapi: list[str] = field(default_factory=list)  # PeerAPI URLs
    cap_map: dict = field(default_factory=dict)  # node attributes (self only)
    tags: list[str] = field(default_factory=list)
    is_self: bool = False

    # ---- derived, UI-facing properties -------------------------------------

    @property
    def name(self) -> str:
        """Prefer the MagicDNS label; fall back to OS hostname.

        iOS devices report ``localhost`` as their OS hostname, so we surface the
        tailnet name (first DNS label) instead — matching the official apps.
        """
        if self.host_name.lower() not in _GENERIC_HOSTNAMES:
            return self.host_name
        label = self.dns_name.split(".", 1)[0]
        return label or self.host_name or "unknown"

    @property
    def host_label(self) -> str:
        """The raw OS hostname, shown as a secondary annotation when generic."""
        return self.host_name

    @property
    def ipv4(self) -> str:
        for ip in self.ips:
            if ":" not in ip:
                return ip
        return self.ips[0] if self.ips else ""

    @property
    def ipv6(self) -> str:
        for ip in self.ips:
            if ":" in ip:
                return ip
        return ""

    @property
    def magic_dns(self) -> str:
        # DNSName comes with a trailing dot from the daemon.
        return self.dns_name.rstrip(".")

    @property
    def conn_type(self) -> ConnType:
        if self.is_self:
            return ConnType.SELF
        if not self.online:
            return ConnType.OFFLINE
        if self.cur_addr:
            return ConnType.DIRECT
        if self.relay:
            return ConnType.DERP
        return ConnType.IDLE

    @property
    def relay_label(self) -> str:
        """Human label for the current path, e.g. 'direct' or 'DERP·nyc'."""
        match self.conn_type:
            case ConnType.DIRECT:
                return "direct"
            case ConnType.DERP:
                return f"DERP·{self.relay}"
            case ConnType.OFFLINE:
                return "offline"
            case ConnType.SELF:
                return "this device"
            case _:
                return "idle"

    @classmethod
    def from_json(cls, d: dict, *, is_self: bool = False) -> "Peer":
        return cls(
            id=str(d.get("ID", "")),
            host_name=d.get("HostName", ""),
            dns_name=d.get("DNSName", ""),
            os=d.get("OS", ""),
            ips=list(d.get("TailscaleIPs") or []),
            online=bool(d.get("Online", False)),
            active=bool(d.get("Active", False)),
            exit_node=bool(d.get("ExitNode", False)),
            exit_node_option=bool(d.get("ExitNodeOption", False)),
            relay=d.get("Relay", "") or "",
            cur_addr=d.get("CurAddr", "") or "",
            rx_bytes=int(d.get("RxBytes", 0) or 0),
            tx_bytes=int(d.get("TxBytes", 0) or 0),
            last_handshake=_parse_time(d.get("LastHandshake")),
            key_expiry=_parse_time(d.get("KeyExpiry")),
            created=_parse_time(d.get("Created")),
            allowed_ips=list(d.get("AllowedIPs") or []),
            addrs=list(d.get("Addrs") or []),
            peerapi=list(d.get("PeerAPIURL") or []),
            cap_map=dict(d.get("CapMap") or {}),
            tags=list(d.get("Tags") or []),
            is_self=is_self,
        )

    @property
    def attributes(self) -> list[tuple[str, str]]:
        """Flatten CapMap into (name, value) rows for display (self only)."""
        rows: list[tuple[str, str]] = []
        for key, vals in sorted(self.cap_map.items()):
            short = key.rsplit("/", 1)[-1]
            if isinstance(vals, list) and vals:
                rows.append((short, ", ".join(str(v) for v in vals)))
            else:
                rows.append((short, "true"))
        return rows


@dataclass
class Status:
    """A full snapshot of tailnet state from ``tailscale status --json``."""

    version: str
    backend_state: str  # "Running", "Stopped", "NeedsLogin", "NoState", ...
    tailscale_ips: list[str]
    magic_dns_suffix: str
    user_display: str
    self_peer: Peer
    peers: list[Peer]

    @property
    def connected(self) -> bool:
        return self.backend_state == "Running"

    @property
    def online_count(self) -> int:
        return sum(1 for p in self.peers if p.online)

    @property
    def total_count(self) -> int:
        return len(self.peers)

    def sorted_peers(self) -> list[Peer]:
        """Online first, then alphabetical — matches the GUI's feel."""
        return sorted(self.peers, key=lambda p: (not p.online, p.name.lower()))

    def all_nodes(self) -> list[Peer]:
        """Self pinned at the top, then sorted peers (like the official apps).

        A blank self (e.g. disconnected / no state) is omitted.
        """
        nodes: list[Peer] = []
        if self.self_peer.id:
            nodes.append(self.self_peer)
        nodes.extend(self.sorted_peers())
        return nodes

    @classmethod
    def from_json(cls, d: dict) -> "Status":
        self_raw = d.get("Self") or {}
        self_peer = Peer.from_json(self_raw, is_self=True)

        peers = [Peer.from_json(p) for p in (d.get("Peer") or {}).values()]

        # Resolve the current user's display name via the User map.
        users = d.get("User") or {}
        self_uid = str(self_raw.get("UserID", ""))
        user_display = ""
        if self_uid and self_uid in users:
            user_display = users[self_uid].get("LoginName", "")

        return cls(
            version=d.get("Version", ""),
            backend_state=d.get("BackendState", ""),
            tailscale_ips=list(d.get("TailscaleIPs") or []),
            magic_dns_suffix=d.get("MagicDNSSuffix", ""),
            user_display=user_display,
            self_peer=self_peer,
            peers=peers,
        )
