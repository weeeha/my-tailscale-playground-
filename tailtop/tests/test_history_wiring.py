"""Task 15: VitalsStore wired into TailtopApp.

Tests that:
- Pre-recorded store samples are backfilled into vitals_history on first _on_status.
- _on_vitals records each round into the store.
- VitalsHistory.seed correctly appends a list of samples.
- vitals_store.close() is called on unmount.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tailtop.app import TailtopApp, pid_for
from tailtop.data.history import VitalsStore
from tailtop.data.models import Status
from tailtop.data.vitals import Vitals

FIXTURE = Path(__file__).parent / "fixtures" / "status.json"


class FakeClient:
    available = True
    _binary = "tailscale"

    def __init__(self, status: Status) -> None:
        self._status = status

    async def status(self) -> Status:
        return self._status

    async def collect_vitals(self, host, user_map, addr_map=None):
        return Vitals(host=host, soc_temp_c=55.0, cpu_pct=9.0)

    async def run(self, *args, **kwargs) -> str:
        return ""

    async def ping_once(self, host: str) -> str:
        return ""


@pytest.fixture()
def status() -> Status:
    return Status.from_json(json.loads(FIXTURE.read_text()))


@pytest.fixture()
def mem_store():
    s = VitalsStore(":memory:")
    yield s
    s.close()


# ---------------------------------------------------------------------------
# VitalsHistory.seed helper
# ---------------------------------------------------------------------------


def test_vitals_history_seed_appends_series() -> None:
    """seed() should bulk-append temps and cpus for a peer."""
    from tailtop.state import VitalsHistory

    vh = VitalsHistory()
    vh.seed("peer1", [40.0, 45.0, 50.0], [10.0, 15.0, 20.0])

    assert vh.temp_series("peer1") == [40.0, 45.0, 50.0]
    assert vh.cpu_series("peer1") == [10.0, 15.0, 20.0]


def test_vitals_history_seed_unknown_peer_empty() -> None:
    from tailtop.state import VitalsHistory

    vh = VitalsHistory()
    # Seeding with empty lists should not crash and leave series empty
    vh.seed("peer1", [], [])
    assert vh.temp_series("peer1") == []
    assert vh.cpu_series("peer1") == []


def test_vitals_history_seed_respects_width() -> None:
    """seed() beyond WIDTH should keep only the most-recent WIDTH entries."""
    from tailtop.state import VitalsHistory

    vh = VitalsHistory()
    many = list(range(40))  # more than WIDTH=32
    vh.seed("peer1", many, [])
    # Should have at most WIDTH=32 entries, the most recent ones
    result = vh.temp_series("peer1")
    assert len(result) == 32
    assert result[-1] == 39  # newest preserved


# ---------------------------------------------------------------------------
# App wiring — store= kwarg, backfill, record
# ---------------------------------------------------------------------------


async def test_backfill_seeds_vitals_history_on_first_status(status: Status, mem_store: VitalsStore) -> None:
    """Pre-recorded store samples are backfilled into vitals_history after first _on_status."""
    # Find fastclock peer id so we can assert correct key
    fastclock_pid = pid_for(status, "fastclock")
    assert fastclock_pid != "fastclock", "fastclock must be in the fixture status"

    # Pre-record two samples for fastclock in the store (keyed by host_name)
    v1 = Vitals(host="fastclock", soc_temp_c=40.0, cpu_pct=10.0)
    v2 = Vitals(host="fastclock", soc_temp_c=50.0, cpu_pct=20.0)
    mem_store.record("fastclock", 1000.0, v1)
    mem_store.record("fastclock", 1001.0, v2)

    app = TailtopApp(
        client=FakeClient(status),
        store=mem_store,
        auto_poll=False,
        splash=False,
    )
    async with app.run_test() as pilot:
        # Trigger first _on_status — this should backfill
        app._on_status(status)
        await pilot.pause()

        temps = app.vitals_history.temp_series(fastclock_pid)
        assert temps == [40.0, 50.0], f"Expected backfilled temps, got {temps}"
        cpus = app.vitals_history.cpu_series(fastclock_pid)
        assert cpus == [10.0, 20.0], f"Expected backfilled cpus, got {cpus}"


async def test_backfill_only_happens_once(status: Status, mem_store: VitalsStore) -> None:
    """Calling _on_status a second time must not double the seed."""
    fastclock_pid = pid_for(status, "fastclock")

    v = Vitals(host="fastclock", soc_temp_c=42.0, cpu_pct=12.0)
    mem_store.record("fastclock", 1000.0, v)

    app = TailtopApp(
        client=FakeClient(status),
        store=mem_store,
        auto_poll=False,
        splash=False,
    )
    async with app.run_test() as pilot:
        app._on_status(status)
        await pilot.pause()
        app._on_status(status)  # second call — should NOT re-seed
        await pilot.pause()

        temps = app.vitals_history.temp_series(fastclock_pid)
        assert temps.count(42.0) == 1, f"Seed duplicated — got {temps}"


async def test_on_vitals_records_into_store(status: Status, mem_store: VitalsStore) -> None:
    """_on_vitals should record each vitals object into the store."""
    app = TailtopApp(
        client=FakeClient(status),
        store=mem_store,
        auto_poll=False,
        splash=False,
    )
    async with app.run_test() as pilot:
        # Provide status first so _on_vitals can remap host→peer.id
        app._on_status(status)
        await pilot.pause()

        # Simulate a vitals poll round arriving
        vitals_round = {
            "fastclock": Vitals(host="fastclock", soc_temp_c=62.0, cpu_pct=30.0),
        }
        app._on_vitals(vitals_round)
        await pilot.pause()

        # The store should now have one row for fastclock
        temps = mem_store.recent_temps("fastclock")
        assert temps == [62.0], f"Expected [62.0] in store, got {temps}"
        cpus = mem_store.recent_cpu("fastclock")
        assert cpus == [30.0], f"Expected [30.0] in store, got {cpus}"


async def test_store_closes_on_unmount(status: Status) -> None:
    """on_unmount must call vitals_store.close() without raising."""
    store = VitalsStore(":memory:")
    app = TailtopApp(
        client=FakeClient(status),
        store=store,
        auto_poll=False,
        splash=False,
    )
    async with app.run_test():
        pass  # unmount happens on __aexit__

    # After unmount, the connection is closed — a subsequent op should raise
    with pytest.raises(Exception):  # sqlite3.ProgrammingError: Cannot operate on a closed database.
        store.recent_temps("any")
