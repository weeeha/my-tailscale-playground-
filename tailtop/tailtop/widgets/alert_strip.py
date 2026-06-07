"""AlertStrip — a one-line summary of tailnet anomalies for TheBaseMode.

Computes offline peer count, peers with keys expiring within 7 days, any
non-Running backend state, and fleet hardware-health warnings from vitals.
Pure ``summarise_alerts(status, vitals_by_id)`` is unit-tested without
Textual; the widget is a thin Static wrapper.
"""

from __future__ import annotations

from datetime import datetime, timezone

from rich.text import Text
from textual.widgets import Static

from tailtop.data.models import Status
from tailtop.data.vitals import Vitals, summarise_health

_EXPIRY_WARNING_DAYS = 7


def summarise_alerts(
    status: Status,
    vitals_by_id: dict[str, Vitals] | None = None,
) -> str:
    """Return a single-line summary; empty string when nothing's wrong."""
    parts: list[str] = []

    if status.backend_state and status.backend_state != "Running":
        parts.append(status.backend_state)

    offline = sum(1 for p in status.peers if not p.online)
    if offline:
        parts.append(f"{offline} offline")

    now = datetime.now(timezone.utc)
    expiring = 0
    for p in status.peers:
        if p.key_expiry is None:
            continue
        delta = p.key_expiry.astimezone(timezone.utc) - now
        if 0 <= delta.total_seconds() <= _EXPIRY_WARNING_DAYS * 86400:
            expiring += 1
    if expiring:
        parts.append(f"{expiring} key expiring soon")

    if vitals_by_id:
        health = summarise_health(vitals_by_id)
        if health:
            parts.append(health)

    return " · ".join(parts)


class AlertStrip(Static):
    """Thin Textual wrapper around summarise_alerts."""

    def set_status(
        self,
        status: Status,
        vitals_by_id: dict[str, Vitals] | None = None,
    ) -> None:
        text = summarise_alerts(status, vitals_by_id)
        if not text:
            self.update(Text("", style="dim"))
        else:
            self.update(Text(f"⚠ {text}", style="#f0c674"))
