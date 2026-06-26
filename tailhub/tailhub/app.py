"""FastAPI read API over the hub store (no scheduler; that lives in scheduler.py)."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .settings import Settings
from .store import Store


def create_app(store: Store, settings: Settings) -> FastAPI:
    app = FastAPI(title="tailhub", version="0.1.0")

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/fleet")
    def fleet() -> dict:
        return {"devices": store.latest_devices()}

    @app.get("/device/{host}")
    def device(host: str, since: float | None = None) -> dict:
        d = store.latest_device(host)
        if d is None:
            raise HTTPException(status_code=404, detail=f"unknown host {host}")
        d = dict(d)
        d["recent_events"] = store.recent_events(host, since=since)
        return d

    @app.get("/history")
    def history(host: str, metric: str, since: float, until: float | None = None) -> dict:
        return {
            "host": host,
            "metric": metric,
            "since": since,
            "until": until,
            "points": store.metric_history(host, metric, since=since, until=until),
        }

    # Phase-1/3 stubs (documented; real wiring in later plans).
    @app.get("/alerts")
    def alerts() -> dict:
        return {"active": [], "recent": []}

    @app.get("/presence")
    def presence() -> dict:
        return {"devices": []}

    return app
