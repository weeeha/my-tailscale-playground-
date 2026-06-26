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

echo "test_deploy: unit+manifest OK"
