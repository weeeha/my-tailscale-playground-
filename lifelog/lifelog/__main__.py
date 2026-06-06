"""Lifelog CLI.

    python -m lifelog demo                 # simulate a day → fuse → print report
    python -m lifelog report --db PATH      # re-print a stored day
    python -m lifelog tui --db PATH         # interactive Textual timeline (optional)
"""

from __future__ import annotations

import argparse
import sys
import tempfile

from . import simulator
from .bus import LocalBus
from .fusion import Fusion
from .report import render_day
from .store import Store


def _build_demo(db_path: str, date: str | None) -> Store:
    """Run the full pipeline end-to-end: agent → bus → fusion → store."""
    store = Store(db_path)
    bus = LocalBus(store)
    for ev in simulator.generate(date=date):   # edge agents (simulated)
        bus.publish(ev)
    fusion = Fusion(store)
    fusion.run_stream(bus.drain_since())        # the brain
    return store


def cmd_demo(args: argparse.Namespace) -> int:
    db_path = args.db or tempfile.mktemp(prefix="lifelog-demo-", suffix=".db")
    store = _build_demo(db_path, args.date)
    print(render_day(store, args.date))
    if not args.db:
        print(f"\n(demo db: {db_path})")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    store = Store(args.db)
    print(render_day(store, args.date))
    return 0


def cmd_tui(args: argparse.Namespace) -> int:
    try:
        from .tui import run_tui
    except ImportError:
        print("TUI needs Textual: pip install 'lifelog[tui]'", file=sys.stderr)
        return 1
    run_tui(args.db, args.date)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="lifelog", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="simulate a day and print the timeline")
    d.add_argument("--db", help="persist to this SQLite file (default: temp)")
    d.add_argument("--date", help="YYYY-MM-DD to anchor the day (default: today)")
    d.set_defaults(func=cmd_demo)

    r = sub.add_parser("report", help="print a stored day")
    r.add_argument("--db", required=True)
    r.add_argument("--date")
    r.set_defaults(func=cmd_report)

    t = sub.add_parser("tui", help="interactive timeline (Textual)")
    t.add_argument("--db", required=True)
    t.add_argument("--date")
    t.set_defaults(func=cmd_tui)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
