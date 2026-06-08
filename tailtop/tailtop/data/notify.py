"""Pluggable notifier backends for Telegram, Slack, and ntfy.

Secrets are read exclusively from the supplied env mapping — never hardcoded.
Channels are enabled only when all required env vars are present.

Default HTTP poster uses stdlib ``urllib.request`` wrapped in
``asyncio.to_thread`` — no additional dependencies required.
"""
from __future__ import annotations

import asyncio
import json as _json
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def enabled_channels(env: Mapping[str, str]) -> list[str]:
    """Return which notification channels are configured in *env*.

    Channels:
    - ``telegram`` — requires both ``TAILTOP_TELEGRAM_TOKEN`` and
      ``TAILTOP_TELEGRAM_CHAT_ID``.
    - ``slack`` — requires ``TAILTOP_SLACK_WEBHOOK``.
    - ``ntfy`` — requires ``TAILTOP_NTFY_TOPIC`` (optional
      ``TAILTOP_NTFY_SERVER``, default ``https://ntfy.sh``).
    """
    channels: list[str] = []
    if env.get("TAILTOP_TELEGRAM_TOKEN") and env.get("TAILTOP_TELEGRAM_CHAT_ID"):
        channels.append("telegram")
    if env.get("TAILTOP_SLACK_WEBHOOK"):
        channels.append("slack")
    if env.get("TAILTOP_NTFY_TOPIC"):
        channels.append("ntfy")
    return channels


async def notify_all(
    message: str,
    env: Mapping[str, str],
    *,
    post: Callable[..., Any] | None = None,
) -> list[str]:
    """Send *message* to every enabled channel.

    Parameters
    ----------
    message:
        The text to send.
    env:
        Env-var mapping used to discover and configure channels.
    post:
        Injectable async callable ``post(url, *, data, json, headers) -> None``
        used for testing.  When ``None`` the default real poster is used
        (``urllib.request`` in ``asyncio.to_thread``).

    Returns
    -------
    list[str]
        Names of channels that were notified (in the same order as
        ``enabled_channels``).
    """
    if post is None:
        post = _real_post

    notified: list[str] = []
    channels = enabled_channels(env)

    for channel in channels:
        if channel == "telegram":
            token = env["TAILTOP_TELEGRAM_TOKEN"]
            chat_id = env["TAILTOP_TELEGRAM_CHAT_ID"]
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            await post(url, json={"chat_id": chat_id, "text": message})
            notified.append("telegram")

        elif channel == "slack":
            url = env["TAILTOP_SLACK_WEBHOOK"]
            await post(url, json={"text": message})
            notified.append("slack")

        elif channel == "ntfy":
            server = env.get("TAILTOP_NTFY_SERVER", "https://ntfy.sh").rstrip("/")
            topic = env["TAILTOP_NTFY_TOPIC"]
            url = f"{server}/{topic}"
            await post(url, data=message.encode())
            notified.append("ntfy")

    return notified


# ---------------------------------------------------------------------------
# Default real poster (stdlib urllib, no extra deps)
# ---------------------------------------------------------------------------


async def _real_post(
    url: str,
    *,
    data: bytes | None = None,
    json: dict | None = None,
    headers: dict | None = None,
) -> None:
    """HTTP POST via stdlib urllib wrapped in asyncio.to_thread."""

    def _do_post() -> None:
        body: bytes | None
        req_headers: dict[str, str] = dict(headers or {})

        if json is not None:
            body = _json.dumps(json).encode()
            req_headers.setdefault("Content-Type", "application/json")
        else:
            body = data

        req = urllib.request.Request(url, data=body, headers=req_headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            resp.read()

    await asyncio.to_thread(_do_post)
