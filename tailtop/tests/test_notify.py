"""Tests for tailtop.data.notify — pluggable Telegram/Slack/ntfy notifier."""
from __future__ import annotations

import pytest

from tailtop.data.notify import enabled_channels, notify_all


# ---------------------------------------------------------------------------
# enabled_channels
# ---------------------------------------------------------------------------


def test_enabled_channels_empty_env():
    assert enabled_channels({}) == []


def test_enabled_channels_telegram_requires_both_vars():
    # Only token — not enough
    assert enabled_channels({"TAILTOP_TELEGRAM_TOKEN": "tok"}) == []
    # Only chat id — not enough
    assert enabled_channels({"TAILTOP_TELEGRAM_CHAT_ID": "123"}) == []
    # Both present
    env = {"TAILTOP_TELEGRAM_TOKEN": "tok", "TAILTOP_TELEGRAM_CHAT_ID": "123"}
    assert "telegram" in enabled_channels(env)


def test_enabled_channels_slack_requires_webhook():
    assert enabled_channels({"TAILTOP_SLACK_WEBHOOK": "https://hooks.slack.com/x"}) == ["slack"]


def test_enabled_channels_ntfy_requires_topic():
    assert enabled_channels({"TAILTOP_NTFY_TOPIC": "mytopic"}) == ["ntfy"]


def test_enabled_channels_all_three():
    env = {
        "TAILTOP_TELEGRAM_TOKEN": "tok",
        "TAILTOP_TELEGRAM_CHAT_ID": "123",
        "TAILTOP_SLACK_WEBHOOK": "https://hooks.slack.com/x",
        "TAILTOP_NTFY_TOPIC": "mytopic",
    }
    channels = enabled_channels(env)
    assert set(channels) == {"telegram", "slack", "ntfy"}


# ---------------------------------------------------------------------------
# notify_all — fake poster captures calls
# ---------------------------------------------------------------------------


class FakePoster:
    """Captures async post calls for assertion."""

    def __init__(self):
        self.calls: list[dict] = []

    async def __call__(
        self,
        url: str,
        *,
        data: bytes | None = None,
        json: dict | None = None,
        headers: dict | None = None,
    ) -> None:
        self.calls.append({"url": url, "data": data, "json": json, "headers": headers})


@pytest.mark.asyncio
async def test_notify_all_empty_env_no_calls():
    poster = FakePoster()
    result = await notify_all("hello", {}, post=poster)
    assert result == []
    assert poster.calls == []


@pytest.mark.asyncio
async def test_notify_all_telegram():
    env = {"TAILTOP_TELEGRAM_TOKEN": "mytoken", "TAILTOP_TELEGRAM_CHAT_ID": "99"}
    poster = FakePoster()
    result = await notify_all("test msg", env, post=poster)
    assert result == ["telegram"]
    assert len(poster.calls) == 1
    call = poster.calls[0]
    assert call["url"] == "https://api.telegram.org/botmytoken/sendMessage"
    assert call["json"] == {"chat_id": "99", "text": "test msg"}
    assert call["data"] is None


@pytest.mark.asyncio
async def test_notify_all_slack():
    env = {"TAILTOP_SLACK_WEBHOOK": "https://hooks.slack.com/services/abc"}
    poster = FakePoster()
    result = await notify_all("slack alert", env, post=poster)
    assert result == ["slack"]
    assert len(poster.calls) == 1
    call = poster.calls[0]
    assert call["url"] == "https://hooks.slack.com/services/abc"
    assert call["json"] == {"text": "slack alert"}
    assert call["data"] is None


@pytest.mark.asyncio
async def test_notify_all_ntfy_default_server():
    env = {"TAILTOP_NTFY_TOPIC": "alerts"}
    poster = FakePoster()
    result = await notify_all("ntfy msg", env, post=poster)
    assert result == ["ntfy"]
    assert len(poster.calls) == 1
    call = poster.calls[0]
    assert call["url"] == "https://ntfy.sh/alerts"
    assert call["data"] == b"ntfy msg"
    assert call["json"] is None


@pytest.mark.asyncio
async def test_notify_all_ntfy_custom_server():
    env = {"TAILTOP_NTFY_TOPIC": "alerts", "TAILTOP_NTFY_SERVER": "https://my.ntfy.example.com"}
    poster = FakePoster()
    result = await notify_all("custom server", env, post=poster)
    assert result == ["ntfy"]
    call = poster.calls[0]
    assert call["url"] == "https://my.ntfy.example.com/alerts"


@pytest.mark.asyncio
async def test_notify_all_all_channels():
    env = {
        "TAILTOP_TELEGRAM_TOKEN": "tok",
        "TAILTOP_TELEGRAM_CHAT_ID": "42",
        "TAILTOP_SLACK_WEBHOOK": "https://hooks.slack.com/x",
        "TAILTOP_NTFY_TOPIC": "pings",
    }
    poster = FakePoster()
    result = await notify_all("broadcast", env, post=poster)
    assert set(result) == {"telegram", "slack", "ntfy"}
    assert len(poster.calls) == 3


@pytest.mark.asyncio
async def test_notify_all_returns_channel_names_not_urls():
    env = {"TAILTOP_SLACK_WEBHOOK": "https://hooks.slack.com/x"}
    poster = FakePoster()
    result = await notify_all("hi", env, post=poster)
    assert result == ["slack"]
    # Should be the name, not the URL
    assert "https" not in result[0]
