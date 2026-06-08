# tailsnap

A **CLI snapshot of your tailnet** — type a command, get a visual readout, back
to your prompt. The print-and-exit, pipe-into-a-script companion to the
[`tailtop`](../tailtop) TUI (which is the live, interactive view).

Standalone: its only data source is `tailscale status --json`. Pure stdlib.

## Use

```sh
tailsnap            # colored peer status table (default)
tailsnap health     # one-line summary — great for a prompt / cron / watch
tailsnap map        # tailnet topology tree (exit node, direct vs relayed)
tailsnap traffic    # top-talkers bar chart

tailsnap --demo     # run against a built-in fixture (no tailnet needed)
tailsnap status --color never   # plain output for pipes/logs
```

## What each view looks like (`--demo`)

```
$ tailsnap
   PEER         OS       TAILNET IP   CONN      TRAFFIC
●  nas ⮐exit    linux    100.64.0.3   direct    11.0GB
●  laptop       macOS    100.64.0.1   direct    3.2GB
●  phone        iOS      100.64.0.2   DERP·fra  160.0MB
●  pi-garage    linux    100.64.0.4   DERP·fra  23.0MB
○  old-tablet   android  100.64.0.7   —         —

$ tailsnap health
tailnet ● 4/5 online · exit:nas · self:workstation
```

## CLI vs the TUI

| | tailsnap (CLI) | tailtop (TUI) |
|---|---|---|
| one-shot, scriptable, pipeable | ✅ | ❌ |
| live updates, navigate, run actions | ❌ | ✅ |

Use tailsnap for a quick look or in scripts; use tailtop when you want to sit and
operate the tailnet.

## Develop

```sh
pip install -e '.[dev]'
pytest
```
