#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

# Ignore heavy/generated directories
EXCLUDES=(
  "--glob" "!web/node_modules/**"
  "--glob" "!third_party/**"
  "--glob" "!.git/**"
)

PATTERN='^<<<<<<< |^>>>>>>> |^=======$'

if rg -n "$PATTERN" "${EXCLUDES[@]}" >/tmp/conflicts.out; then
  echo "[conflicts] Merge conflict markers found:"
  cat /tmp/conflicts.out
  exit 1
fi

echo "[ok] No merge conflict markers found."
