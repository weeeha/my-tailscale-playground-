#!/usr/bin/env bash
#
# extract-subprojects.sh — split sub-projects out of this playground monorepo
# into their own repos, PRESERVING each sub-directory's git history (the files
# land at the new repo's root, not under lifelog/ or tailtop/).
#
# Why a script you run locally: the cloud session is scoped to this repo only,
# so it cannot push to the new repos. Run this on your machine, where you have
# push access to the targets.
#
# Usage:
#   bash scripts/extract-subprojects.sh
#
# If a target repo was created WITH an initial commit (a README/license), the
# first push is a non-fast-forward — re-run with PUSH_OPTS=--force to overwrite:
#   PUSH_OPTS=--force bash scripts/extract-subprojects.sh
#
# Override any default via env:
#   LIFELOG_REMOTE=...  TAILTOP_REMOTE=...  BRANCH=main  PUSH_OPTS=...

set -euo pipefail

LIFELOG_REMOTE="${LIFELOG_REMOTE:-https://github.com/weeeha/wifi-life-log.git}"
TAILTOP_REMOTE="${TAILTOP_REMOTE:-https://github.com/weeeha/tailtop.git}"
BRANCH="${BRANCH:-main}"
PUSH_OPTS="${PUSH_OPTS:-}"

split_and_push() {
  local prefix="$1" remote="$2" tmp="export/${1}"

  if [ ! -d "$prefix" ]; then
    echo "!! skipping '$prefix' — directory not found (run from the repo root)"
    return 1
  fi

  echo ">> splitting '$prefix/' → $remote ($BRANCH)"
  git branch -D "$tmp" >/dev/null 2>&1 || true
  git subtree split --prefix="$prefix" -b "$tmp"
  # shellcheck disable=SC2086
  git push $PUSH_OPTS "$remote" "$tmp:$BRANCH"
  git branch -D "$tmp" >/dev/null 2>&1 || true
  echo ">> done: $prefix"
  echo
}

split_and_push lifelog "$LIFELOG_REMOTE"
split_and_push tailtop "$TAILTOP_REMOTE"

cat <<'EOF'
All set. Each target repo now has its sub-project at the root, with history.

Optional follow-up (do this in a PR on the playground, not here):
  - remove the extracted dirs from the playground once you've confirmed the
    new repos look right:  git rm -r lifelog tailtop
EOF
