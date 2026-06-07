"""AlertStrip tests — collates offline/expiring-key counts into a one-line summary."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tailtop.data.models import Peer, Status
from tailtop.widgets.alert_strip import AlertStrip, summarise_alerts


def _peer(pid: str, online: bool = True, expiry_days: int | None = None) -> Peer:
    expiry = None
    if expiry_days is not None:
        expiry = datetime.now(timezone.utc) + timedelta(days=expiry_days)
    return Peer(
        id=pid,
        host_name=pid,
        dns_name=f"{pid}.example.",
        os="linux",
        ips=["100.64.0.1"],
        online=online,
        active=True,
        exit_node=False,
        exit_node_option=False,
        relay="",
        cur_addr="100.64.0.1:41641",
        rx_bytes=0,
        tx_bytes=0,
        last_handshake=None,
        key_expiry=expiry,
    )


def _status(peers: list[Peer], state: str = "Running") -> Status:
    return Status(
        version="dev",
        backend_state=state,
        tailscale_ips=["100.64.0.1"],
        magic_dns_suffix="example.ts.net",
        user_display="me",
        self_peer=_peer("self"),
        peers=peers,
    )


def test_summary_empty_when_no_issues() -> None:
    status = _status([_peer("p1"), _peer("p2")])
    assert summarise_alerts(status) == ""


def test_summary_counts_offline() -> None:
    status = _status([_peer("on"), _peer("off1", online=False), _peer("off2", online=False)])
    out = summarise_alerts(status)
    assert "2 offline" in out


def test_summary_counts_expiring_keys_within_seven_days() -> None:
    status = _status([_peer("hot", expiry_days=3), _peer("safe", expiry_days=60)])
    assert "1 key expiring" in summarise_alerts(status)


def test_summary_flags_backend_not_running() -> None:
    status = _status([], state="NeedsLogin")
    assert "NeedsLogin" in summarise_alerts(status)


def test_alert_strip_widget_instantiates_and_updates() -> None:
    strip = AlertStrip()
    strip.set_status(_status([_peer("a", online=False)]))
    rendered = strip.render()
    plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
    assert "1 offline" in plain


def test_summarise_alerts_includes_health() -> None:
    from tailtop.data.vitals import Vitals
    from tailtop.widgets.alert_strip import summarise_alerts

    status = _status([])
    vbi = {"p1": Vitals(host="fastclock", soc_temp_c=85.0)}
    out = summarise_alerts(status, vbi)
    assert "fastclock" in out
