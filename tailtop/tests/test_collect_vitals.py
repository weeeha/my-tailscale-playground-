"""collect_vitals: user resolution + parse of piped script output."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tailtop.data.client import TailscaleClient, ssh_user_for

FIX = Path(__file__).parent / "fixtures"

USER_MAP = {
    "fastclock": "nickv2026", "slowclock": "nickv2026",
    "smallclock": "nickv2026", "squareclock": "nickv2026",
    "nickv-orangepizero2w": "nickv",
}


def test_ssh_user_for_known_hosts() -> None:
    assert ssh_user_for("fastclock", USER_MAP) == "nickv2026"
    assert ssh_user_for("nickv-orangepizero2w", USER_MAP) == "nickv"


def test_ssh_user_for_unknown_falls_back_to_default() -> None:
    assert ssh_user_for("dashboard-ink-bed", USER_MAP, default="pi") == "pi"


async def test_collect_vitals_parses_piped_output(monkeypatch) -> None:
    raw = (FIX / "vitals_fastclock.json").read_text()
    client = TailscaleClient()

    async def fake_ssh(self, host, user):  # noqa: ANN001
        assert user == "nickv2026"
        return raw

    monkeypatch.setattr(TailscaleClient, "_ssh_collect", fake_ssh, raising=True)
    v = await client.collect_vitals("fastclock", user_map=USER_MAP)
    assert v is not None
    # The fixture's "host" field is the Pi's actual hostname ("SuperClockFast"),
    # which differs from the Tailscale peer name ("fastclock"). Both are valid;
    # the fixture is ground truth.
    assert v.host == "SuperClockFast"
    assert v.vcgencmd_present is True
