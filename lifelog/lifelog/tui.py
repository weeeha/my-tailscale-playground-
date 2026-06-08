"""Optional Textual timeline view (the seed of a tailtop "Lifelog" mode).

Kept deliberately small: a totals table + the same 24h ribbon as the text
report. When folded into tailtop this becomes a ModeView fed by the app's poll
loop; here it's a standalone App so Phase 1 runs without tailtop's data plumbing.
"""

from __future__ import annotations

import time

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header, Static

from . import config as C
from .report import render_day
from .store import Store


class LifelogApp(App):
    CSS = """
    #ribbon { padding: 1 2; color: $accent; }
    DataTable { height: auto; }
    """
    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self, db: str, date: str | None) -> None:
        super().__init__()
        self.store = Store(db)
        self.date = date or time.strftime("%Y-%m-%d")

    def compose(self) -> ComposeResult:
        yield Header()
        # Reuse the text renderer for the ribbon block (first 5 lines).
        ribbon = "\n".join(render_day(self.store, self.date).splitlines()[:6])
        with Vertical():
            yield Static(ribbon, id="ribbon")
            yield DataTable(id="totals")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#totals", DataTable)
        table.add_columns("activity", "time", "share")
        totals = self.store.activity_totals(self.date)
        grand = sum(totals.values()) or 1.0
        for activity, secs in totals.items():
            mins = int(round(secs / 60))
            table.add_row(activity, f"{mins // 60}h{mins % 60:02d}m",
                          f"{100 * secs / grand:.0f}%")


def run_tui(db: str, date: str | None) -> None:
    LifelogApp(db, date).run()
