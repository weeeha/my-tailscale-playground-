# tailhub

Central collector for a Tailscale fleet. Discovers devices via `tailscale status`,
scrapes each `tailprobe` agent's `/vitals` on a schedule into a SQLite timeline,
and serves `/fleet`, `/device/{host}`, and `/history` over HTTP. Part of the
fleet-tracking stack (`docs/superpowers/specs/2026-06-07-tailfleet-tracking-design.md`).

    cd tailhub && uv run pytest tests/ -q     # tests
    cd tailhub && uv run tailhub               # run the collector + API
