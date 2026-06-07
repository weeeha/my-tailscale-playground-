"""Tests for VitalsStore — SQLite-backed vitals history (Task 14)."""
from __future__ import annotations

import pytest

from tailtop.data.vitals import Vitals


@pytest.fixture()
def store():
    from tailtop.data.history import VitalsStore

    s = VitalsStore(":memory:")
    yield s
    s.close()


def _make_vitals(host: str, temp: float, cpu: float, disk: float, health: str) -> Vitals:
    return Vitals(
        host=host,
        soc_temp_c=temp,
        cpu_pct=cpu,
        disk_used_pct=disk,
    )


def test_record_and_recent_temps_oldest_to_newest(store) -> None:
    v1 = _make_vitals("pi1", 40.0, 10.0, 20.0, "ok")
    v2 = _make_vitals("pi1", 50.0, 20.0, 30.0, "ok")

    store.record("pi1", 1000.0, v1)
    store.record("pi1", 1001.0, v2)

    temps = store.recent_temps("pi1")
    assert temps == [40.0, 50.0], f"Expected oldest→newest, got {temps}"


def test_record_and_recent_cpu_oldest_to_newest(store) -> None:
    v1 = _make_vitals("pi1", 40.0, 10.0, 20.0, "ok")
    v2 = _make_vitals("pi1", 50.0, 20.0, 30.0, "ok")

    store.record("pi1", 1000.0, v1)
    store.record("pi1", 1001.0, v2)

    cpus = store.recent_cpu("pi1")
    assert cpus == [10.0, 20.0], f"Expected oldest→newest, got {cpus}"


def test_absent_host_returns_empty_list(store) -> None:
    assert store.recent_temps("ghost") == []
    assert store.recent_cpu("ghost") == []


def test_limit_truncates_to_most_recent(store) -> None:
    v1 = _make_vitals("pi1", 40.0, 10.0, 20.0, "ok")
    v2 = _make_vitals("pi1", 50.0, 20.0, 30.0, "ok")
    v3 = _make_vitals("pi1", 60.0, 30.0, 40.0, "ok")

    store.record("pi1", 1000.0, v1)
    store.record("pi1", 1001.0, v2)
    store.record("pi1", 1002.0, v3)

    # With limit=2, should return the 2 most-recent, oldest→newest
    temps = store.recent_temps("pi1", limit=2)
    assert temps == [50.0, 60.0], f"Expected two most-recent, got {temps}"

    cpus = store.recent_cpu("pi1", limit=2)
    assert cpus == [20.0, 30.0], f"Expected two most-recent, got {cpus}"


def test_multiple_hosts_are_isolated(store) -> None:
    va = _make_vitals("pi-a", 40.0, 10.0, 20.0, "ok")
    vb = _make_vitals("pi-b", 70.0, 50.0, 80.0, "warn")

    store.record("pi-a", 1000.0, va)
    store.record("pi-b", 1001.0, vb)

    assert store.recent_temps("pi-a") == [40.0]
    assert store.recent_temps("pi-b") == [70.0]


def test_vitals_without_temp_still_records_cpu(store) -> None:
    """A sample with no temp (soc_temp_c=None) should still store cpu."""
    v = Vitals(host="pi1", soc_temp_c=None, cpu_pct=25.0, disk_used_pct=50.0)
    store.record("pi1", 1000.0, v)

    cpus = store.recent_cpu("pi1")
    assert cpus == [25.0]


def test_skip_row_when_both_temp_and_cpu_are_none(store) -> None:
    """If both soc_temp_c and cpu_pct are absent (0.0 is valid), only skip
    truly absent data — the plan says skip only when BOTH are None."""
    # Vitals with explicitly-None temp and zero cpu_pct (0.0 != None, record it)
    v = Vitals(host="pi1", soc_temp_c=None, cpu_pct=0.0, disk_used_pct=10.0)
    store.record("pi1", 1000.0, v)
    assert store.recent_cpu("pi1") == [0.0]


def test_default_path_creates_inmemory_independently(store) -> None:
    """Two :memory: stores are independent."""
    from tailtop.data.history import VitalsStore

    store2 = VitalsStore(":memory:")
    v = _make_vitals("pi1", 55.0, 15.0, 25.0, "ok")
    store.record("pi1", 1000.0, v)
    # store2 should not see store's data
    assert store2.recent_temps("pi1") == []
    store2.close()
