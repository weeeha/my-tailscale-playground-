# Running tailhub always-on (macOS launchd)

Install `tailhub` as a stable, worktree-independent CLI and run it 24/7 on the
hub (Mac Studio), so it scrapes the fleet every ~30s and records history.

```sh
# 1. Install a stable snapshot (its own venv; survives worktree changes)
uv tool install --from "$(git rev-parse --show-toplevel)/tailhub" tailhub

# 2. Data dir + launchd agent
mkdir -p ~/.tailhub
cp tailhub/deploy/com.weeeha.tailhub.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/"$(id -u)" ~/Library/LaunchAgents/com.weeeha.tailhub.plist
```

The agent runs `~/.local/bin/tailhub` — the uvicorn API on `127.0.0.1:8099`
plus the 30s scraper — storing history in `~/.tailhub/tailhub.db`
(`TAILHUB_DB_PATH`, WAL). `RunAtLoad` + `KeepAlive` start it at login and restart
on crash.

## Manage

```sh
curl -s http://127.0.0.1:8099/fleet | python3 -m json.tool      # live fleet
tail -f ~/.tailhub/tailhub.log                                  # logs
launchctl print gui/"$(id -u)"/com.weeeha.tailhub | grep state  # status
launchctl kickstart -k gui/"$(id -u)"/com.weeeha.tailhub        # restart
launchctl bootout gui/"$(id -u)"/com.weeeha.tailhub             # stop / unload
```

## After changing tailhub code

```sh
uv tool install --reinstall --from "$(git rev-parse --show-toplevel)/tailhub" tailhub
launchctl kickstart -k gui/"$(id -u)"/com.weeeha.tailhub
```

## Notes

- The plist uses absolute paths (this host's `$HOME` and `/usr/local/bin/tailscale`);
  adjust for another machine.
- The API binds loopback (`127.0.0.1:8099`) — local consumers (`tailtop`, OpenClaw
  agents on the hub) only. To expose it on the tailnet, set `TAILHUB_API_HOST` to
  the hub's `100.x` and tighten access with a Tailscale ACL.
- `tailscale status --json` must work in the launchd context (it does on macOS with
  the Tailscale app running); `PATH` includes `/usr/local/bin` so the CLI resolves.
