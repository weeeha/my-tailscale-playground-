# tailprobe

A single static Go binary that serves one device's vitals over a Tailscale-only
HTTP endpoint, reproducing the `schema:1` JSON of `tailtop/agent/fleet_collect.sh`.

It is the per-device agent of the fleet-tracking stack (see
`docs/superpowers/specs/2026-06-07-tailfleet-tracking-design.md`); the `tailhub`
collector scrapes it.

## Endpoints

- `GET /healthz` — liveness (`ok`).
- `GET /vitals` — the full `schema:1` JSON (consumed by `tailhub` and `tailtop`).
- `GET /metrics` — Prometheus exposition of the numeric vitals.

The HTTP listener binds **only** the device's Tailscale address (or an explicit
`--addr`), never `0.0.0.0`. The agent is read-only and never executes
caller-supplied commands.

## Build

One arm64 build covers the whole Phase-0 fleet (4 clocks, 3 dashboards, the
Orange Pi):

```sh
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 ./tool/go build -trimpath -ldflags='-s -w' \
  -o dist/tailprobe-linux-arm64 ./cmd/tailprobe
```

Build with the repo's pinned toolchain (`./tool/go`), not a system `go`.

## Run

```sh
tailprobe --addr 100.x.y.z:9100      # bind the device's Tailscale IP only
tailprobe                            # or auto-detect the 100.64.0.0/10 address, port 9100
```

Binding retries until `tailscaled` has assigned the address at boot. The
installer (a later phase) supplies `--addr <device-100.x>` and runs `tailprobe`
as a systemd service.

## Test

```sh
./tool/go test ./cmd/tailprobe/...
```

The collectors read through an injectable `io/fs` root, so the full suite runs on
any OS (Linux-only syscalls are behind build tags). On a real Pi, confirm the
output matches the shell script's shape:

```sh
curl -fsS http://<device-100.x>:9100/vitals | python3 -m json.tool
```
