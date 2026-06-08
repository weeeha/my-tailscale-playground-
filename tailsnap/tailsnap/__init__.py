"""tailsnap — a CLI snapshot of your tailnet.

One-shot, scriptable visual readouts of the Tailscale network: a status table,
a one-line health summary, a topology tree, and a top-talkers chart. A companion
to the ``tailtop`` TUI (the live/interactive view); tailsnap is the
print-and-exit, pipe-into-a-script half.

Standalone: its only data source is ``tailscale status --json`` (or a built-in
``--demo`` fixture), with no dependency on tailtop.
"""

from __future__ import annotations

__version__ = "0.1.0"
