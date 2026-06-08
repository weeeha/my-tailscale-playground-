"""Render each tailsnap view from a Tailnet. Pure: Tailnet → string."""

from __future__ import annotations

from . import render as R
from .models import Tailnet


def status(t: Tailnet, color: bool = True) -> str:
    headers = ["", "PEER", "OS", "TAILNET IP", "CONN", "TRAFFIC"]
    rows = []
    for p in t.peers:
        dot = R.color("●", R.GREEN, color) if p.online else R.color("○", R.DIM, color)
        name = p.name + (R.color(" ⮐exit", R.CYAN, color) if p.is_exit_node else "")
        rows.append([
            dot,
            name,
            p.os,
            p.ip,
            p.conn if p.online else R.color("—", R.DIM, color),
            R.human_bytes(p.traffic) if p.online else R.color("—", R.DIM, color),
        ])
    return R.table(headers, rows)


def health(t: Tailnet, color: bool = True) -> str:
    n_on, n_tot = len(t.online), len(t.peers)
    dot_code = R.GREEN if n_on == n_tot else (R.YELLOW if n_on else R.RED)
    dot = R.color("●", dot_code, color)
    exit_node = t.exit_node or "none"
    return (f"tailnet {dot} {n_on}/{n_tot} online · "
            f"exit:{exit_node} · self:{t.self_name}")


def topology(t: Tailnet, color: bool = True) -> str:
    direct = [p for p in t.online if not p.relay and not p.is_exit_node]
    relayed = [p for p in t.online if p.relay]
    exit_nodes = [p for p in t.peers if p.is_exit_node]

    def names(peers, with_relay=False):
        if not peers:
            return R.color("—", R.DIM, color)
        return ", ".join(f"{p.name}({p.relay})" if with_relay else p.name for p in peers)

    lines = [R.color(f"{t.self_name} (you)", R.BOLD, color)]
    if exit_nodes:
        lines.append(f"├─ exit-node ── {R.color(exit_nodes[0].name, R.CYAN, color)}  (all traffic)")
    lines.append(f"├─ direct ───── {names(direct)}")
    lines.append(f"├─ relayed ──── {names(relayed, with_relay=True)}")
    lines.append(f"└─ offline ──── {R.color(names(t.offline), R.DIM, color)}")
    return "\n".join(lines)


def traffic(t: Tailnet, color: bool = True) -> str:
    peers = sorted((p for p in t.peers if p.traffic > 0),
                   key=lambda p: p.traffic, reverse=True)
    if not peers:
        return "no traffic recorded"
    top = peers[0].traffic
    width = max(len(p.name) for p in peers)
    lines = []
    for p in peers:
        b = R.bar(p.traffic, top)
        lines.append(f"{p.name:<{width}}  {R.color(b, R.CYAN, color)}  {R.human_bytes(p.traffic)}")
    return "\n".join(lines)
