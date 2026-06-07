"""The VitalsPoller wires into the app and populates app.vitals."""
from __future__ import annotations

import json
from pathlib import Path

from tailtop.app import TailtopApp
from tailtop.data.models import Status
from tailtop.data.vitals import Vitals

FIXTURE = Path(__file__).parent / "fixtures" / "status.json"


class FakeClient:
    available = True

    def __init__(self, status: Status) -> None:
        self._status = status

    async def status(self) -> Status:
        return self._status

    async def collect_vitals(self, host, user_map, addr_map=None):  # noqa: ANN001
        return Vitals(host=host, soc_temp_c=55.0, cpu_pct=9.0)


async def test_app_populates_vitals() -> None:
    status = Status.from_json(json.loads(FIXTURE.read_text()))
    # Resolve the peer id for "fastclock" so we can assert with the right key
    # after the hostname→peer-id remap in _on_vitals.
    from tailtop.app import pid_for
    fastclock_pid = pid_for(status, "fastclock")

    app = TailtopApp(client=FakeClient(status), auto_poll=True, splash=False)
    # Poll only a couple of known hosts to keep the test fast/deterministic.
    app.vitals_poller._hosts = ["fastclock"]
    async with app.run_test() as pilot:
        for _ in range(8):
            await pilot.pause()
            if app.vitals:
                break
        assert fastclock_pid in app.vitals
        assert app.vitals[fastclock_pid].soc_temp_c == 55.0
        # auto_poll may fire the vitals poller more than once before we observe
        # it; every round records 55.0, so assert the value, not an exact length.
        series = app.vitals_history.temp_series(fastclock_pid)
        assert series and all(t == 55.0 for t in series)
