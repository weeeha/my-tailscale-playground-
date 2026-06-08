"""Tests for alert_message (pure) and the 'tailtop alert' subcommand wiring."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from tailtop.data.vitals import Vitals
from tailtop.fleet_report import alert_message


# ---------------------------------------------------------------------------
# Pure alert_message tests
# ---------------------------------------------------------------------------


def _ok_vitals(host: str) -> Vitals:
    return Vitals(host=host, soc_temp_c=55.0, cpu_pct=20.0, mem_pct=40.0, disk_used_pct=30.0)


def _warn_vitals(host: str) -> Vitals:
    # Warm temperature (>= TEMP_WARN_C = 70) triggers warn
    return Vitals(host=host, soc_temp_c=72.0, cpu_pct=20.0, mem_pct=40.0, disk_used_pct=30.0)


def _crit_vitals(host: str) -> Vitals:
    # Hot temperature (>= TEMP_CRIT_C = 80) triggers crit
    return Vitals(host=host, soc_temp_c=85.0, cpu_pct=20.0, mem_pct=40.0, disk_used_pct=30.0)


def test_alert_message_returns_none_when_all_ok() -> None:
    vbi = {
        "a": _ok_vitals("fastclock"),
        "b": _ok_vitals("slowclock"),
    }
    assert alert_message(vbi) is None


def test_alert_message_returns_none_for_empty_dict() -> None:
    assert alert_message({}) is None


def test_alert_message_returns_string_for_crit_host() -> None:
    vbi = {"a": _crit_vitals("fastclock")}
    msg = alert_message(vbi)
    assert msg is not None
    assert "fastclock" in msg


def test_alert_message_returns_string_for_warn_host() -> None:
    vbi = {"a": _warn_vitals("slowclock")}
    msg = alert_message(vbi)
    assert msg is not None
    assert "slowclock" in msg


def test_alert_message_names_all_unhealthy_hosts() -> None:
    vbi = {
        "a": _crit_vitals("fastclock"),
        "b": _ok_vitals("slowclock"),
        "c": _warn_vitals("smallclock"),
    }
    msg = alert_message(vbi)
    assert msg is not None
    assert "fastclock" in msg
    assert "smallclock" in msg
    # ok host not mentioned
    assert "slowclock" not in msg


def test_alert_message_returns_none_when_previously_crit_now_ok() -> None:
    vbi = {"a": _ok_vitals("fastclock")}
    assert alert_message(vbi) is None


# ---------------------------------------------------------------------------
# alert subcommand wiring — monkeypatches collect_round + notify_all
# ---------------------------------------------------------------------------


def test_alert_subcommand_calls_notify_all_when_message_exists(capsys) -> None:
    """When alert_message is non-None, notify_all should be called with that message."""
    crit_vitals = {"a": _crit_vitals("fastclock")}
    notified_calls: list = []

    async def fake_collect_round(self) -> dict[str, Vitals]:  # noqa: ANN001
        return crit_vitals

    async def fake_notify_all(msg, env, *, post=None) -> list[str]:  # noqa: ANN001
        notified_calls.append((msg, env))
        return ["ntfy"]

    with (
        patch("tailtop.data.vitals_poller.VitalsPoller.collect_round", fake_collect_round),
        patch("tailtop.data.notify.notify_all", fake_notify_all),
    ):
        from tailtop.app import main
        with pytest.raises(SystemExit) as exc_info:
            main(["alert"])

    assert exc_info.value.code == 0
    assert len(notified_calls) == 1
    msg_sent, _ = notified_calls[0]
    assert "fastclock" in msg_sent

    captured = capsys.readouterr()
    assert "fastclock" in captured.out


def test_alert_subcommand_prints_all_clear_when_no_issues(capsys) -> None:
    """When all hosts are ok, notify_all should NOT be called, and 'all clear' is printed."""
    ok_vitals = {"a": _ok_vitals("fastclock")}
    notified_calls: list = []

    async def fake_collect_round(self) -> dict[str, Vitals]:  # noqa: ANN001
        return ok_vitals

    async def fake_notify_all(msg, env, *, post=None) -> list[str]:  # noqa: ANN001
        notified_calls.append(msg)
        return []

    with (
        patch("tailtop.data.vitals_poller.VitalsPoller.collect_round", fake_collect_round),
        patch("tailtop.data.notify.notify_all", fake_notify_all),
    ):
        from tailtop.app import main
        with pytest.raises(SystemExit) as exc_info:
            main(["alert"])

    assert exc_info.value.code == 0
    assert len(notified_calls) == 0

    captured = capsys.readouterr()
    assert "all clear" in captured.out.lower()
