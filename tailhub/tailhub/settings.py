"""Runtime configuration, overridable via TAILHUB_* env vars."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

# The 8 Phase-0 Linux SBCs that run a tailprobe agent (design §12).
DEFAULT_PROBE_HOSTS = [
    "fastclock", "slowclock", "smallclock", "squareclock",
    "dashboard-ink-bed", "dashboard3eink", "plantdashboard",
    "nickv-orangepizero2w",
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TAILHUB_", env_file=None)

    db_path: str = "tailhub.db"
    scrape_interval_s: float = 30.0
    probe_port: int = 9100
    request_timeout_s: float = 5.0
    retention_days: int = 14
    probe_hosts: list[str] = DEFAULT_PROBE_HOSTS
    bearer_token: str | None = None
    api_host: str = "127.0.0.1"
    api_port: int = 8099
