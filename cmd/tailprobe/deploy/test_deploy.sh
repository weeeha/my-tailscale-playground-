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
