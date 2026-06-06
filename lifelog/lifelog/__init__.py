"""Lifelog — a private, local WiFi-sensing time-tracker.

Phase 1 scaffold (stub-first, runnable): the full pipeline
    sensor agent → bus → fusion → SQLite timeline → report/TUI
runs end-to-end on any machine using a simulated day of sensor events.
Real CSI/RSSI capture drops in behind the ``bus``/``agent`` interfaces later.

See ``notes/lifelog-wifi-sensing-design.md`` for the full design.
"""

from __future__ import annotations

__version__ = "0.1.0"
