# Deploying tailprobe to the fleet

All 8 targets are arm64, so one binary covers the fleet. Run these from the repo
root on the **hub** (Mac Studio), which can reach the Pis on the LAN (SSH) and the
tailnet (verify).

## 0. Preconditions
- Key-based SSH to each Pi works: `ssh -i ~/.ssh/id_ed25519 nickv2026@plantdashboard true`
- **Passwordless sudo** for the SSH user on each Pi (the installer runs `sudo install`,
  `sudo systemctl`). Test: `ssh nickv2026@plantdashboard sudo -n true`.
- SSH users per host are in `fleet.tsv` (clocks/dashboards = `nickv2026`, orange pi = `nickv`).

## 1. Build the arm64 binary
    CGO_ENABLED=0 GOOS=linux GOARCH=arm64 ./tool/go build -trimpath -ldflags='-s -w' \
      -o dist/tailprobe-linux-arm64 ./cmd/tailprobe

## 2. Canary: one host first
    ./cmd/tailprobe/deploy/install-tailprobe.sh plantdashboard 100.64.79.16 nickv2026
    curl -fsS http://100.64.79.16:9100/vitals | python3 -m json.tool   # sanity

## 3. The rest of the fleet
    ./cmd/tailprobe/deploy/install-tailprobe.sh --all

## 4. Lock the port to the hub
Apply `acl-snippet.hujson` in the admin console and tag the devices (see that file).

## 5. Bring up the hub
    cd tailhub && uv run tailhub        # serves the API on 127.0.0.1:8099
    curl -fsS http://127.0.0.1:8099/fleet | python3 -m json.tool   # all 8 probes appear

## Upgrades
Re-run the installer (idempotent: install-over + daemon-reload + restart). Roll back
by re-installing the previous binary. The hub never pushes binaries (no control plane).

## Dry run anytime
    ./cmd/tailprobe/deploy/install-tailprobe.sh --dry-run --all
