"""Inventory export — render a markdown table from collected Vitals and patch
a markdown file in-place.

Public API
----------
render_inventory(vitals_by_id) -> str
    Produce a GFM markdown table of hardware config fields, sorted by host.

update_markdown_file(path, table, marker="<!-- tailtop:inventory -->") -> None
    Replace (or append) the fenced block delimited by ``marker`` /
    ``<!-- /marker-name -->`` in ``path``.  Idempotent.
"""
from __future__ import annotations

from pathlib import Path

from tailtop.data.vitals import Vitals

_COLUMNS = ("Host", "Model", "Serial", "Cores", "RAM", "OS", "Kernel", "Disk")


def _ram_str(mem_total_mb: int) -> str:
    """Format megabytes as a compact GB string (e.g. 4096 → '4.0 GB')."""
    gb = mem_total_mb / 1024
    if gb == int(gb):
        return f"{int(gb)} GB"
    return f"{gb:.1f} GB"


def _disk_str(disk_total_gb: float) -> str:
    """Format disk total (e.g. 29.7 → '29.7 GB')."""
    if disk_total_gb == int(disk_total_gb):
        return f"{int(disk_total_gb)} GB"
    return f"{disk_total_gb:.1f} GB"


def _row(v: Vitals) -> str:
    cols = [
        v.host,
        v.model,
        v.serial,
        str(v.cpu_cores) if v.cpu_cores else "",
        _ram_str(v.mem_total_mb) if v.mem_total_mb else "",
        v.os,
        v.kernel,
        _disk_str(v.disk_total_gb) if v.disk_total_gb else "",
    ]
    return "| " + " | ".join(cols) + " |"


def render_inventory(vitals_by_id: dict[str, "Vitals"]) -> str:
    """Return a GFM markdown table of hardware config fields, sorted by host.

    Columns: Host | Model | Serial | Cores | RAM | OS | Kernel | Disk
    """
    header = "| " + " | ".join(_COLUMNS) + " |"
    separator = "| " + " | ".join("---" for _ in _COLUMNS) + " |"
    rows = [header, separator]
    for v in sorted(vitals_by_id.values(), key=lambda x: x.host):
        rows.append(_row(v))
    return "\n".join(rows)


def _end_marker(marker: str) -> str:
    """Derive the closing tag from the opening tag.

    ``<!-- tailtop:inventory -->`` → ``<!-- /tailtop:inventory -->``
    """
    # Strip the surrounding comment syntax and reconstruct.
    inner = marker.strip().removeprefix("<!--").removesuffix("-->").strip()
    return f"<!-- /{inner} -->"


def update_markdown_file(
    path: str | Path,
    table: str,
    marker: str = "<!-- tailtop:inventory -->",
) -> None:
    """Replace (or append) the block bounded by *marker* / end-marker in *path*.

    If the markers are already present their content is replaced with *table*.
    If neither marker exists, the pair is appended at end-of-file.

    The function is idempotent: calling it twice with identical *table* leaves
    the file unchanged on the second call.
    """
    path = Path(path)
    end = _end_marker(marker)
    text = path.read_text() if path.exists() else ""

    block = f"{marker}\n{table}\n{end}"

    if marker in text:
        # Replace existing block (everything from marker to end_marker inclusive).
        before_marker, _, rest = text.partition(marker)
        _, _, after_end = rest.partition(end)
        new_text = before_marker + block + after_end
    else:
        # Append at EOF; ensure exactly one trailing newline before the block.
        new_text = text.rstrip("\n") + "\n" + block + "\n"

    path.write_text(new_text)
