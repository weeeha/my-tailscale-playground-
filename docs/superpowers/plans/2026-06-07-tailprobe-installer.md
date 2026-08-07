# tailprobe Installer & Deploy Plan (Phase 0, Plan 3 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **⚠️ Tasks 1–3 are safe/offline (author + test artifacts). Task 4 is the LIVE deploy to real hardware — it is operator-run and must NOT be executed by an autonomous agent. Stop at Task 4 and hand control to the user.**

**Goal:** Deploy the `tailprobe` agent (Plan 1) to the 8 Linux SBCs over key-based OpenSSH as a systemd service bound to each device's Tailscale address, lock the probe port to the hub with a Tailscale ACL, and bring `tailhub` (Plan 2) up against the live fleet.

**Architecture:** A POSIX-sh installer (`cmd/tailprobe/deploy/install-tailprobe.sh`) streams the prebuilt arm64 binary over OpenSSH stdin, renders a systemd unit template with the host's `100.x` address, enables the service, and verifies it by curling the probe from the hub. A tab-separated `fleet.tsv` manifest drives the `--all` loop. A `--dry-run` mode makes the whole thing offline-testable. The Tailscale ACL stanza (applied by the operator in the admin console) restricts port 9100 to the hub.

**Tech Stack:** POSIX `sh`, OpenSSH (`ssh -i ~/.ssh/id_ed25519 -o BatchMode=yes`, the transport `tailtop` already proves), systemd, `curl`, Tailscale ACLs. Offline tests use `sh -n` + `--dry-run` output assertions (and `shellcheck` if present).

**Key facts (design §12):** all 8 targets are arm64 → one binary. SSH is **key-based OpenSSH to the LAN hostname** (NOT `tailscale ssh` — Tailscale SSH intercepts port 22 and demands browser auth). The probe binds the device's `100.x` (passed via `--addr`); the hub verifies over the tailnet. Preconditions for the live deploy: **passwordless sudo** on each Pi for the SSH user, and the per-host SSH users below.

---

## Fleet manifest (host ⇒ tailscale addr ⇒ ssh user)

| Host (LAN/SSH) | Tailscale addr | SSH user |
|---|---|---|
| `fastclock` | 100.78.29.28 | nickv2026 |
| `slowclock` | 100.107.135.128 | nickv2026 |
| `smallclock` | 100.99.148.91 | nickv2026 |
| `squareclock` | 100.118.12.74 | nickv2026 |
| `dashboard-ink-bed` | 100.90.45.73 | nickv2026 |
| `dashboard3eink` | 100.92.15.33 | nickv2026 |
| `plantdashboard` | 100.64.79.16 | nickv2026 |
| `nickv-orangepizero2w` | 100.79.94.56 | nickv |

---

## File Structure

| File | Responsibility |
|------|----------------|
| `cmd/tailprobe/deploy/tailprobe.service` | systemd unit template (`__ADDR__` placeholder, `DynamicUser`, `After=tailscaled`) |
| `cmd/tailprobe/deploy/fleet.tsv` | the 8 `host⇥addr⇥user` rows |
| `cmd/tailprobe/deploy/install-tailprobe.sh` | the installer (single-host + `--all`, `--dry-run`) |
| `cmd/tailprobe/deploy/acl-snippet.hujson` | Tailscale ACL stanza restricting `:9100` to the hub |
| `cmd/tailprobe/deploy/README.md` | the deploy runbook (canary → all → ACL → tailhub → verify) |
| `cmd/tailprobe/deploy/test_deploy.sh` | offline checks: `sh -n`, unit render, manifest, dry-run assertions |

---

## Task 1: systemd unit template + fleet manifest

**Files:**
- Create: `cmd/tailprobe/deploy/tailprobe.service`, `cmd/tailprobe/deploy/fleet.tsv`
- Test: `cmd/tailprobe/deploy/test_deploy.sh` (created here, extended in Task 2)

- [ ] **Step 1: Create the unit template**

`cmd/tailprobe/deploy/tailprobe.service`:
```ini
[Unit]
Description=tailprobe fleet telemetry agent
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
Type=simple
# __ADDR__ is replaced by the installer with this device's Tailscale (100.x) IP.
ExecStart=/usr/local/bin/tailprobe --addr __ADDR__:9100
DynamicUser=yes
SupplementaryGroups=video
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
```

(`DynamicUser` runs the probe as a transient unprivileged user; `SupplementaryGroups=video` grants `/dev/vchiq` access so `vcgencmd` works on Broadcom Pis. All vitals reads are world-readable `/proc` + `/sys`. The probe retries binding until `tailscaled` assigns the `100.x` at boot, so `After=tailscaled.service` plus the in-binary retry covers the boot race.)

- [ ] **Step 2: Create the fleet manifest**

`cmd/tailprobe/deploy/fleet.tsv` (tab-separated; keep the literal tabs):
```
# host	tailscale_addr	ssh_user
fastclock	100.78.29.28	nickv2026
slowclock	100.107.135.128	nickv2026
smallclock	100.99.148.91	nickv2026
squareclock	100.118.12.74	nickv2026
dashboard-ink-bed	100.90.45.73	nickv2026
dashboard3eink	100.92.15.33	nickv2026
plantdashboard	100.64.79.16	nickv2026
nickv-orangepizero2w	100.79.94.56	nickv
```

- [ ] **Step 3: Write the offline test harness (unit render + manifest)**

`cmd/tailprobe/deploy/test_deploy.sh`:
```sh
#!/bin/sh
# Offline checks for the tailprobe deploy artifacts. No hardware touched.
set -eu
cd "$(dirname "$0")"
fail() { echo "FAIL: $1"; exit 1; }

# 1. unit renders: __ADDR__ is substituted and none remains.
rendered="$(sed 's|__ADDR__|100.64.79.16|g' tailprobe.service)"
echo "$rendered" | grep -q -- '--addr 100.64.79.16:9100' || fail "unit did not render addr"
echo "$rendered" | grep -q '__ADDR__' && fail "unit still has __ADDR__ after render"
echo "$rendered" | grep -q '^ExecStart=/usr/local/bin/tailprobe ' || fail "unit ExecStart wrong"

# 2. manifest has exactly 8 non-comment rows, 3 tab-separated fields each.
rows="$(grep -cv '^#' fleet.tsv)"
[ "$rows" -eq 8 ] || fail "expected 8 fleet rows, got $rows"
while IFS="$(printf '\t')" read -r host addr user; do
  case "$host" in ''|\#*) continue;; esac
  [ -n "$host" ] && [ -n "$addr" ] && [ -n "$user" ] || fail "bad row: $host/$addr/$user"
  case "$addr" in 100.*) : ;; *) fail "addr not 100.x: $addr";; esac
done < fleet.tsv

echo "test_deploy: unit+manifest OK"
```

- [ ] **Step 4: Run the test**

Run: `sh cmd/tailprobe/deploy/test_deploy.sh`
Expected: `test_deploy: unit+manifest OK` (exit 0).

- [ ] **Step 5: Commit**

```bash
chmod +x cmd/tailprobe/deploy/test_deploy.sh
git add cmd/tailprobe/deploy/tailprobe.service cmd/tailprobe/deploy/fleet.tsv cmd/tailprobe/deploy/test_deploy.sh
git commit -m "feat(tailprobe/deploy): systemd unit template + fleet manifest + offline checks"
```

---

## Task 2: the installer script

**Files:**
- Create: `cmd/tailprobe/deploy/install-tailprobe.sh`
- Modify: `cmd/tailprobe/deploy/test_deploy.sh` (add dry-run assertions)

- [ ] **Step 1: Write the installer**

`cmd/tailprobe/deploy/install-tailprobe.sh`:
```sh
#!/bin/sh
# Copyright (c) Tailscale Inc & contributors
# SPDX-License-Identifier: BSD-3-Clause
#
# install-tailprobe.sh — push the tailprobe binary + systemd unit to one or all
# fleet hosts over key-based OpenSSH, enable the service, and verify it.
#
#   ./install-tailprobe.sh --dry-run --all              # print, touch nothing
#   ./install-tailprobe.sh <host> <addr> <ssh_user>     # one host
#   ./install-tailprobe.sh --all                        # whole fleet.tsv
set -eu

PORT=9100
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
HERE="$(dirname "$0")"
BIN="${BIN:-$HERE/../../../dist/tailprobe-linux-arm64}"
UNIT_TEMPLATE="$HERE/tailprobe.service"
FLEET="$HERE/fleet.tsv"
DRY_RUN=0
SSH_OPTS="-i $SSH_KEY -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8"

usage() { echo "usage: $0 [--dry-run] {--all | <host> <addr> <ssh_user>}" >&2; exit 2; }

install_one() {
  host="$1"; addr="$2"; user="$3"; dest="$user@$host"
  echo "=== $host ($addr) as $user ==="

  # 1. stream the binary → /usr/local/bin/tailprobe (atomic install).
  echo "+ ssh $dest 'install binary' < $BIN"
  if [ "$DRY_RUN" != 1 ]; then
    [ -f "$BIN" ] || { echo "missing binary: $BIN (build it first)" >&2; return 1; }
    # shellcheck disable=SC2086
    ssh $SSH_OPTS "$dest" \
      'cat >/tmp/tailprobe.new && chmod +x /tmp/tailprobe.new && sudo install -m0755 /tmp/tailprobe.new /usr/local/bin/tailprobe && rm -f /tmp/tailprobe.new' \
      <"$BIN"
  fi

  # 2. render + install the unit with this host's tailscale addr, enable+restart.
  echo "+ ssh $dest 'install unit --addr $addr'"
  if [ "$DRY_RUN" != 1 ]; then
    sed "s|__ADDR__|$addr|g" "$UNIT_TEMPLATE" | \
    # shellcheck disable=SC2086
    ssh $SSH_OPTS "$dest" \
      'sudo tee /etc/systemd/system/tailprobe.service >/dev/null && sudo systemctl daemon-reload && sudo systemctl enable --now tailprobe && sudo systemctl restart tailprobe'
  fi

  # 3. verify from here over the tailnet.
  echo "+ curl http://$addr:$PORT/healthz"
  if [ "$DRY_RUN" != 1 ]; then
    sleep 2
    curl -fsS --max-time 5 "http://$addr:$PORT/healthz" >/dev/null \
      && echo "  verify OK" \
      || { echo "  VERIFY FAILED: $host" >&2; return 1; }
  fi
}

[ "${1:-}" = "--dry-run" ] && { DRY_RUN=1; shift; }
case "${1:-}" in
  --all)
    rc=0
    while IFS="$(printf '\t')" read -r host addr user; do
      case "$host" in ''|\#*) continue;; esac
      install_one "$host" "$addr" "$user" || { rc=1; echo "  (continuing)"; }
    done <"$FLEET"
    exit $rc ;;
  --*|"") usage ;;
  *) [ $# -eq 3 ] || usage; install_one "$1" "$2" "$3" ;;
esac
```

- [ ] **Step 2: Add dry-run assertions to the test harness**

Append to `cmd/tailprobe/deploy/test_deploy.sh` (before the final `echo`):
```sh
# 3. installer syntax is valid POSIX sh.
sh -n install-tailprobe.sh || fail "install-tailprobe.sh has a syntax error"

# 4. dry-run --all prints an install plan for all 8 hosts and touches nothing.
out="$(sh install-tailprobe.sh --dry-run --all)"
echo "$out" | grep -q '=== fastclock (100.78.29.28) as nickv2026 ===' || fail "dry-run missing fastclock"
echo "$out" | grep -q '=== nickv-orangepizero2w (100.79.94.56) as nickv ===' || fail "dry-run missing orangepi"
hosts="$(echo "$out" | grep -c '^=== ')"
[ "$hosts" -eq 8 ] || fail "dry-run covered $hosts hosts, expected 8"
echo "$out" | grep -q "curl http://100.64.79.16:9100/healthz" || fail "dry-run missing verify step"
# dry-run must NOT actually invoke ssh/curl — assert no real side-effect markers.
echo "$out" | grep -q 'verify OK' && fail "dry-run performed a real verify"

# 5. shellcheck if available (optional).
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck -s sh install-tailprobe.sh test_deploy.sh || fail "shellcheck flagged an issue"
fi
```

- [ ] **Step 3: Run the test**

Run: `chmod +x cmd/tailprobe/deploy/install-tailprobe.sh && sh cmd/tailprobe/deploy/test_deploy.sh`
Expected: `test_deploy: unit+manifest OK` and exit 0 (all 5 checks pass; no SSH/curl performed).

- [ ] **Step 4: Commit**

```bash
git add cmd/tailprobe/deploy/install-tailprobe.sh cmd/tailprobe/deploy/test_deploy.sh
git commit -m "feat(tailprobe/deploy): OpenSSH installer (binary + unit + verify) with dry-run"
```

---

## Task 3: Tailscale ACL stanza + deploy runbook

**Files:**
- Create: `cmd/tailprobe/deploy/acl-snippet.hujson`, `cmd/tailprobe/deploy/README.md`

- [ ] **Step 1: Write the ACL stanza**

`cmd/tailprobe/deploy/acl-snippet.hujson`:
```hujson
// Merge into your Tailscale policy (admin console → Access controls).
// Restricts the tailprobe port (9100) so ONLY the hub can scrape it.
{
  "tagOwners": {
    "tag:tailprobe": ["autogroup:admin"],
    "tag:tailhub":   ["autogroup:admin"],
  },
  "acls": [
    // ...your existing acls...
    { "action": "accept", "src": ["tag:tailhub"], "dst": ["tag:tailprobe:9100"] },
  ],
  // Optional: lets the hub use `tailscale ssh` to the probes (removes the LAN-SSH
  // dependency for installs). Without this, installs use key-based OpenSSH on the LAN.
  "ssh": [
    { "action": "accept", "src": ["tag:tailhub"], "dst": ["tag:tailprobe"], "users": ["nickv2026", "nickv"] },
  ],
}
```

Then tag the devices: the 8 SBCs get `tag:tailprobe`, the Mac Studio gets `tag:tailhub` (admin console → each device → Edit ACL tags, or `tailscale up --advertise-tags=tag:tailprobe`). If you'd rather not tag, replace `"src": ["tag:tailhub"]` with `"src": ["100.75.213.56"]` (the hub's IP).

- [ ] **Step 2: Write the deploy runbook**

`cmd/tailprobe/deploy/README.md`:
```markdown
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
```

- [ ] **Step 3: Verify the artifacts are well-formed**

Run:
```bash
sh cmd/tailprobe/deploy/test_deploy.sh
grep -q 'tag:tailprobe:9100' cmd/tailprobe/deploy/acl-snippet.hujson && echo "acl stanza present"
grep -q 'install-tailprobe.sh --all' cmd/tailprobe/deploy/README.md && echo "runbook present"
```
Expected: `test_deploy: unit+manifest OK`, `acl stanza present`, `runbook present`.

- [ ] **Step 4: Commit**

```bash
git add cmd/tailprobe/deploy/acl-snippet.hujson cmd/tailprobe/deploy/README.md
git commit -m "docs(tailprobe/deploy): Tailscale ACL stanza + deploy runbook"
```

---

## Task 4: LIVE deploy (operator-run — DO NOT auto-execute)

> **This task touches real hardware (the 8 Pis) and the Tailscale admin console. An autonomous agent MUST stop here and hand control to the operator.** Run it interactively, canary-first, confirming each stage. The steps are the runbook in `cmd/tailprobe/deploy/README.md`.

- [ ] **Step 1 (operator):** Build the arm64 binary (runbook §1).
- [ ] **Step 2 (operator):** Confirm preconditions on the canary host (`ssh ... true`, `sudo -n true`).
- [ ] **Step 3 (operator):** Canary deploy to `plantdashboard`; curl `/vitals`; confirm the schema:1 JSON looks right and the service is `active` (`ssh nickv2026@plantdashboard systemctl is-active tailprobe`).
- [ ] **Step 4 (operator):** `--all` deploy; note any per-host failures (the loop continues).
- [ ] **Step 5 (operator):** Apply the ACL stanza + device tags in the admin console.
- [ ] **Step 6 (operator):** Start `tailhub`; confirm `/fleet` lists the probe hosts with `online: true` and populated `snapshot.metrics`.
- [ ] **Step 7:** Capture the live `/fleet` output in the PR / notes as the Phase-0 "it works on real hardware" evidence.

---

## Self-Review

**Spec coverage (design §6.1 deploy + §12):**
- One arm64 binary for all 8 SBCs → runbook §1 + installer `BIN`. ✅
- OpenSSH-to-LAN-hostname transport (not `tailscale ssh`) → installer `ssh $SSH_OPTS "$user@$host"`. ✅
- systemd **system** service, `DynamicUser`, `SupplementaryGroups=video`, `After=tailscaled`, retry-bind → Task 1 unit. ✅
- Probe binds the device `100.x` via `--addr` (never `0.0.0.0`) → unit `--addr __ADDR__:9100` rendered per host. ✅
- Verify by curling the probe `100.x` from the hub → installer step 3. ✅
- Idempotent install + operator-run upgrades (no hub push, preserves §3 no-C2) → install-over + `daemon-reload` + `restart`; runbook "Upgrades". ✅
- Tailscale ACL restricting `:9100` to the hub (tag-based, IP fallback) → Task 3 `acl-snippet.hujson`. ✅
- Point `tailhub` at the fleet (8 default probe_hosts already in Plan 2 `settings.py`) → runbook §5. ✅
- Live deploy is operator-gated → Task 4 marked DO-NOT-AUTO-EXECUTE. ✅
- *Deferred (correct):* macOS/Windows/iOS agents (Plan 4 / later); a launchd plist for tailhub-as-a-service (optional polish, not Phase-0-blocking — `uv run tailhub` suffices).

**Placeholder scan:** No TBD/TODO. Every artifact is complete; every offline check is a real, runnable assertion with expected output. Task 4's steps are intentionally operator-run (clearly marked), not agent steps. ✅

**Consistency:** Port `9100` agrees across the unit (`--addr __ADDR__:9100`), the installer `PORT=9100` + verify-curl, the ACL `dst …:9100`, and `tailhub` `settings.probe_port=9100`. The 8 `fleet.tsv` hosts/addrs/users match the design §12 table and `tailhub`'s `DEFAULT_PROBE_HOSTS`. SSH users (`nickv2026`/`nickv`) match the infra doc. ✅

---

## Phase 0 remaining plan (after this)

4. **tailtop repoint** — `TailscaleClient.fetch_fleet(hub_url)` + `vitals_poller` hub GET; `tailtop fleet` reads `tailhub`'s `/fleet` instead of SSH-streaming `fleet_collect.sh`.
