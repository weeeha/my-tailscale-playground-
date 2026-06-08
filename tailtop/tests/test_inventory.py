"""Tests for tailtop/inventory.py — render_inventory + update_markdown_file."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from tailtop.data.vitals import Vitals
from tailtop.inventory import render_inventory, update_markdown_file

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VITALS_A = Vitals(
    host="fastclock",
    model="Raspberry Pi 4 Model B Rev 1.5",
    serial="100000abc123",
    cpu_cores=4,
    mem_total_mb=4096,
    os="Raspbian GNU/Linux 12",
    kernel="6.6.31+rpt-rpi-v8",
    disk_total_gb=29.7,
)

VITALS_B = Vitals(
    host="artstation",
    model="Custom Build",
    serial="N/A",
    cpu_cores=16,
    mem_total_mb=131072,  # 128 GB
    os="Windows 11",
    kernel="10.0.26100",
    disk_total_gb=2000.0,
)

VITALS_BY_ID = {"id-fast": VITALS_A, "id-art": VITALS_B}


# ---------------------------------------------------------------------------
# render_inventory
# ---------------------------------------------------------------------------


def test_render_inventory_header_row() -> None:
    table = render_inventory(VITALS_BY_ID)
    assert "| Host |" in table
    assert "| Model |" in table
    assert "| Serial |" in table
    assert "| Cores |" in table
    assert "| RAM |" in table
    assert "| OS |" in table
    assert "| Kernel |" in table
    assert "| Disk |" in table


def test_render_inventory_contains_each_host() -> None:
    table = render_inventory(VITALS_BY_ID)
    assert "fastclock" in table
    assert "artstation" in table


def test_render_inventory_contains_model_and_serial() -> None:
    table = render_inventory(VITALS_BY_ID)
    assert "Raspberry Pi 4 Model B Rev 1.5" in table
    assert "100000abc123" in table
    assert "Custom Build" in table
    assert "N/A" in table


def test_render_inventory_ram_rendered_as_gb() -> None:
    table = render_inventory(VITALS_BY_ID)
    # 4096 MB → "4.0 GB" or "4 GB"
    assert "4" in table
    # 131072 MB → 128 GB
    assert "128" in table


def test_render_inventory_disk_gb_present() -> None:
    table = render_inventory(VITALS_BY_ID)
    assert "29.7" in table or "29" in table
    assert "2000" in table or "2000.0" in table


def test_render_inventory_sorted_by_host() -> None:
    table = render_inventory(VITALS_BY_ID)
    lines = table.splitlines()
    # Find data rows (skip header + separator)
    data_lines = [l for l in lines if l.startswith("|") and "---" not in l and "Host" not in l]
    hosts_in_order = [l.split("|")[1].strip() for l in data_lines]
    assert hosts_in_order == sorted(hosts_in_order)


def test_render_inventory_separator_row() -> None:
    table = render_inventory(VITALS_BY_ID)
    assert "|---|" in table or "| --- |" in table or "|:---|" in table


def test_render_inventory_empty_dict() -> None:
    # Should still produce a header + separator with no data rows.
    table = render_inventory({})
    assert "| Host |" in table
    lines = [l for l in table.splitlines() if l.startswith("|") and "---" not in l and "Host" not in l]
    assert lines == []


# ---------------------------------------------------------------------------
# update_markdown_file
# ---------------------------------------------------------------------------

MARKER = "<!-- tailtop:inventory -->"
END_MARKER = "<!-- /tailtop:inventory -->"
SAMPLE_TABLE = "| A | B |\n|---|---|\n| x | y |"


def _make_temp(content: str) -> Path:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
    f.write(content)
    f.close()
    return Path(f.name)


def test_update_markdown_file_inserts_between_markers() -> None:
    content = f"# Doc\n\n{MARKER}\n{END_MARKER}\n\n## Other\n"
    path = _make_temp(content)
    update_markdown_file(path, SAMPLE_TABLE)
    result = path.read_text()
    assert SAMPLE_TABLE in result
    assert MARKER in result
    assert END_MARKER in result
    # Original section still present
    assert "## Other" in result


def test_update_markdown_file_is_idempotent() -> None:
    content = f"# Doc\n\n{MARKER}\n{END_MARKER}\n\n## Other\n"
    path = _make_temp(content)
    update_markdown_file(path, SAMPLE_TABLE)
    first_result = path.read_text()
    update_markdown_file(path, SAMPLE_TABLE)
    second_result = path.read_text()
    assert first_result == second_result


def test_update_markdown_file_appends_when_no_markers() -> None:
    content = "# Doc\n\nSome text.\n"
    path = _make_temp(content)
    update_markdown_file(path, SAMPLE_TABLE)
    result = path.read_text()
    assert MARKER in result
    assert END_MARKER in result
    assert SAMPLE_TABLE in result
    # Original content preserved
    assert "Some text." in result


def test_update_markdown_file_appends_idempotent() -> None:
    content = "# Doc\n\nSome text.\n"
    path = _make_temp(content)
    update_markdown_file(path, SAMPLE_TABLE)
    first_result = path.read_text()
    update_markdown_file(path, SAMPLE_TABLE)
    second_result = path.read_text()
    assert first_result == second_result


def test_update_markdown_file_replaces_old_table() -> None:
    old_table = "| A | B |\n|---|---|\n| old | data |"
    content = f"# Doc\n\n{MARKER}\n{old_table}\n{END_MARKER}\n"
    path = _make_temp(content)
    update_markdown_file(path, SAMPLE_TABLE)
    result = path.read_text()
    assert SAMPLE_TABLE in result
    assert "old" not in result


def test_update_markdown_file_custom_marker() -> None:
    custom_marker = "<!-- custom:block -->"
    custom_end = "<!-- /custom:block -->"
    content = f"# Doc\n\n{custom_marker}\n{custom_end}\n"
    path = _make_temp(content)
    update_markdown_file(path, SAMPLE_TABLE, marker=custom_marker)
    result = path.read_text()
    assert SAMPLE_TABLE in result
    assert custom_marker in result
    assert custom_end in result
