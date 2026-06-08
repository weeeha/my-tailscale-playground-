"""tailsnap CLI.

    tailsnap [status]      colored peer table (default)
    tailsnap health        one-line summary (scriptable)
    tailsnap map           tailnet topology tree
    tailsnap traffic       top-talkers bar chart

    --demo                 use the built-in fixture (no tailnet needed)
    --color always|never|auto
"""

from __future__ import annotations

import argparse
import os
import sys

from . import client, commands

_VIEWS = {
    "status": commands.status,
    "health": commands.health,
    "map": commands.topology,
    "traffic": commands.traffic,
}


def _color_enabled(mode: str) -> bool:
    if mode == "always":
        return True
    if mode == "never":
        return False
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tailsnap", description="a CLI snapshot of your tailnet")
    p.add_argument("view", nargs="?", default="status", choices=list(_VIEWS),
                   help="what to show (default: status)")
    p.add_argument("--demo", action="store_true", help="use the built-in fixture")
    p.add_argument("--color", choices=["always", "never", "auto"], default="auto")
    args = p.parse_args(argv if argv is not None else sys.argv[1:])

    try:
        tailnet = client.demo() if args.demo else client.load()
    except FileNotFoundError:
        print("tailsnap: `tailscale` not found on PATH. Try --demo.", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - surface any CLI/parse failure cleanly
        print(f"tailsnap: could not read tailnet status ({exc}). Try --demo.", file=sys.stderr)
        return 2

    print(_VIEWS[args.view](tailnet, color=_color_enabled(args.color)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
