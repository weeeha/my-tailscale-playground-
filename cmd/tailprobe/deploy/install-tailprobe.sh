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
